"""Tests for consensus_editor core logic (no BAM/pysam needed)."""
from collections import Counter

from src.degenresolve.pipeline.consensus_editor import (
    ConsensusDegeneracyProcessor,
    SiteMetrics,
    get_pileup_statistics,
)


def _loader(tmp_path, contents):
    """Drive _load_consensus_sequences without a BAM or a full __init__."""
    fasta = tmp_path / "barcode01_consensus.fasta"
    fasta.write_text(contents)
    proc = object.__new__(ConsensusDegeneracyProcessor)
    proc.sample_id = "barcode01"
    proc.consensus_file = str(fasta)
    proc.diagnostic_mode = False
    return proc._load_consensus_sequences()


def test_site_metrics_defaults():
    m = SiteMetrics()
    assert m.coverage == 0
    assert m.decision == ""
    assert m.warning_flags == []


def test_site_metrics_populated():
    m = SiteMetrics(segment="HA", coverage=500, decision="RESOLVE", resolved_base="G")
    assert m.segment == "HA"
    assert m.resolved_base == "G"


def test_load_consensus_strips_sample_prefix(tmp_path):
    # Drafts published to step_7 carry a "<sample_id>_" prefix that stops segment
    # matching, which previously produced a silent 0-degeneracy run.
    seqs = _loader(tmp_path, ">barcode01_H9_NC_004908.1\nACGT\n>barcode01_N2_ON497150.1\nACGT\n")
    assert sorted(seqs) == ["H9_NC_004908.1", "N2_ON497150.1"]


def test_load_consensus_keeps_unprefixed_ids(tmp_path):
    seqs = _loader(tmp_path, ">H9_NC_004908.1\nACGT\n")
    assert list(seqs) == ["H9_NC_004908.1"]


def test_load_consensus_strips_prefix_only_at_start(tmp_path):
    seqs = _loader(tmp_path, ">PB2_barcode01_OP023708.1\nACGT\n")
    assert list(seqs) == ["PB2_barcode01_OP023708.1"]


def test_get_pileup_statistics():
    base_counts = Counter({"A": 10, "G": 80, "C": 5, "T": 5})
    strand_counts = {
        "A": {"forward": 5, "reverse": 5},
        "G": {"forward": 40, "reverse": 40},
        "C": {"forward": 3, "reverse": 2},
        "T": {"forward": 2, "reverse": 3},
    }
    stats = get_pileup_statistics(base_counts, strand_counts, 100)
    assert stats["sorted_bases"][0][0] == "G"
    assert stats["sorted_bases"][0][1] == 80
    assert stats["standard_base_counts"]["A"] == 10


def test_tie_break_is_insertion_order_independent():
    """An exact count tie must resolve alphabetically, not by BAM read order.

    base_counts is a Counter filled in pileup order, so before the fixed
    tie-break the same tie came out differently depending on which read the
    aligner happened to emit first - i.e. on the machine.
    """
    proc = object.__new__(ConsensusDegeneracyProcessor)
    proc.min_coverage = 10
    proc.min_percentage_diff = 20
    proc.diagnostic_mode = False
    proc.indel_insertions = "equal_or_more"
    proc.indel_deletions = "equal_or_more"
    proc.indel_custom_percentage = 50.0
    proc.degeneracy_codes = {"R": ["A", "G"]}

    g_first = Counter()
    g_first["G"] = 50
    g_first["A"] = 50
    a_first = Counter()
    a_first["A"] = 50
    a_first["G"] = 50

    out = [
        proc._analyze_degeneracy_decision_enhanced(c, 100, "R", 1, 1)
        for c in (g_first, a_first)
    ]
    assert out[0]["top_base"] == out[1]["top_base"] == "A"
    assert out[0]["second_base"] == out[1]["second_base"] == "G"
    # A true tie stays ambiguous: the degenerate code is kept either way.
    assert out[0]["decision"] == out[1]["decision"] == "KEEP"


# ---------------------------------------------------------------------------
# Coverage denominators
#
# pysam's pileup_column.n is NOT base-quality filtered, but the base counts drawn
# from the same column are. Gating on n let a column clear min_coverage on reads
# that never got a vote: measured on barcode01 NP 1086, n=478 with 88 bases
# surviving -Q5.
# ---------------------------------------------------------------------------

def _decider(min_coverage=100, min_percentage_diff=20):
    proc = object.__new__(ConsensusDegeneracyProcessor)
    proc.min_coverage = min_coverage
    proc.min_percentage_diff = min_percentage_diff
    proc.degeneracy_codes = {"R": ["A", "G"], "Y": ["C", "T"]}
    return proc


def test_gate_uses_called_bases_not_raw_depth():
    """The NP 1086 shape: deep column, few usable bases."""
    counts = Counter({"A": 60, "G": 28, "DEL": 361})
    analysis = _decider()._analyze_degeneracy_decision_enhanced(
        counts, 478, "R", 100, 100)
    assert analysis["decision"] == "KEEP"
    assert analysis["usable_coverage"] == 88
    # the reason must show both numbers, or the log looks like a contradiction
    assert "88 usable of 478" in analysis["reason"]


def test_gate_passes_when_enough_bases_are_called():
    counts = Counter({"A": 90, "G": 20, "DEL": 5})
    analysis = _decider()._analyze_degeneracy_decision_enhanced(
        counts, 400, "R", 100, 100)
    assert analysis["decision"] == "RESOLVE"
    assert analysis["resolved_base"] == "A"
    assert analysis["usable_coverage"] == 110


def test_deletions_never_count_toward_usable_coverage():
    """A column that is almost all deletions must not clear the gate."""
    counts = Counter({"A": 15, "DEL": 90})
    analysis = _decider()._analyze_degeneracy_decision_enhanced(
        counts, 105, "R", 100, 100)
    assert analysis["decision"] == "KEEP"
    assert analysis["usable_coverage"] == 15


def test_n_bases_do_not_count_toward_usable_coverage():
    counts = Counter({"A": 60, "G": 30, "N": 50})
    analysis = _decider()._analyze_degeneracy_decision_enhanced(
        counts, 140, "R", 100, 100)
    assert analysis["usable_coverage"] == 90
    assert analysis["decision"] == "KEEP"
