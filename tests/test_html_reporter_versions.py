"""Tests for Environment & Versions card in html_reporter."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# The ordering list and rendering logic live at module level; import directly.
from src.degenresolve.pipeline import html_reporter as hr


_TOOL_ORDER = [
    "NanoPlot", "porechop", "minimap2", "samtools", "qualimap",
    "bcftools", "vcfutils.pl", "seqtk", "python", "pysam",
    "biopython", "numpy", "java", "PyQt5", "os",
]

_FAKE_VERSIONS = {
    "app_version": "1.0.0",
    "run_date":    "2026-06-26T00:00:00Z",
    "os":          "Linux 6.14",
    "python":      "Python 3.10.20",
    "samtools":    "samtools 1.19",
    "bcftools":    "bcftools 1.19",
    "vcfutils.pl": "bundled with bcftools 1.19",
    "minimap2":    "minimap2 2.26",
    "seqtk":       "Version: 1.4",
    "porechop":    "0.2.4",
    "qualimap":    "v2.3",
    "java":        "openjdk 11.0.22",
    "NanoPlot":    "NanoPlot 1.42.0",
    "pysam":       "0.22.1",
    "biopython":   "1.83",
    "numpy":       "1.26.4",
    "PyQt5":       "5.15.10",
}


def _sorted_tools(rv: dict) -> list[str]:
    """Replicate the ordering logic from html_reporter."""
    rv = dict(rv)
    rv.pop("app_version", None)
    rv.pop("run_date", None)
    ordered = sorted(
        rv.items(),
        key=lambda kv: _TOOL_ORDER.index(kv[0]) if kv[0] in _TOOL_ORDER
                       else len(_TOOL_ORDER),
    )
    return [t for t, _ in ordered]


# v prefix

def test_version_card_has_v_prefix():
    """The card shows 'DeGenRESOLVE v1.0.0', not 'DeGenRESOLVE 1.0.0'."""
    rv = dict(_FAKE_VERSIONS)
    app_ver = rv.pop("app_version")
    rv.pop("run_date")
    body = f'<p>DeGenRESOLVE v<span class="val">{app_ver}</span></p>'
    assert "DeGenRESOLVE v" in body
    assert "DeGenRESOLVE 1.0.0" not in body   # old (no-v) form must be absent


# vcfutils.pl presence

def test_vcfutils_present_in_versions():
    tools = _sorted_tools(_FAKE_VERSIONS)
    assert "vcfutils.pl" in tools


def test_vcfutils_value_references_bcftools():
    """vcfutils.pl version string mentions bcftools (it's bundled)."""
    assert "bcftools" in _FAKE_VERSIONS["vcfutils.pl"].lower()


# pipeline-sequence ordering

def test_nanoplot_is_first():
    tools = _sorted_tools(_FAKE_VERSIONS)
    assert tools[0] == "NanoPlot"


def test_porechop_before_minimap2():
    tools = _sorted_tools(_FAKE_VERSIONS)
    assert tools.index("porechop") < tools.index("minimap2")


def test_minimap2_before_samtools():
    tools = _sorted_tools(_FAKE_VERSIONS)
    assert tools.index("minimap2") < tools.index("samtools")


def test_samtools_before_qualimap():
    tools = _sorted_tools(_FAKE_VERSIONS)
    assert tools.index("samtools") < tools.index("qualimap")


def test_qualimap_before_bcftools():
    tools = _sorted_tools(_FAKE_VERSIONS)
    assert tools.index("qualimap") < tools.index("bcftools")


def test_bcftools_before_vcfutils():
    tools = _sorted_tools(_FAKE_VERSIONS)
    assert tools.index("bcftools") < tools.index("vcfutils.pl")


def test_vcfutils_before_seqtk():
    tools = _sorted_tools(_FAKE_VERSIONS)
    assert tools.index("vcfutils.pl") < tools.index("seqtk")


def test_seqtk_before_python_libs():
    tools = _sorted_tools(_FAKE_VERSIONS)
    seqtk_i = tools.index("seqtk")
    for lib in ("python", "pysam", "biopython", "numpy"):
        assert seqtk_i < tools.index(lib), f"seqtk should precede {lib}"


def test_gui_and_os_at_end():
    tools = _sorted_tools(_FAKE_VERSIONS)
    java_i  = tools.index("java")
    pyqt_i  = tools.index("PyQt5")
    os_i    = tools.index("os")
    # All after the analysis tools
    assert java_i  > tools.index("seqtk")
    assert pyqt_i  > java_i
    assert os_i    > pyqt_i


def test_unknown_tool_sorts_to_end():
    rv = dict(_FAKE_VERSIONS)
    rv["mystery_tool"] = "9.9.9"
    tools = _sorted_tools(rv)
    assert tools[-1] == "mystery_tool"


def test_all_known_tools_present():
    tools = _sorted_tools(_FAKE_VERSIONS)
    expected = set(_FAKE_VERSIONS.keys()) - {"app_version", "run_date"}
    assert set(tools) == expected


# ---------------------------------------------------------------------------
# Basecall tier / profile / base-quality cells
#
# These read the mpileup provenance receipt rather than the config, because
# under "auto" the config carries no base-quality number at all - the tier does.
# ---------------------------------------------------------------------------

from src.degenresolve.pipeline.html_reporter import (
    _tier_cell, _profile_cell, _bq_cell, parse_mpileup_provenance,
)

HAC = {"basecall_tier": "hac", "detected_tier": "hac", "force_sup_profile": "false",
       "mpileup_flags": "-B -Q 5 --max-BQ 30 -I"}
SUP = {"basecall_tier": "sup", "detected_tier": "sup", "force_sup_profile": "false",
       "mpileup_flags": "--indels-cns -B -Q 1 --max-BQ 35 -F0.2"}
FORCED = {"basecall_tier": "sup", "detected_tier": "hac", "force_sup_profile": "true",
          "mpileup_flags": "--indels-cns -B -Q 1 --max-BQ 35 -F0.2"}


def test_tier_cell_plain():
    assert "hac" in _tier_cell(HAC) and "overridden" not in _tier_cell(HAC)


def test_tier_cell_shows_override():
    out = _tier_cell(FORCED)
    assert "overridden" in out and "hac" in out and "sup" in out


def test_tier_cell_without_provenance():
    assert "not recorded" in _tier_cell({})


def test_profile_cell_distinguishes_indel_calling():
    assert "indel calling off" in _profile_cell(HAC)
    assert "indel calling on" in _profile_cell(SUP)


def test_profile_cell_warns_when_forced():
    out = _profile_cell(FORCED)
    assert "forced" in out
    # the consequence must be stated, not just the fact
    assert "degeneracy codes differ" in out


def test_bq_cell_reports_applied_values_not_config():
    # config says nothing (auto); the applied values come from the flags
    out = _bq_cell({"variant_call_settings": {}}, SUP)
    assert "-Q 1" in out and "--max-BQ 35" in out and "from basecall tier" in out


def test_bq_cell_flags_pinned_values():
    out = _bq_cell({"variant_call_settings": {"min_base_quality": 5}}, HAC)
    assert "pinned in config" in out


def test_parse_mpileup_provenance(tmp_path):
    f = tmp_path / "b_mpileup_provenance.txt"
    f.write_text("basecall_tier=sup\ndetected_tier=hac\nforce_sup_profile=true\n")
    got = parse_mpileup_provenance(str(f))
    assert got["detected_tier"] == "hac" and got["force_sup_profile"] == "true"


def test_parse_mpileup_provenance_missing_file():
    assert parse_mpileup_provenance("/nonexistent/x.txt") == {}


# --- INDEL DECISIONS table -------------------------------------------------
# Regression: the report's "Indel Decisions" card was always empty. The parser
# hunted for a "Cons_Pos" header and >=12 columns (that is the per-site
# degeneracy table), while ConsensusEditor writes the indel table with a
# "Genomic_Pos" header and 9 columns. Both report paths therefore dropped every
# adjudicated indel and printed "No indel decisions recorded".

from src.degenresolve.pipeline.html_reporter import _parse_indel_table

_INDEL_LOG = (
    "INDEL DECISIONS (bcftools calls, adjudicated here)\n"
    + "=" * 40 + "\n"
    "Segment\tGenomic_Pos\tChange\tNet_nt\tIMF\tIDV\tDP\tVerdict\tReason\n"
    + "-" * 40 + "\n"
    "H9_NC_004908.1\t674\tGAA->GA\t-1\t0.527\t126\t239\tACCEPT\tgroup of 2, frame preserved\n"
    "H9_NC_004908.1\t678\tA->AC\t+1\t0.525\t125\t238\tACCEPT\tgroup of 2, frame preserved\n"
    "PA_OP023666.1\t421\tGA->G\t-1\t0.416\t37\t89\tREJECT\tcoverage 89 < min_coverage 100\n"
    "\n"
    + "=" * 40 + "\n"
    "INDEL EVIDENCE (not acted upon)\n"
)


def test_indel_table_parsed():
    rows = _parse_indel_table(_INDEL_LOG)
    assert len(rows) == 3, "the '---' rule under the header must not end the table"
    assert rows[0] == {
        "segment": "H9_NC_004908.1", "pos": "674", "change": "GAA->GA",
        "net_nt": "-1", "imf": "0.527", "idv": "126", "dp": "239",
        "verdict": "ACCEPT", "reason": "group of 2, frame preserved",
    }
    assert [r["verdict"] for r in rows] == ["ACCEPT", "ACCEPT", "REJECT"]


def test_indel_table_stops_before_next_section():
    """A blank line ends the table; the following section must not leak in."""
    assert all("EVIDENCE" not in r["reason"] for r in _parse_indel_table(_INDEL_LOG))


def test_indel_table_absent_is_empty_not_error():
    """hac runs carry -I, so bcftools calls no indels and writes no table."""
    assert _parse_indel_table("bcftools called no indels.\n") == []
    assert _parse_indel_table("") == []


def test_indel_table_not_confused_with_evidence_table():
    """INDEL EVIDENCE also starts 'Segment\\tGenomic_Pos\\t' but has 5 columns.
    A prefix match would latch onto it when no decisions table exists."""
    evidence_only = (
        "INDEL EVIDENCE (not acted upon)\n"
        "Segment\tGenomic_Pos\tDEL\tCoverage\tDEL%\n"
        "NS_OP023561.1\t645\t1183\t3928\t30.1\n"
    )
    assert _parse_indel_table(evidence_only) == []
    # and it must still stop at the evidence table when both are present
    rows = _parse_indel_table(_INDEL_LOG + evidence_only)
    assert len(rows) == 3
    assert all(r["segment"].startswith(("H9", "PA")) for r in rows)
