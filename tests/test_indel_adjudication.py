"""Tests for indel adjudication: IMF gating, frame grouping, splicing.

No BAM or VCF needed - the adjudicator is driven from plain dicts, the same
shape _read_vcf_indels() produces.
"""
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from src.degenresolve.pipeline.consensus_editor import ConsensusDegeneracyProcessor


def _proc(orfs=None, indels=None, *, min_coverage=100,
          deletions="equal_or_more", insertions="equal_or_more", custom=50.0):
    p = object.__new__(ConsensusDegeneracyProcessor)
    p._orfs = orfs
    p._vcf_indels = indels or {}
    p.min_coverage = min_coverage
    p.indel_deletions = deletions
    p.indel_insertions = insertions
    p.indel_custom_percentage = custom
    p.diagnostic_mode = False
    return p


def _indel(pos, ref, alt, imf, dp):
    return {'pos': pos, 'ref': ref, 'alt': alt, 'dlen': len(alt) - len(ref),
            'imf': imf, 'idv': int(imf * dp), 'dp': dp}


def _verdicts(decisions):
    return {d[0]['pos']: d[1] for d in decisions}


# --- the case that motivated the grouping rule ------------------------------
# H9:674 GAA->GA (-1) and H9:678 A->AC (+1) sit four bases apart inside the HA
# ORF. Judged one at a time each frameshifts the gene and truncates a 560 aa
# protein to ~217. Judged together they net zero and leave one amino acid
# changed. bcftools proposes both and cannot tell the difference.

def test_compensating_pair_accepted_together():
    p = _proc(orfs={"H9": (32, 1714)},
              indels={"H9": [_indel(674, "GAA", "GA", 0.527, 239),
                             _indel(678, "A", "AC", 0.525, 238)]})
    accepted, decisions = p._adjudicate_indels("H9")
    assert _verdicts(decisions) == {674: 'ACCEPT', 678: 'ACCEPT'}
    assert len(accepted) == 2
    assert "nets +0 nt" in decisions[0][2]


def test_lone_frameshift_rejected():
    p = _proc(orfs={"H9": (32, 1714)},
              indels={"H9": [_indel(674, "GAA", "GA", 0.527, 239)]})
    accepted, decisions = p._adjudicate_indels("H9")
    assert accepted == []
    assert _verdicts(decisions) == {674: 'REJECT'}
    assert "frameshift" in decisions[0][2]


def test_pair_too_far_apart_is_not_grouped():
    """Beyond INDEL_GROUP_WINDOW they cannot compensate - each is judged alone."""
    far = ConsensusDegeneracyProcessor.INDEL_GROUP_WINDOW + 5
    p = _proc(orfs={"H9": (32, 1714)},
              indels={"H9": [_indel(674, "GAA", "GA", 0.6, 239),
                             _indel(674 + far, "A", "AC", 0.6, 239)]})
    accepted, decisions = p._adjudicate_indels("H9")
    assert accepted == []
    assert set(_verdicts(decisions).values()) == {'REJECT'}


def test_in_frame_deletion_accepted():
    p = _proc(orfs={"H9": (32, 1714)},
              indels={"H9": [_indel(500, "GACT", "G", 0.8, 400)]})   # -3 nt
    accepted, decisions = p._adjudicate_indels("H9")
    assert len(accepted) == 1
    assert _verdicts(decisions) == {500: 'ACCEPT'}


def test_frameshift_outside_orf_rejected():
    """Frame is required across the whole segment, not only inside the primary ORF.

    _load_orfs finds the longest M..* stretch - the primary product only. Influenza's
    spliced products (M2, NEP) have their second exon outside that span, so gating the
    frame test on in_orf applied out-of-frame indels there with no check at all. This
    test previously asserted that acceptance; it now asserts the guard.
    """
    p = _proc(orfs={"H9": (32, 100)},
              indels={"H9": [_indel(1500, "GA", "G", 0.8, 400)]})
    accepted, decisions = p._adjudicate_indels("H9")
    assert accepted == []
    assert decisions[0][1] == "REJECT"
    assert "outside primary ORF" in decisions[0][2]


def test_in_frame_outside_orf_still_accepted():
    """Only frame-breaking indels are stopped; a multiple of 3 is fine anywhere."""
    p = _proc(orfs={"H9": (32, 100)},
              indels={"H9": [_indel(1500, "GACT", "G", 0.8, 400)]})   # net -3
    accepted, decisions = p._adjudicate_indels("H9")
    assert len(accepted) == 1
    assert decisions[0][1] == "ACCEPT"


def test_frameshift_rejected_when_no_orf_detected():
    """A segment with no detectable ORF used to accept every indel unchecked."""
    p = _proc(orfs={}, indels={"H9": [_indel(500, "GA", "G", 0.8, 400)]})
    accepted, decisions = p._adjudicate_indels("H9")
    assert accepted == []
    assert decisions[0][1] == "REJECT"


# --- the two gates that run before the frame test ---------------------------

