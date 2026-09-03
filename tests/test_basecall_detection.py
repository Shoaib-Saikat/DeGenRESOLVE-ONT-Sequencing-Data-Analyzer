"""Tests for basecall model detection and input fingerprinting.

The awk-equivalence test is the important one: this module replaced an awk block
in _clean_master_cmd_with_config.sh, and the tier it returns decides the mpileup
flag set. A silent divergence would change variant calling.
"""
import gzip
import os
import subprocess
import sys

# Loaded by path, not as a package member: src/degenresolve/__init__.py pulls in
# PyQt5, and this module is deliberately standalone - the pipeline shells out to
# it with plain python3, so it must import with nothing else installed.
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "basecall",
    os.path.join(os.path.dirname(__file__), "..", "src", "degenresolve",
                 "utils", "basecall.py"))
basecall = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(basecall)

AWK = r'''NR % 4 == 1 {
        total++
        if (match($0, /basecall_model_version_id=[^ \t]+/))
            c[substr($0, RSTART + 26, RLENGTH - 26)]++
     }
     END {
        n = 0; best = ""; bestc = 0
        for (k in c) { n++; if (c[k] > bestc) { bestc = c[k]; best = k } }
        print (n ? best : "unknown"), bestc + 0, total + 0, n
     }'''

HAC = "dna_r10.4.1_e8.2_400bps_hac@v4.3.0"
SUP = "dna_r10.4.1_e8.2_400bps_sup@v5.0.0"


def _read(i, model=None):
    head = f"@read{i} runid=x"
    if model:
        head += f" basecall_model_version_id={model}"
    return f"{head}\nACGT\n+\n!!!!\n"


def _write(path, models, gz=False):
    body = "".join(_read(i, m) for i, m in enumerate(models))
    opener = gzip.open if gz else open
    with opener(path, "wt") as fh:
        fh.write(body)
    return path


def test_uniform_hac(tmp_path):
    f = _write(tmp_path / "a.fastq", [HAC] * 10)
    r = basecall.detect([str(f)])
    assert (r["model"], r["tier"], r["distinct"], r["total"]) == (HAC, "hac", 1, 10)


def test_gzip_is_read(tmp_path):
    f = _write(tmp_path / "a.fastq.gz", [SUP] * 4, gz=True)
    r = basecall.detect([str(f)])
    assert r["tier"] == "sup" and r["total"] == 4


def test_mixed_models_are_visible(tmp_path):
    f = _write(tmp_path / "a.fastq", [HAC] * 6 + [SUP] * 3)
    r = basecall.detect([str(f)])
    # The majority wins, but distinct>1 is what the pipeline hard-exits on.
    assert r["distinct"] == 2 and r["model"] == HAC


def test_headerless_is_unknown(tmp_path):
    f = _write(tmp_path / "a.fastq", [None] * 5)
    r = basecall.detect([str(f)])
    assert r["distinct"] == 0 and r["tier"] == "unknown" and r["total"] == 5


def test_fast_and_unknown_tiers():
    assert basecall.tier_for("dna_r10.4.1_e8.2_400bps_fast@v4.3.0") == "fast"
    assert basecall.tier_for("something_else") == "unknown"
    assert basecall.tier_for("") == "unknown"


def test_matches_awk(tmp_path):
    """The replaced awk and this module must agree exactly."""
    for models in ([HAC] * 7, [HAC] * 5 + [SUP] * 2, [None] * 3, []):
        f = _write(tmp_path / "eq.fastq", models)
        awk = subprocess.run(["awk", AWK, str(f)], capture_output=True, text=True)
        r = basecall.detect([str(f)])
        mine = f"{r['model']} {r['count']} {r['total']} {r['distinct']}\n"
        assert awk.stdout == mine, f"{models}: awk={awk.stdout!r} py={mine!r}"


def test_signature_tracks_content(tmp_path):
    d = tmp_path / "barcode01"
    d.mkdir()
    _write(d / "a.fastq.gz", [HAC] * 3, gz=True)
    first = basecall.input_signature(str(d))
    _write(d / "b.fastq.gz", [HAC] * 3, gz=True)
    assert basecall.input_signature(str(d)) != first, "new file must change signature"


def test_signature_of_missing_dir_is_empty_shaped():
    assert basecall.input_signature("/nonexistent/barcode99") == "0:0:0"
