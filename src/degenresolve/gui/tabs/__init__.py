"""
Tab widgets for DegenResolve GUI

This module contains the individual tab widgets for the main interface.
"""

from .analysis_tab import AnalysisTab
from .configuration_tab import ConfigurationTab
from .logs_tab import LogsTab

__all__ = [
    "AnalysisTab",
    "ConfigurationTab", 
    "LogsTab",
]
