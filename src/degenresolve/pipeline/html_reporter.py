#!/usr/bin/env python3
"""
DeGenRESOLVE - HTML Summary Report Generator

Produces a self-contained, single-file HTML report for each barcode
and a combined summary for all barcodes in the run.

Usage (called automatically by the pipeline after Step 6):
    python3 html_reporter.py \\
        --barcode barcode01 \\
        --results-dir ./results \\
        --config pipeline_config.json \\
        --reference reference/reference.fasta

Author : Shoaib Saikat
Version: 1.0.0
"""

import argparse
import html as _html
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Optional


# Data parsers

def parse_config(config_path: str) -> dict:
    try:
        with open(config_path) as f:
            return json.load(f)
    except Exception:
        return {}


def parse_coverage(coverage_path: str) -> dict:
    """Parse `samtools depth -a` output -> coverage statistics.

    REQUIRES the depth file to have been produced with -a. Plain `samtools depth` emits only
    positions that already carry at least one read, so the file cannot contain a depth-0 row
    and every statistic derived from it is degenerate: zero-coverage is structurally 0,
    breadth is structurally 100.0%, minimum depth is never below 1, and the mean is divided by
    covered positions rather than reference length. That made a half-covered sample
    indistinguishable from a complete one on every report.

    Files produced by an older pipeline are detected and reported as indeterminate rather than
    silently republished as a perfect result.
    """
    stats = {"mean": "N/A", "min": "N/A", "max": "N/A",
             "positions": 0, "zero_cov": 0, "breadth": "N/A",
             "per_contig": {}, "contigs": 0, "breadth_verified": True, "note": ""}
    try:
        depths = []
        per_contig = {}
        with open(coverage_path) as f:
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) >= 3:
                    try:
                        d = int(parts[2])
                    except ValueError:
                        continue
                    depths.append(d)
                    c = per_contig.setdefault(parts[0], {"positions": 0, "zero": 0, "sum": 0})
                    c["positions"] += 1
                    c["sum"] += d
                    if d == 0:
                        c["zero"] += 1
        if depths:
            zero_cov = sum(1 for d in depths if d == 0)
            stats["positions"] = len(depths)
            stats["mean"]      = f"{sum(depths) / len(depths):.1f}"
            stats["min"]       = min(depths)
            stats["max"]       = max(depths)
            stats["zero_cov"]  = zero_cov
            covered            = len(depths) - zero_cov
            stats["breadth"]   = f"{100 * covered / len(depths):.1f}%"
            stats["contigs"]   = len(per_contig)
            stats["per_contig"] = {
                name: {
                    "positions": c["positions"],
                    "zero": c["zero"],
                    "mean": round(c["sum"] / c["positions"], 1) if c["positions"] else 0.0,
                    "breadth": (f"{100 * (c['positions'] - c['zero']) / c['positions']:.1f}%"
                                if c["positions"] else "N/A"),
                }
                for name, c in sorted(per_contig.items())
            }
            if zero_cov == 0:
                # No depth-0 row anywhere. Either genuinely complete coverage, or the file was
                # written without -a. Say so instead of publishing an unqualified 100.0%.
                stats["breadth_verified"] = False
                stats["note"] = (
                    "No zero-depth rows are present in this file. If it was produced by a "
                    "pipeline version that ran `samtools depth` without -a, uncovered "
                    "positions are simply absent and breadth cannot be computed from it; "
                    "re-run the alignment step to obtain a definitive figure.")
    except Exception:
        pass
    return stats


def parse_nanostats(nanostats_path: str) -> dict:
    """Parse NanoPlot NanoStats.txt."""
    stats = {}
    key_map = {
        "mean read length":    "mean_length",
        "mean read quality":   "mean_quality",
        "median read length":  "median_length",
        "median read quality": "median_quality",
        "number of reads":     "num_reads",
        "read length n50":     "n50",
        "total bases":         "total_bases",
    }
    try:
        with open(nanostats_path) as f:
            for line in f:
                line = line.strip()
                for raw_key, out_key in key_map.items():
                    if line.lower().startswith(raw_key):
                        val = line.split(":")[-1].strip().replace(",", "")
                        stats[out_key] = val
    except Exception:
        pass
    return stats


def parse_qualimap(qualimap_dir: str) -> dict:
    """Parse qualimap genome_results.txt."""
    stats = {}
    results_file = Path(qualimap_dir) / "genome_results.txt"
    if not results_file.exists():
        return stats
    try:
        with open(results_file) as f:
            text = f.read()
        patterns = {
            "num_reads":    r"number of reads\s*=\s*([\d,]+)",
            "mapped_reads": r"number of mapped reads\s*=\s*([\d,]+)",
            "mapping_rate": r"number of mapped reads\s*=\s*[\d,]+\s*\(([\d.]+%)\)",
            "mean_cov":     r"mean coverageData\s*=\s*([\d.]+)",
            "std_cov":      r"std coverageData\s*=\s*([\d.]+)",
            "bases_mapped": r"number of mapped bases\s*=\s*([\d,]+ bp)",
        }
        for key, pat in patterns.items():
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                stats[key] = m.group(1)
    except Exception:
        pass
    return stats


def parse_coverage_per_contig(qualimap_dir: str) -> list:
    """Parse the 'Coverage per contig' table from qualimap genome_results.txt.

    Returns a list of dicts (name, length, mapped_bases, mean_cov, std),
    one per reference contig, in qualimap's native order.
    """
    rows = []
    results_file = Path(qualimap_dir) / "genome_results.txt"
    if not results_file.exists():
        return rows
    try:
        text = results_file.read_text()
        marker = ">>>>>>> Coverage per contig"
        if marker not in text:
            return rows
        for line in text.split(marker, 1)[1].splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                rows.append({
                    "name":         parts[0],
                    "length":       int(parts[1]),
                    "mapped_bases": int(parts[2]),
                    "mean_cov":     float(parts[3]),
                    "std":          float(parts[4]),
                })
            except ValueError:
                continue
    except Exception:
        pass
    return rows


