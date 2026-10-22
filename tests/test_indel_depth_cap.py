"""
The sup profile must propose indels at any depth the pileup is allowed to reach.

bcftools mpileup calls indels only where depth is below --max-idepth, which defaults to 250.
The pipeline raises the pileup depth (-d, 10,000 by default) for deep amplicon data, so without
raising --max-idepth as well no indel is ever proposed above 250 reads, and with the Minimum
Coverage Threshold of 100 the adjudication could act only between 100 and 250.

Setting --max-idepth equal to -d is not enough: where the reads saturate the pileup the depth
equals or slightly exceeds -d, and the indel is skipped again. That is exactly where an amplicon
sample is deepest. The limit therefore has to sit where the pileup can never reach it.

Synthetic data: every read carries the same 3-base deletion.
"""
import os
import subprocess

import pytest

SCRIPT = os.path.abspath(
    os.path.join(os.path.dirname(__file__),
                 "../src/degenresolve/scripts/combined_consensus_script.sh")
)
REF = ("ACGTTGCAAGCTTCGATCGGATCCTAGCATGCAACGTTAGCCTAGGATCGTACGTAGCTAGCATCGATGCTAGCTAGGCTAACGTAGCTAGCATGCA"
       "TCGATCGTAGCTAGCTAGGATCCA")
DEL_AT, DEL_LEN = 60, 3            # reads lack reference bases 61-63
READ = REF[:DEL_AT] + REF[DEL_AT + DEL_LEN:]
CIGAR = f"{DEL_AT}M{DEL_LEN}D{len(REF) - DEL_AT - DEL_LEN}M"


def _called_indels(tmp_path, depth, depth_per_site="10000"):
    """Run the script on `depth` identical deletion-carrying reads; return its called indel records."""
    ref = tmp_path / "reference.fasta"
    ref.write_text(f">ref\n{REF}\n")
    subprocess.run(["samtools", "faidx", str(ref)], check=True)
    sam = tmp_path / "input.sam"
    sam.write_text("\n".join(
        ["@HD\tVN:1.6\tSO:coordinate", f"@SQ\tSN:ref\tLN:{len(REF)}"] +
        [f"read{i}\t{0 if i % 2 else 16}\tref\t1\t60\t{CIGAR}\t*\t0\t0\t{READ}\t" + "I" * len(READ)
         for i in range(depth)]) + "\n")
    bam = tmp_path / "barcode01.bam"
    subprocess.run(f"samtools view -bS {sam} | samtools sort -o {bam}", shell=True, check=True)
    subprocess.run(["samtools", "index", str(bam)], check=True)
    env = {**os.environ, "VARIANT_CALL_MODE": "c", "PLOIDY": "2", "VARIANT_CALL_DEPTH": depth_per_site,
           "BASECALL_TIER": "sup"}
    r = subprocess.run(["bash", SCRIPT, str(bam), str(ref), "bc"], capture_output=True, text=True,
                       env=env, cwd=str(tmp_path))
    assert r.returncode == 0, r.stderr + r.stdout
    out = subprocess.run(["bcftools", "view", "-H", "-i", 'INFO/INDEL=1 && ALT!="."',
                          str(tmp_path / "bc_variants.vcf.gz")], capture_output=True, text=True, check=True)
    return [line.split("\t") for line in out.stdout.splitlines()]


def test_sup_profile_calls_a_deletion_below_the_default_indel_depth_cap(tmp_path):
    records = _called_indels(tmp_path, depth=200)
    assert len(records) == 1 and len(records[0][3]) - len(records[0][4]) == DEL_LEN


def test_sup_profile_calls_the_same_deletion_above_the_default_indel_depth_cap(tmp_path):
    records = _called_indels(tmp_path, depth=300)
    assert len(records) == 1 and len(records[0][3]) - len(records[0][4]) == DEL_LEN


def test_sup_profile_calls_the_deletion_where_reads_saturate_the_depth_per_site(tmp_path):
    records = _called_indels(tmp_path, depth=300, depth_per_site="200")
    assert len(records) == 1 and len(records[0][3]) - len(records[0][4]) == DEL_LEN


def test_indel_depth_limit_is_recorded_in_the_run_provenance(tmp_path):
    _called_indels(tmp_path, depth=20)
    words = (tmp_path / "bc_mpileup_provenance.txt").read_text().split()
    assert words[words.index("--max-idepth") + 1] == "1000000000"
