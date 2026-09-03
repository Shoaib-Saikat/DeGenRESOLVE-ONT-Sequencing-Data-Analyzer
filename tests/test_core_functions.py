#!/usr/bin/env python3
"""Regression tests for the DeGenRESOLVE scientific core and report generation.

Every test here pins the behaviour of a defect that was found and fixed. They are written to
run BOTH under pytest and as a plain script (`python3 tests/test_core_functions.py`), because
the bundle does not ship pytest and a reviewer must be able to run them with Python alone.

The modules under test are loaded by path and, where possible, individual functions are
exec'd in isolation, so the suite runs without pysam, Biopython or PyQt5 installed.
"""

import os
import re
import sys
import json
import tempfile
import importlib.util
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src", "degenresolve")
CONSENSUS_EDITOR = os.path.join(SRC, "pipeline", "consensus_editor.py")
HTML_REPORTER = os.path.join(SRC, "pipeline", "html_reporter.py")
CONFIG_PY = os.path.join(SRC, "core", "config.py")


def _extract(path, pattern):
    """Exec a single top-level function out of a module without importing the module."""
    src = open(path).read()
    m = re.search(pattern, src, re.S | re.M)
    if not m:
        raise AssertionError(f"could not locate {pattern!r} in {path}")
    ns = {"Counter": Counter}
    exec(m.group(0), ns)
    return ns


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --------------------------------------------------------------------------- homopolymer
def _hp():
    ns = _extract(CONSENSUS_EDITOR,
                  r"_MAX_HOMOPOLYMER_SCAN = \d+.*?def compute_homopolymer_metrics.*?\n(?=\ndef |\nclass )")
    return ns["compute_homopolymer_metrics"]


FLANK = "CGTA" * 40          # contains no run of length >= 2


def test_homopolymer_detection_radius_is_symmetric():
    """A run within `window` of the site must be found on BOTH sides.

    Regression: the scan region was sliced at pos +/- window, which truncated runs at the
    boundary. With the shipped defaults (window=5, min_length=5) the effective radius was
    1 base, so a site 2 bases past a poly-A was reported as having no homopolymer - exactly
    the ONT positions most prone to indel artefacts.
    """
    hp = _hp()
    ref = FLANK[:146] + "AAAAA" + FLANK[:40]      # 5-mer at 146..150
    assert hp(ref, 145) == (5, 1, True)
    assert hp(ref, 152) == (5, 2, True)
    assert hp(ref, 155) == (5, 5, True)
    assert hp(ref, 156) == (0, 6, False)          # outside the window


def test_homopolymer_length_is_not_clipped_by_the_window():
    """Regression: a true 20-mer poly-A was reported as HP_Len 11 (2*window+1)."""
    hp = _hp()
    ref = FLANK[:50] + "A" * 20 + FLANK[:50]
    assert hp(ref, 60) == (20, 0, True)
    assert hp(ref, 74) == (20, 5, True)


def test_homopolymer_ignores_non_acgt_runs():
    """A run of N is missing data, not a homopolymer."""
    hp = _hp()
    assert _hp()(FLANK[:50] + "N" * 20 + FLANK[:50], 60) == (0, 6, False)


# ------------------------------------------------------------------------- pileup stats
def _gp():
    return _extract(CONSENSUS_EDITOR, r"def get_pileup_statistics.*?\n(?=\ndef )")["get_pileup_statistics"]


def test_major_base_is_not_fabricated_when_no_base_survives_filtering():
    """Regression: sorting all four bases including zero counts put 'A' first purely because
    it sorts first, so a column where nothing passed the quality filter reported
    Major_Base 'A' at 0.0% - which reads as a real call on real evidence."""
    assert _gp()(Counter(), {}, 478)["sorted_bases"] == []


def test_pileup_tie_break_is_deterministic():
    """An exact tie must not be decided by BAM read order or dict ordering."""
    assert _gp()(Counter({"T": 50, "C": 50}), {}, 100)["sorted_bases"] == [("C", 50), ("T", 50)]