def parse_qc_summary(qc_json_path: str) -> dict:
    """Read the consensus editor's own QC JSON.

    The editor writes <barcode>_consensus_edited_qc_summary.json with exact counts. Scraping
    them back out of the human-readable diagnostic log was fragile in both directions: the
    per-segment regex required a trailing "Resolution rate:" line that is omitted for any
    segment with zero degeneracies (so those segments vanished from the report), and the
    indel counter searched for the string "Insertions accepted", which nothing in the codebase
    ever emits (so "Resolved to Insertion" was permanently 0). Prefer the JSON; fall back to
    the log only when the JSON is absent.
    """
    try:
        with open(qc_json_path) as f:
            summary = json.load(f)
    except Exception:
        return {}
    if not isinstance(summary, dict):
        return {}

    out = {
        "source": "qc_json",
        "total_degeneracies": summary.get("total_sites_examined", 0),
        "total_resolved":     summary.get("resolved_to_dominant_base", 0),
        "total_kept":         summary.get("retained_as_iupac", 0),
        "resolved_to_ins":    summary.get("converted_to_indel", 0),
        "resolved_to_del":    summary.get("indels_rejected_by_guard", 0),
        "low_coverage":       summary.get("retained_low_coverage", 0),
        "strict_reverted":    summary.get("retained_strict_mode_revert", 0),
        "allele_conflict":    summary.get("retained_allele_set_conflict", 0),
        "unaccounted":        summary.get("sites_unaccounted_for", 0),
        "flagged_strand_bias":  summary.get("flagged_strand_bias", 0),
        "flagged_homopolymer":  summary.get("flagged_homopolymer", 0),
        "flagged_read_end":     summary.get("flagged_read_end_enrichment", 0),
        "coverage_summary":        summary.get("coverage_summary", {}),
        "usable_coverage_summary": summary.get("usable_coverage_summary", {}),
        "segments": [],
        "indel_decisions": [],
    }
    total = out["total_degeneracies"] or 0
    out["resolution_rate"] = (f"{100 * out['total_resolved'] / total:.1f}%" if total else "N/A")
    out["resolved_to_bases"] = out["total_resolved"]
    for name, info in (summary.get("per_segment") or {}).items():
        seg_total = info.get("total_degeneracies", 0)
        seg_res = info.get("resolved", 0)
        out["segments"].append({
            "name": name,
            "total": seg_total,
            "resolved": seg_res,
            "kept": info.get("kept", 0),
            # Computed, not scraped: a segment with zero degeneracies is a legitimate result
            # and must still appear in the table.
            "rate": (f"{100 * seg_res / seg_total:.1f}%" if seg_total else "n/a"),
        })
    return out


_INDEL_HEADER = "Segment\tGenomic_Pos\tChange\tNet_nt\tIMF\tIDV\tDP\tVerdict\tReason"


def _parse_indel_table(text: str) -> list:
    """Rows of the diagnostic log's INDEL DECISIONS table.

    Written by ConsensusEditor as:
        Segment  Genomic_Pos  Change  Net_nt  IMF  IDV  DP  Verdict  Reason
    Tab-separated, 9 columns, terminated by a blank line or a rule of '=' / '-'.
    Returns [] when the section is absent (hac runs call no indels) or empty.
    """
    rows = []
    in_table = False
    for line in text.splitlines():
        # Exact header. The INDEL EVIDENCE table that follows also begins
        # "Segment\tGenomic_Pos\t", so a prefix match would latch onto it too.
        if line.rstrip("\n") == _INDEL_HEADER:
            in_table = True
            continue
        if in_table:
            stripped = line.strip()
            if not stripped:
                break
            if set(stripped) <= {"-", "="}:
                continue          # the rule the writer prints under the header
            parts = line.split("\t")
            if len(parts) < 9:
                continue
            rows.append({
                "segment": parts[0], "pos": parts[1], "change": parts[2],
                "net_nt":  parts[3], "imf": parts[4], "idv":    parts[5],
                "dp":      parts[6], "verdict": parts[7], "reason": parts[8],
            })
    return rows


def parse_diagnostic_log(log_path: str) -> dict:
    """Parse consensus degeneracy diagnostic log."""
    stats = {
        "total_degeneracies": 0,
        "total_resolved":     0,
        "total_kept":         0,
        "resolution_rate":    "N/A",
        "resolved_to_bases":  0,
        "resolved_to_del":    0,
        "resolved_to_ins":    0,
        "low_coverage_kept":  0,
        "ambiguous_kept":     0,
        "segments":           [],
        "indel_decisions":    [],
        # False until a parse actually succeeds. This dict is fully populated with zeros, so
        # the callers' `.get(key, "N/A")` fallbacks could never fire and a barcode whose log
        # was missing or unreadable was published as "0 Ambiguous / 0 Resolved" - visually the
        # best possible result - rather than as unknown.
        "parsed":             False,
    }
    try:
        with open(log_path) as f:
            text = f.read()

        # Summary stats
        m = re.search(r"Total degeneracies processed:\s*(\d+)", text)
        if m: stats["total_degeneracies"] = int(m.group(1))
        m = re.search(r"Total degeneracies resolved:\s*(\d+)", text)
        if m: stats["total_resolved"] = int(m.group(1))
        m = re.search(r"Total kept unchanged:\s*(\d+)", text)
        if m: stats["total_kept"] = int(m.group(1))
        m = re.search(r"Resolution rate:\s*([\d.]+%)", text)
        if m: stats["resolution_rate"] = m.group(1)
        m = re.search(r"Total resolved to deletions:\s*(\d+)", text)
        if m: stats["resolved_to_del"] = int(m.group(1))
        stats["resolved_to_bases"] = stats["total_resolved"] - stats["resolved_to_del"]

        # Per-segment stats
        seg_pattern = re.compile(
            r"^\s{2}(\S+):\s*$.*?"
            r"Total degeneracies:\s*(\d+).*?"
            r"Resolved:\s*(\d+).*?"
            r"Kept:\s*(\d+).*?"
            r"Resolution rate:\s*([\d.]+%)",
            re.MULTILINE | re.DOTALL,
        )
        for m in seg_pattern.finditer(text):
            stats["segments"].append({
                "name":     m.group(1),
                "total":    m.group(2),
                "resolved": m.group(3),
                "kept":     m.group(4),
                "rate":     m.group(5),
            })

        # Indel decisions live only in the diagnostic log's own table, whose header is
        # "Segment\tGenomic_Pos\t..." (9 columns). This used to hunt for "Cons_Pos" and
        # require >=12 columns, which is the per-site degeneracy table, not this one - so the
        # indel table was never parsed and the report's "Indel Decisions" card was always
        # empty even when indels had been adjudicated. See _parse_indel_table().
        stats["indel_decisions"] = _parse_indel_table(text)
        stats["resolved_to_ins"] = sum(1 for d in stats["indel_decisions"]
                                       if d["verdict"] == "ACCEPT")
        stats["parsed"] = True

    except Exception:
        # Leave parsed=False so callers can render "N/A" rather than a fabricated zero.
        pass
    return stats


def parse_mpileup_provenance(path: str) -> dict:
    """key=value lines from <barcode>_mpileup_provenance.txt.

    Records what variant calling actually ran with, including the detected
    basecall tier and whether force_sup_profile overrode it.
    """
    out = {}
    try:
        for line in Path(path).read_text().splitlines():
            if "=" in line:
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip()
    except OSError:
        pass
    return out


def parse_timing(timing_path: str) -> dict:
    """Parse barcode timing JSON."""
    try:
        with open(timing_path) as f:
            data = json.load(f)
        secs = data.get("elapsed_seconds", 0)
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        data["elapsed_fmt"] = f"{h:02d}h:{m:02d}m:{s:02d}s"
        return data
    except Exception:
        return {}


