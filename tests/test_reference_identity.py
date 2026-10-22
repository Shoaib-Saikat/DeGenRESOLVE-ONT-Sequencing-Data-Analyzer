"""How close the reads are to the reference they were mapped to.

Scored against Illumina-derived genomes (BioProject PRJNA1173216), segments whose reads
were under 85% identical to the reference held 656 of the 695 incorrect consensus bases.
The pipeline cannot see that from the consensus, which collapses toward the reference
where mapping fails, so the measure is taken from the reads.
"""
import pysam

from src.degenresolve.pipeline.consensus_editor import (
    ConsensusDegeneracyProcessor,
    read_identity_to_reference,
)

PRIMARY, SECONDARY, SUPPLEMENTARY = 0, 256, 2048


def _bam(tmp_path, reads):
    """A real indexed BAM on one 1 kb reference; reads are (length, de or None, flag)."""
    path = str(tmp_path / "reads.bam")
    header = {"HD": {"VN": "1.6", "SO": "coordinate"}, "SQ": [{"SN": "seg", "LN": 1000}]}
    with pysam.AlignmentFile(path, "wb", header=header) as out:
        for i, (length, de, flag) in enumerate(reads):
            a = pysam.AlignedSegment()
            a.query_name = f"read{i}"
            a.query_sequence = "A" * length
            a.flag = flag
            a.reference_id = 0
            a.reference_start = 10
            a.mapping_quality = 60
            a.cigar = [(0, length)]
            a.query_qualities = pysam.qualitystring_to_array("I" * length)
            if de is not None:
                a.set_tag("de", de, "f")
            out.write(a)
    pysam.index(path)
    return pysam.AlignmentFile(path)


def test_identity_is_weighted_by_aligned_length(tmp_path):
    bam = _bam(tmp_path, [(100, 0.10, PRIMARY), (300, 0.20, PRIMARY)])
    # (0.90 * 100 + 0.80 * 300) / 400
    assert abs(read_identity_to_reference(bam, "seg") - 82.5) < 0.01


def test_only_primary_alignments_count(tmp_path):
    bam = _bam(tmp_path, [(200, 0.10, PRIMARY), (200, 0.50, SECONDARY), (200, 0.50, SUPPLEMENTARY)])
    assert abs(read_identity_to_reference(bam, "seg") - 90.0) < 0.01


def test_identity_is_unknown_without_the_divergence_tag(tmp_path):
    """A BAM from an aligner that does not write de gives no figure, not a wrong one."""
    bam = _bam(tmp_path, [(200, None, PRIMARY)])
    assert read_identity_to_reference(bam, "seg") is None


def _proc():
    return object.__new__(ConsensusDegeneracyProcessor)


def test_reads_under_85_percent_identical_raise_a_warning():
    note = _proc()._identity_warning(82.4)
    assert "82.4%" in note and "85%" in note


def test_close_or_unknown_reference_raises_no_warning():
    assert _proc()._identity_warning(85.0) == ""
    assert _proc()._identity_warning(93.7) == ""
    assert _proc()._identity_warning(None) == ""