# ------------------------------------------------------------------------- segment names
def _segment_type():
    """_segment_type is a method, so wrap it in a throwaway class before exec'ing it."""
    src = open(CONSENSUS_EDITOR).read()
    m = re.search(r"    def _segment_type.*?\n(?=    def )", src, re.S)
    assert m, "could not locate _segment_type"
    ns = {}
    exec("class _T:\n" + m.group(0), ns)
    return ns["_T"]()._segment_type


def test_segment_type_accepts_both_influenza_naming_conventions():
    """Regression: only H<digit>/N<digit> were recognised, so a reference using the NCBI
    Influenza Virus Database convention (HA_/NA_) - the spelling the interface guide and the
    GUI checkbox both advertise - had HA and NA silently dropped from the output FASTA."""
    st = _segment_type()
    assert st("H5_OP023667.1") == "H"
    assert st("HA_MH393827.1") == "H"
    assert st("N1_MH393828.1") == "N"
    assert st("NA_X") == "N"
    assert st("PB2_OP023708.1") == "PB2"
    assert st("M1_X") == "MP"
    assert st("NS1_X") == "NS"
    assert st("NOT_A_SEGMENT") is None


# ------------------------------------------------------------------------------ reporter
def test_report_escapes_untrusted_text():
    """Regression: html_reporter performed no escaping at all. Contig names, sample IDs and
    diagnostic-log reason strings all reach it from outside."""
    hr = _load(HTML_REPORTER, "hr_esc")
    out = hr._table(["Segment"], [("<img src=x onerror=alert(1)>",)])
    assert "<img" not in out
    assert "&lt;img" in out


def test_report_preserves_its_own_markup():
    """Escaping must not destroy the pill badges the module builds itself."""
    hr = _load(HTML_REPORTER, "hr_pill")
    assert 'class="pill' in hr._table(["Tier"], [(hr._pill("hac"),)])


def test_coverage_breadth_is_not_structurally_100_percent():
    """Regression: `samtools depth` without -a emits no zero-depth rows, so breadth was
    pinned at 100.0% and zero-coverage at 0 for every barcode regardless of the real result."""
    hr = _load(HTML_REPORTER, "hr_cov")
    with tempfile.TemporaryDirectory() as d:
        # produced WITH -a: 60 of 100 positions covered
        p = os.path.join(d, "with_a.txt")
        with open(p, "w") as f:
            for i in range(1, 61):
                f.write(f"H5_X\t{i}\t50\n")
            for i in range(61, 101):
                f.write(f"H5_X\t{i}\t0\n")
        stats = hr.parse_coverage(p)
        assert stats["breadth"] == "60.0%"
        assert stats["zero_cov"] == 40
        assert stats["breadth_verified"] is True

        # produced WITHOUT -a: the same sample, uncovered positions simply absent
        p2 = os.path.join(d, "no_a.txt")
        with open(p2, "w") as f:
            for i in range(1, 61):
                f.write(f"H5_X\t{i}\t50\n")
        stats2 = hr.parse_coverage(p2)
        assert stats2["breadth_verified"] is False, "must flag that breadth is indeterminate"
        assert stats2["note"]


def test_residual_ambiguity_counts_every_iupac_code():
    """Regression: only the literal character N was counted, so a sequence full of R/Y/S/W -
    the entire point of this tool - reported zero residual ambiguity."""
    hr = _load(HTML_REPORTER, "hr_fa")
    with tempfile.NamedTemporaryFile("w", suffix=".fa", delete=False) as f:
        f.write(">seg1\nAARYWNNNNNGCGC\n")
        path = f.name
    try:
        row = hr.parse_consensus_fasta(path)["sequences"][0]
        assert row["n_count"] == 5
        assert row["ambiguous_count"] == 8       # R, Y, W + 5 N
        assert row["degenerate_count"] == 3
    finally:
        os.unlink(path)


