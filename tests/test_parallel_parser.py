"""Tests for parallel log parser in PipelineWorker and the Completed Barcode label."""
import os
import sys
import threading
from unittest.mock import patch, MagicMock

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
app = QApplication.instance() or QApplication(sys.argv)

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from src.degenresolve.pipeline.worker import PipelineWorker
from src.degenresolve.gui.main_window import ONTSequencingAnalyzer


# Realistic interleaved output from 3 barcodes running in parallel.
# barcode01 reaches step 3, barcode02/03 reach step 2.
PARALLEL_LOG = [
    "Total barcodes       : 3",
    "[barcode01] === Starting Pipeline for barcode01",
    "[barcode02] === Starting Pipeline for barcode02",
    "[barcode03] === Starting Pipeline for barcode03",
    "[barcode01] === Step 0.5: NanoPlot QC",
    "[barcode02] === Step 0.5: NanoPlot QC",
    "[barcode03] === Step 0.5: NanoPlot QC",
    "[barcode01] === Step 1: Concatenating reads",
    "[barcode02] === Step 1: Concatenating reads",
    "[barcode01] === Step 2: Porechop trimming",
    "[barcode03] === Step 1: Concatenating reads",
    "[barcode01] === Step 3: Mapping to reference",
    "Time for barcode01: 00h:01m:30s [exit 0]",
    "[barcode02] === Step 2: Porechop trimming",
    "[barcode03] === Step 2: Porechop trimming",
    "Time for barcode02: 00h:01m:45s [exit 0]",
    "Time for barcode03: 00h:01m:50s [exit 0]",
]

# Sequential output (no prefix) - backward-compat mode.
# barcode01 reaches step 2, barcode02 reaches step 1.
SEQUENTIAL_LOG = [
    "Total barcodes       : 2",
    "=== Starting Pipeline for barcode01",
    "=== Step 0.5: NanoPlot QC",
    "=== Step 1: Concatenating reads",
    "=== Step 2: Porechop trimming",
    "Time for barcode01: 00h:01m:00s [exit 0]",
    "=== Starting Pipeline for barcode02",
    "=== Step 0.5: NanoPlot QC",
    "=== Step 1: Concatenating reads",
    "Time for barcode02: 00h:01m:00s [exit 0]",
]


def run_worker_with_log(lines):
    """
    Run PipelineWorker with a fake subprocess that emits the given lines.
    Returns (worker, list of (barcode, step) emissions, list of finished barcode names).
    """
    w = PipelineWorker("/tmp", {}, threading.Event())

    step_emissions = []
    finished_emissions = []
    w.signals.barcode_step.connect(lambda bc, st: step_emissions.append((bc, st)))
    w.signals.barcode_finished.connect(finished_emissions.append)

    log = list(lines)
    idx = [0]

    def fake_readline():
        i = idx[0]
        idx[0] += 1
        return (log[i] + "\n") if i < len(log) else ""

    fake_proc = MagicMock()
    fake_proc.stdout.readline = fake_readline
    fake_proc.wait.return_value = 0

    with (
        patch("subprocess.Popen", return_value=fake_proc),
        patch.object(w, "_validate_input_structure"),
        patch.object(w, "_create_config_file"),
        patch("os.chdir"),
    ):
        w.run()

    return w, step_emissions, finished_emissions


def _last_step(emissions):
    """Collapse emission list to {barcode: last_step_seen}."""
    last = {}
    for bc, st in emissions:
        last[bc] = st
    return last


# parallel mode

def test_parallel_step_attribution():
    """Each [barcodeXX] prefixed step is credited to the right barcode, not the last one seen."""
    _, steps, _ = run_worker_with_log(PARALLEL_LOG)
    last = _last_step(steps)
    assert last["barcode01"] == 3, last
    assert last["barcode02"] == 2, last
    assert last["barcode03"] == 2, last


def test_parallel_step_order_per_barcode():
    """Step numbers for each barcode only ever increase."""
    _, steps, _ = run_worker_with_log(PARALLEL_LOG)
    per_bc: dict = {}
    for bc, st in steps:
        prev = per_bc.get(bc, -1)
        assert st > prev, f"{bc}: step went {prev} -> {st}"
        per_bc[bc] = st


def test_parallel_finished_signals():
    """barcode_finished fires once per barcode when 'Time for barcodeXX:' appears."""
    _, _, finished = run_worker_with_log(PARALLEL_LOG)
    assert set(finished) == {"barcode01", "barcode02", "barcode03"}


def test_parallel_completed_count():
    """completed_barcodes increments for each 'Time for' line."""
    w, _, _ = run_worker_with_log(PARALLEL_LOG)
    assert w.completed_barcodes == 3


def test_parallel_total_barcodes():
    w, _, _ = run_worker_with_log(PARALLEL_LOG)
    assert w.total_barcodes == 3


def test_parallel_barcode_steps_cleared_on_finish():
    """Worker's internal barcode_steps dict empties as each barcode finishes."""
    w, _, _ = run_worker_with_log(PARALLEL_LOG)
    assert w.barcode_steps == {}


# sequential mode (no prefix)

def test_sequential_step_attribution():
    """Without prefixes, steps are attributed via current_barcode fallback."""
    _, steps, _ = run_worker_with_log(SEQUENTIAL_LOG)
    last = _last_step(steps)
    assert last["barcode01"] == 2, last
    assert last["barcode02"] == 1, last


def test_sequential_finished_signals():
    _, _, finished = run_worker_with_log(SEQUENTIAL_LOG)
    assert set(finished) == {"barcode01", "barcode02"}


def test_sequential_completed_count():
    w, _, _ = run_worker_with_log(SEQUENTIAL_LOG)
    assert w.completed_barcodes == 2


# Completed Barcode label

def test_completed_label_default():
    """Label starts at 0 before any run."""
    w = ONTSequencingAnalyzer()
    assert w.analysis_tab.completed_label.text() == "Completed Barcode: 0"


def test_completed_label_set():
    """set_completed_barcodes updates the label text."""
    w = ONTSequencingAnalyzer()
    w.analysis_tab.set_completed_barcodes(2, 5)
    assert w.analysis_tab.completed_label.text() == "Completed Barcode: 2/5"


def test_completed_label_resets():
    """reset_session clears the label back to 0."""
    w = ONTSequencingAnalyzer()
    w.analysis_tab.set_completed_barcodes(3, 3)
    w.reset_session()
    assert w.analysis_tab.completed_label.text() == "Completed Barcode: 0"


def test_completed_label_updates_on_barcode_finished():
    """_on_barcode_finished increments the label by reading worker.completed_barcodes."""
    win = ONTSequencingAnalyzer()

    # Plant a fake worker with known counts
    fake_worker = MagicMock()
    fake_worker.completed_barcodes = 1
    fake_worker.total_barcodes = 3
    fake_processor = MagicMock()
    fake_processor.worker = fake_worker
    win.processor = fake_processor

    win._on_barcode_finished("barcode01")
    assert win.analysis_tab.completed_label.text() == "Completed Barcode: 1/3"

    # Second barcode finishes
    fake_worker.completed_barcodes = 2
    win._on_barcode_finished("barcode02")
    assert win.analysis_tab.completed_label.text() == "Completed Barcode: 2/3"

    # All done
    fake_worker.completed_barcodes = 3
    win._on_barcode_finished("barcode03")
    assert win.analysis_tab.completed_label.text() == "Completed Barcode: 3/3"