def parse_idxstats(idxstats_path: str) -> list:
    """Parse samtools idxstats TSV -> list of dicts.

    The `*` row carries the count of reads with no coordinate at all - the real "how many
    reads failed to map" figure, and the one that tells a bench scientist whether the
    reference is even the right organism. It was previously dropped by the `!= "*"` filter,
    while the per-reference column 4 (a paired-end concept: mate-mapped-here) was displayed
    as "Unmapped" and is structurally 0 for single-end ONT reads. It is returned here as a
    separate pseudo-row so the caller can report the number that actually means something.
    """
    rows = []
    try:
        with open(idxstats_path) as f:
            for line in f:
                parts = line.strip().split("\t")
                if len(parts) < 4:
                    continue
                try:
                    length, mapped, unmapped = int(parts[1]), int(parts[2]), int(parts[3])
                except ValueError:
                    continue
                if parts[0] == "*":
                    rows.append({"ref": "*", "length": 0, "mapped": mapped,
                                 "unmapped": unmapped, "is_unplaced": True})
                else:
                    rows.append({"ref": parts[0], "length": length, "mapped": mapped,
                                 "unmapped": unmapped, "is_unplaced": False})
    except Exception:
        pass
    return rows


def parse_hn_selection(hn_path: str) -> dict:
    """Parse the H/N dominant segment selection JSON."""
    try:
        with open(hn_path) as f:
            return json.load(f)
    except Exception:
        return {}


