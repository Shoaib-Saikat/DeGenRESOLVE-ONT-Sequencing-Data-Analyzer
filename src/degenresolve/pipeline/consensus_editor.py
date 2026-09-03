#!/usr/bin/env python3
"""
Consensus Degeneracy Diagnostic and Editor

This version handles combined consensus FASTA files (e.g., barcode01_consensus.fasta)
and matches them with corresponding BAM files (e.g., barcode01.bam) using reference/reference.fasta.

Key features:
- Processes combined consensus files with multiple segments (HA, NA, PB2, etc.)
- Matches consensus files with BAM files based on filename pattern
- Uses reference/reference.fasta as the reference for position mapping
- Handles degeneracy resolution for each segment independently
- Enhanced segment matching to resolve all segments properly
- Comprehensive logging with detailed statistics for all positions
- Strand-balance analysis with configurable warning thresholds
- Homopolymer proximity detection for indel context
- Read-end enrichment analysis for amplicon-aware quality assessment
- JSON and optional HTML QC summary reports

Author: Adapted from MSA Editor by Shoaib Saikat
Date: 2025-07-26
Version: 5.0 (Enhanced QC and Modular Decision Engine)
"""

import os
import sys
import html as _html
import json
import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
import pysam
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from datetime import datetime
import re


@dataclass
class SiteMetrics:
    """Structured container for all per-site analysis metrics."""
    segment: str = ""
    consensus_position: int = 0
    genomic_position: int = 0
    original_base: str = ""
    coverage: int = 0
    a_count: int = 0
    c_count: int = 0
    g_count: int = 0
    t_count: int = 0
    insertion_count: int = 0
    deletion_count: int = 0
    major_base: str = ""
    second_base: str = ""
    major_allele_freq: float = 0.0
    second_allele_freq: float = 0.0
    freq_delta: float = 0.0
    forward_total: int = 0
    reverse_total: int = 0
    strand_balance: float = 0.0
    strand_bias_warning: bool = False
    homopolymer_length: int = 0
    homopolymer_distance: int = 0
    homopolymer_warning: bool = False
    read_end_enrichment_score: float = 0.0
    read_end_warning: bool = False
    # Base-quality-filtered depth (A+C+G+T that survived the -Q floor). This is the number the
    # min_coverage gate actually judges, and the number README.md:211 promises the log prints.
    # It used to be computed in decide_site() and thrown away, so every passing site was
    # reported at raw column depth - overstating voting depth by whatever fraction of reads
    # failed the quality floor.
    usable_coverage: int = 0
    warning_flags: list = field(default_factory=list)
    decision: str = ""
    reason: str = ""
    resolved_base: str = ""

def get_pileup_statistics(base_counts: Counter, strand_counts: dict, total_coverage: int) -> dict:
    """Extract structured pileup statistics from raw counts.

    Returns a dict with per-base counts, sorted bases, and forward/reverse totals.
    """
    standard_base_counts = {b: base_counts.get(b, 0) for b in "ACGT"}
    # Only bases actually observed can be ranked. Sorting all four including zeros meant that
    # at a column where no base survived the quality filter, 'A' came first purely because it
    # is alphabetically first with count 0 - so the log reported Major_Base 'A' at 0.0% for
    # every such site, which reads as a real call on real evidence.
    # Sort by count desc then base asc, matching the tie-break in the decision engine so an
    # exact tie is not decided by dict ordering.
    sorted_bases = sorted(((b, c) for b, c in standard_base_counts.items() if c > 0),
                          key=lambda x: (-x[1], x[0]))
    standard_total = sum(standard_base_counts.values())

    fwd = sum(strand_counts.get(b, {}).get('forward', 0) for b in "ACGT")
    rev = sum(strand_counts.get(b, {}).get('reverse', 0) for b in "ACGT")

    return {
        'standard_base_counts': standard_base_counts,
        'sorted_bases': sorted_bases,
        'standard_total': standard_total,
        'deletion_count': base_counts.get('DEL', 0),
        'insertion_count': base_counts.get('INS', 0),
        'forward_total': fwd,
        'reverse_total': rev,
    }


def compute_strand_balance(strand_counts: dict, major_base: str) -> float:
    """Compute strand balance for the dominant base.

    Returns min(fwd, rev) / max(fwd, rev), or 0.0 when no reads are present.
    """
    fwd = strand_counts.get(major_base, {}).get('forward', 0)
    rev = strand_counts.get(major_base, {}).get('reverse', 0)
    mx = max(fwd, rev)
    return min(fwd, rev) / mx if mx > 0 else 0.0


def html_escape(value) -> str:
    """Escape a value for safe interpolation into generated HTML.

    Segment names, file paths and sample IDs all reach these reports from the filesystem and
    the reference FASTA, so they are not trusted to be markup-free.
    """
    return _html.escape(str(value), quote=True)


# Longest homopolymer run the detector will measure in full. A run longer than this is
# reported at this length; influenza references contain nothing close to it.
_MAX_HOMOPOLYMER_SCAN = 60


def compute_homopolymer_metrics(ref_seq: str, pos: int, window: int = 5, min_length: int = 5) -> tuple:
    """Detect homopolymer runs near a reference position.

    Returns (homopolymer_length, distance_to_site, warning_flag).
    """
    # The scan region must be wide enough to hold a qualifying run that merely STARTS within
    # `window` of the site. Slicing at pos +/- window truncated every run at the boundary, so a
    # run only cleared min_length when it lay almost on top of the site: with the shipped
    # defaults (window=5, min_length=5) the effective detection radius was 1 base, not 5, and a
    # true 20-mer poly-A reported HP_Len 11. Both errors hit exactly the ONT positions most
    # prone to indel artefacts, and understated the length a reviewer reads in the QC column.
    #
    # Scan out to `window` on each side PLUS enough room for a maximal run to be measured in
    # full, then clip the CENTRE (which runs qualify) rather than the run lengths themselves.
    scan_start = max(0, pos - window - _MAX_HOMOPOLYMER_SCAN)
    scan_end = min(len(ref_seq), pos + window + _MAX_HOMOPOLYMER_SCAN + 1)
    region = ref_seq[scan_start:scan_end].upper()

    best_len = 0
    best_dist = window + 1

    i = 0
    while i < len(region):
        run_char = region[i]
        run_len = 1
        while i + run_len < len(region) and region[i + run_len] == run_char:
            run_len += 1
        if run_len >= min_length and run_char in 'ACGT':
            run_start_abs = scan_start + i
            run_end_abs = run_start_abs + run_len - 1
            if run_start_abs <= pos <= run_end_abs:
                dist = 0
            elif pos < run_start_abs:
                dist = run_start_abs - pos
            else:
                dist = pos - run_end_abs
            # Only runs within `window` of the site are reportable; the wider scan exists
            # solely so that such a run is measured at its true length.
            if dist <= window and (run_len > best_len or
                                   (run_len == best_len and dist < best_dist)):
                best_len = run_len
                best_dist = dist
        i += run_len

    if best_len < min_length:
        return 0, window + 1, False
    return best_len, best_dist, True


def compute_read_end_enrichment(bam_handle, ref_name: str, pos: int,
                                 edge_fraction: float = 0.1,
                                 min_reads: int = 3,
                                 alt_base: str = None) -> float:
    """Measure whether ALT-supporting reads cluster near read ends.

    `alt_base` is the allele whose read placement is under suspicion - normally the minority
    base at a degenerate site. Only reads actually carrying that base are counted, which is
    what the metric claims to measure and what the documentation describes.

    This previously counted EVERY read overlapping the position regardless of which base it
    carried (the code said so: "Simplified: count all reads and flag those near edges"). That
    made the score a property of the amplicon's read-position distribution rather than of the
    variant, so it was near-identical at every site in a segment - it could not discriminate a
    real variant from a primer artefact, yet strict_read_end reverts calls on it.

    With alt_base=None the old whole-column behaviour is retained for callers that have no
    allele in mind. Returns a score between 0 and 1, or 0.0 when there is too little evidence.

    Uses a conservative edge fraction to avoid false positives at amplicon boundaries.
    """
    alt_edge = 0
    alt_total = 0
    want = alt_base.upper() if alt_base else None

    try:
        for read in bam_handle.fetch(ref_name, pos, pos + 1):
            if read.is_unmapped or read.is_secondary or read.is_supplementary:
                continue

            pairs = read.get_aligned_pairs(with_seq=False)
            query_pos_at_site = None
            for qpos, rpos in pairs:
                if rpos == pos and qpos is not None:
                    query_pos_at_site = qpos
                    break
            if query_pos_at_site is None:
                continue

            read_len = read.query_length or read.infer_query_length() or 0
            if read_len == 0:
                continue

            # Restrict to reads carrying the allele under suspicion.
            if want is not None:
                seq = read.query_sequence
                if not seq or query_pos_at_site >= len(seq):
                    continue
                if seq[query_pos_at_site].upper() != want:
                    continue

            edge_size = max(1, int(read_len * edge_fraction))
            near_edge = query_pos_at_site < edge_size or query_pos_at_site >= (read_len - edge_size)
            alt_total += 1
            if near_edge:
                alt_edge += 1
    except Exception:
        return 0.0

    if alt_total < min_reads:
        return 0.0
    return alt_edge / alt_total