def test_missing_diagnostic_log_is_not_published_as_a_perfect_result():
    """Regression: the parser returned a fully-zeroed dict on failure, so a barcode whose log
    was missing appeared in the summary as '0 ambiguous / 0 resolved' - the best-looking row."""
    hr = _load(HTML_REPORTER, "hr_diag")
    assert hr.parse_diagnostic_log("/definitely/not/here.txt")["parsed"] is False


def test_soft_mask_is_preserved_and_reported():
    """Lowercase in the consensus FASTA marks a low-confidence call and must survive.

    Regression, two halves. (1) `consensus_editor._process_sequence` uppercased the whole
    draft, destroying vcf2fq's soft-mask (depth < 3 or quality < 10) so every position was
    published as equally confident. (2) `html_reporter.parse_consensus_fasta` then also
    uppercased on read, so even once the mask survived, no report could show it.

    On the shipped demo data this is the difference between barcode01 at 0.3% low-confidence
    and barcode09 at 60.2% - the single most important fact about the latter sample.
    """
    hr = _load(HTML_REPORTER, "hr_soft")
    with tempfile.NamedTemporaryFile("w", suffix=".fa", delete=False) as f:
        # 4 lowercase (low-confidence) of 12; GC counted over ACGT regardless of case
        f.write(">seg1\nACGTacgtACGT\n")
        path = f.name
    try:
        row = hr.parse_consensus_fasta(path)["sequences"][0]
        assert row["length"] == 12
        assert row["soft_masked"] == 4, f"expected 4 lowercase, got {row['soft_masked']}"
        assert abs(row["soft_masked_pct"] - 100 * 4 / 12) < 0.01
        # case must not leak into the composition figures
        assert row["acgt_count"] == 12
        assert row["gc_pct"] == "50.0%"
        assert row["ambiguous_count"] == 0
    finally:
        os.unlink(path)


def test_soft_mask_absent_is_reported_as_zero():
    """A fully uppercase consensus must report 0% low-confidence, not crash or omit."""
    hr = _load(HTML_REPORTER, "hr_soft0")
    with tempfile.NamedTemporaryFile("w", suffix=".fa", delete=False) as f:
        f.write(">seg1\nACGTACGTACGT\n")
        path = f.name
    try:
        row = hr.parse_consensus_fasta(path)["sequences"][0]
        assert row["soft_masked"] == 0
        assert row["soft_masked_pct"] == 0.0
    finally:
        os.unlink(path)


def test_styled_values_render_as_markup_not_literal_text():
    """A .val span placed in a table cell must render, not appear as literal text.

    Regression: adding cell escaping to _table() made every cell escape its input, but several
    tables still built '<span class="val">...</span>' as a plain f-string. Those tags were then
    escaped and displayed to the user as literal markup - visible in the Qualimap per-contig
    table, Analysis Parameters, Input Files, per-segment Degeneracy and Tool Versions.

    val() is the fix: it returns trusted markup wrapping an escaped value, so the tags render
    while the value itself is still neutralised.
    """
    hr = _load(HTML_REPORTER, "hr_val")
    out = hr._table(["Name", "Mean coverage"],
                    [("H9_NC_004908.1", hr.val(f"{318.16:.2f}"))])
    assert '<span class="val">318.16</span>' in out, "styled value did not render"
    assert "&lt;span" not in out, "markup was escaped and would show as literal text"


def test_val_escapes_its_own_content():
    """val() must not become a hole in the escaping it was introduced alongside."""
    hr = _load(HTML_REPORTER, "hr_val2")
    v = hr.val("<script>alert(1)</script>")
    assert "<script>" not in v
    assert "&lt;script&gt;" in v
    # and it must still be trusted markup, so the span itself survives a table cell
    assert '<span class="val">' in hr._table(["x"], [(v,)])


def test_no_unwrapped_val_spans_remain_in_the_reporter():
    """Guard against reintroducing the bug elsewhere in the module.

    Any '<span class="val">' built as a plain f-string is a candidate for the same defect, so
    the module should construct them only through val().
    """
    import re
    src = open(HTML_REPORTER).read()
    src = src.split("def val(", 1)[1].split("\n\n\n", 1)[1]   # skip val()'s own definition
    offenders = re.findall(r"""f'<span class="val">""", src)
    assert not offenders, f"{len(offenders)} inline .val span(s) not routed through val()"


