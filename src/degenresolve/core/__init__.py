"""
Core functionality for DegenResolve

This module contains core application logic including
configuration management, validation, and shared utilities.
"""

from .config import ConfigManager
from .validator import InputValidator

__all__ = [
    "ConfigManager",
    "InputValidator", 
    "PipelineSignals",
]


def __getattr__(name):
    """Resolve the Qt-dependent PipelineSignals lazily (PEP 562).

    signals.py imports PyQt5.QtCore at module scope, so importing it here made the whole
    package - including the headless consensus-editor CLI - require the GUI stack.
    """
    if name == "PipelineSignals":
        from .signals import PipelineSignals
        return PipelineSignals
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
