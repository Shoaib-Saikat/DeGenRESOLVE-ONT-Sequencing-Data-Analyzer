"""Tests for InputValidator."""
import tempfile
from pathlib import Path

from src.degenresolve.core.validator import InputValidator


def test_empty_directory():
    v = InputValidator("")
    ok, issues = v.validate_directory_structure()
    assert not ok


def test_missing_directory():
    v = InputValidator("/nonexistent/path")
    ok, issues = v.validate_directory_structure()
    assert not ok


def test_valid_structure():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "fastq_pass" / "barcode01").mkdir(parents=True)
        (Path(d) / "fastq_pass" / "barcode01" / "reads.fastq.gz").touch()
        (Path(d) / "reference").mkdir()
        (Path(d) / "reference" / "reference.fasta").touch()
        v = InputValidator(d)
        ok, issues = v.validate_directory_structure()
        assert ok, issues


def test_missing_fastq_pass():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "reference").mkdir()
        (Path(d) / "reference" / "reference.fasta").touch()
        v = InputValidator(d)
        ok, issues = v.validate_directory_structure()
        assert not ok
        assert any("fastq_pass" in i for i in issues)


def test_barcode_count():
    with tempfile.TemporaryDirectory() as d:
        for i in range(3):
            (Path(d) / "fastq_pass" / f"barcode{i:02d}").mkdir(parents=True)
        v = InputValidator(d)
        assert v.get_barcode_count() == 3
        assert len(v.get_barcode_list()) == 3
