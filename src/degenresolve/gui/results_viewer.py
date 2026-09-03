"""
Results viewer widget for DegenResolve

This module contains the results viewer widget that displays
analysis results and file organization.
"""

import html
import sys
import subprocess
from pathlib import Path
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QMessageBox, QListWidget, QSizePolicy, QFrame
)
from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QFont, QPainter, QPen, QColor, QDesktopServices
from PyQt5.QtWebEngineWidgets import QWebEngineView, QWebEngineSettings, QWebEnginePage
from .styles import DARK_COLORS


class _ReportPage(QWebEnginePage):
    """Navigation policy for the results web view: local HTML reports (our
    summary, qualimap, nanoplot) open embedded; PDFs, data files, and external
    URLs open in the system default app instead of navigating the view to them.
    """

    def acceptNavigationRequest(self, url, nav_type, is_main_frame):
        if nav_type == QWebEnginePage.NavigationTypeLinkClicked:
            if url.scheme() in ("http", "https"):
                QDesktopServices.openUrl(url)
                return False
            # HTML reports and PDFs render inside the view (QtWebEngine's
            # built-in PDF viewer). Any other local file (BAM, FASTA, ...) goes
            # to the system so we never navigate the view to binary data.
            path = url.path().lower()
            if not path.endswith((".html", ".htm", ".pdf")):
                QDesktopServices.openUrl(url)
                return False
        return True


class SampleListWidget(QListWidget):
    """QListWidget that draws empty rows to fill visible space."""

    def paintEvent(self, event):
        super().paintEvent(event)
        row_height = 37
        item_count = self.count()
        viewport_height = self.viewport().height()
        filled_height = item_count * row_height
        if filled_height >= viewport_height:
            return
        painter = QPainter(self.viewport())
        pen = QPen(getattr(self, '_grid_color', QColor("#cbd5e1")))
        pen.setWidth(1)
        painter.setPen(pen)
        y = filled_height
        while y + row_height < viewport_height:
            y += row_height
            painter.drawLine(0, y, self.viewport().width(), y)
        painter.end()