def test_every_cell_helper_returns_renderable_markup():
    """Helpers that build a table cell must return trusted markup, or their tags show as text.

    Regression: _tier_cell, _profile_cell and _bq_cell each build pill/val markup for the
    Analysis Parameters table. Once _table() started escaping cells, any helper returning a
    plain str had its tags escaped and displayed literally in the GUI report viewer.
    _profile_cell was missed in the first pass and shipped that way.

    This checks the class rather than one helper, so a new cell helper cannot reintroduce it.
    """
    hr = _load(HTML_REPORTER, "hr_cells")
    prov_sup = {"mpileup_flags": "--indels-cns -B -Q 1 --max-BQ 35",
                "basecall_tier": "sup", "detected_tier": "hac", "force_sup_profile": "true"}
    prov_hac = {"mpileup_flags": "-B -Q 5 --max-BQ 30 -I",
                "basecall_tier": "hac", "detected_tier": "hac", "force_sup_profile": "false"}
    cases = [
        ("_tier_cell",    lambda: hr._tier_cell(prov_sup)),
        ("_tier_cell",    lambda: hr._tier_cell({})),
        ("_profile_cell", lambda: hr._profile_cell(prov_hac)),
        ("_profile_cell", lambda: hr._profile_cell(prov_sup)),
        ("_profile_cell", lambda: hr._profile_cell({})),
        ("_bq_cell",      lambda: hr._bq_cell({"variant_call_settings": {}}, prov_hac)),
        ("_bq_cell",      lambda: hr._bq_cell({"variant_call_settings": {"min_base_quality": 5}}, prov_sup)),
    ]
    for name, call in cases:
        cell = call()
        rendered = hr._table(["Parameter", "Value"], [("x", cell)])
        assert "&lt;span" not in rendered, f"{name} output was escaped and would show as literal tags"
        assert "&lt;code" not in rendered, f"{name} output was escaped and would show as literal tags"
        if "<span" in str(cell):
            assert "<span" in rendered, f"{name} markup was lost"


def test_profile_cell_escapes_the_flags_it_interpolates():
    """The mpileup flag string comes from a file on disk, so it is not trusted input."""
    hr = _load(HTML_REPORTER, "hr_prof")
    out = hr._profile_cell({"mpileup_flags": "-I <script>alert(1)</script>",
                            "force_sup_profile": "false"})
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_report_generation_runs_end_to_end_and_emits_no_literal_tags():
    """Render a real report and assert no markup leaks through as text.

    This is the test that would have caught two defects the unit tests missed:

    1. build_barcode_report() assigned a local named `_pill`, which made the module-level
       _pill() helper local to the whole function, so an earlier call raised
       UnboundLocalError and report generation crashed. The pipeline invokes the reporter
       with stderr suppressed, so reports silently stayed stale instead of failing loudly.
    2. Helpers returning plain str instead of raw() had their tags escaped and shown to the
       user as literal text.

    Unit-testing the helpers individually caught neither. Only rendering the whole page does.
    """
    import glob
    hr = _load(HTML_REPORTER, "hr_e2e")
    root = os.path.join(HERE, "..", "..", "..", "test_data")
    results = os.path.join(root, "results")
    if not os.path.isdir(results):
        import pytest
        pytest.skip("shipped test_data/results not present")
    barcodes = sorted(
        os.path.basename(p).replace("_consensus_edited.fasta", "")
        for p in glob.glob(os.path.join(results, "step_8_refined_consensus", "*_consensus_edited.fasta")))
    assert barcodes, "no barcodes to render"

    ref = glob.glob(os.path.join(root, "reference", "*.fasta"))
    cfg = os.path.join(root, "pipeline_config.json")
    import json
    config = json.load(open(cfg)) if os.path.exists(cfg) else {}

    for bc in barcodes:
        html = hr.build_barcode_report(bc, results, config, ref[0] if ref else "",
                                       "2026-01-01 00:00:00")
        assert html, f"{bc}: empty report"
        for tag in ("&lt;span", "&lt;div", "&lt;td", "&lt;p", "&lt;code", "&lt;table"):
            assert tag not in html, f"{bc}: {tag} shown as literal text in the report"
        # and the markup that should render, does
        assert '<span class="pill' in html or '<span class="val"' in html, \
            f"{bc}: no styled markup rendered at all"


