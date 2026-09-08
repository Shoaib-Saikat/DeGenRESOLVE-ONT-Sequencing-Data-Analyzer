"""
Analysis tab for DegenResolve GUI

This module contains the main analysis tab with directory selection,
control buttons, and progress tracking.
"""

import os

from collections import deque

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QProgressBar, QSizePolicy, QFrame,
    QTreeWidget, QTreeWidgetItem, QAbstractItemView, QStyle
)
from PyQt5.QtCore import Qt, QPoint, QPropertyAnimation, QParallelAnimationGroup
from PyQt5.QtCore import QEasingCurve

from ..styles import DARK_COLORS


class SlidingStatusTicker(QFrame):
    """Single-line status box: new message slides in from bottom, old exits top."""

    _H = 38

    def __init__(self, colors: dict, parent=None):
        super().__init__(parent)
        c = colors
        self.setFixedHeight(self._H)
        self.setStyleSheet(
            f"background: rgba(125,211,252,0.08);"
            f" border: 1px solid rgba(125,211,252,0.2); border-radius: 4px;"
        )
        lbl_style = (
            f"color: {c['accent']}; font-weight: 600; font-size: 13px;"
            f" background: transparent; border: none; padding: 0 8px;"
        )
        self._lbl_a = QLabel("Ready to start analysis", self)
        self._lbl_b = QLabel("", self)
        for lbl in (self._lbl_a, self._lbl_b):
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet(lbl_style)
        self._active   = self._lbl_a
        self._incoming = self._lbl_b
        self._queue: deque = deque()
        self._group = None
        self._animating = False
        self._relayout()

    def resizeEvent(self, event):
        self._relayout()
        super().resizeEvent(event)

    def _relayout(self):
        w = self.width()
        self._active.setGeometry(0, 0, w, self._H)
        self._incoming.setGeometry(0, self._H, w, self._H)

    def push(self, text: str):
        self._queue.append(text)
        if not self._animating:
            self._advance()

    def _advance(self):
        if not self._queue:
            return
        text = self._queue.popleft()
        w = self.width()
        self._incoming.setText(text)
        self._incoming.setGeometry(0, self._H, w, self._H)

        out = QPropertyAnimation(self._active, b"pos")
        out.setDuration(220)
        out.setStartValue(QPoint(0, 0))
        out.setEndValue(QPoint(0, -self._H))
        out.setEasingCurve(QEasingCurve.InOutQuad)

        inn = QPropertyAnimation(self._incoming, b"pos")
        inn.setDuration(220)
        inn.setStartValue(QPoint(0, self._H))
        inn.setEndValue(QPoint(0, 0))
        inn.setEasingCurve(QEasingCurve.InOutQuad)

        self._group = QParallelAnimationGroup()
        self._group.addAnimation(out)
        self._group.addAnimation(inn)
        self._group.finished.connect(self._on_done)
        self._animating = True
        self._group.start()

    def _on_done(self):
        self._active, self._incoming = self._incoming, self._active
        self._active.setGeometry(0, 0, self.width(), self._H)
        self._animating = False
        if self._queue:
            self._advance()

    def reset(self):
        self._queue.clear()
        if self._group:
            self._group.stop()
        self._animating = False
        self._active   = self._lbl_a
        self._incoming = self._lbl_b
        self._lbl_a.setText("Ready to start analysis")
        self._lbl_b.setText("")
        self._relayout()


PIPELINE_STEPS = [
    "Raw Read\nQC",
    "Unzipping &\nConcatenation",
    "Adapter\nTrimming",
    "Mapping",
    "Alignment\nQC",
    "Variant\nCalling",
    "Draft\nConsensus",
    "Refining\nConsensus",
]


