"""
Configuration management for DegenResolve

This module handles configuration loading, saving, and validation
for the ONT Sequencing Data Analyzer.
"""

import json
import os
from typing import Dict, Any, Optional
from pathlib import Path


class ConfigManager:
    """Manages configuration settings for the application."""

    DEFAULT_CONFIG = {
        "min_coverage": 100,
        "degeneracy_threshold": 20,
        "ploidy": 2,
        "indel_rules": "equal_or_more",
        "indel_custom_percentage": 50.0,
        "variant_call_depth": 10000,
        # None means "omit the key", which lets the shell resolve the base-quality
        # pair from the basecall tier (1/35 sup, 5/30 hac). A number here pins it
        # for every tier - that was the defect fixed in this release.
        "min_base_quality": None,
        "max_base_quality": None,
        "force_sup_profile": False,
        "variant_call_mode": "c",
        "filter_mode": "general",
        "qualimap_enabled": True,
        "nanoplot_enabled": True,
        # These were absent from DEFAULT_CONFIG, so a headless run that relied on the defaults
        # silently executed single-threaded with none of the advanced filters configured,
        # while README.md documented values for all of them.
        "parallel_enabled": True,
        "parallel_threads": os.cpu_count() or 1,
        "strand_balance_threshold": 0.1,
        "homopolymer_min_length": 5,
        "homopolymer_window": 5,
        "read_end_threshold": 0.8,
        "read_end_edge_fraction": 0.1,
        "strict_strand_bias": False,
        "strict_homopolymer": False,
        "strict_read_end": False,
    }

    def __init__(self, config_file: Optional[str] = None):
        """Initialize configuration manager.

        Args:
            config_file: Path to configuration file. If None, uses default location.
        """
        self.config_file = config_file or "ont_analyzer_config.json"
        self.config = self.DEFAULT_CONFIG.copy()

    def load_config(self, config_file: Optional[str] = None) -> Dict[str, Any]:
        """Load configuration from file.

        Args:
            config_file: Path to configuration file to load.

        Returns:
            Dictionary containing configuration parameters.

        Raises:
            FileNotFoundError: If config file doesn't exist.
            json.JSONDecodeError: If config file is invalid JSON.
        """
        file_path = config_file or self.config_file

        if not os.path.exists(file_path):
            # Return default config if file doesn't exist
            return self.DEFAULT_CONFIG.copy()

        try:
            with open(file_path, 'r') as f:
                loaded_config = json.load(f)

            # Merge with defaults to ensure all keys exist
            config = self.DEFAULT_CONFIG.copy()
            config.update(loaded_config)

            # Handle backward compatibility for degeneracy_threshold
            # Backward compatibility for the legacy 0-1 fraction form. The bound is strict:
            # `<= 1.0` also caught a literal 1.0, converting a deliberate 1% threshold into
            # 100% and inverting the resolution rule.
            deg_threshold = config.get("degeneracy_threshold", 20)
            if isinstance(deg_threshold, (int, float)) and 0 < deg_threshold < 1:
                config["degeneracy_threshold"] = max(1, int(round(deg_threshold * 100)))

            self.config = config
            return config

        except json.JSONDecodeError as e:
            # json.JSONDecodeError.__init__ requires (msg, doc, pos). Constructing it with a
            # single argument raised TypeError instead of the intended error, so a malformed
            # config surfaced as an unrelated crash with no mention of the file. Preserve the
            # original doc/pos so the reported line and column still point at the real fault.
            raise json.JSONDecodeError(
                f"Invalid JSON in config file {file_path}: {e.msg}", e.doc, e.pos) from e

    def save_config(self, config: Dict[str, Any], config_file: Optional[str] = None) -> None:
        """Save configuration to file.

        Args:
            config: Configuration dictionary to save.
            config_file: Path to save configuration file to.

        Raises:
            OSError: If unable to write to file.
        """
        file_path = config_file or self.config_file

        try:
            with open(file_path, 'w') as f:
                json.dump(config, f, indent=2)

            self.config = config.copy()

        except OSError as e:
            raise OSError(f"Unable to save config to {file_path}: {e}")

    def validate_config(self, config: Optional[Dict[str, Any]] = None) -> tuple[bool, str]:
        """Validate configuration parameters.

        Args:
            config: Configuration to validate. Uses current config if None.

        Returns:
            Tuple of (is_valid, error_message).
        """
        cfg = config or self.config

        # Check min_coverage
        if cfg.get("min_coverage", 0) < 1:
            return False, "Minimum coverage must be at least 1"

        # Check degeneracy_threshold
        deg_threshold = cfg.get("degeneracy_threshold", 20)
        if deg_threshold <= 0 or deg_threshold > 100:
            return False, "Degeneracy threshold must be between 1 and 100%"

        # Check ploidy
        if cfg.get("ploidy", 1) < 1:
            return False, "Ploidy must be at least 1"

        # Check variant_call_depth
        if cfg.get("variant_call_depth", 10000) < 1:
            return False, "Variant call depth must be at least 1"

        # Check indel_custom_percentage
        if cfg.get("indel_custom_percentage", 50.0) <= 0 or cfg.get("indel_custom_percentage", 50.0) > 100:
            return False, "Indel custom percentage must be between 0 and 100"

        return True, "Configuration is valid"

    def reset_to_defaults(self) -> None:
        """Reset configuration to default values."""
        self.config = self.DEFAULT_CONFIG.copy()

    def get(self, key: str, default=None):
        """Get configuration value by key.

        Args:
            key: Configuration key to retrieve.
            default: Default value if key not found.

        Returns:
            Configuration value or default.
        """
        return self.config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value by key.

        Args:
            key: Configuration key to set.
            value: Value to set for the key.
        """
        self.config[key] = value

    def to_dict(self) -> Dict[str, Any]:
        """Return configuration as dictionary.

        Returns:
            Copy of current configuration.
        """
        return self.config.copy()