def test_diagnostic_log_table_excludes_trailing_sections():
    """The per-site table must stop before INDEL DECISIONS / INDEL EVIDENCE.

    Regression: the results viewer's section state machine had no exit from the "tsv" state,
    so every later line - section headings, explanatory prose, and the 5-column indel evidence
    table - was appended to the 28-column per-site table and rendered as malformed rows
    (87 of 643 rows on the shipped example log).

    The parsing rule is reproduced here rather than importing the viewer, which needs Qt
    WebEngine; the assertion is on the rule the viewer uses.
    """
    import glob
    logs = glob.glob(os.path.join(HERE, "..", "..", "..", "test_data", "log",
                                  "*_consensus_edited_diagnostic_log.txt"))
    if not logs:
        import pytest
        pytest.skip("shipped diagnostic log not present")

    for path in logs:
        section, tsv = None, []
        for line in (l.rstrip("\n") for l in open(path)):
            if line.startswith("Segment\t") and section in ("params", "skip_mapping", None):
                section = "tsv"
            if section == "tsv":
                if line.startswith("===") or line.startswith("---") or not line.strip():
                    continue
                if "\t" not in line:          # end of the tabular section
                    section = "after_tsv"
                    continue
                tsv.append(line)
            elif "SEGMENT MAPPING" in line:
                section = "skip_mapping"
            elif section is None:
                section = "params"
        assert tsv, f"{path}: no table rows parsed"
        width = len(tsv[0].split("\t"))
        bad = [r for r in tsv[1:] if len(r.split("\t")) != width]
        assert not bad, (f"{os.path.basename(path)}: {len(bad)} malformed rows would render "
                         f"in the per-site table, e.g. {bad[0][:60]!r}")


def test_degeneracy_threshold_normalisation_agrees_across_shell_and_python():
    """The CLI and the config loader must normalise the threshold identically.

    Regression, twice over. The rule accepts both the percentage form (20) and the legacy
    0-1 fraction form (0.2). A bound of `<= 1` also catches a literal 1, turning a deliberate
    1% threshold - "resolve almost everything" - into 100%, "resolve almost nothing". That
    inversion was fixed in the GUI and in core/config.py, then reintroduced in the shell.

    This compares the shell's awk expression against the Python rule across the range, so the
    two cannot drift apart again.
    """
    import re, subprocess
    sh_path = os.path.join(SRC, "scripts", "_clean_master_cmd_with_config.sh")
    src = open(sh_path).read()
    m = re.search(r"_DEG_PCT=\$\(awk -v v=\"\$DEGENERACY_THRESHOLD\" 'BEGIN\{(.*?)\}'\)", src, re.S)
    assert m, "could not locate the awk normalisation in the pipeline script"
    body = m.group(1)

    def python_rule(v):
        v = float(v)
        if 0 < v < 1:
            v = v * 100.0
        return int(max(1, min(100, round(v))))

    for v in ("0.01", "0.2", "0.5", "0.99", "1", "1.0", "2", "20", "100", "150", "0"):
        out = subprocess.run(["awk", "-v", f"v={v}", "BEGIN{" + body + "}"],
                             capture_output=True, text=True).stdout.strip()
        assert out, f"awk produced nothing for {v}"
        assert int(out) == python_rule(v), (
            f"threshold {v}: shell gives {out}, python gives {python_rule(v)}")


# ------------------------------------------------------------------------- GUI lifecycle
PROCESSOR_PY = os.path.join(SRC, "pipeline", "processor.py")