class AnalysisTab(QWidget):
    """Analysis tab with input selection, controls, and progress display."""

    def __init__(self, parent_window):
        super().__init__()
        self.parent_window = parent_window
        self._colors = DARK_COLORS
        self.step_labels = []
        self.step_dots = []
        self.step_lines = []
        self._current_pipeline_step = -1
        self._skipped_steps = set()
        self.setup_ui()

    def setup_ui(self):
        main_layout = QHBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(10, 10, 10, 10)

        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setSpacing(15)
        left_layout.setContentsMargins(5, 5, 5, 5)

        left_layout.addWidget(self._create_input_section())
        left_layout.addWidget(self._create_control_section())
        left_layout.addWidget(self._create_progress_section())

        left_panel.setLayout(left_layout)
        main_layout.addWidget(left_panel, 1)
        self.setLayout(main_layout)
        self.setAcceptDrops(True)

    # Input section

    def _create_input_section(self):
        group = QGroupBox("Input Directory")
        group.setMinimumHeight(140)
        layout = QVBoxLayout()
        layout.setSpacing(2)
        layout.setContentsMargins(10, 12, 10, 4)
        dir_layout = QHBoxLayout()
        dir_layout.setSpacing(5)

        self.dir_label = QLabel("No directory selected")
        self.dir_label.setStyleSheet(
            f"color: {self._colors['error']}; font-weight: bold;"
            " font-size: 12px; background: transparent;"
        )
        self.dir_label.setWordWrap(True)
        self.dir_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.dir_label.setMinimumHeight(28)
        self.dir_label.setMaximumHeight(48)
        dir_layout.addWidget(self.dir_label)

        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.parent_window.browse_directory)
        self.browse_btn.setObjectName("success")
        self.browse_btn.setMinimumWidth(80)
        self.browse_btn.setMaximumWidth(80)
        self.browse_btn.setMinimumHeight(28)
        self.browse_btn.setMaximumHeight(32)
        dir_layout.addWidget(self.browse_btn)

        layout.addLayout(dir_layout)

        drag_hint = QLabel(
            "<p style=\"font-size:28px;font-style:normal;text-align:center;"
            "color:#4a6070;margin:8px 0 4px 0;\">"
            "Drag &amp; Drop <i>CustomFolder</i></p>"
        )
        drag_hint.setAlignment(Qt.AlignCenter)
        drag_hint.setStyleSheet("background: transparent;")
        layout.addWidget(drag_hint)

        tree = QTreeWidget()
        tree.setHeaderHidden(True)
        tree.setRootIsDecorated(True)
        tree.setIndentation(14)
        tree.setSelectionMode(QAbstractItemView.NoSelection)
        tree.setFocusPolicy(Qt.NoFocus)
        tree.setExpandsOnDoubleClick(False)
        tree.setStyleSheet(
            "QTreeWidget { background: transparent; border: none; font-size: 12px;"
            " font-family: monospace; color: #e0e8f0; }"
            "QTreeWidget::item { padding: 0px 0; margin: 0; }"
        )
        tree.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tree.setFixedHeight(150)

        folder_icon = self.style().standardIcon(QStyle.SP_DirIcon)
        file_icon = self.style().standardIcon(QStyle.SP_FileIcon)

        root = QTreeWidgetItem(tree, ["CustomFolder/"])
        root.setIcon(0, folder_icon)
        fq = QTreeWidgetItem(root, ["fastq_pass/"])
        fq.setIcon(0, folder_icon)
        bc1 = QTreeWidgetItem(fq, ["barcode01/"])
        bc1.setIcon(0, folder_icon)
        QTreeWidgetItem(bc1, ["reads.fastq.gz"]).setIcon(0, file_icon)
        bc2 = QTreeWidgetItem(fq, ["barcode02/"])
        bc2.setIcon(0, folder_icon)
        QTreeWidgetItem(bc2, ["reads.fastq.gz"]).setIcon(0, file_icon)
        ref = QTreeWidgetItem(root, ["reference/"])
        ref.setIcon(0, folder_icon)
        QTreeWidgetItem(ref, ["reference.fasta"]).setIcon(0, file_icon)

        tree.expandAll()
        layout.addWidget(tree)

        group.setLayout(layout)
        return group

    # Control section

    def _create_control_section(self):
        group = QGroupBox("Analysis Controls")
        group.setMinimumHeight(100)
        layout = QHBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 15, 10, 10)
        self.start_btn = QPushButton("Start Analysis")
        self.start_btn.clicked.connect(self.parent_window.start_analysis)
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setMaximumHeight(45)
        self.start_btn.setObjectName("success")
        layout.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop Analysis")
        self.stop_btn.clicked.connect(self.parent_window.stop_analysis)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumHeight(40)
        self.stop_btn.setMaximumHeight(45)
        self.stop_btn.setObjectName("danger")
        layout.addWidget(self.stop_btn)

        self.validate_btn = QPushButton("Validate Setup")
        self.validate_btn.clicked.connect(self.parent_window.validate_pipeline_setup)
        self.validate_btn.setMinimumHeight(40)
        self.validate_btn.setMaximumHeight(45)
        self.validate_btn.setObjectName("info")
        layout.addWidget(self.validate_btn)

        group.setLayout(layout)
        return group

    # Progress section

    def _create_progress_section(self):
        c = self._colors
        group = QGroupBox("Analysis Progress")
        group.setMinimumHeight(280)
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(16, 25, 16, 16)
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)

        self.status_label = SlidingStatusTicker(c)
        layout.addWidget(self.status_label)

        time_row = QHBoxLayout()
        time_row.setSpacing(12)

        self.time_label = QLabel("Time Elapsed: 00:00:00")
        self.time_label.setFixedSize(200, 28)
        self.time_label.setAlignment(Qt.AlignCenter)
        self.time_label.setStyleSheet(
            f"color: {c['accent']}; font-size: 13px; font-weight: bold;"
            f" padding: 2px 10px; background: rgba(125,211,252,0.05);"
            f" border: 1px solid {c['border']}; border-radius: 4px;"
        )
        time_row.addWidget(self.time_label)

        self.completed_label = QLabel("Completed Barcode: 0")
        self.completed_label.setFixedHeight(28)
        self.completed_label.setAlignment(Qt.AlignCenter)
        self.completed_label.setStyleSheet(
            f"color: {c['green']}; font-size: 13px; font-weight: bold;"
            f" padding: 2px 10px; background: rgba(110,231,183,0.05);"
            f" border: 1px solid {c['border']}; border-radius: 4px;"
        )
        time_row.addWidget(self.completed_label)

        time_row.addStretch()
        layout.addLayout(time_row)

        # Combined row: count badge above each dot, connecting lines at dot level.
        # Column height: 18 (badge) + 2 (gap) + 12 (dot) = 32px
        # Dot centre from column top: 18+2+6 = 26px -> line top-margin = 25
        _COL_H = 32
        combined_row = QHBoxLayout()
        combined_row.setSpacing(0)
        combined_row.setContentsMargins(4, 4, 4, 0)
        self.step_dots = []
        self.step_lines = []
        self.step_counts = []
        self._arrows = []
        for i in range(len(PIPELINE_STEPS)):
            if i > 0:
                lc = QWidget()
                lc.setFixedHeight(_COL_H)
                lc.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                lc_lay = QVBoxLayout(lc)
                lc_lay.setContentsMargins(0, 25, 0, 0)
                lc_lay.setSpacing(0)
                line = QFrame()
                line.setFixedHeight(2)
                line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                lc_lay.addWidget(line)
                lc_lay.addStretch()
                combined_row.addWidget(lc, 1)
                self.step_lines.append(line)

            col_w = QWidget()
            col_w.setFixedSize(20, _COL_H)
            col_lay = QVBoxLayout(col_w)
            col_lay.setContentsMargins(0, 0, 0, 0)
            col_lay.setSpacing(2)

            badge = QLabel("")
            badge.setFixedSize(20, 18)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet("background: transparent; color: transparent;")
            col_lay.addWidget(badge)

            dot = QLabel()
            dot.setFixedSize(12, 12)
            col_lay.addWidget(dot, 0, Qt.AlignHCenter)

            combined_row.addWidget(col_w)
            self.step_dots.append(dot)
            self.step_counts.append(badge)
        layout.addLayout(combined_row)

        labels_row = QHBoxLayout()
        labels_row.setSpacing(0)
        labels_row.setContentsMargins(0, 2, 0, 0)
        self.step_labels = []
        for i, step in enumerate(PIPELINE_STEPS):
            if i > 0:
                arrow = QLabel("❯")
                arrow.setFixedWidth(16)
                arrow.setAlignment(Qt.AlignCenter)
                arrow.setStyleSheet(f"color: {c['accent']}; font-size: 12px; font-weight: bold;")
                labels_row.addWidget(arrow)
                self._arrows.append(arrow)
            lbl = QLabel(step)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            labels_row.addWidget(lbl)
            self.step_labels.append(lbl)
        layout.addLayout(labels_row)

        layout.addSpacing(6)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Ready - 0%")
        self.progress_bar.setMinimumHeight(26)
        layout.addWidget(self.progress_bar)

        group.setLayout(layout)
        self._refresh_step_styles()
        return group

    def _refresh_step_styles(self):
        c = self._colors
        current = self._current_pipeline_step
        for i in range(len(PIPELINE_STEPS)):
            dot = self.step_dots[i]
            lbl = self.step_labels[i]
            if i in self._skipped_steps:
                dot.setStyleSheet(
                    f"background: {c['error']}; border: 2px solid {c['error']};"
                    "border-radius: 6px; min-width: 12px; max-width: 12px;"
                )
                lbl.setStyleSheet(f"color: {c['error']}; font-size: 12px; font-weight: bold;")
            elif i < current:
                dot.setStyleSheet(
                    f"background: {c['accent']}; border: 2px solid {c['accent']};"
                    "border-radius: 6px; min-width: 12px; max-width: 12px;"
                )
                lbl.setStyleSheet(f"color: {c['accent']}; font-size: 12px; font-weight: bold;")
            elif i == current:
                dot.setStyleSheet(
                    f"background: {c['green']}; border: 2px solid {c['green']};"
                    "border-radius: 6px; min-width: 12px; max-width: 12px;"
                )
                lbl.setStyleSheet(f"color: {c['green']}; font-size: 12px; font-weight: bold;")
            else:
                dot.setStyleSheet(
                    f"background: {c['border']}; border: 2px solid {c['border']};"
                    "border-radius: 6px; min-width: 12px; max-width: 12px;"
                )
                lbl.setStyleSheet(f"color: {c['placeholder']}; font-size: 12px;")

        for i, line in enumerate(self.step_lines):
            if i < current:
                line.setStyleSheet(f"background: {c['accent']}; border: none;")
            else:
                line.setStyleSheet(f"background: {c['border']}; border: none;")

    # Drag-and-drop

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile() and os.path.isdir(urls[0].toLocalFile()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        event.acceptProposedAction()

    def dropEvent(self, event):
        path = event.mimeData().urls()[0].toLocalFile()
        if os.path.isdir(path):
            self.parent_window._apply_directory(path)

    # Public API used by main_window

    def set_directory(self, directory: str):
        self.dir_label.setText(directory)
        self.dir_label.setStyleSheet(
            f"color: {self._colors['accent']}; font-weight: bold; background: transparent;"
        )

    def set_running_state(self, is_running: bool):
        self.start_btn.setEnabled(not is_running)
        self.stop_btn.setEnabled(is_running)
        self.browse_btn.setEnabled(not is_running)
        self.validate_btn.setEnabled(not is_running)

    def update_progress(self, progress_value: int):
        self.progress_bar.setValue(progress_value)
        self._refresh_step_styles()

        if progress_value == 0:
            self.progress_bar.setFormat("Ready - 0%")
        elif progress_value == 100:
            self.progress_bar.setFormat("Complete - 100%")
        else:
            self.progress_bar.setFormat(f"Processing - {progress_value}%")

    def set_completed_barcodes(self, done: int, total: int):
        self.completed_label.setText(f"Completed Barcode: {done}/{total}")

    def update_step_counts(self, counts: dict):
        """Update per-step count badges. counts = {step_index: n}"""
        c = self._colors
        for i, badge in enumerate(self.step_counts):
            n = counts.get(i, 0)
            if n > 0:
                badge.setText(str(n))
                badge.setStyleSheet(
                    f"background: {c['green']}; color: {c['bg']};"
                    " font-size: 10px; font-weight: bold; border-radius: 3px;"
                )
            else:
                badge.setText("")
                badge.setStyleSheet("background: transparent; color: transparent;")

    def update_elapsed_time(self, time_str: str):
        self.time_label.setText(time_str)

    def on_job_started(self, job_name: str):
        self.status_label.push(f"Running: {job_name}")

    def on_job_finished(self, job_name: str, success: bool, message: str):
        if success:
            self.status_label.push("Analysis completed successfully")
            self.progress_bar.setFormat("Complete - 100%")
        else:
            self.status_label.push("Analysis failed")
            self.progress_bar.setFormat("Failed")

    def on_pipeline_step(self, job_name: str, step_description: str):
        self.status_label.push(step_description)
        _step_keywords = ["Raw Read QC", "Unzipping", "Adapter Trimming", "Mapping",
                          "Alignment QC", "Variant Calling", "Draft Consensus", "Refining"]
        for i, kw in enumerate(_step_keywords):
            if kw.lower() in step_description.lower():
                self._current_pipeline_step = i
                self.update_progress(self.progress_bar.value())
                break

    def on_step_skipped(self, dot_index: int):
        self._skipped_steps.add(dot_index)
        self.update_progress(self.progress_bar.value())

    def reset_progress(self):
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Ready - 0%")
        self.status_label.reset()
        self._current_pipeline_step = -1
        self._skipped_steps.clear()
        self._refresh_step_styles()
        self.update_step_counts({})
        self.completed_label.setText("Completed Barcode: 0")
        self.time_label.setText("Time Elapsed: 00:00:00")