def test_low_coverage_rejected():
    p = _proc(orfs={"H9": (32, 1714)},
              indels={"H9": [_indel(500, "GACT", "G", 0.9, 35)]}, min_coverage=100)
    accepted, decisions = p._adjudicate_indels("H9")
    assert accepted == []
    assert "coverage 35 < min_coverage 100" in decisions[0][2]


def test_imf_below_rule_rejected():
    p = _proc(orfs={"H9": (32, 1714)},
              indels={"H9": [_indel(500, "GACT", "G", 0.416, 400)]})
    accepted, decisions = p._adjudicate_indels("H9")
    assert accepted == []
    assert "IMF 0.416 fails equal_or_more" in decisions[0][2]


def test_imf_gate_rule_mapping():
    p = _proc()
    assert p._imf_gate(0.50, "equal_or_more")[0] is True
    assert p._imf_gate(0.50, "more_than")[0] is False
    assert p._imf_gate(0.51, "more_than")[0] is True
    p.indel_custom_percentage = 30.0
    assert p._imf_gate(0.30, "custom_percentage")[0] is True
    assert p._imf_gate(0.29, "custom_percentage")[0] is False


# --- splicing ---------------------------------------------------------------

def test_apply_indels_preserves_frame_and_resolved_bases():
    # ORF at position 1: ATG + 9 codons + TAA
    orf = "ATG" + "GCT" * 9 + "TAA"
    rec = SeqRecord(Seq(orf), id="seg")
    before = str(Seq(orf).translate())
    assert before == "MAAAAAAAAA*"

    # delete one base at 5, insert one back at 9 -> frame restored downstream
    accepted = [_indel(4, "GGC", "GC", 0.6, 400), _indel(8, "T", "TC", 0.6, 400)]
    out = str(_proc()._apply_indels(rec, accepted).seq)
    assert len(out) == len(orf)                      # -1 then +1
    after = str(Seq(out).translate())
    assert after.endswith("*") and after.count("*") == 1   # frame intact
    assert after != before                                 # but not identical


def test_apply_indels_right_to_left_is_order_safe():
    rec = SeqRecord(Seq("AAAACCCCGGGGTTTT"), id="seg")
    accepted = [_indel(1, "AA", "A", 0.9, 400), _indel(13, "TT", "T", 0.9, 400)]
    out = str(_proc()._apply_indels(rec, accepted).seq)
    assert out == "AAACCCCGGGGTTT"


# --- ORF discovery ----------------------------------------------------------

def test_load_orfs_finds_longest_reading_frame():
    orf = "ATG" + "GCT" * 20 + "TAA"
    seq = "CCC" + orf + "GGG"                 # ORF starts at 1-based 4
    p = _proc()
    p._orfs = None
    p.reference_sequences = {"seg": SeqRecord(Seq(seq), id="seg")}
    assert p._load_orfs()["seg"] == (4, 3 + len(orf))


if __name__ == "__main__":
    # pytest is not installed in the runtime environment; run the asserts directly.
    import sys, traceback
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in fns:
        try:
            fn()
            print(f"  PASS  {name}")
        except Exception:
            failed += 1
            print(f"  FAIL  {name}")
            traceback.print_exc()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
    sys.exit(1 if failed else 0)


# --- allele-set guard on the single-base path -------------------------------
# The guard stops a site being resolved to a base its own ambiguity code declares
# impossible. It used to live only inside the threshold branch, so the
# "only one base type found" shortcut returned RESOLVE without consulting it.

def _degen_proc():
    """_proc() builds the bare object the indel tests need; the degeneracy engine
    additionally reads degeneracy_codes and min_percentage_diff."""
    p = _proc(orfs={}, indels={}, min_coverage=10)
    p.degeneracy_codes = {'R': ['A', 'G'], 'Y': ['C', 'T'], 'S': ['G', 'C'],
                          'W': ['A', 'T'], 'K': ['G', 'T'], 'M': ['A', 'C'],
                          'N': ['A', 'C', 'G', 'T']}
    p.min_percentage_diff = 20
    return p


def test_allele_set_guard_applies_to_single_base_shortcut():
    from collections import Counter
    p = _degen_proc()
    # site called R (A/G) but every surviving read says C
    a = p._analyze_degeneracy_decision_enhanced(
        Counter({"C": 200}), 200, "R", 1, 1)
    assert a["decision"] == "KEEP"
    assert a.get("allele_set_conflict") is True
    assert "not in the R allele set" in a["reason"]


def test_single_base_within_allele_set_still_resolves():
    from collections import Counter
    p = _degen_proc()
    a = p._analyze_degeneracy_decision_enhanced(
        Counter({"A": 200}), 200, "R", 1, 1)      # A is in R = A/G
    assert a["decision"] == "RESOLVE"
    assert a["resolved_base"] == "A"


def test_n_code_is_not_enforced():
    """N's allele set is all four bases, so there is nothing to enforce."""
    from collections import Counter
    p = _degen_proc()
    a = p._analyze_degeneracy_decision_enhanced(
        Counter({"C": 200}), 200, "N", 1, 1)
    assert a["decision"] == "RESOLVE"
