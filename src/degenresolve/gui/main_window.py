"""
Main window for DegenResolve

This module contains the main application window with tabs
for analysis, configuration, results, and logs.
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, Any, Optional

from collections import Counter

from PyQt5.QtWidgets import (
    QMainWindow, QTabWidget, QMessageBox, QFileDialog,
    QStatusBar, QApplication, QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton
)
from PyQt5.QtCore import QThreadPool, QTimer, QSettings, Qt
from PyQt5.QtGui import QFont, QTextCursor, QPixmap

from .styles import get_modern_theme_stylesheet
from .results_viewer import ResultsViewer
from .tabs import AnalysisTab, ConfigurationTab, LogsTab
from ..core.config import ConfigManager
from ..core.validator import InputValidator
from ..pipeline.processor import PipelineProcessor
from ..utils.logging import log_with_timestamp


# Shared stylesheet for the in-app Markdown document viewers
_DOC_CSS = """
        body { background: #0a1020; color: #e0e8f0; font-family: 'Inter','Segoe UI',sans-serif;
               font-size: 14px; line-height: 1.7; padding: 32px 40px; max-width: 900px; margin: 0 auto; }
        h1 { color: #7dd3fc; font-size: 26px; border-bottom: 1px solid #2a3a48; padding-bottom: 10px; }
        h2 { color: #7dd3fc; font-size: 20px; margin-top: 32px; border-bottom: 1px solid #2a3a48; padding-bottom: 6px; }
        h3 { color: #c8a0f0; font-size: 16px; margin-top: 24px; }
        h4 { color: #e0e8f0; font-size: 14px; margin-top: 18px; }
        p { margin: 10px 0; }
        a { color: #7dd3fc; text-decoration: none; }
        a:hover { text-decoration: underline; }
        code { background: #0f1524; color: #6ee7b7; padding: 2px 6px; border-radius: 3px; font-size: 13px; }
        pre { background: #0f1524; border: 1px solid #2a3a48; border-radius: 6px; padding: 14px 18px;
              overflow-x: auto; font-size: 12px; line-height: 1.5; }
        pre code { background: none; padding: 0; color: #e0e8f0; }
        table { width: 100%; border-collapse: collapse; margin: 14px 0; font-size: 13px; }
        th { background: #1a2438; color: #7dd3fc; padding: 8px 12px; text-align: left;
             border-bottom: 2px solid #2a3a48; font-weight: 600; }
        td { padding: 8px 12px; border-bottom: 1px solid #2a3a48; }
        tr:hover td { background: #1a2438; }
        hr { border: none; border-top: 1px solid #2a3a48; margin: 24px 0; }
        strong { color: #ffffff; }
        ul, ol { padding-left: 24px; }
        li { margin: 4px 0; }
        """


class _DocPage:
    """Mixin-free QWebEnginePage subclass that routes link clicks to handlers."""
    # Defined lazily so PyQt5.QtWebEngineWidgets isn't imported at module load.
    _cls = None

    @classmethod
    def create(cls, nav_handlers, parent=None):
        if cls._cls is None:
            from PyQt5.QtWebEngineWidgets import QWebEnginePage
            from PyQt5.QtCore import QUrl
            from PyQt5.QtGui import QDesktopServices

            class _Page(QWebEnginePage):
                def acceptNavigationRequest(self, url, nav_type, is_main_frame):
                    if nav_type != QWebEnginePage.NavigationTypeLinkClicked:
                        return True
                    fname = os.path.basename(url.path())
                    if fname in self._handlers:
                        self._handlers[fname]()
                        return False
                    if url.scheme() in ("http", "https"):
                        QDesktopServices.openUrl(url)
                        return False
                    return True

            cls._cls = _Page

        page = cls._cls(parent)
        page._handlers = nav_handlers
        return page


class ONTSequencingAnalyzer(QMainWindow):
    """Main application window for the ONT Sequencing Data Analyzer."""
    
    def __init__(self):
        """Initialize the main window."""
        super().__init__()
        
        # Core components
        self.config_manager = ConfigManager()
        self.processor = None
        self.thread_pool = QThreadPool()
        self.settings = QSettings("ONTSequencing", "DataAnalyzer")
        
        # State tracking
        self.working_directory = ""
        self.is_running = False
        self.analysis_start_time = None
        self._barcode_steps: dict = {}  # barcode -> step_index (0-7)

        
        # Progress tracking
        self.progress_timer = QTimer()
        self.progress_timer.timeout.connect(self.update_elapsed_time)
        self.current_step = 0
        
        # Setup UI
        self.setup_ui()
        self.load_settings()
        self.update_gui_state()
    
    def setup_ui(self):
        """Setup the main application UI."""
        self.setWindowTitle("DeGenRESOLVE")
        self.setMinimumSize(1100, 900)
        self.showMaximized()
        
        # Apply theme
        self.setStyleSheet(get_modern_theme_stylesheet())
        
        # Create central widget with tabs
        self.central_widget = QTabWidget()
        self.setCentralWidget(self.central_widget)
        
        # Create tab instances
        self.analysis_tab = AnalysisTab(self)
        self.config_tab = ConfigurationTab(self)
        self.results_tab = ResultsViewer()
        self.logs_tab = LogsTab(self)
        
        # Store reference to results viewer
        self.results_viewer = self.results_tab
        
        # Add tabs
        self.central_widget.addTab(self.analysis_tab, "Analysis")
        self.central_widget.addTab(self.config_tab, "Configuration")
        self.central_widget.addTab(self.results_tab, "Results")
        self.central_widget.addTab(self.logs_tab, "Logs")

        self.central_widget.currentChanged.connect(self._on_tab_changed)

        # Setup status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setFixedHeight(24)
        self.status_bar.setSizeGripEnabled(True)
        self.status_bar.showMessage("Ready")
        
        # Setup menu bar
        self.setup_menu_bar()
    
    def setup_menu_bar(self):
        """Setup the application menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("File")
        
        open_action = file_menu.addAction("Open Directory")
        open_action.triggered.connect(self.browse_directory)
        
        file_menu.addSeparator()
        
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)
        
        # Help menu
        help_menu = menubar.addMenu("Help")
        
        guide_action = help_menu.addAction("Bench Scientist Guide")
        guide_action.triggered.connect(self.show_bench_guide)

        interface_action = help_menu.addAction("Understanding DeGenRESOLVE Interface")
        interface_action.triggered.connect(self.show_interface_guide)

        about_action = help_menu.addAction("About")
        about_action.triggered.connect(self.show_about)
    
    def browse_directory(self):
        """Browse for input directory."""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Input Directory", self.working_directory,
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        if directory:
            self._apply_directory(directory)

    def _apply_directory(self, directory):
        # Refuse to swap the processor while a run is live. The worker polls the stop flag
        # owned by the processor it was started with; replacing that object left the running
        # pipeline holding an Event nothing would ever set, so Stop and Exit both became
        # no-ops and the pipeline carried on writing into the previous directory.
        if getattr(self, "is_running", False):
            QMessageBox.warning(
                self, "Analysis Running",
                "An analysis is currently running.\n\n"
                "Stop it before changing the input directory - otherwise the running "
                "pipeline could no longer be stopped.")
            return
        self.working_directory = directory
        self.analysis_tab.set_directory(directory)
        self.results_viewer.set_working_directory(directory)
        self.config_tab.set_working_directory(directory)
        self.processor = PipelineProcessor(directory, self.config_manager)
        self.save_settings()
        self.validate_pipeline_setup()
    
    def validate_pipeline_setup(self):
        """Validate the pipeline setup and requirements."""
        if not self.working_directory:
            QMessageBox.warning(self, "Validation Error", "Please select an input directory first.")
            return
        
        if not self.processor:
            self.processor = PipelineProcessor(self.working_directory, self.config_manager)
        
        try:
            is_valid, issues = self.processor.validate_setup()
            
            if issues:
                error_msg = "Validation failed:\n" + "\n".join(f"- {issue}" for issue in issues)
                QMessageBox.critical(self, "Validation Error", error_msg)
                self.append_log(f"[VALIDATION] FAILED: {error_msg}")
            else:
                barcode_count = self.processor.get_barcode_count()
                QMessageBox.information(
                    self, "Validation Success", 
                    f"Pipeline setup is valid and ready for analysis. Found {barcode_count} barcode directories."
                )
                self.append_log(f"[VALIDATION] SUCCESS: Pipeline setup is valid. Found {barcode_count} barcodes")
                
        except Exception as e:
            QMessageBox.critical(self, "Validation Error", f"Error during validation: {str(e)}")
            self.append_log(f"[VALIDATION] ERROR: {str(e)}")
    
    def start_analysis(self):
        """Start the analysis pipeline."""
        # Validate input
        is_valid, error_msg = self.validate_input()
        if not is_valid:
            QMessageBox.critical(self, "Input Error", error_msg)
            return
        
        # Get configuration from the UI controls
        config = self.config_tab.get_configuration()
        
        # Create and configure worker
        worker = self.processor.create_worker(config)
        
        # Connect signals
        worker.signals.log_message.connect(self.append_log)
        worker.signals.progress_update.connect(self.analysis_tab.update_progress)
        worker.signals.job_started.connect(self.on_job_started)
        worker.signals.job_finished.connect(self.on_job_finished)
        worker.signals.pipeline_step.connect(self.on_pipeline_step)
        worker.signals.step_skipped.connect(self.analysis_tab.on_step_skipped)
        worker.signals.error_occurred.connect(self.on_error_occurred)
        worker.signals.barcode_step.connect(self._on_barcode_step)
        worker.signals.barcode_finished.connect(self._on_barcode_finished)
        worker.signals.refresh_results.connect(self.results_viewer.refresh_results)
        
        # Start worker
        self.thread_pool.start(worker)
        
        # Update GUI state
        self.is_running = True
        self.update_gui_state()
        self.append_log("[ANALYSIS] Starting enhanced ONT Sequencing Data Analyzer...")
    
    def stop_analysis(self):
        """Stop the analysis pipeline."""
        if not getattr(self, "is_running", False):
            return
        if self.processor:
            self.processor.stop_processing()
        # Mark the stop as requested so the terminal job_finished handler can report it as a
        # cancellation rather than an analysis failure, and disable the button immediately so
        # the user is not left clicking a control that appears to do nothing.
        self._stop_requested = True
        self.append_log("[ANALYSIS] Stopping analysis...")
        self.update_gui_state()
    
    def validate_input(self) -> tuple[bool, str]:
        """Validate user input before starting analysis."""
        if not self.working_directory:
            return False, "Please select an input directory"
        
        if not self.processor:
            return False, "Pipeline processor not initialized"
        
        # Validate setup
        is_valid, issues = self.processor.validate_setup()
        if not is_valid:
            return False, "\n".join(issues)
        
        # Validate the live GUI config (not the stale config_manager default)
        config_valid, config_error = self.config_manager.validate_config(
            self.config_tab.get_configuration()
        )
        if not config_valid:
            return False, config_error
        
        barcode_count = self.processor.get_barcode_count()
        return True, f"Input validation passed. Found {barcode_count} barcode directories."
    
    def on_job_started(self, job_name: str):
        """Handle job started event."""
        self.analysis_start_time = datetime.now()
        self.progress_timer.start(1000)  # Update every second
        self.analysis_tab.on_job_started(job_name)
        self.append_log(f"[JOB] Started: {job_name}")
        self.is_running = True
        self.update_gui_state()
    
    def on_job_finished(self, job_name: str, success: bool, message: str):
        """Handle job finished event."""
        if not self.is_running:
            return
        self.is_running = False
        self.progress_timer.stop()
        # Tell the processor the run is over so is_running() stops reporting True forever
        # after the first successful analysis.
        if self.processor:
            self.processor.mark_finished()

        self.analysis_tab.on_job_finished(job_name, success, message)
        self.logs_tab.autosave()

        stopped_by_user = getattr(self, "_stop_requested", False)
        self._stop_requested = False

        if success:
            self.append_log(f"[JOB] Completed: {job_name} - {message}")
            QMessageBox.information(self, "Analysis Complete", "Analysis completed successfully!")
        elif stopped_by_user:
            # A cancelled run is not a failed run. Reporting "Analysis failed" for a
            # user-requested stop told people their data was bad when they had pressed Stop.
            self.append_log(f"[JOB] Stopped by user: {job_name}")
            QMessageBox.information(self, "Analysis Stopped",
                                    "The analysis was stopped. Partial results in the output "
                                    "directory are incomplete and should not be published.")
        else:
            self.append_log(f"[JOB] Failed: {job_name} - {message}")
            QMessageBox.critical(self, "Analysis Failed", f"Analysis failed: {message}")

        # Allow starting a new session without restarting the app
        self.reset_session()
    
    def _on_barcode_step(self, barcode: str, step: int):
        self._barcode_steps[barcode] = step
        self.analysis_tab.update_step_counts(dict(Counter(self._barcode_steps.values())))

    def _on_barcode_finished(self, barcode: str):
        self._barcode_steps.pop(barcode, None)
        self.analysis_tab.update_step_counts(dict(Counter(self._barcode_steps.values())))
        w = self.processor.worker if self.processor else None
        if w:
            self.analysis_tab.set_completed_barcodes(w.completed_barcodes, w.total_barcodes)

    def on_pipeline_step(self, job_name: str, step_description: str):
        """Handle pipeline step update."""
        self.analysis_tab.on_pipeline_step(job_name, step_description)
        self.append_log(f"[STEP] {step_description}")
    
    def on_error_occurred(self, error_type: str, error_message: str):
        """Handle error events."""
        self.append_log(f"[ERROR] {error_type}: {error_message}")
        QMessageBox.critical(self, error_type, error_message)
    
    def update_elapsed_time(self):
        """Update elapsed time display."""
        if self.analysis_start_time:
            elapsed = datetime.now() - self.analysis_start_time
            hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            self.analysis_tab.time_label.setText(
                f"Time Elapsed: {hours:02d}:{minutes:02d}:{seconds:02d}"
            )
    
    def append_log(self, message: str):
        """Append a message to the log display."""
        formatted_message = log_with_timestamp(message)
        self.logs_tab.append_log(formatted_message)
    
    def _on_tab_changed(self, index):
        if self.central_widget.widget(index) is self.results_tab:
            self.results_tab.refresh_results()

    def update_gui_state(self):
        """Update the GUI state based on current status."""
        self.analysis_tab.set_running_state(self.is_running)
    
    def reset_session(self):
        """Prepare the UI and state for starting a fresh analysis session."""
        self.is_running = False
        self._barcode_steps.clear()
        if self.processor:
            self.processor.reset()
        self.current_step = 0
        self.progress_timer.stop()
        self.analysis_tab.reset_progress()
        self.update_gui_state()
    
    def save_settings(self):
        """Save application settings."""
        self.settings.setValue("working_directory", self.working_directory)
    
    def load_settings(self):
        """Load application settings."""
        saved_dir = self.settings.value("working_directory", "")
        if saved_dir and os.path.isdir(saved_dir):
            self.working_directory = saved_dir
            self.analysis_tab.set_directory(self.working_directory)
            self.results_viewer.set_working_directory(self.working_directory)
            self.config_tab.set_working_directory(self.working_directory)
            self.processor = PipelineProcessor(self.working_directory, self.config_manager)
        elif saved_dir:
            self.settings.remove("working_directory")
    
    def show_bench_guide(self):
        import re
        guide_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "readme_bench_scientist.md"
        )
        if not os.path.exists(guide_path):
            QMessageBox.warning(self, "Not Found", f"Guide not found:\n{guide_path}")
            return
        try:
            from markdown_it import MarkdownIt
            md = MarkdownIt("commonmark", {"html": True}).enable("table")
            with open(guide_path, "r") as f:
                html_body = md.render(f.read())
        except ImportError:
            with open(guide_path, "r") as f:
                html_body = f"<pre>{f.read()}</pre>"

        def _add_heading_ids(html):
            def _slugify(m):
                tag = m.group(1)
                text = re.sub(r'<[^>]+>', '', m.group(2))
                slug = re.sub(r'[^\w\s-]', '', text.lower().strip())
                slug = re.sub(r'[\s]+', '-', slug).strip('-')
                return f'<{tag} id="{slug}">{m.group(2)}</{tag}>'
            return re.sub(r'<(h[1-4])>(.*?)</\1>', _slugify, html)
        html_body = _add_heading_ids(html_body)

        css = _DOC_CSS
        full_html = f"<html><head><style>{css}</style></head><body>{html_body}</body></html>"

        from PyQt5.QtWebEngineWidgets import QWebEngineView
        dlg = QDialog(self)
        dlg.setWindowTitle("Bench Scientist Guide")
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        dlg.resize(960, 700)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)
        view = QWebEngineView()
        view.setPage(_DocPage.create({
            "DeGenRESOLVE_interface.md": self.show_interface_guide,
            "README.md": self.show_readme,
        }, view))
        view.setHtml(full_html)
        layout.addWidget(view)
        dlg.exec_()

    def show_interface_guide(self):
        import re
        guide_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "DeGenRESOLVE_interface.md"
        )
        if not os.path.exists(guide_path):
            QMessageBox.warning(self, "Not Found", f"Interface guide not found:\n{guide_path}")
            return
        try:
            from markdown_it import MarkdownIt
            md = MarkdownIt("commonmark", {"html": True}).enable("table")
            with open(guide_path, "r") as f:
                html_body = md.render(f.read())
        except ImportError:
            with open(guide_path, "r") as f:
                html_body = f"<pre>{f.read()}</pre>"

        def _add_heading_ids(html):
            def _slugify(m):
                tag = m.group(1)
                text = re.sub(r'<[^>]+>', '', m.group(2))
                slug = re.sub(r'[^\w\s-]', '', text.lower().strip())
                slug = re.sub(r'[\s]+', '-', slug).strip('-')
                return f'<{tag} id="{slug}">{m.group(2)}</{tag}>'
            return re.sub(r'<(h[1-4])>(.*?)</\1>', _slugify, html)
        html_body = _add_heading_ids(html_body)

        css = _DOC_CSS
        full_html = f"<html><head><style>{css}</style></head><body>{html_body}</body></html>"

        from PyQt5.QtWebEngineWidgets import QWebEngineView
        dlg = QDialog(self)
        dlg.setWindowTitle("Understanding DeGenRESOLVE Interface")
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        dlg.resize(960, 700)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)
        view = QWebEngineView()
        view.setPage(_DocPage.create({
            "readme_bench_scientist.md": self.show_bench_guide,
            "README.md": self.show_readme,
        }, view))
        view.setHtml(full_html)
        layout.addWidget(view)
        dlg.exec_()

    def show_readme(self):
        import re
        guide_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "README.md"
        )
        if not os.path.exists(guide_path):
            QMessageBox.warning(self, "Not Found", f"README not found:\n{guide_path}")
            return
        try:
            from markdown_it import MarkdownIt
            md = MarkdownIt("commonmark", {"html": True}).enable("table")
            with open(guide_path, "r") as f:
                html_body = md.render(f.read())
        except ImportError:
            with open(guide_path, "r") as f:
                html_body = f"<pre>{f.read()}</pre>"

        css = _DOC_CSS
        full_html = f"<html><head><style>{css}</style></head><body>{html_body}</body></html>"

        from PyQt5.QtWebEngineWidgets import QWebEngineView
        dlg = QDialog(self)
        dlg.setWindowTitle("README")
        dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowMaximizeButtonHint | Qt.WindowMinimizeButtonHint)
        dlg.resize(960, 700)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)
        view = QWebEngineView()
        view.setPage(_DocPage.create({
            "readme_bench_scientist.md": self.show_bench_guide,
            "DeGenRESOLVE_interface.md": self.show_interface_guide,
        }, view))
        view.setHtml(full_html)
        layout.addWidget(view)
        dlg.exec_()

    def show_about(self):
        """Show about dialog."""
        dlg = QDialog(self)
        dlg.setWindowTitle("About DeGenRESOLVE")
        dlg.setFixedWidth(500)
        dlg.setStyleSheet("QDialog { background: #0f1524; } QLabel { background: transparent; }")

        layout = QVBoxLayout()
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 20)

        app_label = QLabel(
            "<div style='color:#e0e8f0;font-family:sans-serif;'>"
            "<p style='font-size:18px;font-weight:bold;color:#7dd3fc;margin:0 0 8px 0;'>"
            "DeGenRESOLVE v1.0.0</p>"
            "<p style='font-size:12px;margin:0 0 8px 0;'>A comprehensive Linux-based standalone "
            "application for processing ONT raw FASTQ files and generating refined consensus "
            "FASTA sequences.</p>"
            "<p style='font-size:12px;font-weight:bold;color:#7dd3fc;margin:0 0 4px 0;'>Features:</p>"
            "<p style='font-size:12px;margin:0;'>"
            "- Dynamic configuration of analysis parameters<br>"
            "- Influenza-specific or general filtering<br>"
            "- Real-time progress tracking<br>"
            "- Comprehensive logging and result management</p>"
            "</div>"
        )
        app_label.setWordWrap(True)
        layout.addWidget(app_label)

        dev_label = QLabel(
            "<div style='color:#e0e8f0;font-size:13px;line-height:1.4;'>"
            "<p style='font-weight:bold;font-size:14px;color:#7dd3fc;margin:0 0 6px 0;'>"
            "Developed By:</p>"
            "<p style='font-weight:bold;font-size:14px;color:#7dd3fc;margin:0 0 10px 0;'>"
            "Shoaib Saikat</p>"
            "<p style='font-size:12px;color:#e0e8f0;margin:0 0 8px 0;'>"
            "<strong>Research Fellow, One Health Laboratory</strong><br>"
            "Infectious Diseases Division<br>"
            "International Centre for Diarrhoeal Disease Research, Bangladesh (icddr,b)<br>"
            "Dhaka 1212, Bangladesh</p>"
            "<p style='font-size:12px;color:#e0e8f0;margin:0 0 8px 0;'>"
            "<strong>MS in Biochemistry and Biotechnology</strong><br>"
            "University of Barishal, Barishal-8254, Bangladesh</p>"
            "<p style='font-size:12px;color:#e0e8f0;margin:0 0 4px 0;'>"
            "<strong>Email:</strong> saikatshoaib@gmail.com</p>"
            "<p style='font-size:12px;color:#7dd3fc;margin:0;'>"
            "<strong>LinkedIn:</strong> linkedin.com/in/shoaib-saikat</p>"
            "</div>"
        )
        dev_label.setWordWrap(True)
        layout.addWidget(dev_label)

        banner_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))),
            "app_data", "img", "banner.jpg"
        )
        if os.path.exists(banner_path):
            pixmap = QPixmap(banner_path)
            if not pixmap.isNull():
                banner_lbl = QLabel()
                banner_lbl.setPixmap(pixmap.scaledToWidth(452, Qt.SmoothTransformation))
                banner_lbl.setAlignment(Qt.AlignCenter)
                layout.addWidget(banner_lbl)

        footer = QLabel(
            "One Health Laboratory, Infectious Diseases Division, icddr,b, Bangladesh"
        )
        footer.setAlignment(Qt.AlignCenter)
        footer.setWordWrap(True)
        footer.setStyleSheet("color: #a0b4c4; font-size: 12px;")
        layout.addWidget(footer)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok_btn = QPushButton("OK")
        ok_btn.setFixedWidth(80)
        ok_btn.setStyleSheet(
            "QPushButton { background: rgba(125,211,252,0.1); color: #7dd3fc;"
            " border: 1px solid #7dd3fc; border-radius: 4px; padding: 6px; }"
            "QPushButton:hover { background: rgba(125,211,252,0.2); }"
        )
        ok_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

        dlg.setLayout(layout)
        dlg.exec_()
    
    def closeEvent(self, event):
        """Handle application close event."""
        if self.is_running:
            reply = QMessageBox.question(
                self, "Exit Application",
                "Analysis is currently running. Are you sure you want to exit?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                if self.processor:
                    self.processor.stop_processing()
                # Wait for the pool to actually drain. Accepting immediately tore down the
                # GUI while the worker thread was still alive; because the pipeline is started
                # with start_new_session=True it then survived as an orphan, continuing to
                # write consensus and report files after the application had vanished.
                QApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    self.append_log("[ANALYSIS] Waiting for the pipeline to stop...")
                    if not self.thread_pool.waitForDone(30000):
                        QApplication.restoreOverrideCursor()
                        keep_waiting = QMessageBox.question(
                            self, "Still Stopping",
                            "The pipeline has not stopped yet.\n\n"
                            "Quit anyway? External tools may keep running in the background.",
                            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                        if keep_waiting != QMessageBox.Yes:
                            event.ignore()
                            return
                        QApplication.setOverrideCursor(Qt.WaitCursor)
                finally:
                    QApplication.restoreOverrideCursor()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
