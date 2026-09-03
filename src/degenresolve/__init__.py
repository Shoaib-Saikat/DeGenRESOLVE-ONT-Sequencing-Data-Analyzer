"""
DegenResolve - ONT Sequencing Data Analyzer

A comprehensive application for processing ONT raw FASTQ files
and generating refined consensus FASTA sequences.

Author: Shoaib Saikat
Version: 1.0
"""

__version__ = "1.0.0"
__author__ = "Shoaib Saikat"
__email__ = "saikatshoaib@gmail.com"

from .core.config import ConfigManager

__all__ = [
    "ConfigManager",
    "PipelineProcessor",
]


def __getattr__(name):
    """Resolve PipelineProcessor lazily (PEP 562).

    Importing it at module scope pulled PyQt5 into every `import degenresolve`, including
    the documented headless CLI (`degenresolve-consensus`), so the console-only path could
    not run on a server without the full GUI stack installed. Behaviour is unchanged for
    callers that actually use it.
    """
    if name == "PipelineProcessor":
        from .pipeline.processor import PipelineProcessor
        return PipelineProcessor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
