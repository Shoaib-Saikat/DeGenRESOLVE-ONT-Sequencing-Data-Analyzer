"""Tests for GUI components (offscreen, no display needed)."""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication.instance() or QApplication(sys.argv)

from src.degenresolve.gui.main_window import ONTSequencingAnalyzer
from src.degenresolve.gui.tabs import AnalysisTab, ConfigurationTab, LogsTab
from src.degenresolve.gui.results_viewer import ResultsViewer


def test_window_loads():
    w = ONTSequencingAnalyzer()
    assert w.central_widget.count() == 4


def test_tab_types():
    w = ONTSequencingAnalyzer()
    assert isinstance(w.analysis_tab, AnalysisTab)
    assert isinstance(w.config_tab, ConfigurationTab)
    assert isinstance(w.results_tab, ResultsViewer)
    assert isinstance(w.logs_tab, LogsTab)


def test_config_roundtrip():
    w = ONTSequencingAnalyzer()
    cfg = w.config_tab.get_configuration()
    cfg["min_coverage"] = 123
    w.config_tab.apply_configuration(cfg)
    assert w.config_tab.get_configuration()["min_coverage"] == 123


def test_log_flow():
    w = ONTSequencingAnalyzer()
    w.append_log("hello")
    assert "hello" in w.logs_tab.log_display.toPlainText()


def test_analysis_tab_progress():
    w = ONTSequencingAnalyzer()
    w.analysis_tab.update_progress(50)
    assert w.analysis_tab.progress_bar.value() == 50
    w.analysis_tab.reset_progress()
    assert w.analysis_tab.progress_bar.value() == 0


def test_validate_no_directory():
    w = ONTSequencingAnalyzer()
    w.working_directory = ""
    ok, _ = w.validate_input()
    assert not ok


def test_config_all_fields_roundtrip():
    w = ONTSequencingAnalyzer()
    cfg = {
        "min_coverage": 99,
        "degeneracy_threshold": 30,
        "ploidy": 3,
        "indel_rules": "custom_percentage",
        "indel_custom_percentage": 75.0,
        "variant_call_depth": 500,
        "variant_call_mode": "c",
        "filter_mode": "influenza",
        "qualimap_enabled": False,
        "nanoplot_enabled": False,
        "strand_balance_threshold": 0.25,
        "homopolymer_min_length": 5,
        "homopolymer_window": 10,
        "read_end_threshold": 0.6,
        "read_end_edge_fraction": 0.2,
        "strict_strand_bias": True,
        "strict_homopolymer": True,
        "strict_read_end": True,
    }
    w.config_tab.apply_configuration(cfg)
    got = w.config_tab.get_configuration()
    for key, val in cfg.items():
        assert got[key] == val, f"{key}: expected {val}, got {got[key]}"


def test_analysis_tab_step_labels():
    w = ONTSequencingAnalyzer()
    assert len(w.analysis_tab.step_labels) == 8
    w.analysis_tab.update_progress(60)
    w.analysis_tab.update_progress(100)
    assert w.analysis_tab.progress_bar.value() == 100
    assert "Complete" in w.analysis_tab.progress_bar.format()


def test_analysis_tab_running_state():
    w = ONTSequencingAnalyzer()
    w.analysis_tab.set_running_state(True)
    assert not w.analysis_tab.start_btn.isEnabled()
    assert w.analysis_tab.stop_btn.isEnabled()
    assert not w.analysis_tab.browse_btn.isEnabled()
    w.analysis_tab.set_running_state(False)
    assert w.analysis_tab.start_btn.isEnabled()
    assert not w.analysis_tab.stop_btn.isEnabled()
    assert w.analysis_tab.browse_btn.isEnabled()


def test_analysis_tab_set_directory():
    w = ONTSequencingAnalyzer()
    w.analysis_tab.set_directory("/some/test/path")
    assert w.analysis_tab.dir_label.text() == "/some/test/path"


def test_log_clear():
    w = ONTSequencingAnalyzer()
    w.append_log("line1")
    w.append_log("line2")
    w.logs_tab.clear_logs()
    text = w.logs_tab.log_display.toPlainText()
    assert "line1" not in text
    assert "Logs cleared" in text


def test_results_viewer_add_and_update():
    rv = ResultsViewer()
    rv.add_result("barcode01", "Running", "50%", "file.fasta")
    assert rv.barcode_list.count() == 1
    assert rv.barcode_list.item(0).data(Qt.UserRole) == "barcode01"
    assert "1)" in rv.barcode_list.item(0).text()
    rv.update_result("barcode01", "Completed", "100%")
    assert rv.results["barcode01"]["status"] == "Completed"


def test_results_viewer_clear():
    rv = ResultsViewer()
    rv.add_result("barcode01", "Done", "100%", "out.fasta")
    rv.add_result("barcode02", "Done", "100%", "out.fasta")
    assert rv.barcode_list.count() == 2
    rv.clear_results()
    assert rv.barcode_list.count() == 0
    assert rv.results == {}


def test_reset_session():
    w = ONTSequencingAnalyzer()
    w.is_running = True
    w.current_step = 5
    w.analysis_tab.update_progress(75)
    w.reset_session()
    assert not w.is_running
    assert w.current_step == 0
    assert w.analysis_tab.progress_bar.value() == 0


def test_menu_bar_exists():
    w = ONTSequencingAnalyzer()
    menubar = w.menuBar()
    actions = [a.text() for a in menubar.actions()]
    assert "File" in actions
    assert "Help" in actions
    assert "Tools" not in actions


def test_tab_count_and_labels():
    w = ONTSequencingAnalyzer()
    assert w.central_widget.count() == 4
    labels = [w.central_widget.tabText(i) for i in range(4)]
    assert labels == ["Analysis", "Configuration", "Results", "Logs"]


