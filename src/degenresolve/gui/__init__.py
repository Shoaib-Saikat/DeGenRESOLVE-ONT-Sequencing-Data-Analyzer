"""
GUI Components for DegenResolve

This module contains all GUI-related components including
the main window, dialogs, and UI widgets.
"""

from .main_window import ONTSequencingAnalyzer
from .results_viewer import ResultsViewer

__all__ = [
    "ONTSequencingAnalyzer",
    "ResultsViewer",
]
