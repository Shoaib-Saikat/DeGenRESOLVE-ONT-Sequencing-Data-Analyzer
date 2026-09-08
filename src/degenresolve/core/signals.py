"""
Qt signals for DegenResolve

This module contains signal definitions for communication
between pipeline workers and the main GUI.
"""

from PyQt5.QtCore import QObject, pyqtSignal


class PipelineSignals(QObject):
    """Signals for communication between pipeline workers and main GUI."""
    
    # Log message signal
    log_message = pyqtSignal(str)
    
    # Progress update signal (0-100)
    progress_update = pyqtSignal(int)
    
    # Job lifecycle signals
    job_started = pyqtSignal(str)  # barcode_name
    job_finished = pyqtSignal(str, bool, str)  # barcode_name, success, final_message
    
    # Pipeline step signal
    pipeline_step = pyqtSignal(str, str)  # barcode_name, step_description
    step_skipped = pyqtSignal(int)        # dot index to mark as skipped

    # Per-barcode step tracking (for parallel runs)
    barcode_step     = pyqtSignal(str, int)  # barcode, step_index 0-7
    barcode_finished = pyqtSignal(str)        # barcode

    # All jobs finished signal
    all_jobs_finished = pyqtSignal()

    # Request main thread to refresh results viewer
    refresh_results = pyqtSignal()
    
    # Error signal
    error_occurred = pyqtSignal(str, str)  # error_type, error_message
