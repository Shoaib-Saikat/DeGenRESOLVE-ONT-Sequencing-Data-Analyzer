"""
Logs tab for DegenResolve GUI

This module contains the logs tab with a scrollable log display
and controls for clearing and saving logs to file.
"""

import os
from datetime import datetime

from PyQt5.QtGui import QTextCursor
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QTextEdit, QFileDialog, QMessageBox, QSizePolicy
)


class LogsTab(QWidget):
    """Logs tab with log display, clear, and save controls."""

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()

        controls = QHBoxLayout()

        self.clear_btn = QPushButton("Clear Logs")
        self.clear_btn.clicked.connect(self.clear_logs)
        controls.addWidget(self.clear_btn)

        self.save_btn = QPushButton("Save Logs")
        self.save_btn.clicked.connect(self.save_logs)
        controls.addWidget(self.save_btn)

        controls.addStretch()
        layout.addLayout(controls)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        layout.addWidget(self.log_display)

        self.setLayout(layout)

    def append_log(self, message: str):
        self.log_display.append(message)
        self.log_display.moveCursor(QTextCursor.End)
        self.log_display.repaint()

    def clear_logs(self):
        self.log_display.clear()
        self.append_log("Logs cleared")

    def _default_log_path(self):
        """log/ under the run directory, so run logs sit with the other logs."""
        name = f"ont_analysis_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        wd = getattr(self.parent_window, "working_directory", "") or ""
        return os.path.join(wd, "log", name) if wd else name

    def autosave(self):
        """Write the run log to log/ without prompting. Called at run end."""
        wd = getattr(self.parent_window, "working_directory", "") or ""
        if not wd:
            return None
        path = self._default_log_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(self.log_display.toPlainText())
            self.append_log(f"Run log saved to: {path}")
            return path
        except OSError as e:
            self.append_log(f"Could not save run log: {e}")
            return None

    def save_logs(self):
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save Logs",
            self._default_log_path(),
            "Text Files (*.txt);;All Files (*)",
        )
        if filename:
            try:
                with open(filename, "w") as f:
                    f.write(self.log_display.toPlainText())
                self.append_log(f"Logs saved to: {filename}")
            except Exception as e:
                QMessageBox.critical(self, "Save Error", f"Failed to save logs: {e}")
