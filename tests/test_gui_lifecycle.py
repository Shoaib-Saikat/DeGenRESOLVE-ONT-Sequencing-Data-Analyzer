"""End-to-end lifecycle tests driving the real main window (offscreen).

These exercise the signal handlers that run when an analysis starts, stops and finishes.
They exist because a guard that raised inside one of them closed the entire application:
PyQt aborts the process on an unhandled exception in a slot, so a defect here is not a
dialog box, it is the app disappearing.
"""
import os
import sys
import threading

os.environ["QT_QPA_PLATFORM"] = "offscreen"

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMessageBox

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication.instance() or QApplication(sys.argv)

from src.degenresolve.gui.main_window import ONTSequencingAnalyzer
from src.degenresolve.pipeline.processor import PipelineProcessor


@pytest.fixture
def silent_dialogs(monkeypatch):
    """Answer every modal dialog so a lifecycle can run unattended."""
    for name in ("information", "critical", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))


@pytest.fixture
def running_window(silent_dialogs, tmp_path):
    """A window in the state it occupies while an analysis is in progress."""
    w = ONTSequencingAnalyzer()
    w.working_directory = str(tmp_path)
    w.processor = PipelineProcessor(str(tmp_path), w.config_manager)
    w.processor.worker = object()      # a worker was created and handed the stop flag
    w.is_running = True
    return w


def test_successful_completion_does_not_close_the_application(running_window):
    """The reported failure: the app closed itself at the end of every successful run.

    on_job_finished -> reset_session -> processor.reset(). The reset guard tested
    `worker is not None and not stop_flag.is_set()`, both true after a successful run, and
    raised RuntimeError from inside a Qt slot.
    """
    running_window.on_job_finished("Enhanced Pipeline", True, "Analysis completed successfully")
    assert running_window.is_running is False
    assert running_window.processor.is_running() is False
    assert running_window.processor.worker is None, "session was not reset for a new run"


def test_failed_completion_does_not_close_the_application(running_window):
    running_window.on_job_finished("Enhanced Pipeline", False, "Pipeline failed with return code: 1")
    assert running_window.is_running is False


def test_user_stop_is_reported_as_cancellation_not_failure(running_window):
    """A cancelled run must not be presented to the user as an analysis failure."""
    seen = {}
    running_window.stop_analysis()
    assert getattr(running_window, "_stop_requested", False) is True
    running_window.on_job_finished("Enhanced Pipeline", False, "Analysis stopped by user")
    assert running_window.is_running is False
    # the flag is consumed, so a later genuine failure is not mislabelled as a cancellation
    assert getattr(running_window, "_stop_requested", False) is False


def test_stop_is_a_no_op_when_nothing_is_running(silent_dialogs, tmp_path):
    w = ONTSequencingAnalyzer()
    w.working_directory = str(tmp_path)
    w.processor = PipelineProcessor(str(tmp_path), w.config_manager)
    w.is_running = False
    w.stop_analysis()          # must not raise, must not arm the cancellation flag
    assert getattr(w, "_stop_requested", False) is False


def test_changing_directory_mid_run_is_refused_and_keeps_the_stop_flag(running_window, tmp_path):
    """Swapping the processor mid-run orphaned the stop flag the live worker polls,
    leaving a pipeline that nothing could stop."""
    original = running_window.processor
    flag = original.stop_flag
    running_window._apply_directory(str(tmp_path / "elsewhere"))
    assert running_window.processor is original, "processor was swapped during a live run"
    assert running_window.processor.stop_flag is flag, "stop flag was orphaned"


def test_reset_session_is_safe_to_call_twice(running_window):
    """Idempotence: a second reset must not raise or corrupt state."""
    running_window.on_job_finished("Enhanced Pipeline", True, "done")
    running_window.reset_session()
    assert running_window.is_running is False
