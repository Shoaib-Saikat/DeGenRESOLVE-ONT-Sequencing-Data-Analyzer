"""Tests for ConfigManager."""
import json
import tempfile
from pathlib import Path

from src.degenresolve.core.config import ConfigManager


def test_defaults():
    cm = ConfigManager()
    d = cm.to_dict()
    assert d["min_coverage"] == 100
    assert d["degeneracy_threshold"] == 20
    assert d["filter_mode"] == "general"


def test_set_get():
    cm = ConfigManager()
    cm.set("min_coverage", 99)
    assert cm.get("min_coverage") == 99


def test_validate_valid():
    cm = ConfigManager()
    ok, msg = cm.validate_config()
    assert ok


def test_validate_invalid_coverage():
    cm = ConfigManager()
    cm.set("min_coverage", 0)
    ok, _ = cm.validate_config()
    assert not ok


def test_save_load_roundtrip():
    cm = ConfigManager()
    cm.set("min_coverage", 77)
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        path = f.name
    cm.save_config(cm.to_dict(), path)
    cm2 = ConfigManager()
    loaded = cm2.load_config(path)
    assert loaded["min_coverage"] == 77
    Path(path).unlink()


def test_reset():
    cm = ConfigManager()
    cm.set("min_coverage", 999)
    cm.reset_to_defaults()
    assert cm.get("min_coverage") == 100


def test_backward_compat_fraction_threshold():
    cm = ConfigManager()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        json.dump({"degeneracy_threshold": 0.2}, f)
        path = f.name
    loaded = cm.load_config(path)
    assert loaded["degeneracy_threshold"] == 20
    Path(path).unlink()
