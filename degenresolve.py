#!/usr/bin/env python3
"""
DeGenRESOLVE - ONT Sequencing Data Analyzer
Main launcher script for the modular application

This script serves as the main entry point for the DeGenRESOLVE application.
It can be used to launch the GUI or run specific pipeline components.
"""

import sys
import os
import argparse
from pathlib import Path

# Add the src directory to Python path
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

def launch_gui():
    """Launch the main GUI application."""
    try:
        from degenresolve.main import main
        main()
    except ImportError as e:
        print(f"Error: Required dependencies not found: {e}")
        print("Please install requirements: pip install -r requirements.txt")
        print("")
        print("For Linux/WSL, you may need to install PyQt5 with:")
        print("  sudo apt-get install python3-pyqt5")
        print("  pip install PyQt5")
        sys.exit(1)

def run_consensus_editor():
    """Run the consensus editor standalone."""
    try:
        from degenresolve.pipeline.consensus_editor import main
        main()
    except ImportError as e:
        print(f"Error: Required dependencies not found: {e}")
        print("Please install requirements: pip install -r requirements.txt")
        sys.exit(1)

def main():
    """Main entry point with command line argument handling."""
    parser = argparse.ArgumentParser(
        description="DegenResolve - ONT Sequencing Data Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python degenresolve.py                    # Launch GUI
  python degenresolve.py --gui              # Launch GUI (explicit)
  python degenresolve.py --consensus        # Run consensus editor only
        """
    )
    
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the GUI application (default when no mode is given)"
    )
    
    parser.add_argument(
        "--consensus", 
        action="store_true",
        help="Run the consensus editor standalone"
    )
    
    parser.add_argument(
        "--version", 
        action="version", 
        version="DeGenRESOLVE 1.0.0"
    )
    
    args = parser.parse_args()
    
    if args.consensus:
        run_consensus_editor()
    else:
        launch_gui()

if __name__ == "__main__":
    main()
