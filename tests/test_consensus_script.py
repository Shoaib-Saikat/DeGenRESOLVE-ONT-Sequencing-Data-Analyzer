"""
Integration tests for combined_consensus_script.sh - both call-mode branches.

Synthetic test data: 16-base reference, 10 reads covering positions 1-8 only.
Positions 9-16 have zero coverage - must appear as N in -m output.
"""
import os
import subprocess
import pytest

SCRIPT = os.path.abspath(
    os.path.join(os.path.dirname(__file__),
                 "../src/degenresolve/scripts/combined_consensus_script.sh")
)
REF_SEQ = "ACGTACGTACGTACGT"   # 16 bases; reads cover only first 8
READ_SEQ = "ACGTACGT"           # 8 bases matching ref positions 1-8


# fixtures

@pytest.fixture(scope="module")
def bam_env(tmp_path_factory):
    """Build a minimal indexed BAM + indexed reference in a shared temp dir."""
    d = tmp_path_factory.mktemp("consensus_script")

    ref = d / "reference.fasta"
    ref.write_text(f">ref\n{REF_SEQ}\n")
    subprocess.run(["samtools", "faidx", str(ref)], check=True)

    # SAM: 10 identical reads, each 8M starting at pos 1
    sam_lines = [
        "@HD\tVN:1.6\tSO:coordinate",
        f"@SQ\tSN:ref\tLN:{len(REF_SEQ)}",
    ] + [
        f"read{i}\t0\tref\t1\t60\t8M\t*\t0\t0\t{READ_SEQ}\t" + "I" * len(READ_SEQ)
        for i in range(10)
    ]
    sam = d / "input.sam"
    sam.write_text("\n".join(sam_lines) + "\n")

    bam = d / "barcode01.bam"
    subprocess.run(
        f"samtools view -bS {sam} | samtools sort -o {bam}",
        shell=True, check=True,
    )
    subprocess.run(["samtools", "index", str(bam)], check=True)

    return {"dir": d, "bam": bam, "ref": ref}


def _run(bam_env, mode, barcode):
    """Call the script with the given mode; return CompletedProcess."""
    env = {
        **os.environ,
        "VARIANT_CALL_MODE": mode,
        "PLOIDY": "1",
        "VARIANT_CALL_DEPTH": "1000",
    }
    return subprocess.run(
        ["bash", SCRIPT, str(bam_env["bam"]), str(bam_env["ref"]), barcode],
        capture_output=True, text=True, env=env,
        cwd=str(bam_env["dir"]),
    )


# -c branch

def test_c_exits_zero(bam_env):
    r = _run(bam_env, "c", "bc_c1")
    assert r.returncode == 0, r.stderr + r.stdout


def test_c_produces_fasta(bam_env):
    _run(bam_env, "c", "bc_c2")
    out = bam_env["dir"] / "bc_c2_consensus.fasta"
    assert out.exists() and out.stat().st_size > 0
    assert out.read_text().startswith(">")


def test_c_fasta_correct_length(bam_env):
    # bcftools mpileup emits no records for zero-coverage positions, so vcfutils.pl
    # vcf2fq only outputs the covered region (8 bases here, not 16).
    # This is expected -c behaviour; the -m path uses samtools depth to fill gaps with N.
    _run(bam_env, "c", "bc_c3")
    lines = (bam_env["dir"] / "bc_c3_consensus.fasta").read_text().splitlines()
    seq = "".join(l for l in lines if not l.startswith(">"))
    assert len(seq) == len(READ_SEQ), f"expected {len(READ_SEQ)} covered bases, got {len(seq)}"


def test_c_emits_step_marker(bam_env):
    r = _run(bam_env, "c", "bc_c4")
    assert "=== Step 5.5" in r.stdout, "Step 5.5 marker missing from -c stdout"


def test_c_covered_positions_not_N(bam_env):
    """Positions 1-8 are covered -> should NOT be N in output."""
    _run(bam_env, "c", "bc_c5")
    lines = (bam_env["dir"] / "bc_c5_consensus.fasta").read_text().splitlines()
    seq = "".join(l for l in lines if not l.startswith(">")).upper()
    assert "N" not in seq[:8], f"Covered region contains N: {seq[:8]!r}"


# -m branch

def test_m_exits_zero(bam_env):
    r = _run(bam_env, "m", "bc_m1")
    assert r.returncode == 0, r.stderr + r.stdout


def test_m_produces_fasta(bam_env):
    _run(bam_env, "m", "bc_m2")
    out = bam_env["dir"] / "bc_m2_consensus.fasta"
    assert out.exists() and out.stat().st_size > 0
    assert out.read_text().startswith(">")


def test_m_fasta_correct_length(bam_env):
    _run(bam_env, "m", "bc_m3")
    lines = (bam_env["dir"] / "bc_m3_consensus.fasta").read_text().splitlines()
    seq = "".join(l for l in lines if not l.startswith(">"))
    assert len(seq) == len(REF_SEQ), f"expected {len(REF_SEQ)} bases, got {len(seq)}"


def test_m_emits_step_marker(bam_env):
    r = _run(bam_env, "m", "bc_m4")
    assert "=== Step 5.5" in r.stdout, "Step 5.5 marker missing from -m stdout"


def test_m_masks_zero_coverage_as_N(bam_env):
    """Positions 9-16 (zero coverage) must be uppercase N in -m output."""
    _run(bam_env, "m", "bc_m5")
    lines = (bam_env["dir"] / "bc_m5_consensus.fasta").read_text().splitlines()
    seq = "".join(l for l in lines if not l.startswith(">"))
    tail = seq[8:]
    assert len(tail) == 8, f"expected 8 zero-cov bases, got {len(tail)}"
    assert all(b == "N" for b in tail), f"zero-coverage positions not masked: {tail!r}"


def test_m_covered_positions_not_N(bam_env):
    """Positions 1-8 are covered -> should NOT be N in -m output."""
    _run(bam_env, "m", "bc_m6")
    lines = (bam_env["dir"] / "bc_m6_consensus.fasta").read_text().splitlines()
    seq = "".join(l for l in lines if not l.startswith(">"))
    assert "N" not in seq[:8], f"Covered region contains N: {seq[:8]!r}"


def test_m_no_temp_bed_leftover(bam_env):
    """Zero-coverage BED file must be cleaned up after -m run."""
    _run(bam_env, "m", "bc_m7")
    bed = bam_env["dir"] / "bc_m7_zero_cov.bed"
    assert not bed.exists(), "Temp BED mask file was not cleaned up"


# error handling

def test_missing_bam_exits_nonzero(bam_env):
    env = {**os.environ, "VARIANT_CALL_MODE": "c", "PLOIDY": "1", "VARIANT_CALL_DEPTH": "1000"}
    r = subprocess.run(
        ["bash", SCRIPT, "/nonexistent/file.bam", str(bam_env["ref"]), "bc_err"],
        capture_output=True, text=True, env=env, cwd=str(bam_env["dir"]),
    )
    assert r.returncode != 0


def test_no_args_exits_nonzero():
    r = subprocess.run(
        ["bash", SCRIPT],
        capture_output=True, text=True,
    )
    assert r.returncode != 0
