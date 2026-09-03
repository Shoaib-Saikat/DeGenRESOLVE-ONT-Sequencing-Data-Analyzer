"""
Pipeline processing components for DegenResolve

This module contains pipeline processing logic including
the main processor, worker threads, and consensus editing.
"""

# PipelineProcessor and PipelineWorker pull in PyQt5 (QRunnable, signals). Importing them
# here made the documented headless path - `degenresolve-consensus`, which only needs
# ConsensusDegeneracyProcessor - depend on the entire GUI stack, so the CLI could not run on
# a server without Qt installed. They are resolved lazily instead; `from
# degenresolve.pipeline import PipelineWorker` still works exactly as before.
from .consensus_editor import ConsensusDegeneracyProcessor

__all__ = [
    "PipelineProcessor",
    "PipelineWorker",
    "ConsensusDegeneracyProcessor",
]


def __getattr__(name):
    """Lazily import the Qt-dependent members (PEP 562)."""
    if name == "PipelineProcessor":
        from .processor import PipelineProcessor
        return PipelineProcessor
    if name == "PipelineWorker":
        from .worker import PipelineWorker
        return PipelineWorker
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
