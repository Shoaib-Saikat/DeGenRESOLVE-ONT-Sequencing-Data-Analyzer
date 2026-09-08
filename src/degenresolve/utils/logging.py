"""
Logging utilities for DegenResolve

This module provides logging utilities for the application.
"""

from datetime import datetime


def log_with_timestamp(message: str) -> str:
    """Add timestamp to a log message.

    Args:
        message: Log message.

    Returns:
        Message with timestamp prefix.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    return f"[{timestamp}] {message}"
