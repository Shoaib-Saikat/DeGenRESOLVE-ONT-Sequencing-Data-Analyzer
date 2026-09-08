"""
Pipeline worker for DegenResolve

This module contains the worker class that runs the enhanced
pipeline with configurable parameters in a separate thread.
"""

import os
import re
import signal
import subprocess
import threading
import json
from typing import Dict, Any
from PyQt5.QtCore import QRunnable

from ..core.signals import PipelineSignals


class PipelineWorker(QRunnable):
    """Worker class to run the enhanced pipeline with configurable parameters."""
    
    def __init__(self, working_directory: str, config: Dict[str, Any], stop_flag: threading.Event):
        """Initialize pipeline worker.
        
        Args:
            working_directory: Directory containing the data to process.
            config: Configuration dictionary with pipeline parameters.
            stop_flag: Threading event to signal worker to stop.
        """
        super().__init__()
        self.working_directory = working_directory
        self.config = config
        self.stop_flag = stop_flag
        self.signals = PipelineSignals()
        
        self.step_names = [
            "Running Raw Read QC (NanoPlot)",
            "Unzipping & Concatenating reads",
            "Adapter Trimming (Porechop)",
            "Mapping to reference (minimap2)",
            "Alignment QC (samtools/Qualimap)",
            "Variant Calling (bcftools)",
            "Generating Draft Consensus",
            "Refining Consensus",
        ]
        self.current_step = -1        # kept for backward compat
        self.completed_barcodes = 0
        self.total_barcodes = 1
        self.current_barcode = ""
        self.barcode_steps: dict = {} # barcode -> current step index (-1 = not started)
    
    def run(self):
        """Execute the enhanced pipeline with configurable parameters."""
        if self.stop_flag.is_set():
            # Emit the terminal signal even on this early path. QThreadPool may start this
            # runnable after Stop was pressed; returning silently left the GUI permanently in
            # the "running" state with no worker alive to ever clear it.
            self.signals.job_finished.emit("Enhanced Pipeline", False, "Cancelled before start")
            return

        process = None
            
        try:
            self.signals.job_started.emit("Enhanced Pipeline")
            self.signals.log_message.emit("[MAIN] Starting enhanced ONT Sequencing Data Analyzer...")
            self.signals.pipeline_step.emit("Enhanced Pipeline", "Initializing enhanced pipeline")
            self.signals.progress_update.emit(5)
            
            # Run relative to the selected directory. We pass it as cwd to the
            # pipeline subprocess rather than calling os.chdir(), which would
            # mutate the whole process's working directory from this worker thread.
            self.signals.log_message.emit(f"[MAIN] Working directory: {self.working_directory}")
            
            # Validate input structure
            self._validate_input_structure()
            
            # Create configuration file
            self._create_config_file()
            
            # Execute our working pipeline script
            script_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                "scripts", "main_with_config.sh"
            )
            command = f'bash "{script_path}" pipeline_config.json'

            self.signals.log_message.emit(f"[MAIN] Executing: {command}")
            self.signals.pipeline_step.emit("Enhanced Pipeline", "Processing barcodes sequentially")
            self.signals.progress_update.emit(10)
            
            # Run the pipeline
            # PYTHONUNBUFFERED=1 prevents Python subprocesses (porechop etc.)
            # from buffering stdout when piped - without it readline() blocks
            # until the buffer fills and the GUI appears hung at adapter trimming.
            _env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                # Decode explicitly with errors='replace'. universal_newlines=True decodes as
                # strict UTF-8, so a single stray byte anywhere in samtools/bcftools/porechop
                # output raised UnicodeDecodeError and killed an otherwise healthy run.
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=_env,
                cwd=self.working_directory,
                start_new_session=True,
            )

            # Stop must work during a quiet phase too. The monitor loop below only observes
            # the flag when a line arrives, and minimap2 or Qualimap can run for many minutes
            # without printing - so Stop appeared to be ignored until the phase ended. This
            # watchdog waits on the flag itself and kills the process group as soon as it is
            # set, independently of subprocess output.
            _watchdog_done = threading.Event()

            def _await_stop():
                while not _watchdog_done.wait(0.2):
                    if self.stop_flag.is_set():
                        self._terminate_process_group(process)
                        return

            _watchdog = threading.Thread(target=_await_stop, name="pipeline-stop-watchdog",
                                         daemon=True)
            _watchdog.start()

            # Monitor output
            _PREFIX = re.compile(r'^\[(barcode\w+)\]\s*(.*)', re.IGNORECASE)
            for line in iter(process.stdout.readline, ''):
                if self.stop_flag.is_set():
                    # Escalates to SIGKILL if the tree ignores SIGTERM. Previously a single
                    # SIGTERM was sent with no follow-up, so a busy samtools kept running and
                    # Stop appeared to do nothing.
                    self._terminate_process_group(process)
                    break

                line = line.strip()
                if not line:
                    continue
                self.signals.log_message.emit(f"[PIPELINE] {line}")

                # Split [barcodeXX] prefix (parallel mode) from content
                pm = _PREFIX.match(line)
                if pm:
                    barcode, content = pm.group(1), pm.group(2)
                else:
                    barcode, content = self.current_barcode, line

                # Total barcode count (outer shell, unprefixed)
                m = re.match(r'Total barcodes\s*:\s*(\d+)', content)
                if m:
                    self.total_barcodes = max(int(m.group(1)), 1)
                    continue

                # Barcode finished - outer shell prints "Time for barcodeXX:" unprefixed
                fin = re.search(r'time for (barcode\w+):', line, re.IGNORECASE)
                if fin:
                    done = fin.group(1)
                    self.completed_barcodes += 1
                    self.barcode_steps.pop(done, None)
                    self.signals.barcode_finished.emit(done)
                    continue

                # New barcode starting
                if re.search(r'starting pipeline for', content, re.IGNORECASE):
                    bc_m = re.search(r'(barcode\w+)', content, re.IGNORECASE)
                    bc = bc_m.group(1) if bc_m else barcode
                    if bc:
                        self.current_barcode = bc
                        self.barcode_steps.setdefault(bc, -1)
                    continue

                # Detect pipeline step - routed to the correct barcode
                if not barcode:
                    continue
                current = self.barcode_steps.get(barcode, -1)
                step = self._detect_pipeline_step(content)
                if step > current:
                    self.barcode_steps[barcode] = step
                    self.current_step = step  # keep for compat
                    active = self.barcode_steps.values()
                    avg_step = sum(active) / max(len(self.barcode_steps), 1)
                    per_barcode = 85.0 / self.total_barcodes
                    progress = int(5 + self.completed_barcodes * per_barcode
                                   + (max(avg_step, 0) / 7.0) * per_barcode)
                    self.signals.progress_update.emit(min(progress, 93))
                    if 0 <= step < len(self.step_names):
                        self.signals.pipeline_step.emit(
                            "Enhanced Pipeline", f"{barcode}: {self.step_names[step]}")
                        self.signals.barcode_step.emit(barcode, step)
            
            # Wait for process to complete
            return_code = process.wait()

            # Re-check the stop flag: a cancelled run exits non-zero, and reporting that as a
            # pipeline failure told the user their data was bad when they had pressed Stop.
            if self.stop_flag.is_set():
                self.signals.log_message.emit("[MAIN] Pipeline stopped at user request")
                self.signals.job_finished.emit("Enhanced Pipeline", False, "Analysis stopped by user")
            elif return_code == 0:
                self.signals.progress_update.emit(100)
                self.signals.pipeline_step.emit("Enhanced Pipeline", "All processing completed")
                self.signals.log_message.emit("[MAIN] Pipeline completed successfully")
                self.signals.job_finished.emit("Enhanced Pipeline", True, "Analysis completed successfully")
                self.signals.refresh_results.emit()
            else:
                self.signals.log_message.emit(f"[MAIN] Pipeline failed with return code: {return_code}")
                self.signals.job_finished.emit("Enhanced Pipeline", False, f"Pipeline failed with return code: {return_code}")

        except Exception as e:
            self.signals.log_message.emit(f"[ERROR] {str(e)}")
            self.signals.job_finished.emit("Enhanced Pipeline", False, f"Error: {str(e)}")
        finally:
            try:
                _watchdog_done.set()
            except NameError:
                pass
            # The pipeline runs in its own session (start_new_session=True), so it survives
            # this thread unless it is explicitly killed. Without this block any exception in
            # the monitor loop above - or a stop that the loop never observed - left the whole
            # samtools/bcftools/minimap2 tree running detached, writing into the user's output
            # directory, while the GUI reported the run finished.
            self._terminate_process_group(process)
    
    @staticmethod
    def _terminate_process_group(process, grace_seconds: float = 10.0):
        """Stop the pipeline and everything it spawned, escalating if it ignores SIGTERM.

        The pipeline is launched with start_new_session=True, so it leads its own process
        group; signalling only the shell would leave samtools/minimap2 children running.
        """
        if process is None or process.poll() is not None:
            return
        try:
            pgid = os.getpgid(process.pid)
        except OSError:
            pgid = None

        for sig, wait_for in ((signal.SIGTERM, grace_seconds), (signal.SIGKILL, 5.0)):
            try:
                if pgid is not None:
                    os.killpg(pgid, sig)
                elif sig == signal.SIGTERM:
                    process.terminate()
                else:
                    process.kill()
            except (ProcessLookupError, PermissionError, OSError):
                return
            try:
                process.wait(timeout=wait_for)
                return
            except subprocess.TimeoutExpired:
                continue

    def _validate_input_structure(self):
        """Validate the input directory structure."""
        self.signals.pipeline_step.emit("Enhanced Pipeline", "Validating input directory structure")
        
        # Check for fastq_pass directory
        if not os.path.exists(os.path.join(self.working_directory, "fastq_pass")):
            raise FileNotFoundError("fastq_pass directory not found")
        
        # Check for barcode directories
        barcode_dirs = [d for d in os.listdir(os.path.join(self.working_directory, "fastq_pass")) if d.startswith("barcode")]
        if not barcode_dirs:
            raise FileNotFoundError("No barcode directories found in fastq_pass")
        
        # Check for exactly one .fasta/.fa in reference/
        if not os.path.isdir(os.path.join(self.working_directory, "reference")):
            raise FileNotFoundError("reference/ directory not found")
        ref_files = [f for f in os.listdir(os.path.join(self.working_directory, "reference")) if f.endswith((".fasta", ".fa"))]
        if len(ref_files) == 0:
            raise FileNotFoundError("No .fasta or .fa file found in reference/")
        if len(ref_files) > 1:
            raise FileNotFoundError(
                f"Found {len(ref_files)} FASTA files in reference/, expected exactly 1 - remove the extra file"
            )
        
        self.signals.log_message.emit(f"[VALIDATION] Found {len(barcode_dirs)} barcode directories")
        self.signals.log_message.emit("[VALIDATION] System pipeline is available")
    
    def _create_config_file(self):
        """Create a configuration file that will be used by the pipeline scripts."""
        # Convert indel_rules string to object format expected by pipeline
        indel_rules_string = self.config.get("indel_rules", "equal_or_more")
        indel_rules_object = {
            "insertions": indel_rules_string,
            "deletions": indel_rules_string,
            "custom_percentage": self.config.get("indel_custom_percentage", 50.0)
        }
        
        # Base quality is written only when explicitly pinned. Omitting the keys is
        # how "auto" reaches the shell, which then resolves them from the basecall
        # tier (1/35 sup, 5/30 hac). Emitting a default here defeats that entirely -
        # which is why every GUI run took -Q5 regardless of tier.
        variant_call_settings = {
            "depth_per_site": self.config.get("variant_call_depth", 10000),
            "call_mode": self.config.get("variant_call_mode", "c"),
        }
        if self.config.get("min_base_quality") is not None:
            variant_call_settings["min_base_quality"] = self.config["min_base_quality"]
        if self.config.get("max_base_quality") is not None:
            variant_call_settings["max_base_quality"] = self.config["max_base_quality"]

        config_data = {
            "min_coverage": self.config.get("min_coverage", 100),
            "degeneracy_threshold": self.config.get("degeneracy_threshold", 20),
            "ploidy": self.config.get("ploidy", 2),
            "indel_rules": indel_rules_object,
            "variant_call_settings": variant_call_settings,
            "force_sup_profile": self.config.get("force_sup_profile", False),
            "filter_mode": self.config.get("filter_mode", "general"),
            "influenza_segments": [
                "HA*", "NA*", "PB2", "PB1", "PA", "NP", "MP", "NS"
            ] if self.config.get("filter_mode") == "influenza" else [],
            "qualimap": {
                "enabled": self.config.get("qualimap_enabled", True)
            },
            "nanoplot": {
                "enabled": self.config.get("nanoplot_enabled", True)
            },
            "parallel": {
                "enabled": self.config.get("parallel_enabled", True),
                "threads": self.config.get("parallel_threads", 1)
            },
            "advanced_criteria": {
                "strand_balance_threshold": self.config.get("strand_balance_threshold", 0.1),
                "homopolymer_min_length": self.config.get("homopolymer_min_length", 5),
                "homopolymer_window": self.config.get("homopolymer_window", 5),
                "read_end_threshold": self.config.get("read_end_threshold", 0.8),
                "read_end_edge_fraction": self.config.get("read_end_edge_fraction", 0.1),
                "strict_strand_bias": self.config.get("strict_strand_bias", False),
                "strict_homopolymer": self.config.get("strict_homopolymer", False),
                "strict_read_end": self.config.get("strict_read_end", False)
            }
        }
        
        config_path = os.path.join(self.working_directory, "pipeline_config.json")
        with open(config_path, "w") as f:
            json.dump(config_data, f, indent=2)
        
        self.signals.log_message.emit("[CONFIG] Created pipeline configuration file")
    
    def _detect_pipeline_step(self, line: str) -> int:
        """Detect pipeline step from log output. Returns 0-7 matching the 8 GUI dots.

        Only matches the '=== Step X' markers emitted by the shell script
        to avoid false hits on config echo lines containing tool names.

        Shell->dot mapping:
          Step 0.5 (NanoPlot)      -> dot 0
          Step 1   (merge)         -> dot 1
          Step 2   (porechop)      -> dot 2
          Step 3   (minimap2)      -> dot 3  Mapping
          Step 4   (sam->bam sort)  -> dot 3  (still Mapping - conversion is part of it)
          Step 4.5 (qualimap)      -> dot 4  Alignment QC
          Step 5   (consensus gen) -> dot 5
          Step 6   (editor)        -> dot 7
        """
        l = line.lower()

        # ponytail: only match "=== step" markers - loose keywords like
        # "qualimap"/"nanoplot" matched config printout and caused false jumps
        if "=== step 6" in l:
            return 7
        if "=== step 5.5" in l:
            return 6
        if "=== step 5" in l:
            return 5
        if "=== step 4.5" in l:
            return 4
        if "=== step 4:" in l:
            return 3  # SAM->BAM is part of Mapping dot
        if "=== step 3" in l:
            return 3
        if "=== step 2" in l:
            return 2
        if "=== step 1" in l:
            return 1
        if "=== step 0.5" in l:
            return 0

        # Detect skipped optional steps
        if "nanoplot disabled" in l:
            self.signals.step_skipped.emit(0)
        elif "qualimap disabled" in l:
            self.signals.step_skipped.emit(4)

        return -1  # no step marker found in this line
