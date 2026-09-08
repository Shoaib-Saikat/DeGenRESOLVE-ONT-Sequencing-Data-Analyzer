"""
Pipeline processor for DegenResolve

This module contains the main pipeline processor that coordinates
the execution of the ONT sequencing analysis pipeline.
"""

import os
import subprocess
import threading
from typing import Dict, Any, Optional
from pathlib import Path

from ..core.config import ConfigManager
from ..core.validator import InputValidator
from .worker import PipelineWorker


class PipelineProcessor:
    """Main pipeline processor for ONT sequencing analysis."""
    
    def __init__(self, working_directory: str, config_manager: Optional[ConfigManager] = None):
        """Initialize pipeline processor.
        
        Args:
            working_directory: Directory containing the data to process.
            config_manager: Configuration manager instance. Creates new one if None.
        """
        self.working_directory = working_directory
        self.config_manager = config_manager or ConfigManager()
        self.validator = InputValidator(working_directory)
        self._finished = False
        self.stop_flag = threading.Event()
        self.worker = None
        
    def validate_setup(self) -> tuple[bool, list[str]]:
        """Validate the pipeline setup.
        
        Returns:
            Tuple of (is_valid, list_of_issues).
        """
        is_valid, issues = self.validator.validate_pipeline_setup()
        # Tool versions are part of a valid setup. bcftools older than 1.21 does not accept
        # the flags the sup profile passes, and without this the run failed mid-pipeline with
        # a bare usage error rather than at validation time.
        versions_ok, version_problems = self.validator.validate_tool_versions()
        if not versions_ok:
            issues = list(issues) + version_problems
            is_valid = False
        return is_valid, issues
    
    def get_barcode_count(self) -> int:
        """Get the number of barcode directories.
        
        Returns:
            Number of barcode directories found.
        """
        return self.validator.get_barcode_count()
    
    def get_barcode_list(self) -> list[str]:
        """Get list of barcode directory names.
        
        Returns:
            List of barcode directory names.
        """
        return self.validator.get_barcode_list()
    
    def create_worker(self, config: Optional[Dict[str, Any]] = None) -> PipelineWorker:
        """Create a pipeline worker with current configuration.
        
        Args:
            config: Configuration dictionary. Uses config manager if None.
            
        Returns:
            Configured pipeline worker.
        """
        if config is None:
            config = self.config_manager.to_dict()

        self.stop_flag.clear()
        self.worker = PipelineWorker(self.working_directory, config, self.stop_flag)
        return self.worker
    
    def stop_processing(self) -> None:
        """Signal the worker to stop processing."""
        self.stop_flag.set()
    
    def reset(self) -> None:
        """Reset the processor for a new run.

        Refuses to swap the stop flag while a worker is still live: the running worker polls
        the Event object it was handed, so replacing it produced a pipeline that could no
        longer be stopped by anything.
        """
        if self.is_running():
            # A live worker polls the Event object it was handed, so replacing it would leave
            # the pipeline unstoppable. Refuse the swap - but do NOT raise. reset() is called
            # from a Qt slot (on_job_finished -> reset_session), and PyQt aborts the whole
            # application on an unhandled exception in a slot, which closed the app at the end
            # of every successful run. Returning quietly keeps the safety property without
            # taking the GUI down with it.
            return
        self.stop_flag = threading.Event()
        self.worker = None
        self._finished = False
    
    def is_running(self) -> bool:
        """Check if processing is currently running.
        
        Returns:
            True if processing is running, False otherwise.
        """
        # A completed run leaves self.worker set and the stop flag clear, so the old test
        # reported True forever after the first successful analysis. Track completion
        # explicitly instead of inferring it from the stop flag.
        return (self.worker is not None
                and not self.stop_flag.is_set()
                and not getattr(self, "_finished", False))

    def mark_finished(self) -> None:
        """Record that the current run has ended, however it ended."""
        self._finished = True
    
    def get_results_directory(self) -> Path:
        """Get the results directory path.
        
        Returns:
            Path to the results directory.
        """
        return Path(self.working_directory) / "results"
    
    def get_log_directory(self) -> Path:
        """Get the log directory path.
        
        Returns:
            Path to the log directory.
        """
        return Path(self.working_directory) / "log"
    
    def cleanup_temporary_files(self) -> None:
        """Clean up temporary files created during processing."""
        config_file = os.path.join(self.working_directory, "pipeline_config.json")
        if os.path.exists(config_file):
            os.remove(config_file)
    
    def get_script_path(self, script_name: str) -> str:
        """Get the full path to a pipeline script.
        
        Args:
            script_name: Name of the script file.
            
        Returns:
            Full path to the script file.
        """
        # Get the path relative to this module
        scripts_dir = Path(__file__).parent.parent / "scripts"
        return str(scripts_dir / script_name)
    
    def check_system_requirements(self) -> tuple[bool, list[str]]:
        """Check if all required system tools are available.
        
        Returns:
            Tuple of (all_available, list_of_missing_tools).
        """
        return self.validator.validate_system_tools()