class ConsensusDegeneracyProcessor:
    def __init__(self, consensus_file, reference_file, bam_file=None, output_file=None,
                 min_coverage=100, min_percentage_diff=20, diagnostic_mode=False, filter_mode="general",
                 indel_insertions="equal_or_more", indel_deletions="equal_or_more", indel_custom_percentage=50.0,
                 major_h: str | None = None, major_n: str | None = None,
                 strand_balance_threshold: float = 0.1,
                 homopolymer_min_length: int = 5,
                 homopolymer_window: int = 5,
                 read_end_threshold: float = 0.8,
                 read_end_edge_fraction: float = 0.1,
                 strict_strand_bias: bool = False,
                 strict_homopolymer: bool = False,
                 strict_read_end: bool = False,
                 min_base_quality: int = 5,
                 vcf_file: str | None = None):
        """Initialize the consensus degeneracy processor.

        Args:
            consensus_file: Path to input consensus file.
            reference_file: Path to reference FASTA file.
            bam_file: Path to BAM file (auto-detected if None).
            output_file: Path for output edited consensus (auto-generated if None).
            min_coverage: Minimum read coverage to consider editing.
            min_percentage_diff: Minimum percentage difference between top two bases.
            diagnostic_mode: If True, provides detailed diagnostic output.
            filter_mode: 'general' or 'influenza'.
            indel_insertions: Rule for accepting insertions.
            indel_deletions: Rule for accepting deletions.
            indel_custom_percentage: Custom percentage threshold for indel rules.
            major_h: Override consensus ID of major H segment.
            major_n: Override consensus ID of major N segment.
            strand_balance_threshold: Warn if strand balance falls below this (0-1).
            homopolymer_min_length: Minimum run length to flag as homopolymer.
            homopolymer_window: Window around each site to search for homopolymers.
            read_end_threshold: Warn if read-end enrichment exceeds this (0-1).
            read_end_edge_fraction: Fraction of each read end considered "edge" (0-0.5, default 0.1).
            strict_strand_bias: If True, strand bias warnings override base calls.
            strict_homopolymer: If True, homopolymer warnings override base calls.
            strict_read_end: If True, read-end enrichment warnings override base calls.
            min_base_quality: Minimum base quality for the pileup. Floored at 5 on
                every basecall tier, deliberately: bcftools admits lower-quality
                bases (-Q1 on the ont-sup profile) but down-weights them via
                --max-BQ, while this pileup counts every surviving base at equal
                weight and has no --max-BQ analogue. Matching bcftools' flag value
                would be more permissive than matching its intent. Weighting the
                counts instead was rejected because the log's A/C/G/T columns must
                stay countable reads a human can verify against IGV.
            vcf_file: Step-6 VCF. When given, bcftools' indel calls are adjudicated
                against IMF, coverage and reading frame and may edit the consensus.
        """
        self.consensus_file = consensus_file
        self.reference_file = reference_file
        self.min_coverage = min_coverage
        self.min_percentage_diff = min_percentage_diff
        self.min_base_quality = min_base_quality
        self.vcf_file = vcf_file
        self._orfs = None
        self._vcf_indels = {}
        self.indel_decisions = []
        self.indel_evidence = []
        self.diagnostic_mode = diagnostic_mode
        self.filter_mode = filter_mode
        self.indel_insertions = indel_insertions
        self.indel_deletions = indel_deletions
        self.indel_custom_percentage = indel_custom_percentage
        self.major_h_override = (major_h or '').strip() or None
        self.major_n_override = (major_n or '').strip() or None

        # New QC thresholds
        self.strand_balance_threshold = strand_balance_threshold
        self.homopolymer_min_length = homopolymer_min_length
        self.homopolymer_window = homopolymer_window
        self.read_end_threshold = read_end_threshold
        self.read_end_edge_fraction = read_end_edge_fraction
        self.strict_strand_bias = strict_strand_bias
        self.strict_homopolymer = strict_homopolymer
        self.strict_read_end = strict_read_end
        
        # Auto-detect BAM file and output file based on consensus filename
        consensus_path = Path(consensus_file)
        base_name = consensus_path.stem.replace('_consensus', '')
        self.sample_id = base_name

        if bam_file is None:
            # Look for BAM file in analysis directory
            analysis_dir = Path(f"./{base_name}_analysis")
            if analysis_dir.exists():
                self.bam_file = analysis_dir / f"{base_name}.bam"
            else:
                self.bam_file = consensus_path.parent / f"{base_name}.bam"
        else:
            self.bam_file = Path(bam_file)
            
        if output_file is None:
            self.output_file = consensus_path.parent / f"{base_name}_consensus_edited.fasta"
        else:
            self.output_file = Path(output_file)
        
        # Define degeneracy codes and their corresponding bases
        self.degeneracy_codes = {
            'R': ['A', 'G'], 'Y': ['C', 'T'], 'S': ['G', 'C'], 'W': ['A', 'T'],
            'K': ['G', 'T'], 'M': ['A', 'C'], 'N': ['A', 'T', 'G', 'C'],
            'B': ['C', 'G', 'T'], 'D': ['A', 'G', 'T'], 'H': ['A', 'C', 'T'],
            'V': ['A', 'C', 'G']
        }
        
        # Initialize statistics tracking
        self.processing_stats = defaultdict(lambda: defaultdict(int))
        self.degeneracy_log = []
        self.site_metrics_log: list[SiteMetrics] = []
        self.segment_mapping = {}  # Track segment to reference mapping
        
        # Load all data components in correct order
        self.consensus_sequences = self._load_consensus_sequences()
        self.reference_sequences = self._load_reference_sequences()
        self.bam_file_handle = self._load_bam_file()
        
        # Apply optional influenza filter to consensus sequences
        if (self.filter_mode or "").lower() == "influenza":
            self._apply_influenza_filter()

        # Build segment mapping after loading (and possibly filtering) sequences
        self._build_segment_mapping()

        # Compute major H/N only after mapping is available (influenza mode only)
        if (self.filter_mode or "").lower() == "influenza":
            self.major_h_ref, self.major_n_ref, self.major_h_seq, self.major_n_seq = self._compute_major_hn_segments()
        else:
            self.major_h_ref, self.major_n_ref, self.major_h_seq, self.major_n_seq = None, None, None, None
        
        if self.diagnostic_mode:
            self._test_bam_access()
    
    def _load_consensus_sequences(self):
        """Load all sequences from the consensus file"""
        sequences = {}
        if self.diagnostic_mode:
            print("Loading consensus sequences...")
        
        # Published draft consensus files carry a "<sample_id>_" header prefix, added
        # when the pipeline copies them into step_7_draft_consensus/. Segment matching
        # and _segment_type() both require the ID to start with the segment name, so
        # strip it back off; write_edited_consensus re-adds it on output.
        sample_prefix = f"{self.sample_id}_"
        for seq_record in SeqIO.parse(self.consensus_file, "fasta"):
            if seq_record.id.startswith(sample_prefix):
                seq_record.id = seq_record.id[len(sample_prefix):]
                if seq_record.description.startswith(sample_prefix):
                    seq_record.description = seq_record.description[len(sample_prefix):]
            sequences[seq_record.id] = seq_record
            if self.diagnostic_mode:
                seq_str = str(seq_record.seq)
                degeneracy_count = sum(1 for base in seq_str if base.upper() in self.degeneracy_codes)
                print(f"  Loaded: {seq_record.id} (length: {len(seq_record.seq)})")
                print(f"    Degeneracies found: {degeneracy_count}")
        
        return sequences

    def _segment_type(self, seq_id: str) -> str | None:
        """Return canonical segment type for a sequence ID, or None if unrecognised.

        Convention: the sequence ID must start with the segment name, optionally
        followed by '_' and an accession (e.g. H5_OP023667.1, PB2_OP023708.1).
        Bare names (H5, PB2) also work.
        """
        prefix = seq_id.split('_')[0].upper()
        # Subtyped spellings: H5_/N1_ (this bundle's reference convention).
        if prefix.startswith('H') and len(prefix) > 1 and prefix[1].isdigit():
            return 'H'
        if prefix.startswith('N') and len(prefix) > 1 and prefix[1].isdigit():
            return 'N'
        # Untyped spellings: HA_/NA_, the NCBI Influenza Virus Database convention and the one
        # DeGenRESOLVE_interface.md and the GUI's influenza checkbox both advertise. These were
        # previously unrecognised, so _apply_influenza_filter dropped them and published a
        # 6-segment consensus with hemagglutinin and neuraminidase silently missing.
        # _compute_major_hn_segments() and process_consensus()'s find_h() already accept them.
        if prefix in {'HA', 'H'}:
            return 'H'
        if prefix in {'NA', 'N'}:
            return 'N'
        # M/M1/M2 are matrix protein synonyms; normalise to MP
        if prefix in {'M', 'M1', 'M2'}:
            return 'MP'
        # NS1/NS2 and NP synonyms follow the same pattern as M/M1/M2.
        if prefix in {'NS1', 'NS2'}:
            return 'NS'
        if prefix in {'PB2', 'PB1', 'PA', 'NP', 'MP', 'NS'}:
            return prefix
        return None

    def _resolve_segment_override(self, override: str):
        """Map a --major-h/--major-n value onto an actual consensus sequence ID.

        Accepts the bare subtype the documentation uses ("H5", "N1"), the full record name
        ("H5_OP023667.1"), and is case-insensitive. Exact match wins; otherwise the value is
        matched against the segment-name prefix (the part before the first underscore), which
        is what a user reading README.md:267 would type.
        """
        if not override:
            return None
        want = override.strip().upper()
        ids = list(self.consensus_sequences)
        for sid in ids:
            if sid.upper() == want:
                return sid
        for sid in ids:
            if sid.split('_')[0].upper() == want:
                return sid
        for sid in ids:
            if sid.upper().startswith(want):
                return sid
        return None

    def _apply_influenza_filter(self):
        """Reduce consensus sequences to the 8 canonical influenza segments.

        For each segment type (H, N, PB2, PB1, PA, NP, MP, NS) the sequence
        with the most mapped reads is chosen.  Missing segments produce a
        warning and are skipped rather than aborting the run.
        """
        REQUIRED = ('H', 'N', 'PB2', 'PB1', 'PA', 'NP', 'MP', 'NS')
        print("\nApplying influenza filter: selecting top-reads sequence for each of 8 segments")

        # Read counts per reference from BAM index
        ref_to_reads: dict = {}
        try:
            for s in self.bam_file_handle.get_index_statistics():
                ref = getattr(s, 'contig', None) or getattr(s, 'chrom', None)
                if ref:
                    ref_to_reads[ref.upper()] = int(getattr(s, 'mapped', 0))
        except Exception:
            pass
        if not ref_to_reads:
            import subprocess as _sp
            try:
                out = _sp.run(
                    ["samtools", "idxstats", str(self.bam_file)],
                    stdout=_sp.PIPE, text=True, check=True
                ).stdout
                for line in out.splitlines():
                    parts = line.split('\t')
                    if len(parts) >= 3 and parts[0] != '*':
                        try:
                            ref_to_reads[parts[0].upper()] = int(parts[2])
                        except ValueError:
                            pass
            except Exception as e:
                print(f"Warning: could not get BAM read counts for influenza filtering: {e}")

        # Pick highest-read sequence per segment type
        best: dict = {}  # type -> (seq_id, reads)
        for seq_id in self.consensus_sequences:
            stype = self._segment_type(seq_id)
            if stype is None:
                continue
            reads = ref_to_reads.get(seq_id.upper(), 0)
            if stype not in best or reads > best[stype][1]:
                best[stype] = (seq_id, reads)

        # --major-h / --major-n are documented as OVERRIDING subtype auto-detection. They
        # previously affected only the order of the output FASTA - the subtype actually kept
        # was still whichever had the most reads - and they were matched by exact sequence-ID
        # equality, so the documented example values (H5, N1) never matched a real reference
        # name like H5_OP023667.1 and the flags silently did nothing at all.
        for stype, override in (('H', getattr(self, 'major_h_override', None)),
                                ('N', getattr(self, 'major_n_override', None))):
            if not override:
                continue
            match = self._resolve_segment_override(override)
            if match is None:
                print(f"Warning: --major-{stype.lower()} '{override}' does not match any "
                      f"consensus sequence; falling back to read-count selection. "
                      f"Available: {sorted(self.consensus_sequences)}")
                continue
            reads = ref_to_reads.get(match.upper(), 0)
            if stype in best and best[stype][0] != match:
                print(f"  {stype}: overriding read-count choice {best[stype][0]} "
                      f"with --major-{stype.lower()} {match}")
            best[stype] = (match, reads)

        kept = {}
        dropped = []
        for stype in REQUIRED:
            if stype in best:
                seq_id, reads = best[stype]
                kept[seq_id] = self.consensus_sequences[seq_id]
                if self.diagnostic_mode:
                    print(f"  {stype}: {seq_id} (reads={reads})")
            else:
                print(f"Warning: influenza mode: no {stype} segment found in reference - skipping")

        dropped = [sid for sid in self.consensus_sequences if sid not in kept]
        if dropped and self.diagnostic_mode:
            print(f"  Dropped {len(dropped)} non-selected: {dropped}")

        self.consensus_sequences = kept

    def _compute_major_hn_segments(self):
        """Detect major H and N references by mapped read counts using BAM index statistics.

        Returns (major_h_ref, major_n_ref, major_h_seq_id, major_n_seq_id).
        """
        ref_to_reads = {}
        # Try pysam API first
        try:
            stats = self.bam_file_handle.get_index_statistics()
            for s in stats:
                ref_name = getattr(s, 'contig', None) or getattr(s, 'chrom', None)
                mapped = getattr(s, 'mapped', None)
                if ref_name is None or mapped is None:
                    continue
                ref_to_reads[ref_name.upper()] = int(mapped)
        except Exception:
            stats = []

        # Fallback to external samtools idxstats if needed or if stats empty
        if not ref_to_reads:
            import subprocess
            try:
                cmd = ["samtools", "idxstats", str(self.bam_file)]
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
                for line in result.stdout.splitlines():
                    parts = line.strip().split('\t')
                    if len(parts) >= 3 and parts[0] != "*":
                        ref_name, length, mapped = parts[0], parts[1], parts[2]
                        try:
                            ref_to_reads[ref_name.upper()] = int(mapped)
                        except ValueError:
                            continue
            except Exception as e:
                if self.diagnostic_mode:
                    print(f"Warning: samtools idxstats failed: {e}")
                return None, None, None, None

        # Helper predicates
        def is_h_ref(name_u: str) -> bool:
            # HA* or H[0-9]
            return name_u.startswith('HA') or (name_u.startswith('H') and len(name_u) > 1 and name_u[1].isdigit())

        def is_n_ref(name_u: str) -> bool:
            # NA* or N[0-9] (exclude NP/NS)
            return name_u.startswith('NA') or (name_u.startswith('N') and len(name_u) > 1 and name_u[1].isdigit())

        major_h_ref = None
        major_n_ref = None
        max_h = -1
        max_n = -1

        for ref_u, reads in ref_to_reads.items():
            if is_h_ref(ref_u) and reads > max_h:
                max_h = reads
                major_h_ref = ref_u
            if is_n_ref(ref_u) and reads > max_n:
                max_n = reads
                major_n_ref = ref_u

        # Map refs back to consensus seq ids via segment_mapping
        ref_to_consensus = {}
        for cons_seg, ref_seg in self.segment_mapping.items():
            if ref_seg:
                ref_to_consensus.setdefault(ref_seg.upper(), []).append(cons_seg)

        major_h_seq = None
        major_n_seq = None
        if major_h_ref and major_h_ref in ref_to_consensus:
            major_h_seq = ref_to_consensus[major_h_ref][0]
        if major_n_ref and major_n_ref in ref_to_consensus:
            major_n_seq = ref_to_consensus[major_n_ref][0]

        if self.diagnostic_mode:
            print("\nInfluenza prioritization (from BAM idxstats):")
            print(f"  Major H ref: {major_h_ref} (reads={max_h if max_h>=0 else 'NA'}) -> consensus: {major_h_seq}")
            print(f"  Major N ref: {major_n_ref} (reads={max_n if max_n>=0 else 'NA'}) -> consensus: {major_n_seq}")

        return major_h_ref, major_n_ref, major_h_seq, major_n_seq
    
    def _load_reference_sequences(self):
        """Load all sequences from the reference file"""
        sequences = {}
        if self.diagnostic_mode:
            print("\nLoading reference sequences...")
        
        for seq_record in SeqIO.parse(self.reference_file, "fasta"):
            sequences[seq_record.id] = seq_record
            if self.diagnostic_mode:
                print(f"  Loaded reference: {seq_record.id} (length: {len(seq_record.seq)})")
        
        return sequences
    
    def _load_bam_file(self):
        """Load and validate BAM file"""
        if not self.bam_file.exists():
            raise FileNotFoundError(f"BAM file not found: {self.bam_file}")
        
        bai_path = self.bam_file.with_suffix(".bam.bai")
        bai_alt = self.bam_file.with_suffix(".bai")
        if not bai_path.exists() and not bai_alt.exists():
            raise FileNotFoundError(f"BAM index not found: expected {bai_path} or {bai_alt}")
        
        try:
            bam_file = pysam.AlignmentFile(str(self.bam_file), "rb")
            if self.diagnostic_mode:
                print(f"\nLoaded BAM file: {self.bam_file}")
                print(f"  References in BAM: {list(bam_file.references)}")
            return bam_file
        except Exception as e:
            raise Exception(f"Error loading BAM file {self.bam_file}: {e}")
    
    def _normalize_segment_name(self, name):
        """Normalize segment names for comparison"""
        # Remove common prefixes and suffixes
        normalized = name.upper().strip()
        
        # Remove common descriptive text
        normalized = re.sub(r'\s*\([^)]*\)', '', normalized)  # Remove parenthetical content
        normalized = re.sub(r'\s+', '_', normalized)  # Replace spaces with underscores
        normalized = re.sub(r'[^A-Z0-9_]', '', normalized)  # Keep only alphanumeric and underscore
        
        return normalized
    
    def _build_segment_mapping(self):
        """Build mapping between consensus segments and reference sequences"""
        if self.diagnostic_mode:
            print("\nBuilding segment mapping...")
        
        consensus_segments = list(self.consensus_sequences.keys())
        reference_segments = list(self.reference_sequences.keys())
        
        if self.diagnostic_mode:
            print(f"  Consensus segments found: {consensus_segments}")
            print(f"  Reference segments available: {reference_segments}")
        
        # First, try exact matches
        for cons_seg in consensus_segments:
            if cons_seg in reference_segments:
                self.segment_mapping[cons_seg] = cons_seg
                if self.diagnostic_mode:
                    print(f"  Exact match: {cons_seg} -> {cons_seg}")
                continue
        
        # Handle special cases for HA and NA - check actual sequence headers
        for cons_seg in consensus_segments:
            if cons_seg not in self.segment_mapping:
                # Get the actual sequence record to check its full description/header
                seq_record = self.consensus_sequences[cons_seg]
                full_header = f"{seq_record.id} {seq_record.description}".strip()
                
                if self.diagnostic_mode:
                    print(f"  Analyzing segment: {cons_seg}")
                    print(f"    Full header: {full_header}")
                
                if cons_seg.startswith("HA") or "HA" in full_header.upper():
                    # Look for H-type in parentheses in either ID or description
                    h_match = re.search(r'\(([H]\d+)\)', full_header, re.IGNORECASE)
                    if h_match:
                        h_type = h_match.group(1).upper()
                        # Look for reference sequence that matches this H type
                        for ref_seg in reference_segments:
                            if h_type.upper() == ref_seg.upper() or h_type in ref_seg.upper():
                                self.segment_mapping[cons_seg] = ref_seg
                                if self.diagnostic_mode:
                                    print(f"    HA match: {cons_seg} -> {ref_seg} (extracted {h_type} from header)")
                                break
                    else:
                        # No parentheses found, try generic H-type matching
                        for ref_seg in reference_segments:
                            if ref_seg.upper().startswith('H') and len(ref_seg) <= 4:
                                self.segment_mapping[cons_seg] = ref_seg
                                if self.diagnostic_mode:
                                    print(f"    HA match: {cons_seg} -> {ref_seg} (generic H-type)")
                                break
                        # If no H-type found, look for anything containing "HA"
                        if cons_seg not in self.segment_mapping:
                            for ref_seg in reference_segments:
                                if 'HA' in ref_seg.upper() or 'HEMAGGLUTININ' in ref_seg.upper():
                                    self.segment_mapping[cons_seg] = ref_seg
                                    if self.diagnostic_mode:
                                        print(f"    HA match: {cons_seg} -> {ref_seg} (contains HA/hemagglutinin)")
                                    break
                
                elif cons_seg.startswith("NA") or "NA" in full_header.upper():
                    # Look for N-type in parentheses in either ID or description
                    n_match = re.search(r'\(([N]\d+)\)', full_header, re.IGNORECASE)
                    if n_match:
                        n_type = n_match.group(1).upper()
                        # Look for reference sequence that matches this N type
                        for ref_seg in reference_segments:
                            if n_type.upper() == ref_seg.upper() or n_type in ref_seg.upper():
                                self.segment_mapping[cons_seg] = ref_seg
                                if self.diagnostic_mode:
                                    print(f"    NA match: {cons_seg} -> {ref_seg} (extracted {n_type} from header)")
                                break
                    else:
                        # No parentheses found, try generic N-type matching
                        for ref_seg in reference_segments:
                            if ref_seg.upper().startswith('N') and len(ref_seg) <= 4:
                                self.segment_mapping[cons_seg] = ref_seg
                                if self.diagnostic_mode:
                                    print(f"    NA match: {cons_seg} -> {ref_seg} (generic N-type)")
                                break
                        # If no N-type found, look for anything containing "NA"
                        if cons_seg not in self.segment_mapping:
                            for ref_seg in reference_segments:
                                if 'NA' in ref_seg.upper() or 'NEURAMINIDASE' in ref_seg.upper():
                                    self.segment_mapping[cons_seg] = ref_seg
                                    if self.diagnostic_mode:
                                        print(f"    NA match: {cons_seg} -> {ref_seg} (contains NA/neuraminidase)")
                                    break
        
        # Try normalized name matching for remaining segments
        for cons_seg in consensus_segments:
            if cons_seg not in self.segment_mapping:
                cons_normalized = self._normalize_segment_name(cons_seg)
                
                best_match = None
                best_score = 0
                
                for ref_seg in reference_segments:
                    ref_normalized = self._normalize_segment_name(ref_seg)
                    
                    # Check for substring matches
                    if cons_normalized in ref_normalized or ref_normalized in cons_normalized:
                        # Calculate similarity score
                        common_chars = len(set(cons_normalized) & set(ref_normalized))
                        total_chars = len(set(cons_normalized) | set(ref_normalized))
                        score = common_chars / total_chars if total_chars > 0 else 0
                        
                        if score > best_score:
                            best_score = score
                            best_match = ref_seg
                
                if best_match and best_score > 0.5:  # Require at least 50% similarity
                    self.segment_mapping[cons_seg] = best_match
                    if self.diagnostic_mode:
                        print(f"  Normalized match: {cons_seg} -> {best_match} (score: {best_score:.2f})")
        
        # Try common segment abbreviations
        segment_abbrev_map = {
            'PB2': ['PB2', 'POLYMERASE_PB2', 'POLYMERASE_BASIC_2'],
            'PB1': ['PB1', 'POLYMERASE_PB1', 'POLYMERASE_BASIC_1'],
            'PA': ['PA', 'POLYMERASE_PA', 'POLYMERASE_ACIDIC'],
            'NP': ['NP', 'NUCLEOPROTEIN', 'NUCLEO_PROTEIN'],
            'M': ['M', 'MATRIX', 'M1', 'M2'],
            'NS': ['NS', 'NON_STRUCTURAL', 'NS1', 'NS2']
        }
        
        for cons_seg in consensus_segments:
            if cons_seg not in self.segment_mapping:
                cons_upper = cons_seg.upper()
                for abbrev, full_names in segment_abbrev_map.items():
                    if abbrev in cons_upper:
                        for ref_seg in reference_segments:
                            ref_upper = ref_seg.upper()
                            for full_name in full_names:
                                if full_name in ref_upper:
                                    self.segment_mapping[cons_seg] = ref_seg
                                    if self.diagnostic_mode:
                                        print(f"  Abbreviation match: {cons_seg} -> {ref_seg}")
                                    break
                            if cons_seg in self.segment_mapping:
                                break
                        if cons_seg in self.segment_mapping:
                            break
        
        # Report unmapped segments
        unmapped = [seg for seg in consensus_segments if seg not in self.segment_mapping]
        if unmapped:
            print(f"\nWarning: Could not map the following consensus segments to references:")
            for seg in unmapped:
                print(f"  - {seg}")
            print(f"Available reference segments: {reference_segments}")
    
    def _get_reference_for_segment(self, segment_id):
        """Get the reference sequence for a given segment"""
        ref_id = self.segment_mapping.get(segment_id)
        if ref_id and ref_id in self.reference_sequences:
            return ref_id, str(self.reference_sequences[ref_id].seq)
        return None, None
    
    def _test_bam_access(self):
        """Test BAM file access with sample positions for all segments"""
        print(f"\nTesting BAM file access...")
        
        for segment_id in self.consensus_sequences:
            ref_name, ref_seq = self._get_reference_for_segment(segment_id)
            if ref_name is None:
                print(f"  {segment_id}: No reference found")
                continue
                
            print(f"  Testing segment: {segment_id} -> reference: {ref_name}")
            
            test_positions = [0, 20, 50, 100]
            for pos in test_positions:
                if pos < len(ref_seq):
                    base_counts, total_coverage, skipped_reads, _sc = self._get_base_counts_at_position(ref_name, pos)
                    print(f"    Position {pos}: coverage={total_coverage}, bases={dict(base_counts)}")
                    if skipped_reads and sum(skipped_reads.values()) > 0:
                        print(f"      Skipped reads: {dict(skipped_reads)}")
    
    def _get_base_counts_at_position(self, reference_name, genomic_position):
        """Get base counts at a specific genomic position from BAM file"""
        base_counts = Counter()
        strand_counts = {
            'A': {'forward': 0, 'reverse': 0}, 'T': {'forward': 0, 'reverse': 0},
            'G': {'forward': 0, 'reverse': 0}, 'C': {'forward': 0, 'reverse': 0},
            'N': {'forward': 0, 'reverse': 0}, 'DEL': {'forward': 0, 'reverse': 0},
            'INS': {'forward': 0, 'reverse': 0}
        }
        total_coverage = 0
        skipped_reads = Counter()
        
        try:
            for pileup_column in self.bam_file_handle.pileup(reference_name, genomic_position, genomic_position + 1, 
                                              truncate=True, min_base_quality=self.min_base_quality, 
                                              ignore_overlaps=False, max_depth=1000000, stepper='all'):
                if pileup_column.pos == genomic_position:
                    total_coverage = pileup_column.n
                    for pileup_read in pileup_column.pileups:
                        is_reverse = pileup_read.alignment.is_reverse
                        strand = 'reverse' if is_reverse else 'forward'
                        
                        if pileup_read.is_del:
                            base_counts['DEL'] += 1
                            strand_counts['DEL'][strand] += 1
                        elif pileup_read.is_refskip:
                            skipped_reads['refskip'] += 1
                        elif pileup_read.query_position is None:
                            skipped_reads['no_query_position'] += 1
                        else:
                            base = pileup_read.alignment.query_sequence[pileup_read.query_position]
                            if base.upper() in ['A', 'T', 'G', 'C']:
                                base_counts[base.upper()] += 1
                                strand_counts[base.upper()][strand] += 1
                            else:
                                base_counts['N'] += 1
                                strand_counts['N'][strand] += 1
                        
                        if pileup_read.indel > 0:
                            base_counts['INS'] += 1
                            strand_counts['INS'][strand] += 1
                    
                    if self.diagnostic_mode:
                        igv_output = [f"Total count: {total_coverage}"]
                        for base in ['A', 'T', 'G', 'C']:
                            if base in base_counts:
                                forward = strand_counts[base]['forward']
                                reverse = strand_counts[base]['reverse']
                                percentage = (base_counts[base] / total_coverage) * 100 if total_coverage > 0 else 0
                                igv_output.append(f"{base} : {base_counts[base]} ({percentage:.0f}%, {forward}+, {reverse}- )")
                        for base in ['N', 'DEL', 'INS']:
                            if base in base_counts:
                                igv_output.append(f"{base} : {base_counts[base]}")
                            else:
                                igv_output.append(f"{base} : 0")
                        
                        print(f"    IGV-style counts for {reference_name}:{genomic_position}:")
                        for line in igv_output:
                            print(f"      {line}")
                    break
        except Exception as e:
            if self.diagnostic_mode:
                print(f"    Error querying position {genomic_position} for {reference_name}: {e}")
        
        return base_counts, total_coverage, skipped_reads, strand_counts

    def _allele_set_violation(self, analysis, top_base, degeneracy_code, top_percentage):
        """True when the majority base falls outside the ambiguity code's own allele set.

        Marks `analysis` as a KEEP with the conflict reason when it does. Factored out
        of the threshold branch because the single-base shortcut below returned RESOLVE
        without ever reaching that check, so a site coded R (A/G) whose only surviving
        base was C could still be published as C - exactly what this guard exists to
        stop. Unreachable on the reference data (no site with an ambiguity code and
        >= min_coverage usable reads carries only one base type), but the guard should
        not depend on that.
        """
        possible = analysis.get('possible_bases') or []
        if not (0 < len(possible) < 4):      # N's set is all four; nothing to enforce
            return False
        if top_base in possible:
            return False
        analysis.update({
            'decision': 'KEEP',
            'reason': (f'Majority base {top_base} ({top_percentage:.1f}%) is not in the '
                       f'{degeneracy_code} allele set {"/".join(possible)} - pileup '
                       f'disagrees with the variant call; kept for review')
        })
        analysis['allele_set_conflict'] = True
        return True

    def _analyze_degeneracy_decision_enhanced(self, base_counts, total_coverage, degeneracy_code, consensus_pos, genomic_pos, skipped_reads=None):
        """Enhanced analysis considering deletions for editing decisions.

        This is the original decision method, preserved for backward compatibility.
        """
        analysis = {
            'consensus_position': consensus_pos,
            'genomic_position': genomic_pos,
            'degeneracy_code': degeneracy_code,
            'total_coverage': total_coverage,
            'base_counts': dict(base_counts),
            'possible_bases': self.degeneracy_codes.get(degeneracy_code, []),
            'deletion_count': base_counts.get('DEL', 0),
            'insertion_count': base_counts.get('INS', 0)
        }

        if skipped_reads and sum(skipped_reads.values()) > 0:
            analysis['skipped_reads'] = dict(skipped_reads)

        # Gate on the same bases the decision below counts. total_coverage is
        # pysam's column depth, which is NOT base-quality filtered: at NP 1086 the
        # column is 478 reads deep but only 88 bases survive -Q5, so the old gate
        # cleared min_coverage on reads that never got a vote.
        usable_coverage = sum(base_counts.get(b, 0) for b in ('A', 'T', 'G', 'C'))
        analysis['usable_coverage'] = usable_coverage

        if usable_coverage < self.min_coverage:
            analysis.update({
                'decision': 'KEEP',
                'reason': (f'Coverage too low ({usable_coverage} usable of '
                           f'{total_coverage} reads < {self.min_coverage})')
            })
            return analysis

        standard_base_counts = {base: count for base, count in base_counts.items()
                               if base in ['A', 'T', 'G', 'C']}
        # Sort by count desc, then base asc. The alphabetical tie-break keeps this
        # in step with get_pileup_statistics() and stops an exact tie from being
        # decided by BAM read order, which is not stable across machines.
        sorted_bases = sorted(standard_base_counts.items(), key=lambda x: (-x[1], x[0]))
        deletion_count = base_counts.get('DEL', 0)
        top_base_count = sorted_bases[0][1] if sorted_bases else 0

        # Indels are no longer decided here. A raw pileup count cannot tell a real
        # indel from an alignment artifact: at three high-deletion columns in the
        # reference dataset, no pileup-visible feature (DEL%, strand balance, gap
        # length purity, mapping quality, read-end score, homopolymer length)
        # separated the one bcftools accepts from the two it rejects - and the
        # strongest signal, 80% deletions, was a false positive. What discriminates
        # is realignment, which the pileup has already discarded.
        # Indels now come from bcftools' --indels-cns calls in the VCF and are
        # adjudicated in _adjudicate_indels() against IMF, coverage and reading
        # frame. DEL/INS counts stay in the log as evidence.

        if not sorted_bases:
            analysis.update({
                'decision': 'KEEP',
                'reason': 'No standard bases found'
            })
            return analysis

        if len(sorted_bases) == 1:
            top_base = sorted_bases[0][0]
            if not self._allele_set_violation(analysis, top_base, degeneracy_code, 100.0):
                analysis.update({
                    'decision': 'RESOLVE',
                    'resolved_base': top_base,
                    'reason': f'Only one base type found: {top_base}'
                })
            return analysis

        top_base, top_count = sorted_bases[0]
        second_base, second_count = sorted_bases[1]
        standard_bases_total = sum(standard_base_counts.values())

        if standard_bases_total == 0:
            analysis.update({
                'decision': 'KEEP',
                'reason': 'No standard bases found (only indels/non-standard)'
            })
            return analysis

        top_percentage = (top_count / standard_bases_total) * 100
        second_percentage = (second_count / standard_bases_total) * 100
        percentage_diff = top_percentage - second_percentage

        analysis.update({
            'top_base': top_base,
            'top_count': top_count,
            'top_percentage': top_percentage,
            'second_base': second_base,
            'second_count': second_count,
            'second_percentage': second_percentage,
            'percentage_diff': percentage_diff,
            'standard_bases_total': standard_bases_total
        })

        if percentage_diff >= self.min_percentage_diff:
            # Enforce the ambiguity code's own allele set. `possible_bases` was looked up at
            # the top of this function and then never consulted, so a site carrying (say) R
            # (A/G) could be resolved to C purely on pileup counts - publishing a base that
            # the variant caller's own code declares impossible at that position. That is a
            # disagreement between bcftools and the pileup, not a resolution, so keep the
            # ambiguity and flag it for review rather than silently picking a side.
            if not self._allele_set_violation(analysis, top_base, degeneracy_code, top_percentage):
                analysis.update({
                    'decision': 'RESOLVE',
                    'resolved_base': top_base,
                    'reason': f'Resolve to {top_base}: {top_percentage:.1f}% vs {second_percentage:.1f}%'
                })
        else:
            analysis.update({
                'decision': 'KEEP',
                'reason': f'Ambiguous: {top_base} {top_percentage:.1f}% vs {second_base} {second_percentage:.1f}%'
            })

        return analysis

    def decide_site(self, segment_id: str, consensus_pos: int, genomic_pos: int,
                    original_base: str, base_counts: Counter, strand_counts: dict,
                    total_coverage: int, ref_seq: str, ref_name: str,
                    skipped_reads=None) -> SiteMetrics:
        """Unified site evaluation producing a SiteMetrics record.

        Runs the original decision logic, then layers strand-balance,
        homopolymer, and read-end enrichment on top as warning signals.
        """
        # Run the original decision engine
        analysis = self._analyze_degeneracy_decision_enhanced(
            base_counts, total_coverage, original_base, consensus_pos, genomic_pos, skipped_reads)

        # Extract pileup stats via the modular helper
        pstats = get_pileup_statistics(base_counts, strand_counts, total_coverage)

        if total_coverage > 0:
            major_base = analysis.get('top_base', pstats['sorted_bases'][0][0] if pstats['sorted_bases'] else '')
            second_base = analysis.get('second_base', pstats['sorted_bases'][1][0] if len(pstats['sorted_bases']) > 1 else '')
        else:
            major_base = analysis.get('top_base', '')
            second_base = analysis.get('second_base', '')
        std_total = pstats['standard_total']
        major_freq = (analysis.get('top_percentage', 0.0))
        second_freq = (analysis.get('second_percentage', 0.0))

        # Strand balance
        sb = compute_strand_balance(strand_counts, major_base) if major_base else 0.0

        # Homopolymer
        hp_len, hp_dist, hp_warn = compute_homopolymer_metrics(
            ref_seq, genomic_pos, window=self.homopolymer_window, min_length=self.homopolymer_min_length)

        # Read-end enrichment
        # Score the MINORITY allele: that is the one a read-end artefact would manufacture.
        # Falls back to the major base, then to the whole column, when no second base exists.
        _ree_target = second_base or major_base or None
        ree = compute_read_end_enrichment(self.bam_file_handle, ref_name, genomic_pos,
                                          edge_fraction=self.read_end_edge_fraction,
                                          alt_base=_ree_target)

        # Build warning flags
        warnings = []
        sb_warn = sb < self.strand_balance_threshold and std_total >= self.min_coverage and major_base != ''
        if sb_warn:
            warnings.append(f"strand_bias({sb:.2f})")
        if hp_warn:
            warnings.append(f"homopolymer(len={hp_len},dist={hp_dist})")
        ree_warn = ree > self.read_end_threshold and std_total >= self.min_coverage
        if ree_warn:
            warnings.append(f"read_end_enrichment({ree:.2f})")

        decision = analysis['decision']
        reason = analysis['reason']
        resolved_base = analysis.get('resolved_base', original_base if decision == 'KEEP' else '')

        # Per-warning strict overrides: only cite warnings whose strict flag is on
        if decision == 'RESOLVE':
            strict_triggers = []
            if self.strict_strand_bias and sb_warn:
                strict_triggers.append(f"strand_bias({sb:.2f})")
            if self.strict_homopolymer and hp_warn:
                strict_triggers.append(f"homopolymer(len={hp_len},dist={hp_dist})")
            if self.strict_read_end and ree_warn:
                strict_triggers.append(f"read_end_enrichment({ree:.2f})")
            if strict_triggers:
                decision = 'KEEP'
                reason = f"Reverted by strict mode: {', '.join(strict_triggers)}"
                resolved_base = original_base

        metrics = SiteMetrics(
            segment=segment_id,
            consensus_position=consensus_pos,
            genomic_position=genomic_pos,
            original_base=original_base,
            coverage=total_coverage,
            usable_coverage=analysis.get('usable_coverage', 0),
            a_count=base_counts.get('A', 0),
            c_count=base_counts.get('C', 0),
            g_count=base_counts.get('G', 0),
            t_count=base_counts.get('T', 0),
            insertion_count=pstats['insertion_count'],
            deletion_count=pstats['deletion_count'],
            major_base=major_base,
            second_base=second_base,
            major_allele_freq=major_freq,
            second_allele_freq=second_freq,
            freq_delta=major_freq - second_freq,
            forward_total=pstats['forward_total'],
            reverse_total=pstats['reverse_total'],
            strand_balance=sb,
            strand_bias_warning=sb_warn,
            homopolymer_length=hp_len,
            homopolymer_distance=hp_dist,
            homopolymer_warning=hp_warn,
            read_end_enrichment_score=ree,
            read_end_warning=ree_warn,
            warning_flags=warnings,
            decision=decision,
            reason=reason,
            resolved_base=resolved_base,
        )
        return metrics
    
    # ------------------------------------------------------------------
    # Indel adjudication
    #
    # bcftools --indels-cns proposes indels; this layer decides whether they
    # make biological sense. Nothing upstream knows where a gene starts or
    # that it is read in triplets, so the reading-frame test lives here.
    # ------------------------------------------------------------------

    # ponytail: fixed 4-codon window. Widen only if a dataset shows compensating
    # indel pairs further apart than this.
    INDEL_GROUP_WINDOW = 12
    INDEL_EVIDENCE_MIN_FRACTION = 0.30

    def _load_orfs(self):
        """Longest M..* ORF per reference segment, 1-based inclusive.

        Needs no annotation file. Verified to recover all eight canonical
        influenza proteins exactly (PB2 759, PB1 757, PA 716, HA 560, NP 498,
        NA 469, M1 252, NS1 230).

        LIMITATION - primary product only. Spliced products (M2, NEP) and
        alternative-frame products (PB1-F2, PA-X) are invisible to it.

        This is why _adjudicate_indels does NOT gate its frame test on the ORF
        span. M2 and NEP have their second exon outside it - MP nt 773-1002 and
        NS nt 708-865 on the bundled panel - so an ORF-gated test applied any
        out-of-frame indel landing there unchecked. A net length change that is
        a multiple of 3 preserves every reading frame at once, so requiring it
        segment-wide covers the primary product, both spliced products and the
        alternative-frame products without needing their coordinates.

        The ORF span is still used, but only to word the log message (whether a
        rejected group fell inside the detected gene or outside it).
        """
        if self._orfs is not None:
            return self._orfs
        self._orfs = {}
        for ref_id, rec in self.reference_sequences.items():
            s = str(rec.seq).upper()
            best = None
            for frame in range(3):
                trimmed = s[frame:len(s) - ((len(s) - frame) % 3)]
                if not trimmed:
                    continue
                prot = str(Seq(trimmed).translate())
                for m in re.finditer(r'M[^*]*\*', prot):
                    if best is None or len(m.group()) > best[1]:
                        best = (frame + m.start() * 3 + 1, len(m.group()))
            if best:
                self._orfs[ref_id] = (best[0], best[0] + best[1] * 3 - 1)
        return self._orfs

    def _imf_gate(self, imf, rule):
        """Map an indel_rules setting onto IMF, bcftools' fraction of reads
        supporting the indel.

        IMF is computed by mpileup and passed through untouched by the caller,
        so unlike QUAL it is identical under `bcftools call -c` and `-m`. QUAL
        is not: the same evidence scores ~4.7 points higher under -m, enough to
        straddle a threshold and make indel strictness depend on a setting
        documented as being about allele multiplicity.
        """
        if rule == "more_than":
            return imf > 0.50, "> 0.50"
        if rule == "custom_percentage":
            t = self.indel_custom_percentage / 100.0
            return imf >= t, f">= {t:.2f}"
        return imf >= 0.50, ">= 0.50"

    def _read_vcf_indels(self):
        """Indel records from the step-6 VCF, keyed by reference name."""
        if not self.vcf_file or not os.path.exists(self.vcf_file):
            return {}
        out = defaultdict(list)
        try:
            with pysam.VariantFile(self.vcf_file) as vf:
                for rec in vf:
                    if not rec.alts:
                        continue
                    alt = rec.alts[0]
                    if not alt or not re.fullmatch(r'[ACGTacgt]+', alt):
                        continue
                    dlen = len(alt) - len(rec.ref)
                    if dlen == 0:
                        continue
                    def _num(key, cast, default):
                        v = rec.info.get(key, default)
                        if isinstance(v, (tuple, list)):
                            v = v[0] if v else default
                        try:
                            return cast(v)
                        except (TypeError, ValueError):
                            return cast(default)
                    out[rec.chrom].append({
                        'pos': rec.pos, 'ref': rec.ref, 'alt': alt, 'dlen': dlen,
                        'imf': _num('IMF', float, 0.0),
                        'idv': _num('IDV', int, 0),
                        'dp': _num('DP', int, 0),
                    })
        except Exception as e:
            if self.diagnostic_mode:
                print(f"  Warning: could not read indels from {self.vcf_file}: {e}")
            return {}
        return dict(out)

    def _adjudicate_indels(self, ref_name):
        """Decide which of bcftools' indels may edit this segment.

        Per indel: the coverage floor and the user's indel rule, via IMF.
        Survivors within INDEL_GROUP_WINDOW are then judged as a group. A lone
        -1 nt wrecks the reading frame and everything downstream of it, but a
        -1 and a +1 four bases apart cancel out and leave a single amino-acid
        change. Judged one at a time both are rejected; judged together they
        are a real and benign variant. bcftools evaluates each independently
        and would apply both without knowing why.
        """
        decisions = []
        passed = []
        for ind in sorted(self._vcf_indels.get(ref_name, []), key=lambda d: d['pos']):
            rule = self.indel_deletions if ind['dlen'] < 0 else self.indel_insertions
            ok_imf, shown = self._imf_gate(ind['imf'], rule)
            if ind['dp'] < self.min_coverage:
                decisions.append((ind, 'REJECT',
                                  f"coverage {ind['dp']} < min_coverage {self.min_coverage}"))
            elif not ok_imf:
                decisions.append((ind, 'REJECT',
                                  f"IMF {ind['imf']:.3f} fails {rule} ({shown})"))
            else:
                passed.append(ind)

        orf = self._load_orfs().get(ref_name)
        groups = []
        for ind in passed:
            if groups and ind['pos'] - groups[-1][-1]['pos'] <= self.INDEL_GROUP_WINDOW:
                groups[-1].append(ind)
            else:
                groups.append([ind])

        accepted = []
        for g in groups:
            net = sum(i['dlen'] for i in g)
            in_orf = orf is not None and any(orf[0] <= i['pos'] <= orf[1] for i in g)
            span = f"{g[0]['pos']}-{g[-1]['pos']}" if len(g) > 1 else str(g[0]['pos'])
            # Frame is required across the WHOLE segment, not only inside the primary ORF.
            # _load_orfs finds the longest M..* stretch, which is the primary product only;
            # influenza's spliced products (M2, NEP) have their second exon OUTSIDE that
            # span - MP nt 773-1002 and NS nt 708-865 on the bundled panel. Gating the frame
            # test on in_orf therefore applied any out-of-frame indel landing there with no
            # check at all, silently frameshifting M2 or NEP. It also accepted everything on
            # a segment where no ORF was detected. A net change that is a multiple of 3
            # preserves every reading frame at once, so this single test covers the primary
            # product, both spliced products, and the alternative-frame products (PB1-F2,
            # PA-X) together. The cost is rejecting a non-multiple-of-3 indel in a true UTR,
            # which is untranslated anyway and at ONT depth is near-always a homopolymer
            # artifact.
            if net % 3 != 0:
                where = (f"inside ORF {orf[0]}-{orf[1]}" if in_orf else
                         "outside primary ORF (spliced product may be affected)")
                why = (f"frameshift: {len(g)} indel(s) at {span} net {net:+d} nt {where}")
                decisions.extend((i, 'REJECT', why) for i in g)
            else:
                if len(g) > 1:
                    why = f"group of {len(g)} at {span} nets {net:+d} nt, frame preserved"
                else:
                    why = "in frame" if in_orf else "in frame (outside primary ORF)"
                decisions.extend((i, 'ACCEPT', why) for i in g)
                accepted.extend(g)
        return accepted, decisions

    def _apply_indels(self, seq_record, accepted):
        """Apply accepted indels right to left so earlier positions stay valid.

        Runs only after every degeneracy is resolved: resolution maps consensus
        position onto reference position 1:1, and an applied indel breaks that
        mapping for everything downstream. Resolved bases are preserved - only
        the differing tail of each record is spliced.
        """
        s = str(seq_record.seq)
        for ind in sorted(accepted, key=lambda d: d['pos'], reverse=True):
            i = ind['pos'] - 1
            r, a = ind['ref'], ind['alt']
            if i < 0 or i + len(r) > len(s):
                continue
            if ind['dlen'] < 0 and r.upper().startswith(a.upper()):
                s = s[:i + len(a)] + s[i + len(r):]
            elif ind['dlen'] > 0 and a.upper().startswith(r.upper()):
                s = s[:i + len(r)] + a[len(r):] + s[i + len(r):]
            else:
                s = s[:i] + a + s[i + len(r):]
        seq_record.seq = Seq(s)
        return seq_record

    def _sweep_indel_evidence(self, applied_keys):
        """Columns whose deletion fraction clears the threshold but where no
        indel was applied.

        On a hac basecall the mpileup profile carries -I, so bcftools calls no
        indels at all and a real deletion would otherwise be reported nowhere.
        The resolver's own indel decisions only ever saw positions that carried
        an IUPAC code, which is why an 80%-deletion column with an unambiguous
        draft base was invisible to every earlier version.
        """
        found = []
        for seq_id in self.consensus_sequences:
            ref_name, _ = self._get_reference_for_segment(seq_id)
            if not ref_name or ref_name not in self.bam_file_handle.references:
                continue
            try:
                for col in self.bam_file_handle.pileup(
                        ref_name, truncate=True,
                        min_base_quality=self.min_base_quality,
                        max_depth=1000000, stepper='all'):
                    # col.n is not base-quality filtered; count what survived the
                    # filter instead. Deletions stay in the denominator - the ratio
                    # is deletions per read, not per called base.
                    dels = 0
                    usable = 0
                    for pr in col.pileups:
                        if pr.is_del:
                            dels += 1
                            usable += 1
                        elif not pr.is_refskip and pr.query_position is not None:
                            usable += 1
                    if usable < self.min_coverage:
                        continue
                    if dels / usable < self.INDEL_EVIDENCE_MIN_FRACTION:
                        continue
                    pos = col.pos + 1
                    if (ref_name, pos) in applied_keys:
                        continue
                    found.append((seq_id, ref_name, pos, dels, usable, 100.0 * dels / usable))
            except Exception:
                continue
        return found

    def _create_log_entry(self, segment_id, consensus_pos, original_base, analysis, new_base):
        """Create a structured log entry for the degeneracy log file"""
        base_counts = analysis.get('base_counts', {})
        standard_bases = [(base, count) for base, count in base_counts.items() if base in ['A', 'T', 'G', 'C']]
        standard_bases.sort(key=lambda x: x[1], reverse=True)
        
        top_base_info = "N/A"
        second_base_info = "N/A"
        
        if len(standard_bases) >= 1:
            base1, count1 = standard_bases[0]
            total_standard = sum(count for _, count in standard_bases)
            if total_standard > 0:
                pct1 = (count1 / total_standard) * 100
                top_base_info = f"{base1}:{count1} ({pct1:.1f}%)"
        
        if len(standard_bases) >= 2:
            base2, count2 = standard_bases[1]
            if total_standard > 0:
                pct2 = (count2 / total_standard) * 100
                second_base_info = f"{base2}:{count2} ({pct2:.1f}%)"
        
        status = "UNCHANGED" if original_base == new_base else "CHANGED"
        
        return {
            'segment': segment_id,
            'consensus_position': consensus_pos + 1,
            'genomic_position': analysis.get('genomic_position', 'N/A') + 1 if analysis.get('genomic_position') is not None else 'N/A',
            'original_base': original_base,
            'new_base': new_base,
            'status': status,
            'coverage': analysis.get('total_coverage', 0),
            'top_base': top_base_info,
            'second_base': second_base_info,
            'deletions': analysis.get('deletion_count', 0),
            'insertions': analysis.get('insertion_count', 0),
            'decision': analysis.get('decision', 'N/A'),
            'reason': analysis.get('reason', 'N/A')
        }
    
    def _process_sequence(self, seq_record):
        """Process a single sequence to resolve degeneracies."""
        # vcfutils.pl vcf2fq (the default `-c` path) SOFT-MASKS low-confidence positions as
        # lowercase - depth < 3 or quality < 10. Uppercasing the whole sequence here destroyed
        # that mask, so those positions were published as confident calls indistinguishable
        # from well-supported ones. Work in uppercase (every comparison below assumes it), but
        # remember the mask and restore it for any position this editor did not resolve.
        raw_sequence = str(seq_record.seq)
        sequence = raw_sequence.upper()
        new_sequence = list(sequence)
        was_soft_masked = [c.islower() for c in raw_sequence]
        resolved_positions = set()

        ref_name, ref_seq = self._get_reference_for_segment(seq_record.id)

        if ref_name is None or ref_seq is None:
            if self.diagnostic_mode:
                print(f"\nProcessing sequence: {seq_record.id}")
                print(f"  Warning: No reference sequence found, keeping original")
            return seq_record

        if self.diagnostic_mode:
            print(f"\nProcessing sequence: {seq_record.id}")
            print(f"  Using reference: {ref_name}")

        sequence_stats = {
            'total_degeneracies': 0,
            'resolved_degeneracies': 0,
            'kept_degeneracies': 0,
            'resolved_to_deletion': 0,
            'degeneracy_types': defaultdict(int),
            'resolution_reasons': defaultdict(int),
            'strand_bias_count': 0,
            'homopolymer_count': 0,
            'read_end_enrichment_count': 0,
        }

        for consensus_pos, base in enumerate(sequence):
            if base in self.degeneracy_codes:
                sequence_stats['total_degeneracies'] += 1
                sequence_stats['degeneracy_types'][base] += 1

                genomic_pos = consensus_pos

                if genomic_pos >= len(ref_seq):
                    sequence_stats['kept_degeneracies'] += 1
                    sequence_stats['resolution_reasons']['position_out_of_range'] += 1

                    oor_metrics = SiteMetrics(
                        segment=seq_record.id, consensus_position=consensus_pos,
                        genomic_position=-1, original_base=base,
                        decision='KEEP', reason='Position out of reference range',
                        resolved_base=base,
                    )
                    self.site_metrics_log.append(oor_metrics)

                    if self.diagnostic_mode:
                        log_entry = {
                            'segment': seq_record.id,
                            'consensus_position': consensus_pos + 1,
                            'genomic_position': 'N/A',
                            'original_base': base, 'new_base': base,
                            'status': 'UNCHANGED', 'coverage': 0,
                            'top_base': 'N/A', 'second_base': 'N/A',
                            'deletions': 0, 'insertions': 0,
                            'decision': 'KEEP', 'reason': 'Position out of reference range'
                        }
                        self.degeneracy_log.append(log_entry)
                    continue

                base_counts, total_coverage, skipped_reads, strand_counts = \
                    self._get_base_counts_at_position(ref_name, genomic_pos)

                # Use the new unified decision engine
                metrics = self.decide_site(
                    seq_record.id, consensus_pos, genomic_pos, base,
                    base_counts, strand_counts, total_coverage, ref_seq, ref_name,
                    skipped_reads)
                self.site_metrics_log.append(metrics)

                # Track warnings
                if metrics.strand_bias_warning:
                    sequence_stats['strand_bias_count'] += 1
                if metrics.homopolymer_warning:
                    sequence_stats['homopolymer_count'] += 1
                if metrics.read_end_warning:
                    sequence_stats['read_end_enrichment_count'] += 1

                if metrics.decision == 'RESOLVE':
                    new_base = metrics.resolved_base
                    new_sequence[consensus_pos] = new_base
                    resolved_positions.add(consensus_pos)
                    sequence_stats['resolved_degeneracies'] += 1
                    if new_base == '-':
                        sequence_stats['resolved_to_deletion'] += 1
                        sequence_stats['resolution_reasons']['resolved_to_deletion'] += 1
                    else:
                        sequence_stats['resolution_reasons']['resolved_to_base'] += 1
                else:
                    new_base = base
                    sequence_stats['kept_degeneracies'] += 1
                    if 'low' in metrics.reason.lower():
                        sequence_stats['resolution_reasons']['low_coverage'] += 1
                    else:
                        sequence_stats['resolution_reasons']['ambiguous'] += 1

                # Build the legacy analysis dict for the old log entry
                analysis = {
                    'consensus_position': consensus_pos,
                    'genomic_position': genomic_pos,
                    'total_coverage': total_coverage,
                    'base_counts': dict(base_counts),
                    'deletion_count': metrics.deletion_count,
                    'insertion_count': metrics.insertion_count,
                    'decision': metrics.decision,
                    'reason': metrics.reason,
                    'resolved_base': metrics.resolved_base,
                    'top_base': metrics.major_base,
                    'top_percentage': metrics.major_allele_freq,
                    'second_base': metrics.second_base,
                    'second_percentage': metrics.second_allele_freq,
                }
                self.degeneracy_log.append(
                    self._create_log_entry(seq_record.id, consensus_pos, base, analysis, new_base))

        self.processing_stats[seq_record.id] = sequence_stats

        if self.diagnostic_mode:
            print(f"  Summary: {sequence_stats['resolved_degeneracies']}/{sequence_stats['total_degeneracies']} degeneracies resolved")
            if sequence_stats['strand_bias_count']:
                print(f"  Strand bias warnings: {sequence_stats['strand_bias_count']}")
            if sequence_stats['homopolymer_count']:
                print(f"  Homopolymer warnings: {sequence_stats['homopolymer_count']}")
            if sequence_stats['read_end_enrichment_count']:
                print(f"  Read-end enrichment warnings: {sequence_stats['read_end_enrichment_count']}")

        # Restore the soft-mask everywhere this editor did not make a positive call. A position
        # we resolved has documented pileup support, so it is published uppercase; everything
        # else keeps the confidence marking vcf2fq gave it.
        for _i, _masked in enumerate(was_soft_masked):
            if _masked and _i not in resolved_positions:
                new_sequence[_i] = new_sequence[_i].lower()

        return SeqRecord(Seq(''.join(new_sequence)), id=seq_record.id, description=seq_record.description)
    
    def _write_diagnostic_log(self):
        """Write comprehensive diagnostic log file with enriched per-site metrics."""
        log_filename = str(self.output_file).rsplit('.', 1)[0] + "_diagnostic_log.txt"
        with open(log_filename, 'w') as log_file:
            log_file.write("CONSENSUS DEGENERACY RESOLUTION LOG\n")
            log_file.write("=" * 200 + "\n")
            log_file.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log_file.write(f"Consensus File: {self.consensus_file}\n")
            log_file.write(f"Reference File: {self.reference_file}\n")
            log_file.write(f"BAM File: {self.bam_file}\n")
            log_file.write(f"Min Coverage: {self.min_coverage}\n")
            log_file.write(f"Min Percentage Diff: {self.min_percentage_diff}%\n")
            log_file.write(f"Strand Balance Threshold: {self.strand_balance_threshold}\n")
            log_file.write(f"Homopolymer Min Length: {self.homopolymer_min_length}\n")
            log_file.write(f"Homopolymer Window: {self.homopolymer_window}\n")
            log_file.write(f"Read-End Enrichment Threshold: {self.read_end_threshold}\n")
            log_file.write(f"Read-End Edge Fraction: {self.read_end_edge_fraction}\n")
            log_file.write(f"Strict Strand Bias: {self.strict_strand_bias}\n")
            log_file.write(f"Strict Homopolymer: {self.strict_homopolymer}\n")
            log_file.write(f"Strict Read-End: {self.strict_read_end}\n")
            log_file.write("=" * 200 + "\n\n")

            # Segment mapping
            log_file.write("SEGMENT MAPPING:\n")
            log_file.write("-" * 60 + "\n")
            for cons_seg, ref_seg in self.segment_mapping.items():
                log_file.write(f"{cons_seg} -> {ref_seg}\n")
            log_file.write("\n")

            # Enriched per-site table
            headers = [
                "Segment", "Cons_Pos", "Genomic_Pos", "Original", "New", "Status",
                # Coverage is pysam's raw column depth; Usable_Coverage is the base-quality
                # filtered A+C+G+T depth that min_coverage is actually judged against. Both are
                # printed because they can differ several-fold and only one of them is the
                # number that decided the call.
                "Coverage", "Usable_Coverage", "A", "C", "G", "T", "INS", "DEL",
                "Major_Base", "Second_Base", "Major_AF%", "Second_AF%", "Delta%",
                "Fwd", "Rev", "Strand_Balance",
                "HP_Len", "HP_Dist", "ReadEnd_Score",
                "Warnings", "Decision", "Reason"
            ]
            log_file.write("\t".join(headers) + "\n")
            log_file.write("-" * 200 + "\n")

            for m in self.site_metrics_log:
                new_base = m.resolved_base if m.decision == 'RESOLVE' else m.original_base
                status = "UNCHANGED" if m.original_base == new_base else "CHANGED"
                warn_str = ";".join(m.warning_flags) if m.warning_flags else "-"
                row = [
                    m.segment,
                    str(m.consensus_position + 1),
                    str(m.genomic_position + 1) if m.genomic_position >= 0 else "N/A",
                    m.original_base,
                    new_base,
                    status,
                    str(m.coverage),
                    str(m.usable_coverage),
                    str(m.a_count), str(m.c_count), str(m.g_count), str(m.t_count),
                    str(m.insertion_count), str(m.deletion_count),
                    m.major_base or "-", m.second_base or "-",
                    f"{m.major_allele_freq:.1f}", f"{m.second_allele_freq:.1f}",
                    f"{m.freq_delta:.1f}",
                    str(m.forward_total), str(m.reverse_total),
                    f"{m.strand_balance:.3f}",
                    str(m.homopolymer_length), str(m.homopolymer_distance),
                    f"{m.read_end_enrichment_score:.3f}",
                    warn_str, m.decision,
                    m.reason.replace('\t', ' '),
                ]
                log_file.write("\t".join(row) + "\n")

            # Summary statistics
            log_file.write("\n" + "=" * 200 + "\n")
            log_file.write("INDEL DECISIONS (bcftools calls, adjudicated here)\n")
            log_file.write("=" * 200 + "\n")
            if not self.vcf_file:
                log_file.write("No VCF supplied; indel adjudication did not run.\n")
            elif not self.indel_decisions:
                log_file.write("bcftools called no indels. On a hac basecall this is expected:\n")
                log_file.write("the ont mpileup profile carries -I, which skips indel calling.\n")
            else:
                log_file.write("Segment\tGenomic_Pos\tChange\tNet_nt\tIMF\tIDV\tDP\tVerdict\tReason\n")
                log_file.write("-" * 200 + "\n")
                for seg, ref_name, ind, verdict, why in self.indel_decisions:
                    log_file.write("\t".join([
                        seg, str(ind['pos']), f"{ind['ref']}->{ind['alt']}",
                        f"{ind['dlen']:+d}", f"{ind['imf']:.3f}", str(ind['idv']),
                        str(ind['dp']), verdict, why]) + "\n")

            log_file.write("\n" + "=" * 200 + "\n")
            log_file.write("INDEL EVIDENCE (not acted upon)\n")
            log_file.write("=" * 200 + "\n")
            log_file.write(f"Columns with deletion fraction >= {self.INDEL_EVIDENCE_MIN_FRACTION:.0%} "
                           f"and coverage >= {self.min_coverage} where no indel was applied.\n")
            if not self.indel_evidence:
                log_file.write("None.\n")
            else:
                log_file.write("Segment\tGenomic_Pos\tDEL\tCoverage\tDEL%\n")
                log_file.write("-" * 200 + "\n")
                for seg, ref_name, pos, dels, n, pct in sorted(
                        self.indel_evidence, key=lambda r: -r[5]):
                    log_file.write(f"{seg}\t{pos}\t{dels}\t{n}\t{pct:.1f}\n")
                log_file.write("These are reported, not resolved. Deletion counts alone cannot\n")
                log_file.write("distinguish a real indel from an alignment artifact; re-basecall\n")
                log_file.write("at sup so bcftools can model them, or inspect in IGV.\n")

            log_file.write("\n" + "=" * 200 + "\n")
            log_file.write("SUMMARY STATISTICS\n")
            log_file.write("=" * 200 + "\n")

            total_degeneracies = sum(s['total_degeneracies'] for s in self.processing_stats.values())
            total_resolved = sum(s['resolved_degeneracies'] for s in self.processing_stats.values())
            total_to_deletion = sum(s['resolved_to_deletion'] for s in self.processing_stats.values())
            total_strand_bias = sum(s.get('strand_bias_count', 0) for s in self.processing_stats.values())
            total_homopolymer = sum(s.get('homopolymer_count', 0) for s in self.processing_stats.values())
            total_read_end = sum(s.get('read_end_enrichment_count', 0) for s in self.processing_stats.values())

            log_file.write(f"Total degeneracies processed: {total_degeneracies}\n")
            log_file.write(f"Total degeneracies resolved: {total_resolved}\n")
            log_file.write(f"Total resolved to deletions: {total_to_deletion}\n")
            log_file.write(f"Total kept unchanged: {total_degeneracies - total_resolved}\n")
            if total_degeneracies > 0:
                log_file.write(f"Resolution rate: {(total_resolved / total_degeneracies) * 100:.1f}%\n")
            log_file.write(f"Strand bias warnings: {total_strand_bias}\n")
            log_file.write(f"Homopolymer warnings: {total_homopolymer}\n")
            log_file.write(f"Read-end enrichment warnings: {total_read_end}\n")

            log_file.write(f"\nPer-segment statistics:\n")
            for segment_id, stats in self.processing_stats.items():
                log_file.write(f"  {segment_id}:\n")
                log_file.write(f"    Total degeneracies: {stats['total_degeneracies']}\n")
                log_file.write(f"    Resolved: {stats['resolved_degeneracies']}\n")
                log_file.write(f"    Kept: {stats['kept_degeneracies']}\n")
                log_file.write(f"    Strand bias warnings: {stats.get('strand_bias_count', 0)}\n")
                log_file.write(f"    Homopolymer warnings: {stats.get('homopolymer_count', 0)}\n")
                log_file.write(f"    Read-end enrichment warnings: {stats.get('read_end_enrichment_count', 0)}\n")
                if stats['total_degeneracies'] > 0:
                    rate = (stats['resolved_degeneracies'] / stats['total_degeneracies']) * 100
                    log_file.write(f"    Resolution rate: {rate:.1f}%\n")
    
    def _print_final_summary(self):
        """Print a comprehensive summary of processing results"""
        print(f"\n{'='*60}")
        print(f"PROCESSING SUMMARY")
        print(f"{'='*60}")
        
        total_degeneracies = sum(stats['total_degeneracies'] for stats in self.processing_stats.values())
        total_resolved = sum(stats['resolved_degeneracies'] for stats in self.processing_stats.values())
        total_to_deletion = sum(stats['resolved_to_deletion'] for stats in self.processing_stats.values())
        
        print(f"Consensus file: {self.consensus_file}")
        print(f"BAM file: {self.bam_file}")
        print(f"Reference file: {self.reference_file}")
        print(f"Segments processed: {len(self.processing_stats)}")
        print(f"Total degeneracies found: {total_degeneracies}")
        print(f"Total degeneracies resolved: {total_resolved}")
        print(f"  - Resolved to bases: {total_resolved - total_to_deletion}")
        print(f"  - Resolved to deletions: {total_to_deletion}")
        
        if total_degeneracies > 0:
            print(f"Resolution rate: {(total_resolved / total_degeneracies) * 100:.1f}%")
        
        print(f"\nPer-segment summary:")
        for segment_id, stats in self.processing_stats.items():
            if stats['total_degeneracies'] > 0:
                rate = (stats['resolved_degeneracies'] / stats['total_degeneracies']) * 100
                print(f"  {segment_id}: {stats['resolved_degeneracies']}/{stats['total_degeneracies']} ({rate:.1f}%)")
        
        print(f"\nSegment mapping used:")
        # Show mapping only for processed segments
        for cons_seg in self.processing_stats.keys():
            ref_seg = self.segment_mapping.get(cons_seg, 'N/A')
            print(f"  {cons_seg} -> {ref_seg}")
    
    def _build_qc_summary(self) -> dict:
        """Build a deterministic QC summary dict from processing results."""
        total_sites = len(self.site_metrics_log)
        resolved_to_base = sum(1 for m in self.site_metrics_log if m.decision == 'RESOLVE' and m.resolved_base not in ('-', 'N'))
        retained_iupac = sum(1 for m in self.site_metrics_log if m.decision == 'KEEP' and 'ambiguous' in m.reason.lower())
        # Indels no longer pass through site_metrics_log; they are adjudicated
        # from the VCF after degeneracy resolution.
        converted_indel = sum(1 for _s, _r, _i, verdict, _w in self.indel_decisions
                              if verdict == 'ACCEPT')
        low_coverage = sum(1 for m in self.site_metrics_log if m.decision == 'KEEP' and 'low' in m.reason.lower())
        # The buckets above are substring tests on the reason string and do NOT partition the
        # sites: a strict-mode revert, an allele-set conflict, an out-of-range position or a
        # segment with no reference all land in none of them, so the published counts silently
        # failed to add up to total_sites_examined. Classify the remainder explicitly and
        # publish an 'unaccounted' figure that a reader can check against zero.
        strict_reverted = sum(1 for m in self.site_metrics_log
                              if m.decision == 'KEEP' and m.reason.startswith('Reverted by strict mode'))
        allele_conflict = sum(1 for m in self.site_metrics_log
                              if m.decision == 'KEEP' and 'allele set' in m.reason)
        _classified = (resolved_to_base + retained_iupac + low_coverage
                       + strict_reverted + allele_conflict)
        unaccounted = total_sites - _classified
        strand_bias_flagged = sum(1 for m in self.site_metrics_log if m.strand_bias_warning)
        homopolymer_flagged = sum(1 for m in self.site_metrics_log if m.homopolymer_warning)
        read_end_flagged = sum(1 for m in self.site_metrics_log if m.read_end_warning)

        def _summarise(values):
            if not values:
                return {}
            sv = sorted(values)
            return {
                'min': sv[0],
                'max': sv[-1],
                'median': sv[len(sv) // 2],
                'mean': round(sum(sv) / len(sv), 1),
            }

        # Two depth summaries, because they are not interchangeable: 'coverage_summary' is raw
        # column depth, 'usable_coverage_summary' is the base-quality-filtered depth that
        # min_coverage is compared against. Publishing only the raw figure overstated the
        # voting depth behind every ambiguous site.
        coverages = [m.coverage for m in self.site_metrics_log if m.coverage > 0]
        usable = [m.usable_coverage for m in self.site_metrics_log if m.coverage > 0]
        cov_summary = _summarise(coverages)
        usable_summary = _summarise(usable)

        per_segment = {}
        for seg_id, stats in self.processing_stats.items():
            per_segment[seg_id] = {
                'total_degeneracies': stats['total_degeneracies'],
                'resolved': stats['resolved_degeneracies'],
                'kept': stats['kept_degeneracies'],
                'resolved_to_deletion': stats['resolved_to_deletion'],
                'strand_bias_warnings': stats.get('strand_bias_count', 0),
                'homopolymer_warnings': stats.get('homopolymer_count', 0),
                'read_end_warnings': stats.get('read_end_enrichment_count', 0),
            }

        return {
            'generated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'consensus_file': str(self.consensus_file),
            'bam_file': str(self.bam_file),
            'reference_file': str(self.reference_file),
            'parameters': {
                'min_coverage': self.min_coverage,
                'min_percentage_diff': self.min_percentage_diff,
                'strand_balance_threshold': self.strand_balance_threshold,
                'homopolymer_min_length': self.homopolymer_min_length,
                'homopolymer_window': self.homopolymer_window,
                'read_end_threshold': self.read_end_threshold,
                'read_end_edge_fraction': self.read_end_edge_fraction,
                'strict': {
                    'strand_bias': self.strict_strand_bias,
                    'homopolymer': self.strict_homopolymer,
                    'read_end': self.strict_read_end,
                },
            },
            'total_sites_examined': total_sites,
            'resolved_to_dominant_base': resolved_to_base,
            'retained_as_iupac': retained_iupac,
            'converted_to_indel': converted_indel,
            'indels_proposed_by_bcftools': len(self.indel_decisions),
            'indels_rejected_by_guard': sum(1 for _s, _r, _i, v, _w in self.indel_decisions
                                            if v == 'REJECT'),
            'indel_evidence_not_acted_upon': len(self.indel_evidence),
            'retained_low_coverage': low_coverage,
            'retained_strict_mode_revert': strict_reverted,
            'retained_allele_set_conflict': allele_conflict,
            # Should be 0. A non-zero value means a site took a decision path none of the
            # published buckets describe - report it rather than hiding it in the arithmetic.
            'sites_unaccounted_for': unaccounted,
            'flagged_strand_bias': strand_bias_flagged,
            'flagged_homopolymer': homopolymer_flagged,
            'flagged_read_end_enrichment': read_end_flagged,
            'coverage_summary': cov_summary,
            'usable_coverage_summary': usable_summary,
            'per_segment': per_segment,
        }

    def _write_qc_json(self):
        """Write a JSON QC summary report."""
        summary = self._build_qc_summary()
        json_path = str(self.output_file).rsplit('.', 1)[0] + "_qc_summary.json"
        with open(json_path, 'w') as f:
            json.dump(summary, f, indent=2)
        return json_path

    def _write_qc_html(self):
        """Write an HTML QC summary report."""
        summary = self._build_qc_summary()
        html_path = str(self.output_file).rsplit('.', 1)[0] + "_qc_summary.html"

        rows = []
        for key in ['total_sites_examined', 'resolved_to_dominant_base', 'retained_as_iupac',
                     'converted_to_indel', 'retained_low_coverage',
                     'retained_strict_mode_revert', 'retained_allele_set_conflict',
                     'sites_unaccounted_for', 'flagged_strand_bias',
                     'flagged_homopolymer', 'flagged_read_end_enrichment']:
            label = key.replace('_', ' ').title()
            rows.append(f"<tr><td>{html_escape(label)}</td><td>{html_escape(summary[key])}</td></tr>")

        # Both depth summaries, side by side and labelled. Showing only raw column depth
        # invited the reader to compare it against min_coverage, which is the wrong comparison.
        cov = summary.get('coverage_summary', {})
        ucov = summary.get('usable_coverage_summary', {})
        cov_rows = "".join(
            f"<tr><td>{html_escape(k)}</td><td>{html_escape(v)}</td>"
            f"<td>{html_escape(ucov.get(k, 'N/A'))}</td></tr>"
            for k, v in cov.items())

        seg_rows = []
        for seg, info in summary.get('per_segment', {}).items():
            seg_rows.append(f"<tr><td>{html_escape(seg)}</td><td>{info['total_degeneracies']}</td>"
                            f"<td>{info['resolved']}</td><td>{info['kept']}</td>"
                            f"<td>{info['strand_bias_warnings']}</td>"
                            f"<td>{info['homopolymer_warnings']}</td>"
                            f"<td>{info['read_end_warnings']}</td></tr>")

        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>QC Summary</title>
<style>
body {{ font-family: sans-serif; margin: 2em; }}
table {{ border-collapse: collapse; margin: 1em 0; }}
th, td {{ border: 1px solid #ccc; padding: 6px 12px; text-align: left; }}
th {{ background: #f4f4f4; }}
h1 {{ font-size: 1.4em; }} h2 {{ font-size: 1.1em; }}
</style></head><body>
<h1>DeGenRESOLVE QC Summary</h1>
<p>Generated: {summary['generated']}</p>
<p>Consensus: {html_escape(summary['consensus_file'])}<br>BAM: {html_escape(summary['bam_file'])}<br>Reference: {html_escape(summary['reference_file'])}</p>
<h2>Overall</h2>
<table><tr><th>Metric</th><th>Value</th></tr>{''.join(rows)}</table>
<h2>Coverage</h2>
<p>Raw column depth vs. base-quality-filtered (usable) depth. <b>min_coverage is judged
against the usable depth</b>, not the raw depth.</p>
<table><tr><th>Stat</th><th>Raw depth</th><th>Usable depth</th></tr>{cov_rows}</table>
<h2>Per Segment</h2>
<table><tr><th>Segment</th><th>Total</th><th>Resolved</th><th>Kept</th><th>Strand Bias</th><th>Homopolymer</th><th>Read-End</th></tr>{''.join(seg_rows)}</table>
</body></html>"""

        with open(html_path, 'w') as f:
            f.write(html)
        return html_path

    def process_consensus(self):
        """Main method to process the consensus file and resolve degeneracies."""
        if self.diagnostic_mode:
            print(f"{'='*60}")
            print(f"CONSENSUS DEGENERACY PROCESSOR")
            print(f"{'='*60}")
            print(f"Consensus file: {self.consensus_file}")
            print(f"Reference file: {self.reference_file}")
            print(f"BAM file: {self.bam_file}")
            print(f"Output file: {self.output_file}")

        # Determine output ordering
        seq_ids = list(self.consensus_sequences.keys())
        ordered_ids = seq_ids
        if (self.filter_mode or "").lower() == "influenza":
            priority = []
            def find_h(seq_list):
                for sid in seq_list:
                    u = sid.upper()
                    if u.startswith('HA') or (u.startswith('H') and len(u) > 1 and u[1].isdigit()):
                        return sid
                return None
            def find_n(seq_list):
                for sid in seq_list:
                    u = sid.upper()
                    if u.startswith('NA') or (u.startswith('N') and len(u) > 1 and u[1].isdigit()):
                        return sid
                return None

            chosen_h = None
            chosen_n = None
            # Same prefix-tolerant resolution as the segment selection above, so ordering
            # and selection can never disagree about what the user asked for.
            _oh = self._resolve_segment_override(getattr(self, 'major_h_override', None))
            _on = self._resolve_segment_override(getattr(self, 'major_n_override', None))
            if _oh in seq_ids:
                chosen_h = _oh
            if _on in seq_ids:
                chosen_n = _on
            if chosen_h is None:
                chosen_h = self.major_h_seq if (self.major_h_seq in seq_ids) else find_h(seq_ids)
            if chosen_n is None:
                chosen_n = self.major_n_seq if (self.major_n_seq in seq_ids) else find_n(seq_ids)

            if chosen_h:
                priority.append(chosen_h)
            if chosen_n and chosen_n not in priority:
                priority.append(chosen_n)

            core_order = ["PB2", "PB1", "PA", "MP", "NP", "NS"]
            for core in core_order:
                present = [sid for sid in seq_ids
                           if core in ([sid.upper()] + sid.upper().replace("-", "_").split("_"))
                           and sid not in priority]
                priority.extend(present)

            # Never silently drop a segment that passed the influenza filter
            ordered_ids = priority + [sid for sid in seq_ids if sid not in priority]

            if self.diagnostic_mode:
                print("\nOutput order (influenza mode):")
                print(f"  Major H: {chosen_h}")
                print(f"  Major N: {chosen_n}")
                for sid in ordered_ids:
                    print(f"  - {sid}")
        else:
            ordered_ids = sorted(seq_ids, key=lambda s: s.upper())

        processed_sequences = []
        for seq_id in ordered_ids:
            processed_seq = self._process_sequence(self.consensus_sequences[seq_id])
            processed_sequences.append(processed_seq)

        # Indels run last. Degeneracy resolution above depends on consensus
        # position == reference position; an applied indel breaks that mapping
        # for every site downstream of it.
        self._vcf_indels = self._read_vcf_indels()
        self.indel_decisions = []
        applied_keys = set()
        for seq in processed_sequences:
            ref_name, _ = self._get_reference_for_segment(seq.id)
            if not ref_name:
                continue
            accepted, decisions = self._adjudicate_indels(ref_name)
            for ind, verdict, why in decisions:
                self.indel_decisions.append((seq.id, ref_name, ind, verdict, why))
            if accepted:
                self._apply_indels(seq, accepted)
                applied_keys.update((ref_name, i['pos']) for i in accepted)
        self.indel_evidence = self._sweep_indel_evidence(applied_keys)

        for seq in processed_sequences:
            seq.id = f"{self.sample_id}_{seq.id}"
            seq.description = seq.id

        with open(self.output_file, 'w') as output_handle:
            SeqIO.write(processed_sequences, output_handle, "fasta")

        # Always write QC reports
        json_path = self._write_qc_json()
        html_path = self._write_qc_html()

        if self.diagnostic_mode:
            self._write_diagnostic_log()
            self._print_final_summary()
            print(f"\nQC JSON report: {json_path}")
            print(f"QC HTML report: {html_path}")

        self.bam_file_handle.close()

def main():
    """Main function to run the consensus degeneracy processor."""
    parser = argparse.ArgumentParser(
        description="Consensus Degeneracy Processor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This tool processes consensus FASTA files to resolve degeneracy codes
using coverage information from corresponding BAM files.

Examples:
  python %(prog)s barcode01_consensus.fasta reference/reference.fasta --diagnostic
  python %(prog)s barcode01_consensus.fasta reference/reference.fasta --bam barcode01_analysis/barcode01.bam
  python %(prog)s barcode01_consensus.fasta reference/reference.fasta --output edited.fasta
  python %(prog)s barcode01_consensus.fasta reference/reference.fasta --filter-mode influenza --diagnostic
        """
    )

    parser.add_argument("consensus_file", help="Input consensus file in FASTA format")
    parser.add_argument("reference_file", help="Reference file in FASTA format (reference/reference.fasta)")
    parser.add_argument("--bam", default=None, help="BAM file (auto-detected if not specified)")
    parser.add_argument("--output", default=None, help="Output file (auto-generated if not specified)")
    parser.add_argument("--min-coverage", type=int, default=100,
                       help="Minimum usable read depth before a site may be edited. Also the "
                            "first gate on every VCF indel: a call whose DP is below this is "
                            "rejected before its IMF is looked at (default: 100)")
    parser.add_argument("--min-percentage-diff", type=int, default=20,
                       help="Minimum percentage difference between top two bases")
    parser.add_argument("--filter-mode", choices=["general", "influenza"], default="general",
                       help="Filter mode: 'general' or 'influenza'")
    parser.add_argument("--indel-insertions", choices=["equal_or_more", "more_than", "custom_percentage"], default="equal_or_more",
                       help="Support an insertion needs, tested against the VCF IMF field "
                            "(IMF = IDV/DP). equal_or_more: IMF >= 0.50; more_than: IMF > 0.50; "
                            "custom_percentage: IMF >= --indel-custom-percentage/100")
    parser.add_argument("--indel-deletions", choices=["equal_or_more", "more_than", "custom_percentage"], default="equal_or_more",
                       help="Same rule applied to deletions (default: equal_or_more)")
    parser.add_argument("--indel-custom-percentage", type=float, default=50.0,
                       help="IMF threshold in percent, used only when a rule above is set to "
                            "custom_percentage. 30.0 means IMF >= 0.30 (default: 50.0)")
    parser.add_argument("--diagnostic", action="store_true",
                       help="Enable detailed diagnostic output and create log file")
    parser.add_argument("--major-h", dest="major_h", default=None,
                       help="Override: consensus ID of major H segment (e.g., H3/HA)")
    parser.add_argument("--major-n", dest="major_n", default=None,
                       help="Override: consensus ID of major N segment (e.g., N2/NA)")

    # New QC parameters
    parser.add_argument("--strand-balance-threshold", type=float, default=0.1,
                       help="Strand balance warning threshold (0-1, default: 0.1)")
    parser.add_argument("--homopolymer-min-length", type=int, default=5,
                       help="Minimum homopolymer run length to flag (default: 5)")
    parser.add_argument("--homopolymer-window", type=int, default=5,
                       help="Window size around site to search for homopolymers (default: 5)")
    parser.add_argument("--read-end-threshold", type=float, default=0.8,
                       help="Read-end enrichment warning threshold (0-1, default: 0.8)")
    parser.add_argument("--read-end-edge-fraction", type=float, default=0.1,
                       help="Fraction of each read end considered 'edge' (0-0.5, default: 0.1)")
    parser.add_argument("--strict-strand-bias", action="store_true",
                       help="Strict: strand bias warnings override base calls")
    parser.add_argument("--strict-homopolymer", action="store_true",
                       help="Strict: homopolymer warnings override base calls")
    parser.add_argument("--min-base-quality", type=int, default=5,
                        help="Minimum base quality for the pileup (floored at 5; this "
                             "pileup counts reads and cannot down-weight like --max-BQ)")
    parser.add_argument("--vcf", default=None,
                        help="Step-6 VCF. When supplied, bcftools indel calls are adjudicated "
                             "and may edit the consensus. Three gates in order: depth against "
                             "--min-coverage, support against the indel rule, then reading "
                             "frame. Calls within 12 bp are judged as one group on their net "
                             "length change, which must be a multiple of 3 anywhere on the "
                             "segment, not only inside the longest detectable ORF")
    parser.add_argument("--strict-read-end", action="store_true",
                       help="Strict: read-end enrichment warnings override base calls")

    args = parser.parse_args()

    if not os.path.exists(args.consensus_file):
        print(f"Error: Consensus file '{args.consensus_file}' not found")
        sys.exit(1)

    if not os.path.exists(args.reference_file):
        print(f"Error: Reference file '{args.reference_file}' not found")
        sys.exit(1)

    try:
        processor = ConsensusDegeneracyProcessor(
            args.consensus_file,
            args.reference_file,
            args.bam,
            args.output,
            args.min_coverage,
            args.min_percentage_diff,
            args.diagnostic,
            args.filter_mode,
            args.indel_insertions,
            args.indel_deletions,
            args.indel_custom_percentage,
            args.major_h,
            args.major_n,
            strand_balance_threshold=args.strand_balance_threshold,
            homopolymer_min_length=args.homopolymer_min_length,
            homopolymer_window=args.homopolymer_window,
            read_end_threshold=args.read_end_threshold,
            read_end_edge_fraction=args.read_end_edge_fraction,
            strict_strand_bias=args.strict_strand_bias,
            strict_homopolymer=args.strict_homopolymer,
            strict_read_end=args.strict_read_end,
            min_base_quality=args.min_base_quality,
            vcf_file=args.vcf,
        )
        processor.process_consensus()

        print(f"\nProcessing complete!")
        print(f"Output saved to: {processor.output_file}")
        if args.diagnostic:
            log_file = str(processor.output_file).rsplit('.', 1)[0] + "_diagnostic_log.txt"
            print(f"Diagnostic log saved to: {log_file}")

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()