def _processor_class():
    """Build a standalone stand-in for PipelineProcessor's lifecycle methods.

    processor.py imports PyQt5 transitively, so the state machine is exec'd in isolation.
    """
    import threading, re
    src = open(PROCESSOR_PY).read()
    def grab(name):
        m = re.search(rf"    def {name}\(self.*?\n(?=    def |\Z)", src, re.S)
        assert m, f"could not locate {name}()"
        return m.group(0)
    body = grab("reset") + grab("is_running") + grab("mark_finished")
    ns = {"threading": threading}
    exec("class P:\n"
         "    def __init__(s):\n"
         "        s._finished = False\n"
         "        s.stop_flag = threading.Event()\n"
         "        s.worker = None\n" + body, ns)
    return ns["P"]


def test_reset_after_a_successful_run_does_not_raise():
    """reset() must never raise: it is called from a Qt slot, and PyQt aborts the process.

    Regression: the guard tested `worker is not None and not stop_flag.is_set()`. After a
    SUCCESSFUL run both hold - the worker reference is still set and the stop flag was never
    set - so reset() raised RuntimeError. The call chain is
    on_job_finished -> reset_session -> processor.reset(), all inside a Qt signal handler, and
    an unhandled exception there takes the whole application down. The app therefore closed
    itself at the end of every successful analysis.
    """
    P = _processor_class()
    p = P()
    p.worker = object()      # a worker ran
    p.mark_finished()        # and completed normally; stop flag never set
    p.reset()                # must not raise
    assert p.worker is None, "reset() should have cleared the finished worker"


def test_reset_refuses_to_swap_the_stop_flag_of_a_live_run():
    """The safety property the guard existed for must survive the crash fix.

    A live worker polls the Event object it was handed; replacing it would leave the pipeline
    unstoppable. reset() must decline - quietly, without raising.
    """
    P = _processor_class()
    p = P()
    p.worker = object()      # live run: worker set, not finished, stop flag clear
    original_flag = p.stop_flag
    p.reset()                # must not raise
    assert p.stop_flag is original_flag, "stop flag was swapped out from under a live worker"
    assert p.worker is not None, "live worker was cleared"


def test_is_running_is_false_once_a_run_has_finished():
    """Regression: is_running() inferred liveness from the stop flag, so it reported True
    forever after the first successful analysis."""
    P = _processor_class()
    p = P()
    assert p.is_running() is False          # nothing started
    p.worker = object()
    assert p.is_running() is True           # running
    p.mark_finished()
    assert p.is_running() is False          # finished


# -------------------------------------------------------------------------------- config
def test_malformed_config_raises_json_error_not_type_error():
    """Regression: the re-raise built JSONDecodeError with one argument, which raises
    TypeError instead - so a bad config surfaced as an unrelated crash naming no file."""
    cfg = _load(CONFIG_PY, "cfg_mod")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write('{"min_coverage": 100,,}')
        path = f.name
    try:
        try:
            cfg.ConfigManager(path).load_config(path)
        except json.JSONDecodeError:
            pass
        except TypeError as e:                     # the original defect
            raise AssertionError(f"still raises TypeError: {e}")
    finally:
        os.unlink(path)


def test_default_config_covers_the_documented_keys():
    """Regression: parallel and advanced_criteria keys were absent, so a headless run using
    the defaults silently went single-threaded with no advanced filters configured."""
    cfg = _load(CONFIG_PY, "cfg_keys")
    d = cfg.ConfigManager.DEFAULT_CONFIG
    for key in ("parallel_enabled", "parallel_threads", "strand_balance_threshold",
                "homopolymer_min_length", "homopolymer_window", "read_end_threshold",
                "read_end_edge_fraction", "strict_strand_bias", "strict_homopolymer",
                "strict_read_end"):
        assert key in d, f"DEFAULT_CONFIG is missing {key}"


def _main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            print(f"  FAIL  {name}: {e}")
            failed.append(name)
        except Exception as e:
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
            failed.append(name)
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