def parse_consensus_fasta(fasta_path: str) -> dict:
    """Basic FASTA stats - length, GC%, remaining N count."""
    stats = {}
    try:
        seqs = {}
        current = None
        with open(fasta_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith(">"):
                    current = line[1:].split()[0]
                    seqs[current] = []
                elif current:
                    # NOT .upper(): lowercase marks a low-confidence position
                    # (vcf2fq soft-mask, depth < 3 or quality < 10). Uppercasing here
                    # discarded the very signal the report needs to show.
                    seqs[current].append(line)
        # Residual ambiguity is every IUPAC degeneracy code, not just the literal N. Counting
        # only N reported zero residual ambiguity for a sequence full of R/Y/S/W/K/M - which
        # is precisely what this tool exists to produce - and contradicted the "Retained
        # (ambiguous)" figure taken from the diagnostic log on the same page.
        _IUPAC_AMBIG = set("RYSWKMBDHVN")
        rows = []
        for name, parts in seqs.items():
            seq = "".join(parts)
            up        = seq.upper()
            n_only    = up.count("N")
            ambiguous = sum(1 for c in up if c in _IUPAC_AMBIG)
            # Low-confidence positions carried over from the variant caller's soft-mask.
            soft      = sum(1 for c in seq if c.islower())
            # GC% over unambiguous ACGT only. Including N and every degenerate code in the
            # denominator depressed GC% for low-coverage segments, and S (G/C) and the other
            # GC-containing codes were never counted toward it.
            acgt = sum(up.count(b) for b in "ACGT")
            gc   = sum(up.count(b) for b in "GC")
            rows.append({
                "name": name,
                "length": len(seq),
                "gc_pct": f"{100 * gc / acgt:.1f}%" if acgt else "N/A",
                "n_count": n_only,
                "ambiguous_count": ambiguous,
                "degenerate_count": ambiguous - n_only,
                "acgt_count": acgt,
                "soft_masked": soft,
                "soft_masked_pct": (100.0 * soft / len(seq)) if seq else 0.0,
            })
        stats["sequences"] = rows
    except Exception:
        stats["sequences"] = []
    return stats


# HTML generation

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: 'Segoe UI', Arial, sans-serif;
    background: #1a2332;
    color: #e0e6ef;
    font-size: 14px;
    line-height: 1.6;
}
.page-wrap { max-width: 1200px; margin: 0 auto; padding: 24px 20px 60px; }
header {
    background: linear-gradient(135deg, #1e3a5f, #2980b9);
    border-radius: 10px 10px 0 0;
    padding: 28px 32px;
}
.sticky-nav {
    position: sticky;
    top: 0;
    z-index: 11;
}
header h1 { font-size: 26px; font-weight: 700; color: #fff; }
header .sub { color: #a8d4f5; font-size: 13px; margin-top: 6px; }
.badge {
    display: inline-block;
    background: #f59e0b;
    color: #1a2332;
    border-radius: 4px;
    padding: 2px 10px;
    font-size: 15px;
    font-weight: 700;
    margin-left: 10px;
    vertical-align: middle;
}
.card {
    background: #243447;
    border-radius: 8px;
    margin-bottom: 22px;
    overflow: hidden;
    border: 1px solid #2d4560;
}
.card-header {
    background: linear-gradient(90deg, #1e3a5f, #243447);
    padding: 12px 20px;
    font-size: 15px;
    font-weight: 600;
    color: #5dade2;
    border-bottom: 1px solid #2d4560;
    display: flex;
    align-items: center;
    gap: 10px;
}
.card-header .icon { font-size: 18px; }
.card-body { padding: 18px 20px; }
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
}
th {
    background: #1e2f44;
    color: #7fb3d3;
    padding: 9px 14px;
    text-align: left;
    font-weight: 600;
    border-bottom: 2px solid #2d4560;
}
td {
    padding: 8px 14px;
    border-bottom: 1px solid #2a3d55;
    vertical-align: top;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: #2a3d55; }
a { color: #a0b4c4; text-decoration: none; }
a:hover { color: #e0e8f0; text-decoration: underline; }
.val { color: #7dcea0; font-weight: 600; font-family: monospace; }
.warn-val { color: #f39c12; font-weight: 600; }
.good { color: #27ae60; }
.bad  { color: #e74c3c; }
.changed { color: #f39c12; }
.unchanged { color: #7fb3d3; }
.stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 14px;
}
.stat-box {
    background: #1e2f44;
    border-radius: 6px;
    padding: 14px 16px;
    text-align: center;
    border: 1px solid #2d4560;
}
.stat-box .num {
    font-size: 24px;
    font-weight: 700;
    color: #5dade2;
    display: block;
}
.stat-box .lbl {
    font-size: 11px;
    color: #7fb3d3;
    margin-top: 4px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}
details { margin: 0; }
details summary {
    cursor: pointer; color: #5dade2; font-weight: 600;
    font-size: 13px; padding: 6px 0; list-style: none;
}
details summary::before { content: "> "; }
details[open] summary::before { content: "v "; }
.link-list { list-style: none; }
.link-list li { margin: 6px 0; }
.link-list a {
    color: #a0b4c4;
    text-decoration: none;
    font-size: 13px;
}
.link-list a:hover { text-decoration: underline; color: #e0e8f0; }
.pill {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 600;
}
.pill-green { background: #1a3d2b; color: #7dcea0; }
.pill-blue  { background: #1a2f4a; color: #5dade2; }
.pill-amber { background: #3d2e0a; color: #f39c12; }
.pill-red   { background: #3d0f0f; color: #e74c3c; }
.toc { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 0; padding: 12px 0; background: #1a2332; border-radius: 0 0 10px 10px; border-top: 1px solid #2d4560; }
.toc a {
    background: #1e3a5f;
    color: #a8d4f5;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 12px;
    text-decoration: none;
    border: 1px solid #2d4560;
}
.toc a:hover { background: #2980b9; color: #fff; }
footer {
    text-align: center;
    color: #4a6278;
    font-size: 12px;
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid #2d4560;
}
"""


def _pill(val, good_fn=None) -> str:
    """Colour-code a value with a pill badge."""
    if good_fn is None:
        return raw(f'<span class="pill pill-blue">{esc(val)}</span>')
    return raw(f'<span class="pill pill-green">{esc(val)}</span>'
               if good_fn(val)
               else f'<span class="pill pill-amber">{esc(val)}</span>')


def _tier_cell(prov: dict) -> str:
    """Detected tier, flagging when an override replaced it."""
    applied  = prov.get("basecall_tier", "unknown")
    detected = prov.get("detected_tier", applied)
    if not prov:
        return raw('<span class="val">not recorded</span>')
    if detected != applied:
        return raw(f'<span class="pill pill-amber">{esc(detected)} &rarr; {esc(applied)}</span>'
                   f' <span class="val">overridden</span>')
    good = detected in ("hac", "sup")
    css = "pill-green" if good else "pill-amber"
    return raw(f'<span class="pill {css}">{esc(detected)}</span>')


def _profile_cell(prov: dict) -> str:
    """Which bcftools profile ran, and whether indels could be called at all."""
    if not prov:
        return raw('<span class="val">not recorded</span>')
    flags = prov.get("mpileup_flags", "")
    forced = prov.get("force_sup_profile", "false") == "true"
    if "--indels-cns" in flags:
        label, css = "ont-sup (indel calling on)", "pill-green"
    elif " -I" in f" {flags}":
        label, css = "ont (indel calling off, -I)", "pill-blue"
    else:
        label, css = "custom", "pill-amber"
    out = f'<span class="pill {css}">{esc(label)}</span>'
    if forced:
        out += (' <span class="pill pill-amber">forced</span>'
                '<p style="margin:6px 0 0;font-size:12px">force_sup_profile applied the sup flag '
                'set regardless of the detected tier. This also changes -Q and --max-BQ, so SNV '
                'calls and degeneracy codes differ from an un-overridden run.</p>')
    out += f'<p style="margin:6px 0 0;font-size:12px"><code>{esc(flags or "not recorded")}</code></p>'
    return raw(out)


def _bq_cell(config: dict, prov: dict) -> str:
    """Applied -Q / --max-BQ, and whether they came from the tier or were pinned."""
    flags = prov.get("mpileup_flags", "")
    q = re.search(r"-Q\s*(\d+)", flags)
    m = re.search(r"--max-BQ\s*(\d+)", flags)
    vcs = config.get("variant_call_settings", {}) or {}
    pinned = vcs.get("min_base_quality") is not None
    if not (q or m):
        return raw('<span class="val">not recorded</span>')
    val_ = val(f'-Q {q.group(1) if q else "?"} / --max-BQ {m.group(1) if m else "?"}')
    src = ("pinned in config" if pinned else "from basecall tier")
    css = "pill-amber" if pinned else "pill-green"
    return raw(f'{val_} <span class="pill {css}">{esc(src)}</span>')


def esc(value) -> str:
    """Escape a value for interpolation into generated HTML.

    Barcode names, reference paths, contig names, FASTA record IDs and the free-text reason
    strings from the diagnostic log all originate outside this module - from the filesystem,
    the reference FASTA and tool output. None of them were escaped, so a `<` in any of them
    silently broke the page structure. Markup that this module builds itself is passed
    through `raw()` instead.
    """
    return _html.escape(str(value), quote=True)


class raw(str):
    """Marks a string as trusted markup built by this module, exempt from esc() in tables."""


def val(value) -> "raw":
    """A value styled with the .val class, safe to place in a table cell.

    Returns trusted markup so _table()/_stat_grid() do not escape the tags, while the value
    itself is escaped. Building this span inline as a plain f-string caused the markup to be
    displayed literally once cell escaping was introduced.
    """
    return raw('<span class="val">' + esc(value) + '</span>')


def _cell(value) -> str:
    return str(value) if isinstance(value, raw) else esc(value)


def _card(title: str, icon: str, body: str) -> str:
    return (f'<div class="card">'
            f'<div class="card-header"><span class="icon">{icon}</span>{esc(title)}</div>'
            f'<div class="card-body">{body}</div></div>')


def _table(headers: list, rows: list) -> str:
    ths = "".join(f"<th>{_cell(h)}</th>" for h in headers)
    trs = ""
    for row in rows:
        tds = "".join(f"<td>{_cell(c)}</td>" for c in row)
        trs += f"<tr>{tds}</tr>"
    return f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>"


def _stat_grid(items: list) -> str:
    """items = list of (label, value) tuples."""
    boxes = ""
    for label, value in items:
        boxes += (f'<div class="stat-box">'
                  f'<span class="num">{_cell(value)}</span>'
                  f'<span class="lbl">{_cell(label)}</span></div>')
    return f'<div class="stat-grid">{boxes}</div>'


def build_barcode_report(
    barcode: str,
    results_dir: str,
    config: dict,
    reference_path: str,
    run_date: str,
) -> str:
    """Build the full HTML for one barcode."""
    results = Path(results_dir)
    data_dir = results.parent
    reports_base = results / "reports"

    # Collect all data
    coverage_file   = results / f"step_4_mapped/{barcode}/{barcode}.coverage"
    nanostats_file  = results / f"step_1_raw_read_qc_nanoplot/{barcode}/NanoStats.txt"
    qualimap_dir    = results / f"step_5_alignment_qc_qualimap/{barcode}/qualimap_output_{barcode}"
    diag_log        = data_dir / "log" / f"{barcode}_consensus_edited_diagnostic_log.txt"
    consensus_fasta = results / f"step_8_refined_consensus/{barcode}_consensus_edited.fasta"
    nanoplot_html   = results / f"step_1_raw_read_qc_nanoplot/{barcode}/NanoPlot-report.html"
    qualimap_html   = results / f"step_5_alignment_qc_qualimap/{barcode}/qualimap_output_{barcode}/qualimapReport.html"

    timing_file  = results / f"reports/{barcode}_timing.json"
    idxstats_file = results / f"step_4_mapped/{barcode}/{barcode}_idxstats.tsv"
    hn_sel_file   = results / f"step_4_mapped/{barcode}/{barcode}_hn_selection.json"

    cov_stats  = parse_coverage(str(coverage_file))     if coverage_file.exists()  else {}
    nano_stats = parse_nanostats(str(nanostats_file))   if nanostats_file.exists() else {}
    qual_stats = parse_qualimap(str(qualimap_dir))      if qualimap_dir.exists()   else {}
    # Prefer the editor's machine-readable QC JSON; the log scrape is a fallback for runs
    # produced before it existed. See parse_qc_summary() for why the scrape is unreliable.
    qc_json    = results / f"step_8_refined_consensus/{barcode}_consensus_edited_qc_summary.json"
    diag_stats = parse_qc_summary(str(qc_json)) if qc_json.exists() else {}
    if not diag_stats:
        diag_stats = parse_diagnostic_log(str(diag_log)) if diag_log.exists() else {}
    elif diag_log.exists():
        # The QC JSON carries only indel COUNTS; the per-indel verdicts and their IMF/IDV/DP
        # evidence exist solely in the diagnostic log. Without this the preferred JSON path
        # left indel_decisions empty and the report claimed "No indel decisions recorded"
        # while the log held the adjudicated calls.
        try:
            with open(diag_log) as _f:
                diag_stats["indel_decisions"] = _parse_indel_table(_f.read())
        except OSError:
            pass
    fasta_stats= parse_consensus_fasta(str(consensus_fasta)) if consensus_fasta.exists() else {}
    timing     = parse_timing(str(timing_file))          if timing_file.exists()    else {}
    idxstats   = parse_idxstats(str(idxstats_file))     if idxstats_file.exists()  else []
    hn_sel     = parse_hn_selection(str(hn_sel_file))    if hn_sel_file.exists()    else {}

    prov_file = data_dir / f"{barcode}_mpileup_provenance.txt"
    if not prov_file.exists():
        prov_file = reports_base / f"{barcode}_mpileup_provenance.txt"
    provenance = parse_mpileup_provenance(str(prov_file)) if prov_file.exists() else {}

    versions_file = results / "reports/runtime_versions.json"
    try:
        runtime_versions = json.loads(versions_file.read_text()) if versions_file.exists() else {}
    except Exception:
        runtime_versions = {}

    #
    sections = []

    # 1. Parameters
    param_rows = [
        ("Minimum Coverage Threshold",
         val(config.get("min_coverage","N/A"))),
        ("Degeneracy Threshold",
         val(f'{config.get("degeneracy_threshold","N/A")}%')),
        ("Ploidy",
         val(config.get("ploidy","N/A"))),
        ("Filter Mode",
         _pill(config.get("filter_mode", "general"))),
        ("Variant Call Depth",
         val(config.get("variant_call_settings",{}).get("depth_per_site","N/A"))),
        ("Basecall Model / Tier", _tier_cell(provenance)),
        ("Variant-calling Profile", _profile_cell(provenance)),
        ("Base Quality (-Q / --max-BQ)", _bq_cell(config, provenance)),
        ("Variant Call Mode",
         val(config.get("variant_call_settings",{}).get("call_mode","N/A"))),
        ("Indel Insertions Rule",
         val(config.get("indel_rules",{}).get("insertions","N/A"))),
        ("Indel Deletions Rule",
         val(config.get("indel_rules",{}).get("deletions","N/A"))),
        ("Qualimap Enabled",
         _pill("Yes" if config.get("qualimap", {}).get("enabled", True) else "No",
               lambda v: v == "Yes")),
        ("NanoPlot Enabled",
         _pill("Yes" if config.get("nanoplot", {}).get("enabled", True) else "No",
               lambda v: v == "Yes")),
    ]
    body = _table(["Parameter","Value"], param_rows)
    sections.append(_card("Analysis Parameters", "", body))

    # 2. Input files
    input_rows = [
        ("Barcode directory",   val(f'fastq_pass/{barcode}/')),
        ("Reference FASTA",     val(reference_path)),
        ("Run start",           val(timing.get("start", "N/A"))),
        ("Run end",             val(timing.get("end", "N/A"))),
        ("Elapsed time",        val(timing.get("elapsed_fmt", "N/A"))),
        ("Report generated",    val(run_date)),
    ]
    sections.append(_card("Input Files", "",
                          _table(["Item", "Path / Value"], input_rows)))

    # 3. Raw Read QC (NanoPlot)
    if nano_stats:
        items = [
            ("Total Reads",   nano_stats.get("num_reads","N/A")),
            ("Total Bases",   nano_stats.get("total_bases","N/A")),
            ("N50",           nano_stats.get("n50","N/A")),
            ("Mean Length",   nano_stats.get("mean_length","N/A")),
            ("Mean Quality",  nano_stats.get("mean_quality","N/A")),
            ("Median Length", nano_stats.get("median_length","N/A")),
            ("Median Quality",nano_stats.get("median_quality","N/A")),
        ]
        body = _stat_grid(items)
        if nanoplot_html.exists():
            rel = os.path.relpath(str(nanoplot_html), str(reports_base))
            body += (f'<p style="margin-top:14px">'
                     f'<a href="{rel}">Open full NanoPlot report</a></p>')
    else:
        body = "<p style='color:#4a6278'>NanoPlot report not found or NanoPlot was disabled.</p>"
    sections.append(_card("Raw Read Quality - NanoPlot", "", body))

    # 4. Mapping Quality (Qualimap)
    if qual_stats:
        items = [
            ("Total Reads",    qual_stats.get("num_reads","N/A")),
            ("Mapped Reads",   qual_stats.get("mapped_reads","N/A")),
            ("Mapping Rate",   qual_stats.get("mapping_rate","N/A")),
            ("Bases Mapped",   qual_stats.get("bases_mapped","N/A")),
            ("Mean coverage (Qualimap, whole panel)", qual_stats.get("mean_cov","N/A")),
            ("Std Coverage",   qual_stats.get("std_cov","N/A")),
        ]
        body = _stat_grid(items)

        # Coverage across genome - qualimap 2.6 "Chromosome stats" (per-contig).
        # Contigs with zero mean coverage are hidden (a flu reference has many).
        contig_rows = parse_coverage_per_contig(str(qualimap_dir))
        covered = [c for c in contig_rows if c["mean_cov"] > 0]
        if covered:
            hidden = len(contig_rows) - len(covered)
            crows = [(
                c["name"],
                f'{c["length"]:,}',
                f'{c["mapped_bases"]:,}',
                val(f'{c["mean_cov"]:.2f}'),
                f'{c["std"]:.2f}',
            ) for c in covered]
            hidden_note = (f' <span style="color:#4a6278">'
                           f'({hidden} zero-coverage contigs hidden)</span>') if hidden else ''
            body += (f'<p style="color:#7fb3d3;font-size:13px;margin:16px 0 6px">'
                     f'<b>Coverage across genome</b>{hidden_note}</p>')
            body += _table(["Name", "Length (bp)", "Mapped bases",
                            "Mean coverage", "Std"], crows)

        # Coverage across reference - qualimap's coverage-depth-vs-position plot
        # (the same graph shown in the PDF report).
        cov_png = qualimap_dir / "images_qualimapReport" / "genome_coverage_across_reference.png"
        if cov_png.exists():
            rel_png = os.path.relpath(str(cov_png), str(reports_base))
            body += (f'<p style="color:#7fb3d3;font-size:13px;margin:16px 0 6px">'
                     f'<b>Coverage across reference</b></p>'
                     f'<img src="{rel_png}" alt="Coverage across reference" '
                     f'style="max-width:100%;border:1px solid #2d4560;border-radius:6px;background:#fff">')

        # Full report link - prefer the PDF, fall back to the HTML report.
        qualimap_pdf = qualimap_dir / f"{barcode}_qualimap_report.pdf"
        if qualimap_pdf.exists():
            rel = os.path.relpath(str(qualimap_pdf), str(reports_base))
            body += (f'<p style="margin-top:14px">'
                     f'<a href="{rel}">Open full Qualimap report (PDF)</a></p>')
        elif qualimap_html.exists():
            rel = os.path.relpath(str(qualimap_html), str(reports_base))
            body += (f'<p style="margin-top:14px">'
                     f'<a href="{rel}">Open full Qualimap report</a></p>')
    else:
        body = "<p style='color:#4a6278'>Qualimap report not found or Qualimap was disabled.</p>"
    sections.append(_card("Mapping Quality - Qualimap", "", body))

    # 4b. Influenza Segment Selection (only when idxstats available)
    if idxstats:
        # Sort by mapped reads descending
        unplaced = next((r for r in idxstats if r.get("is_unplaced")), None)
        placed = [r for r in idxstats if not r.get("is_unplaced")]
        sorted_idx = sorted(placed, key=lambda r: r["mapped"], reverse=True)
        total_mapped = sum(r["mapped"] for r in sorted_idx)
        idx_rows = []
        for r in sorted_idx:
            pct = f'{100 * r["mapped"] / total_mapped:.1f}%' if total_mapped else "0%"
            is_major_h = hn_sel.get("major_h") == r["ref"]
            is_major_n = hn_sel.get("major_n") == r["ref"]
            tag = ""
            if is_major_h:
                tag = ' <span class="pill pill-green">Dominant HA</span>'
            elif is_major_n:
                tag = ' <span class="pill pill-green">Dominant NA</span>'
            idx_rows.append((
                raw(f'{esc(r["ref"])}{tag}'),
                f'{r["length"]:,}',
                raw(val(f'{r["mapped"]:,}')),
                pct,
            ))
        # Column 4 of idxstats is dropped from this table: it counts mate-mapped-here, a
        # paired-end concept that is 0 on every reference for single-end ONT reads, and a
        # column of zeros reads as "nothing failed to map". The real figure is the `*` row.
        body = _table(["Reference", "Length (bp)", "Mapped reads (primary)", "% of mapped"],
                      idx_rows)
        if unplaced is not None:
            _unmapped_n = unplaced["mapped"] + unplaced["unmapped"]
            _denom = total_mapped + _unmapped_n
            _pct = f"{100 * _unmapped_n / _denom:.1f}%" if _denom else "N/A"
            body += (f'<p style="margin-top:10px"><b>Reads that did not map to any reference:'
                     f'</b> {_unmapped_n:,} ({esc(_pct)} of all reads). A high value means the '
                     f'reference panel may be the wrong organism or the sample is dominated by '
                     f'off-target material.</p>')
        if hn_sel:
            body += ('<p style="margin-top:14px;color:#7fb3d3;font-size:12px">'
                     '<b>Selection rule:</b> dominant HA = H* segment with highest mapped read count; '
                     'dominant NA = N[0-9]*/NA* segment with highest mapped read count '
                     '(from <code>samtools idxstats</code>).</p>')
        sections.append(_card("Influenza Segment Selection - idxstats", "", body))

    # 5. Coverage Statistics
    if cov_stats:
        # Labels name their source explicitly. This card is samtools depth over the mapped
        # references; the Mapping Quality card below is Qualimap's genome-wide mean over the
        # whole 37-record panel including references with no reads. Both used to be called
        # "coverage", they differ by roughly an order of magnitude, and the cross-sample
        # summary quoted one of them under the other's name.
        _verified = cov_stats.get("breadth_verified", False)
        items = [
            ("Mean depth (samtools, covered refs)", cov_stats.get("mean", "N/A")),
            ("Min depth",       str(cov_stats.get("min", "N/A"))),
            ("Max depth",       str(cov_stats.get("max", "N/A"))),
            ("Positions in depth file", f'{cov_stats.get("positions", 0):,}'),
            ("References covered", str(cov_stats.get("contigs", "N/A"))),
            ("Zero-coverage positions",
             str(cov_stats.get("zero_cov", "N/A")) if _verified else "indeterminate"),
            ("Breadth ≥ 1×",
             cov_stats.get("breadth", "N/A") if _verified else "indeterminate"),
        ]
        body = _stat_grid(items)
        if not _verified and cov_stats.get("note"):
            body += (f'<p style="margin-top:10px;color:#c8862a"><b>Breadth cannot be '
                     f'confirmed from this file.</b> {esc(cov_stats["note"])}</p>')
        per_contig = cov_stats.get("per_contig") or {}
        if per_contig:
            body += "<h4 style='margin:14px 0 6px'>Per reference</h4>"
            body += _table(
                ["Reference", "Positions", "Zero-coverage", "Breadth ≥ 1×", "Mean depth"],
                [(name, f'{c["positions"]:,}', f'{c["zero"]:,}',
                  c["breadth"] if _verified else "indeterminate", c["mean"])
                 for name, c in per_contig.items()])
    else:
        body = "<p style='color:#4a6278'>Coverage file not found.</p>"
    sections.append(_card("Coverage Statistics", "", body))

    # 6. Degeneracy Resolution
    if diag_stats.get("total_degeneracies", 0) > 0:
        summary_items = [
            ("Ambiguous Bases Found",     str(diag_stats["total_degeneracies"])),
            ("Resolved to Base",          str(diag_stats["resolved_to_bases"])),
            ("Resolved to Insertion",     str(diag_stats["resolved_to_ins"])),
            ("Resolved to Deletion",      str(diag_stats["resolved_to_del"])),
            ("Retained (ambiguous)",      str(diag_stats["total_kept"])),
            ("Resolution Rate",           diag_stats["resolution_rate"]),
        ]
        body = _stat_grid(summary_items)

        if diag_stats.get("segments"):
            seg_rows = [
                (s["name"], s["total"], s["resolved"], s["kept"],
                 val(s["rate"]))
                for s in diag_stats["segments"]
            ]
            body += "<br>" + _table(
                ["Segment","Total Ambiguous","Resolved","Retained","Rate"],
                seg_rows)
    else:
        body = "<p style='color:#4a6278'>Diagnostic log not found or no degeneracies encountered.</p>"
    sections.append(_card("Degeneracy Resolution Summary", "", body))

    # 7. Indel Decisions
    if diag_stats.get("indel_decisions"):
        rows = []
        for d in diag_stats["indel_decisions"][:200]:   # cap at 200 rows
            cls = "pill pill-green" if d["verdict"] == "ACCEPT" else "pill pill-amber"
            rows.append((
                d["segment"],
                d["pos"],
                d["change"],
                d["net_nt"],
                d["imf"],
                f'{d["idv"]}/{d["dp"]}',
                raw(f'<span class="{cls}">{esc(d["verdict"])}</span>'),
                d["reason"],
            ))
        body = _table(["Segment","Position","Change","Net nt","IMF","IDV/DP",
                       "Verdict","Reason"], rows)
        if len(diag_stats["indel_decisions"]) > 200:
            body += (f'<p style="color:#4a6278;margin-top:8px">'
                     f'Showing first 200 of {len(diag_stats["indel_decisions"])} indel decisions.'
                     f'  See diagnostic log for full list.</p>')
    else:
        body = "<p style='color:#4a6278'>No indel decisions recorded.</p>"
    sections.append(_card("Indel Decisions", "", body))

    # 8. Final consensus stats
    if fasta_stats.get("sequences"):
        seq_rows = [(s["name"], f'{s["length"]:,}', s["gc_pct"],
                     f'{s.get("n_count", 0):,}', f'{s.get("degenerate_count", 0):,}',
                     f'{s.get("ambiguous_count", 0):,}',
                     f'{s.get("soft_masked", 0):,} ({s.get("soft_masked_pct", 0.0):.1f}%)')
                    for s in fasta_stats["sequences"]]
        body = _table(["Segment", "Length (bp)", "GC% (of ACGT)", "N (no call)",
                       "IUPAC degenerate", "Total ambiguous",
                       "Low confidence (lowercase)"], seq_rows)
        _tot = sum(s.get("length", 0) for s in fasta_stats["sequences"])
        _sm  = sum(s.get("soft_masked", 0) for s in fasta_stats["sequences"])
        if _tot:
            _pct = 100.0 * _sm / _tot
            _css = "#c8862a" if _pct >= 20 else "#4a6278"
            body += (f'<p style="margin-top:10px;color:{_css}"><b>{_sm:,} of {_tot:,} bases '
                     f'({_pct:.1f}%) are low-confidence</b> - lowercase in the FASTA, meaning '
                     f'read depth below 3 or call quality below 10 at that position. This is '
                     f'the variant caller\'s own marking, preserved rather than discarded. '
                     f'Uppercase with <code>seqtk seq -U</code> if a downstream tool or archive '
                     f'requires it, and report this fraction alongside.</p>')
    else:
        body = "<p style='color:#4a6278'>Edited consensus FASTA not found.</p>"
    sections.append(_card("Consensus Sequence Summary", "", body))

    # 9. Output File Links
    output_files = [
        ("Final Consensus (FASTA)",
         results / f"step_8_refined_consensus/{barcode}_consensus_edited.fasta"),
        ("Initial Consensus (FASTA)",
         results / f"step_7_draft_consensus/{barcode}_consensus.fasta"),
        ("Diagnostic Log (TSV)",
         Path("log") / f"{barcode}_consensus_edited_diagnostic_log.txt"),
        ("BAM File",
         results / f"step_4_mapped/{barcode}/{barcode}.bam"),
        ("Coverage Depth",
         results / f"step_4_mapped/{barcode}/{barcode}.coverage"),
        ("Merged Reads",
         results / f"step_2_unzipped_merged/{barcode}_merged.fastq"),
        ("Trimmed Reads",
         results / f"step_3_adapter_trimmed/{barcode}_trimmed.fastq"),
        ("Mapped SAM",
         results / f"step_4_mapped/{barcode}/{barcode}.sam"),
    ]
    link_items = []
    for label, path in output_files:
        if Path(path).exists():
            rel = os.path.relpath(str(path), str(reports_base))
            size = Path(path).stat().st_size
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024**2:
                size_str = f"{size/1024:.1f} KB"
            else:
                size_str = f"{size/1024**2:.1f} MB"
            link_items.append(
                f'<li><a href="{rel}">{label}</a>'
                f' <span style="color:#4a6278;font-size:11px">({size_str})</span></li>')
        else:
            link_items.append(
                f'<li><span style="color:#4a6278">{label} - not found</span></li>')

    body = f'<ul class="link-list">{"".join(link_items)}</ul>'
    sections.append(_card("Output Files", "", body))

    # 10. Tool & App Versions (collapsible)
    # Tools ordered by pipeline execution sequence (Step 0 -> Step 8),
    # then runtime / GUI dependencies at the end.
    _TOOL_ORDER = [
        "NanoPlot",    # Step 0 - Raw Read QC
        "porechop",    # Step 2 - Adapter Trimming
        "minimap2",    # Step 3 - Mapping
        "samtools",    # Step 3/4 - SAM->BAM, sort, index, depth
        "qualimap",    # Step 4 - Alignment QC
        "bcftools",    # Step 5 - Variant Calling (mpileup + call)
        "vcfutils.pl", # Step 5 - VCF -> consensus FASTQ (bundled with bcftools)
        "seqtk",       # Step 5 - FASTQ -> FASTA
        "python",      # Step 6 - Consensus Editor runtime
        "pysam",       # Step 6 - BAM parsing
        "biopython",   # Step 6 - sequence I/O
        "numpy",       # Step 6 - numerical helpers
        "java",        # Qualimap JVM dependency
        "PyQt5",       # GUI
        "os",          # System info
    ]

    if runtime_versions:
        app_ver = runtime_versions.pop("app_version", "N/A")
        run_dt  = runtime_versions.pop("run_date", "")
        vmatch  = runtime_versions.pop("version_match", None)
        ordered = sorted(
            runtime_versions.items(),
            key=lambda kv: _TOOL_ORDER.index(kv[0]) if kv[0] in _TOOL_ORDER
                           else len(_TOOL_ORDER)
        )
        ver_rows = [(t, val(v)) for t, v in ordered]
        ver_table = _table(["Tool / Library", "Version"], ver_rows)
        if vmatch:
            _st = vmatch.get('status', 'unknown')
            # NOT named _pill: assigning that name anywhere in this function would make the
            # module-level _pill() helper local to it, and every earlier call would raise
            # UnboundLocalError. That silently crashed report generation.
            _st_css = {'MATCHES BUNDLE': 'pill-green', 'DIFFERS': 'pill-amber'}.get(_st, 'pill-blue')
            _diffs = vmatch.get('differences') or {}
            _detail = ('; '.join(f"{k}: {v['runtime']} vs bundled {v['bundled']}"
                                 for k, v in _diffs.items())) if _diffs else ''
            verdict = (f'<p>Tool versions vs offline bundle: '
                       f'<span class="pill {_st_css}">{esc(_st)}</span>'
                       + (f' <span class="val">{_detail}</span>' if _detail else '') + '</p>')
        else:
            verdict = ''
        body = (f'<p>DeGenRESOLVE v<span class="val">{app_ver}</span></p>' + verdict + 
                f'<details><summary>Show all tool versions ({len(ver_rows)} tools)</summary>'
                f'{ver_table}</details>')
    else:
        body = "<p style='color:#4a6278'>Version information not available.</p>"
    sections.append(_card("Environment & Versions", "", body))

    # Assemble page
    toc_names = ["Parameters", "Input Files", "NanoPlot QC", "Qualimap"]
    if idxstats:
        toc_names.append("Segment Selection")
    toc_names += ["Coverage", "Degeneracy", "Indels", "Consensus", "Outputs", "Versions"]
    toc_links = "".join(
        f'<a href="#s{i}">{t}</a>' for i, t in enumerate(toc_names))
    toc = f'<div class="toc">{toc_links}</div>'

    # Anchor wrapping
    wrapped = ""
    for i, sec in enumerate(sections):
        wrapped += f'<div id="s{i}">{sec}</div>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DeGenRESOLVE Report - {barcode}</title>
<style>{CSS}</style>
</head>
<body>
<div class="page-wrap">
<div class="sticky-nav">
<header>
  <h1>DeGenRESOLVE Analysis Report
    <span class="badge">{barcode}</span>
  </h1>
  <div class="sub">Generated: {run_date} &nbsp;|&nbsp;
       DeGenRESOLVE v1.0.0 &nbsp;|&nbsp;
       Reference: {Path(reference_path).name}</div>
</header>
{toc}
</div>
{wrapped}
<footer>Generated by DeGenRESOLVE v1.0.0 &nbsp;-&nbsp; {run_date}</footer>
</div>
<script>
document.querySelectorAll('.toc a').forEach(function(a){{
  a.addEventListener('click',function(e){{
    e.preventDefault();
    var t=document.querySelector(this.getAttribute('href'));
    if(t){{
      var nav=document.querySelector('.sticky-nav');
      var y=t.getBoundingClientRect().top+window.pageYOffset-(nav?nav.offsetHeight+10:200);
      window.scrollTo(0,y);
    }}
  }});
}});
</script>
</body>
</html>"""
    return html


def build_summary_report(barcode_reports: list, run_date: str) -> str:
    """Build a combined summary page linking all barcode reports."""
    rows = []
    for info in barcode_reports:
        rows.append((
            raw(f'<a href="{esc(info["rel_path"])}">{esc(info["barcode"])}</a>'),
            raw('<span class="pill pill-green">Complete</span>' if info["complete"]
                else '<span class="pill pill-amber">Partial</span>'),
            str(info.get("total_degen","N/A")),
            str(info.get("resolved","N/A")),
            info.get("resolution_rate","N/A"),
            str(info.get("mean_cov","N/A")),
            (info.get("breadth","N/A") if info.get("breadth_verified") else "indeterminate"),
        ))
    table = _table(
        ["Barcode", "Status", "Ambiguous bases", "Resolved", "Resolution rate",
         "Mean depth (samtools)", "Breadth ≥ 1×"],
        rows)
    card  = _card("All Samples Summary", "", table)
    html  = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>DeGenRESOLVE - Run Summary</title>
<style>{CSS}</style>
</head>
<body>
<div class="page-wrap">
<header>
  <h1>DeGenRESOLVE - Run Summary Report</h1>
  <div class="sub">Generated: {run_date} &nbsp;|&nbsp; DeGenRESOLVE v1.0.0</div>
</header>
{card}
<footer>Generated by DeGenRESOLVE v1.0.0 &nbsp;-&nbsp; {run_date}</footer>
</div>
</body>
</html>"""
    return html


# CLI entry-point

def main():
    parser = argparse.ArgumentParser(
        description="DeGenRESOLVE HTML Report Generator")
    parser.add_argument("--barcode",      required=True)
    parser.add_argument("--results-dir",  default="./results")
    parser.add_argument("--config",       default="pipeline_config.json")
    parser.add_argument("--reference",    default="./reference/reference.fasta")
    args = parser.parse_args()

    run_date    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    config      = parse_config(args.config)
    results_dir = Path(args.results_dir)
    reports_dir = results_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    # Per-barcode report
    html = build_barcode_report(
        barcode=args.barcode,
        results_dir=str(results_dir),
        config=config,
        reference_path=args.reference,
        run_date=run_date,
    )
    out_file = reports_dir / f"{args.barcode}_summary_report.html"
    _tmp_out = out_file.parent / f".{out_file.name}.{os.getpid()}.tmp"
    _tmp_out.write_text(html)
    os.replace(_tmp_out, out_file)
    print(f"[REPORT] {args.barcode} -> {out_file}")

    # Rebuild combined summary from all existing per-barcode reports
    barcode_infos = []
    for rpt in sorted(reports_dir.glob("*_summary_report.html")):
        bcode = rpt.stem.replace("_summary_report", "")
        if bcode == "summary_all":
            continue
        # Pull a few stats from the diagnostic log for the summary table
        _qc = (results_dir / "step_8_refined_consensus" /
               f"{bcode}_consensus_edited_qc_summary.json")
        diag = parse_qc_summary(str(_qc)) if _qc.exists() else {}
        if not diag:
            diag = parse_diagnostic_log(
                str(results_dir.parent / "log" / f"{bcode}_consensus_edited_diagnostic_log.txt"))
        cov  = parse_coverage(
            str(results_dir / f"step_4_mapped/{bcode}/{bcode}.coverage"))
        # A barcode with no usable QC data must show N/A, not 0. parse_diagnostic_log returns
        # a fully-zeroed dict on failure, so the .get() fallbacks below could never fire and a
        # failed run was published as "0 ambiguous / 0 resolved" - the best-looking row in the
        # table - beside a "Complete" pill earned by a zero-byte FASTA.
        _have_qc = bool(diag) and diag.get("parsed", diag.get("source") == "qc_json")
        _final = (results_dir / "step_8_refined_consensus" / f"{bcode}_consensus_edited.fasta")
        barcode_infos.append({
            "barcode":        bcode,
            "rel_path":       rpt.name,
            "complete":       _final.exists() and _final.stat().st_size > 0,
            "total_degen":    diag.get("total_degeneracies", "N/A") if _have_qc else "N/A",
            "resolved":       diag.get("total_resolved", "N/A") if _have_qc else "N/A",
            "resolution_rate":diag.get("resolution_rate", "N/A") if _have_qc else "N/A",
            # Mean depth over positions in the .coverage file, NOT Qualimap's genome-wide mean
            # over all 37 reference records. The two differ by roughly the ratio of reference
            # length to covered length and were both previously labelled "Mean Coverage".
            "mean_cov":       cov.get("mean", "N/A"),
            "breadth":        cov.get("breadth", "N/A"),
            "breadth_verified": cov.get("breadth_verified", False),
        })

    summary_html = build_summary_report(barcode_infos, run_date)
    # Written atomically. Every per-barcode reporter process rebuilds this shared file, and
    # barcodes run concurrently, so a plain write_text let two processes interleave and
    # produce a truncated or half-written summary page. os.replace is atomic within a
    # filesystem, so a reader sees either the old page or the new one, never a partial one.
    _summary_path = reports_dir / "summary_all.html"
    _tmp = reports_dir / f".summary_all.{os.getpid()}.tmp"
    _tmp.write_text(summary_html)
    os.replace(_tmp, _summary_path)
    print(f"[REPORT] Summary -> {reports_dir / 'summary_all.html'}")


if __name__ == "__main__":
    main()