def test_results_viewer_barcode_list_no_duplicates():
    rv = ResultsViewer()
    assert rv.barcode_list.count() == 0
    rv.add_result("barcode01", "Done", "100%", "out.fasta")
    rv.add_result("barcode02", "Done", "100%", "out.fasta")
    assert rv.barcode_list.count() == 2
    assert rv.barcode_list.item(0).data(Qt.UserRole) == "barcode01"
    rv.add_result("barcode01", "Done", "100%", "out2.fasta")
    assert rv.barcode_list.count() == 2  # no duplicates


def test_results_viewer_working_directory():
    rv = ResultsViewer()
    rv.set_working_directory("/tmp/test")
    assert rv.working_directory == "/tmp/test"


# ---------------------------------------------------------------------------
# Basecall detection, force-sup override, and the base-quality pair
# ---------------------------------------------------------------------------

def _detected(tiers):
    """Minimal detection records, as BasecallDetectWorker would emit them."""
    return [{"barcode": f"barcode{i:02d}", "model": f"m_{t}", "tier": t,
             "count": 10, "total": 10, "distinct": 1, "models": {}, "signature": "1:1:1"}
            for i, t in enumerate(tiers, start=1)]


def test_auto_base_quality_omits_both_keys():
    """Auto must omit the keys entirely - that is how the shell's tier default
    fires. Emitting a number here is the bug that pinned every GUI run to -Q5."""
    w = ONTSequencingAnalyzer()
    w.config_tab.auto_base_quality_check.setChecked(True)
    cfg = w.config_tab.get_configuration()
    assert cfg["min_base_quality"] is None
    assert cfg["max_base_quality"] is None


def test_pinned_base_quality_emits_both_keys():
    w = ONTSequencingAnalyzer()
    w.config_tab.auto_base_quality_check.setChecked(False)
    w.config_tab.min_base_quality_spin.setValue(7)
    w.config_tab.max_base_quality_spin.setValue(31)
    cfg = w.config_tab.get_configuration()
    assert (cfg["min_base_quality"], cfg["max_base_quality"]) == (7, 31)


def test_base_quality_roundtrip_preserves_auto():
    w = ONTSequencingAnalyzer()
    w.config_tab.apply_configuration({})           # no keys => auto
    assert w.config_tab.auto_base_quality_check.isChecked()
    w.config_tab.apply_configuration({"min_base_quality": 3, "max_base_quality": 33})
    assert not w.config_tab.auto_base_quality_check.isChecked()
    got = w.config_tab.get_configuration()
    assert (got["min_base_quality"], got["max_base_quality"]) == (3, 33)


def test_force_sup_roundtrip():
    w = ONTSequencingAnalyzer()
    w.config_tab.apply_configuration({"force_sup_profile": True})
    assert w.config_tab.get_configuration()["force_sup_profile"] is True


def test_auto_pair_follows_detected_tier():
    w = ONTSequencingAnalyzer()
    w.config_tab.auto_base_quality_check.setChecked(True)
    w.config_tab._apply_detection(_detected(["sup", "sup"]))
    assert w.config_tab.min_base_quality_spin.value() == 1
    assert w.config_tab.max_base_quality_spin.value() == 35
    w.config_tab._apply_detection(_detected(["hac", "hac"]))
    assert w.config_tab.min_base_quality_spin.value() == 5
    assert w.config_tab.max_base_quality_spin.value() == 30


def test_force_sup_moves_the_pair_on_hac_data():
    w = ONTSequencingAnalyzer()
    w.config_tab.auto_base_quality_check.setChecked(True)
    w.config_tab._apply_detection(_detected(["hac"]))
    assert w.config_tab.min_base_quality_spin.value() == 5
    w.config_tab.force_sup_check.setChecked(True)
    assert w.config_tab.min_base_quality_spin.value() == 1
    assert w.config_tab.max_base_quality_spin.value() == 35


def test_warning_when_override_contradicts_detection():
    w = ONTSequencingAnalyzer()
    w.config_tab._apply_detection(_detected(["hac", "hac", "sup"]))
    assert w.config_tab.basecall_warning.text() == ""
    w.config_tab.force_sup_check.setChecked(True)
    assert w.config_tab.basecall_warning.isVisibleTo(w.config_tab)
    assert "2 of 3" in w.config_tab.basecall_warning.text()


def test_warning_when_pinned_pair_used_with_override():
    w = ONTSequencingAnalyzer()
    w.config_tab._apply_detection(_detected(["sup"]))
    w.config_tab.force_sup_check.setChecked(True)
    w.config_tab.auto_base_quality_check.setChecked(False)
    assert "--max-BQ" in w.config_tab.basecall_warning.text()


def test_summary_reports_mixed_tiers():
    w = ONTSequencingAnalyzer()
    w.config_tab._apply_detection(_detected(["hac"] * 3 + ["sup"]))
    text = w.config_tab.basecall_summary.text()
    assert "4 barcodes" in text and "3 hac" in text and "1 sup" in text
    assert "mixed tiers" in text


def test_summary_flags_mixed_models_within_a_barcode():
    w = ONTSequencingAnalyzer()
    recs = _detected(["hac"])
    recs[0]["distinct"] = 2
    w.config_tab._apply_detection(recs)
    assert "abort" in w.config_tab.basecall_summary.text()


def test_missing_fastq_pass_is_handled():
    w = ONTSequencingAnalyzer()
    w.config_tab.set_working_directory("/nonexistent/run")
    assert not w.config_tab.basecall_details_btn.isEnabled()
    assert w.config_tab._detection == []
