"""
Main entry point for DegenResolve

This module provides the main entry point for the ONT Sequencing Data Analyzer.
"""

import sys
import os
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

# Ensure conda env bin is on PATH so tools (bcftools, porechop, etc.) are found
# when the app is launched outside an activated environment
_env_bin = os.path.join(sys.prefix, "bin")
if _env_bin not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _env_bin + os.pathsep + os.environ.get("PATH", "")

# NanoPlot / Plotly QC plots use WebGL, which Chromium blocklists on many
# headless / VM / WSL setups (the GPU works but isn't recognised), leaving the
# scatter plots blank. Ignore the blocklist so WebGL renders. Overridable by
# setting QTWEBENGINE_CHROMIUM_FLAGS before launch.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--ignore-gpu-blocklist")

# Import the main window from the modular structure
from .gui.main_window import ONTSequencingAnalyzer


def main():
    """Main application entry point."""
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("DeGenRESOLVE")
    app.setApplicationVersion("1.0.0")
    
    # Create and show the main window
    window = ONTSequencingAnalyzer()
    window.show()
    
    # Start the application event loop
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