class ResultsViewer(QWidget):
    """Widget to display analysis results and file organization."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.working_directory = ""
        self._colors = DARK_COLORS
        self.setup_ui()
        self.results = {}

    def _selected_barcode(self):
        item = self.barcode_list.currentItem()
        return item.data(Qt.UserRole) if item else ""

    # HTML builders

    def _ph_html(self):
        c = self._colors
        return (
            f"<html><body style='background:{c['panel']};color:{c['placeholder']};"
            "font-family:Inter,sans-serif;display:flex;align-items:center;"
            "justify-content:center;height:100vh'>"
            "<p style=\"font-size:28px;font-style:italic;text-align:center;\">"
            "Select Sample ID to<br>View Results</p></body></html>"
        )

    def _not_found_html(self, path):
        c = self._colors
        return (
            f"<html><body style='background:{c['panel']};color:{c['placeholder']};"
            f"font-family:Inter,sans-serif;padding:40px'>"
            f"<h2 style='color:{c['text']}'>Report not found</h2>"
            f"<p>{path}</p></body></html>"
        )

    def _diag_css(self):
        c = self._colors
        return (
            f"body{{background:{c['panel']};color:{c['text']};font-family:'Inter',sans-serif;"
            f"font-size:12px;padding:16px;margin:0}}"
            f"h2{{color:{c['accent']};margin-bottom:10px;font-size:16px}}"
            f"h3{{color:{c['purple']};font-size:15px;margin:0 0 6px 0}}"
            f".box{{color:{c['dim']};font-size:13px;line-height:1.6;margin-bottom:12px;"
            f"padding:10px 12px;background:{c['bg']};border:1px solid {c['border']};border-radius:6px}}"
            f".boxes{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px}}"
            f".boxes .box{{flex:1;min-width:200px}}"
            f".table-wrap{{overflow:auto;max-height:60vh;border:1px solid {c['border']};"
            f"border-radius:6px;margin-bottom:14px}}"
            f"table{{border-collapse:collapse;font-size:12px;font-family:monospace;white-space:nowrap}}"
            f"th{{background:{c['hover']};color:{c['accent']};padding:3px 6px;text-align:left;"
            f"border-bottom:2px solid {c['border']};font-weight:600;position:sticky;top:0;z-index:1}}"
            f"td{{padding:2px 6px;border-bottom:1px solid {c['hover']}}}"
            f"tr:hover td{{background:{c['hover']}}}"
            f".good{{color:{c['green']};font-weight:600}}"
            f".bad{{color:{c['error']};font-weight:600}}"
            f".warn-flag{{color:{c['warn']}}}"
        )

    # Widget style application

    def _apply_widget_styles(self):
        c = self._colors
        icon_btn = (
            f"QPushButton {{ background: {c['panel']}; border: 1px solid {c['border']};"
            f" border-radius: 6px; color: {c['dim']}; font-size: 18px; padding: 6px; }}"
            f"QPushButton:hover {{ background: {c['sel_bg']};"
            f" border-color: rgba(125,211,252,0.3); color: {c['accent']}; }}"
        )
        util_btn = (
            f"QPushButton {{ background: transparent; border: 1px solid {c['border']};"
            f" border-radius: 4px; color: {c['dim']}; font-size: 12px; padding: 4px 10px; }}"
            f"QPushButton:hover {{ border-color: rgba(125,211,252,0.3); color: {c['accent']}; }}"
        )
        self._sidebar_frame.setStyleSheet(
            f"QFrame#sidebar {{ background: {c['panel']}; border-right: 1px solid {c['border']}; }}"
        )
        self._sample_title_lbl.setStyleSheet(
            f"font-weight: bold; font-size: 13px; color: {c['text']}; background: transparent;"
        )
        self.refresh_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            f"QPushButton:hover {{ background: {c['sel_bg']}; border-radius: 4px; }}"
        )
        self._sep_frame.setStyleSheet(f"background: {c['border']};")
        self.barcode_list.setStyleSheet(
            f"QListWidget {{ background: transparent; color: {c['text']}; font-size: 13px;"
            f"  border: none; outline: none; }}"
            f"QListWidget::item {{ padding: 8px 10px; min-height: 20px;"
            f" border-bottom: 1px solid {c['border']}; }}"
            f"QListWidget::item:selected {{ background: {c['sel_bg']}; color: {c['accent']}; }}"
            f"QListWidget::item:hover {{ background: {c['hover']}; }}"
        )
        self.barcode_list._grid_color = QColor(c['border'])
        self._top_bar.setStyleSheet(
            f"QFrame {{ background: {c['topbar']}; border-bottom: 1px solid {c['border']}; }}"
        )
        self._overview_title.setStyleSheet(f"color: {c['text']}; background: transparent;")
        for btn in (self.open_raw_qc_btn, self.open_bam_qc_btn,
                    self.open_bam_btn, self.open_consensus_btn):
            btn.setStyleSheet(icon_btn)
        for btn in (self.open_results_btn, self.open_log_btn, self.back_btn):
            btn.setStyleSheet(util_btn)

    def setup_ui(self):
        outer = QHBoxLayout()
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)

        # Left sidebar: Sample ID list
        self._sidebar_frame = sidebar = QFrame()
        sidebar.setFixedWidth(170)
        sidebar.setObjectName("sidebar")
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(0)

        header_row = QHBoxLayout()
        header_row.setContentsMargins(10, 10, 6, 6)
        self._sample_title_lbl = sample_title = QLabel("Sample ID")
        header_row.addWidget(sample_title)
        header_row.addStretch()
        self.refresh_btn = QPushButton()
        self.refresh_btn.setIcon(self.style().standardIcon(self.style().SP_BrowserReload))
        self.refresh_btn.setFixedSize(26, 26)
        self.refresh_btn.setToolTip("Refresh Results")
        self.refresh_btn.clicked.connect(self.refresh_results)
        header_row.addWidget(self.refresh_btn)
        side_layout.addLayout(header_row)

        self._sep_frame = sep = QFrame()
        sep.setFixedHeight(1)
        side_layout.addWidget(sep)

        self.barcode_list = SampleListWidget()
        self.barcode_list.setUniformItemSizes(True)
        self.barcode_list.currentItemChanged.connect(lambda: self._on_barcode_selected())
        side_layout.addWidget(self.barcode_list)

        outer.addWidget(sidebar)
        outer.addSpacing(18)

        # Right: top bar + preview
        right = QVBoxLayout()
        right.setSpacing(0)
        right.setContentsMargins(0, 0, 0, 0)

        self._top_bar = top_bar = QFrame()
        top_bar.setFixedHeight(50)
        bar_layout = QHBoxLayout(top_bar)
        bar_layout.setContentsMargins(14, 6, 14, 6)
        bar_layout.setSpacing(10)

        self._overview_title = title = QLabel("Overview")
        title.setFont(QFont("Inter", 16, QFont.Bold))
        bar_layout.addWidget(title)
        bar_layout.addStretch()

        self.open_raw_qc_btn = QPushButton("≡")
        self.open_raw_qc_btn.setToolTip("Open Raw Reads QC")
        self.open_raw_qc_btn.setFixedSize(40, 36)
        self.open_raw_qc_btn.clicked.connect(self._open_nanoplot_report)
        bar_layout.addWidget(self.open_raw_qc_btn)

        self.open_bam_qc_btn = QPushButton("≈")
        self.open_bam_qc_btn.setToolTip("Open BAM QC")
        self.open_bam_qc_btn.setFixedSize(40, 36)
        self.open_bam_qc_btn.clicked.connect(self._open_qualimap_report)
        bar_layout.addWidget(self.open_bam_qc_btn)

        self.open_bam_btn = QPushButton("▓")
        self.open_bam_btn.setToolTip("Open BAM File")
        self.open_bam_btn.setFixedSize(40, 36)
        self.open_bam_btn.clicked.connect(self._open_bam_folder)
        bar_layout.addWidget(self.open_bam_btn)

        self.open_consensus_btn = QPushButton("⚗")
        self.open_consensus_btn.setToolTip("Refined Consensus")
        self.open_consensus_btn.setFixedSize(40, 36)
        self.open_consensus_btn.clicked.connect(self._open_refined_consensus)
        bar_layout.addWidget(self.open_consensus_btn)

        bar_layout.addSpacing(16)

        self.open_results_btn = QPushButton("Open Folder")
        self.open_results_btn.clicked.connect(self.open_results_folder)
        bar_layout.addWidget(self.open_results_btn)

        self.open_log_btn = QPushButton("Log")
        self.open_log_btn.setToolTip("Open diagnostic log for selected barcode")
        self.open_log_btn.clicked.connect(self._open_diagnostic_log)
        bar_layout.addWidget(self.open_log_btn)

        self.back_btn = QPushButton("Back ›")
        self.back_btn.clicked.connect(lambda: self.report_view.back())
        bar_layout.addWidget(self.back_btn)

        right.addWidget(top_bar)

        self.report_view = QWebEngineView()
        self.report_view.setPage(_ReportPage(self.report_view))
        _rv_settings = self.report_view.settings()
        _rv_settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, True)
        # Render qualimap PDFs with QtWebEngine's built-in viewer so the
        # "Open full report (PDF)" link works without any external PDF app.
        _rv_settings.setAttribute(QWebEngineSettings.PluginsEnabled, True)
        _rv_settings.setAttribute(QWebEngineSettings.PdfViewerEnabled, True)
        self.report_view.loadFinished.connect(self._inject_link_style)
        self.report_view.setHtml(self._ph_html())
        right.addWidget(self.report_view)

        outer.addLayout(right, 1)
        outer.addSpacing(18)
        self.setLayout(outer)
        self._apply_widget_styles()

    # Data API

    def add_result(self, barcode: str, status: str, progress: str = "0%", output_files: str = ""):
        self.results[barcode] = {
            "status": status,
            "progress": progress,
            "output_files": output_files
        }
        for i in range(self.barcode_list.count()):
            if self.barcode_list.item(i).data(Qt.UserRole) == barcode:
                return
        from PyQt5.QtWidgets import QListWidgetItem
        item = QListWidgetItem(f"{self.barcode_list.count() + 1}) {barcode}")
        item.setData(Qt.UserRole, barcode)
        item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.barcode_list.addItem(item)

    def update_result(self, barcode: str, status: str, progress: str = None, output_files: str = None):
        if barcode in self.results:
            self.results[barcode]["status"] = status
            if progress:
                self.results[barcode]["progress"] = progress
            if output_files:
                self.results[barcode]["output_files"] = output_files

    def refresh_results(self):
        results_dir = Path(self.working_directory) / "results" if self.working_directory else Path("results")
        if not results_dir.exists():
            return

        self.results.clear()
        self.barcode_list.clear()

        final_outputs_dir = results_dir / "step_8_refined_consensus"
        found_results = False

        if final_outputs_dir.exists():
            for consensus_file in sorted(final_outputs_dir.glob("*_consensus_edited.fasta")):
                barcode = consensus_file.stem.replace("_consensus_edited", "")
                found_results = True
                file_size = consensus_file.stat().st_size
                status = "Empty" if file_size == 0 else "Completed"

                if file_size < 1024:
                    size_str = f"{file_size} B"
                elif file_size < 1024 * 1024:
                    size_str = f"{file_size / 1024:.1f} KB"
                else:
                    size_str = f"{file_size / (1024 * 1024):.1f} MB"

                self.add_result(barcode, status, "100%", f"step_8_refined_consensus/{consensus_file.name} ({size_str})")

        if not found_results:
            for consensus_file in sorted(results_dir.glob("*_consensus_edited.fasta")):
                barcode = consensus_file.stem.replace("_consensus_edited", "")
                file_size = consensus_file.stat().st_size
                status = "Empty" if file_size == 0 else "Completed"

                if file_size < 1024:
                    size_str = f"{file_size} B"
                elif file_size < 1024 * 1024:
                    size_str = f"{file_size / 1024:.1f} KB"
                else:
                    size_str = f"{file_size / (1024 * 1024):.1f} MB"

                self.add_result(barcode, status, "100%", f"{consensus_file.name} ({size_str})")

    def open_results_folder(self):
        results_dir = Path(self.working_directory) / "results" if self.working_directory else Path("results")
        if not results_dir.exists():
            results_dir.mkdir(exist_ok=True)

        try:
            if sys.platform == "linux":
                subprocess.run(["xdg-open", str(results_dir)])
            elif sys.platform == "win32":
                subprocess.run(["explorer", str(results_dir)])
            elif sys.platform == "darwin":
                subprocess.run(["open", str(results_dir)])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Could not open results folder: {e}")

    def set_working_directory(self, directory: str):
        self.working_directory = directory
        self.refresh_results()

    def _open_qc_report(self, report_path: Path):
        if report_path.exists():
            try:
                subprocess.run(["xdg-open", str(report_path)])
            except FileNotFoundError:
                QMessageBox.information(self, "File Location", str(report_path))
        else:
            QMessageBox.warning(self, "Report Not Found",
                                f"QC report not found:\n{report_path}")

    def _open_nanoplot_report(self):
        barcode = self._selected_barcode()
        if not barcode:
            return
        self._open_qc_report(
            Path(self.working_directory) / "results" / "step_1_raw_read_qc_nanoplot"
            / barcode / "NanoPlot-report.html")

    def _open_qualimap_report(self):
        barcode = self._selected_barcode()
        if not barcode:
            return
        self._open_qc_report(
            Path(self.working_directory) / "results" / "step_5_alignment_qc_qualimap"
            / barcode / f"qualimap_output_{barcode}" / "qualimapReport.html")

    def _open_bam_folder(self):
        barcode = self._selected_barcode()
        if not barcode:
            return
        folder = Path(self.working_directory) / "results" / "step_4_mapped" / barcode
        if folder.exists():
            try:
                subprocess.run(["xdg-open", str(folder)])
            except FileNotFoundError:
                QMessageBox.information(self, "Folder Location", str(folder))
        else:
            QMessageBox.warning(self, "Folder Not Found",
                                f"BAM folder not found:\n{folder}")

    def _open_refined_consensus(self):
        barcode = self._selected_barcode()
        if not barcode:
            return
        self._open_qc_report(
            Path(self.working_directory) / "results" / "step_8_refined_consensus"
            / f"{barcode}_consensus_edited.fasta")

    def _open_diagnostic_log(self):
        barcode = self._selected_barcode()
        if not barcode:
            return
        log_path = (Path(self.working_directory) / "log"
                    / f"{barcode}_consensus_edited_diagnostic_log.txt")
        if not log_path.exists():
            QMessageBox.warning(self, "Not Found", f"Diagnostic log not found:\n{log_path}")
            return
        try:
            text = log_path.read_text()
        except OSError as e:
            QMessageBox.warning(self, "Read Error", f"Could not read log:\n{e}")
            return
        lines = text.strip().split("\n")

        param_lines = []
        summary_overall = []
        summary_perseg = []
        tsv_lines = []
        section = "params"
        for line in lines:
            if "SUMMARY STATISTICS" in line:
                section = "summary_overall"
                continue
            if "Per-segment statistics:" in line:
                section = "summary_perseg"
                continue
            if line.startswith("Segment\t") and section in ("params", "skip_mapping"):
                section = "tsv"
            if section == "tsv":
                if line.startswith("===") or line.startswith("---") or not line.strip():
                    continue
                # The per-site table ends at the first line with no tab. Sections that follow
                # it - INDEL DECISIONS, INDEL EVIDENCE and their prose - have different column
                # counts, and without this exit they were appended to the per-site table and
                # rendered as malformed rows (87 of 643 rows on the shipped example log).
                if "\t" not in line:
                    section = "after_tsv"
                    continue
                tsv_lines.append(line)
            elif section == "summary_overall":
                if line.strip() and not line.startswith("===") and not line.startswith("---"):
                    summary_overall.append(line)
            elif section == "summary_perseg":
                if line.strip() and not line.startswith("===") and not line.startswith("---"):
                    summary_perseg.append(line)
            elif "SEGMENT MAPPING" in line:
                section = "skip_mapping"
            elif section == "skip_mapping":
                pass
            elif section == "params":
                if line.strip() and not line.startswith("===") and not line.startswith("---"):
                    param_lines.append(line)

        table_html = ""
        if tsv_lines:
            cols = tsv_lines[0].split("\t")
            cov_idx = cols.index("Coverage") if "Coverage" in cols else -1
            th = "".join(f"<th>{c}</th>" for c in cols)
            rows = ""
            skipped = 0
            for row in tsv_lines[1:]:
                cells = row.split("\t")
                # Skip zero-coverage rows - they are always KEEP/UNCHANGED and
                # inflate the table to megabyte scale on large barcodes.
                if cov_idx >= 0 and cov_idx < len(cells) and cells[cov_idx] == "0":
                    skipped += 1
                    continue
                tds = ""
                for j, cell in enumerate(cells):
                    cls = ""
                    col_name = cols[j] if j < len(cols) else ""
                    if col_name == "Status":
                        if cell == "CHANGED":
                            cls = ' class="good"'
                        elif cell == "UNCHANGED":
                            cls = ' class="bad"'
                    elif col_name == "Decision":
                        if cell == "RESOLVE":
                            cls = ' class="good"'
                        elif cell == "KEEP":
                            cls = ' class="bad"'
                    elif col_name == "Warnings":
                        if cell.strip() and cell.strip() != "-":
                            cls = ' class="warn-flag"'
                    tds += f"<td{cls}>{html.escape(cell)}</td>"
                rows += f"<tr>{tds}</tr>"
            skip_note = (f"<p style='color:#94a3b8;font-size:11px;margin:0 0 6px 0'>"
                         f"{skipped:,} zero-coverage positions hidden</p>") if skipped else ""
            table_html = (f"{skip_note}"
                          f"<table><thead><tr>{th}</tr></thead><tbody>{rows}</tbody></table>")

        params_html = "<br>".join(f"<span>{html.escape(l)}</span>" for l in param_lines)
        overall_html = "<br>".join(f"<span>{html.escape(l)}</span>" for l in summary_overall) if summary_overall else ""
        perseg_html = "<br>".join(f"<span>{html.escape(l)}</span>" for l in summary_perseg) if summary_perseg else ""

        boxes = f"<div class='box'><h3>Parameters</h3>{params_html}</div>"
        if overall_html:
            boxes += f"<div class='box'><h3>Summary Statistics</h3>{overall_html}</div>"
        if perseg_html:
            boxes += f"<div class='box'><h3>Per-Segment Statistics</h3>{perseg_html}</div>"

        page = (f"<html><head><style>{self._diag_css()}</style></head><body>"
                f"<h2>Diagnostic Log - {barcode}</h2>"
                f"<div class='table-wrap'>{table_html}</div>"
                f"<div class='boxes'>{boxes}</div></body></html>")
        self.report_view.setHtml(page)

    def _inject_link_style(self, ok=True):
        # Only theme our OWN summary report. Third-party reports (qualimap,
        # nanoplot) ship their own light stylesheet with white content
        # backgrounds - forcing our near-white text colour onto them made
        # them unreadable (whitish text on a white background).
        if not ok:
            return
        if not self.report_view.url().toString().endswith("_summary_report.html"):
            return
        c = self._colors
        self.report_view.page().runJavaScript(
            "var s=document.createElement('style');"
            f"s.textContent='body{{background:{c['bg']}!important;color:{c['text']}!important}}"
            f"a{{color:{c['dim']}!important;text-decoration:none}}"
            f"a:hover{{color:{c['text']}!important;text-decoration:underline}}';"
            "document.head.appendChild(s);"
        )

    def _on_barcode_selected(self):
        barcode = self._selected_barcode()
        if not barcode or not self.working_directory:
            return
        report_path = (Path(self.working_directory) / "results" / "reports"
                       / f"{barcode}_summary_report.html")
        if report_path.exists():
            self.report_view.setUrl(QUrl.fromLocalFile(str(report_path)))
        else:
            self.report_view.setHtml(self._not_found_html(report_path))

    def clear_results(self):
        self.results.clear()
        self.barcode_list.clear()
