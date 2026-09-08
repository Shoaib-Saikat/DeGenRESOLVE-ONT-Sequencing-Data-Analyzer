"""
Input validation for DegenResolve

This module handles validation of input directories, files,
and pipeline setup requirements.
"""

import os
import re
import subprocess
from typing import List, Tuple
from pathlib import Path


class InputValidator:
    """Validates input directories and pipeline setup."""
    
    def __init__(self, working_directory: str = ""):
        """Initialize validator with working directory.
        
        Args:
            working_directory: Path to the working directory to validate.
        """
        self.working_directory = working_directory
    
    def validate_directory_structure(self) -> Tuple[bool, List[str]]:
        """Validate the input directory structure.
        
        Returns:
            Tuple of (is_valid, list_of_issues).
        """
        if not self.working_directory:
            return False, ["No working directory specified"]
        
        if not os.path.exists(self.working_directory):
            return False, ["Working directory does not exist"]
        
        issues = []
        
        # Check for fastq_pass directory
        fastq_pass_dir = os.path.join(self.working_directory, "fastq_pass")
        if not os.path.isdir(fastq_pass_dir):
            # isdir, not exists: a plain FILE named fastq_pass passed the old check and the
            # subsequent os.listdir then raised NotADirectoryError out of the validator -
            # which is exactly the failure this method exists to report cleanly.
            issues.append("fastq_pass is not a directory" if os.path.exists(fastq_pass_dir)
                          else "fastq_pass directory not found")
        
        # Check for reference directory and exactly one .fasta/.fa file
        reference_dir = os.path.join(self.working_directory, "reference")
        if not os.path.isdir(reference_dir):
            issues.append("reference/ is not a directory" if os.path.exists(reference_dir)
                          else "reference/ directory not found")
            ref_files = []
        else:
            try:
                ref_files = [f for f in os.listdir(reference_dir)
                             if f.endswith((".fasta", ".fa"))]
            except OSError as e:
                # An unreadable directory is a validation failure to report, not a traceback.
                issues.append(f"reference/ could not be read: {e.strerror}")
                ref_files = []
            if len(ref_files) == 0:
                issues.append("No .fasta or .fa file found in reference/")
            elif len(ref_files) > 1:
                issues.append(f"Found {len(ref_files)} FASTA files in reference/, expected exactly 1")
        
        # Check for barcode directories
        if os.path.exists(fastq_pass_dir):
            barcode_dirs = [d for d in os.listdir(fastq_pass_dir) 
                          if d.startswith("barcode") and 
                          os.path.isdir(os.path.join(fastq_pass_dir, d))]
            if not barcode_dirs:
                issues.append("No barcode directories found in fastq_pass")
        
        return len(issues) == 0, issues
    
    def validate_barcode_contents(self) -> Tuple[bool, List[str], int]:
        """Validate barcode directory contents.
        
        Returns:
            Tuple of (is_valid, list_of_issues, barcode_count).
        """
        if not self.working_directory:
            return False, ["No working directory specified"], 0
        
        fastq_pass_dir = os.path.join(self.working_directory, "fastq_pass")
        if not os.path.exists(fastq_pass_dir):
            return False, ["fastq_pass directory not found"], 0
        
        issues = []
        barcode_dirs = []
        
        # Find all barcode directories
        for item in os.listdir(fastq_pass_dir):
            item_path = os.path.join(fastq_pass_dir, item)
            if item.startswith("barcode") and os.path.isdir(item_path):
                barcode_dirs.append(item)
                
                # Check if barcode directory contains fastq.gz files
                fastq_files = [f for f in os.listdir(item_path) 
                             if f.endswith('.fastq.gz')]
                if not fastq_files:
                    issues.append(f"No .fastq.gz files found in {item}")
        
        if not barcode_dirs:
            issues.append("No barcode directories found")
        
        return len(issues) == 0, issues, len(barcode_dirs)
    
    # Minimum external tool versions. The sup variant-calling profile passes
    # --indels-cns and --max-BQ to bcftools mpileup; both are 1.21+ flags, and an older
    # bcftools fails with a bare usage error that points at nothing. Nothing in the
    # pipeline checked a version before, so this surfaced as an unexplained mid-run crash.
    MIN_TOOL_VERSIONS = {
        "samtools": (1, 10),
        "bcftools": (1, 21),
        "minimap2": (2, 17),
    }

    @staticmethod
    def _parse_tool_version(text: str):
        """Pull the first dotted version number out of a tool's --version output."""
        m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", text or "")
        if not m:
            return None
        return tuple(int(g) for g in m.groups(default="0"))

    def validate_tool_versions(self) -> Tuple[bool, List[str]]:
        """Check that the external tools on PATH are new enough.

        Returns:
            Tuple of (is_valid, list_of_problems). A tool that is absent is reported by
            validate_system_tools(), not here, so it is skipped rather than double-reported.
        """
        problems = []
        for tool, minimum in self.MIN_TOOL_VERSIONS.items():
            try:
                result = subprocess.run([tool, "--version"], capture_output=True,
                                        text=True, timeout=10)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                continue
            found = self._parse_tool_version(result.stdout or result.stderr)
            if found is None:
                problems.append(f"{tool}: version could not be determined")
                continue
            if found[:len(minimum)] < minimum:
                have = ".".join(str(x) for x in found)
                want = ".".join(str(x) for x in minimum)
                problems.append(
                    f"{tool} {have} is older than the required {want}. "
                    + ("The sup basecall profile passes --indels-cns and --max-BQ, which "
                       "this version does not support." if tool == "bcftools" else ""))
        return len(problems) == 0, problems

    def validate_system_tools(self) -> Tuple[bool, List[str]]:
        """Validate that required system tools are available.
        
        Returns:
            Tuple of (is_valid, list_of_missing_tools).
        """
        required_tools = [
            "samtools",
            "bcftools", 
            "minimap2",
            "porechop",
            "python3"
        ]
        
        missing_tools = []
        
        for tool in required_tools:
            try:
                result = subprocess.run(
                    ["which", tool], 
                    capture_output=True, 
                    text=True,
                    timeout=5
                )
                if result.returncode != 0:
                    missing_tools.append(tool)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                missing_tools.append(tool)
        
        # Check for vcfutils.pl (part of bcftools)
        try:
            result = subprocess.run(
                ["which", "vcfutils.pl"], 
                capture_output=True, 
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                missing_tools.append("vcfutils.pl")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            missing_tools.append("vcfutils.pl")
        
        # Check for seqtk
        try:
            result = subprocess.run(
                ["which", "seqtk"], 
                capture_output=True, 
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                missing_tools.append("seqtk")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            missing_tools.append("seqtk")
        
        return len(missing_tools) == 0, missing_tools
    
    def validate_pipeline_setup(self) -> Tuple[bool, List[str]]:
        """Comprehensive validation of pipeline setup.
        
        Returns:
            Tuple of (is_valid, list_of_all_issues).
        """
        all_issues = []
        
        # Validate directory structure
        dir_valid, dir_issues = self.validate_directory_structure()
        all_issues.extend(dir_issues)
        
        # Validate barcode contents
        barcode_valid, barcode_issues, barcode_count = self.validate_barcode_contents()
        all_issues.extend(barcode_issues)
        
        # Validate system tools
        tools_valid, missing_tools = self.validate_system_tools()
        if missing_tools:
            all_issues.append(f"Missing required tools: {', '.join(missing_tools)}")
        
        is_valid = dir_valid and barcode_valid and tools_valid
        
        return is_valid, all_issues
    
    def get_barcode_count(self) -> int:
        """Get the number of barcode directories found.
        
        Returns:
            Number of barcode directories.
        """
        if not self.working_directory:
            return 0
        
        fastq_pass_dir = os.path.join(self.working_directory, "fastq_pass")
        if not os.path.exists(fastq_pass_dir):
            return 0
        
        barcode_dirs = [d for d in os.listdir(fastq_pass_dir) 
                       if d.startswith("barcode") and 
                       os.path.isdir(os.path.join(fastq_pass_dir, d))]
        
        return len(barcode_dirs)
    
    def get_barcode_list(self) -> List[str]:
        """Get list of barcode directory names.
        
        Returns:
            List of barcode directory names.
        """
        if not self.working_directory:
            return []
        
        fastq_pass_dir = os.path.join(self.working_directory, "fastq_pass")
        if not os.path.exists(fastq_pass_dir):
            return []
        
        barcode_dirs = [d for d in os.listdir(fastq_pass_dir) 
                       if d.startswith("barcode") and 
                       os.path.isdir(os.path.join(fastq_pass_dir, d))]
        
        return sorted(barcode_dirs)
