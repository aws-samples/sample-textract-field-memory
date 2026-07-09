# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Configuration management for textract-field-memory.

Loads settings from a YAML or JSON config file, environment variables,
or uses sensible defaults. Priority order (highest wins):

1. Explicit constructor arguments (always override)
2. Environment variables (FIELD_MEMORY_*)
3. Config file (field_memory.yaml or field_memory.json)
4. Built-in defaults

Usage:
    # Auto-discovers config file in CWD or ~/.field_memory/
    config = FieldMemoryConfig.load()

    # From explicit path
    config = FieldMemoryConfig.load("/path/to/field_memory.yaml")

    # Use in TemplateMemory
    memory = TemplateMemory.from_config(config)
    # or just
    memory = TemplateMemory()  # auto-loads config
"""

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class FieldMemoryConfig:
    """Complete configuration for textract-field-memory.

    All parameters have sensible defaults. Override via config file,
    environment variables, or constructor arguments.
    """

    # ─── Storage ───
    store_path: str = str(Path.home() / ".field_memory" / "templates")
    """Directory for persisting template JSON files."""

    # ─── Spatial Matching ───
    spatial_tolerance: float = 0.05
    """Position tolerance for 'within expected region' checks (0.05 = 5% of page).
    Higher values are more forgiving of positional variation."""

    spatial_weight: float = 0.6
    """Weight given to spatial/positional similarity in combined scoring (0.0-1.0).
    Higher = position matters more. Lower = field names matter more.
    Use 0.7-0.8 for fraud/tampering detection.
    Use 0.3-0.4 for noisy scans with positional variance."""

    name_weight: float = 0.4
    """Weight given to field name similarity in combined scoring (0.0-1.0).
    Should equal 1.0 - spatial_weight."""

    # ─── Template Identification ───
    similarity_threshold: float = 0.7
    """Minimum combined score to accept a template match (0.0-1.0).
    Lower = more lenient matching. Higher = stricter matching.
    Use 0.5-0.6 for diverse document streams.
    Use 0.8+ for high-precision identification."""

    min_spatial_score: float = 0.4
    """Minimum spatial similarity required for a match to be considered.
    Below this threshold, the match is heavily penalized regardless of name similarity.
    Prevents accepting documents with correct field names but wrong positions."""

    min_structural_score: float = 0.3
    """Minimum structural (Jaccard name overlap) score required.
    Below this, the match is penalized. Prevents matching when too few field names overlap."""

    # ─── Drift Detection ───
    drift_threshold: float = 0.03
    """Per-field drift threshold (fraction of page diagonal, 0.0-1.0).
    A field is 'drifting' if its center moves more than this distance from baseline.
    0.03 = ~4mm on letter paper. 0.01 = ~1.5mm (very sensitive).
    0.10 = ~14mm (only detects major layout changes)."""

    min_drifting_ratio: float = 0.2
    """Fraction of shared fields that must exceed drift_threshold to flag a document.
    0.2 = 20% of fields must drift. Prevents false alarms from single-field OCR noise.
    0.0 = any single drifting field triggers the flag."""

    # ─── Confidence & Decay ───
    decay_factor: float = 0.95
    """Weight decay for older observations (0.0-1.0).
    Controls how quickly old positional data loses influence.
    0.95 = gradual decay (older data retains 95% weight per new observation).
    0.80 = aggressive decay (templates adapt quickly to recent data).
    1.0 = no decay (all observations weighted equally forever)."""

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "FieldMemoryConfig":
        """Load configuration from file, environment, and defaults.

        Search order for config file:
        1. Explicit config_path argument
        2. FIELD_MEMORY_CONFIG environment variable
        3. ./field_memory.yaml (current working directory)
        4. ./field_memory.json
        5. ~/.field_memory/config.yaml
        6. ~/.field_memory/config.json

        Environment variables override file values. Use FIELD_MEMORY_ prefix:
            FIELD_MEMORY_SPATIAL_WEIGHT=0.7
            FIELD_MEMORY_DRIFT_THRESHOLD=0.05
            FIELD_MEMORY_STORE_PATH=/custom/path
        """
        config = cls()

        # Find and load config file
        file_data = cls._load_file(config_path)
        if file_data:
            config = cls._apply_file_data(config, file_data)

        # Apply environment variable overrides
        config = cls._apply_env_overrides(config)

        # Ensure weights are consistent
        if abs(config.spatial_weight + config.name_weight - 1.0) > 0.01:
            config.name_weight = 1.0 - config.spatial_weight

        return config

    @classmethod
    def _load_file(cls, config_path: Optional[str]) -> Optional[dict]:
        """Find and load a config file."""
        search_paths = []

        if config_path:
            search_paths.append(Path(config_path))
        elif os.environ.get("FIELD_MEMORY_CONFIG"):
            search_paths.append(Path(os.environ["FIELD_MEMORY_CONFIG"]))
        else:
            # Primary: bundled config inside the package
            package_dir = Path(__file__).parent
            search_paths = [
                package_dir / "field_memory.yaml",
                Path.cwd() / "field_memory.yaml",
                Path.cwd() / "field_memory.json",
                Path.home() / ".field_memory" / "config.yaml",
                Path.home() / ".field_memory" / "config.json",
            ]

        for path in search_paths:
            if path.exists():
                return cls._parse_file(path)
        return None

    @classmethod
    def _parse_file(cls, path: Path) -> dict:
        """Parse a YAML or JSON config file."""
        text = path.read_text()

        if path.suffix in (".yaml", ".yml"):
            # Simple YAML parser (key: value per line, no nesting needed)
            data = {}
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip()
                    value = value.strip()
                    # Strip inline comments
                    if " #" in value:
                        value = value[: value.index(" #")].strip()
                    # Remove quotes
                    if value.startswith(("'", '"')) and value.endswith(("'", '"')):
                        value = value[1:-1]
                    data[key] = value
            return data

        # JSON
        return json.loads(text)

    @classmethod
    def _apply_file_data(
        cls, config: "FieldMemoryConfig", data: dict
    ) -> "FieldMemoryConfig":
        """Apply file values to config."""
        field_map = {
            "store_path": str,
            "spatial_tolerance": float,
            "spatial_weight": float,
            "name_weight": float,
            "similarity_threshold": float,
            "min_spatial_score": float,
            "min_structural_score": float,
            "drift_threshold": float,
            "min_drifting_ratio": float,
            "decay_factor": float,
        }
        for key, cast_fn in field_map.items():
            if key in data:
                try:
                    setattr(config, key, cast_fn(data[key]))
                except (ValueError, TypeError):
                    pass  # Skip invalid values, keep default
        return config

    @classmethod
    def _apply_env_overrides(cls, config: "FieldMemoryConfig") -> "FieldMemoryConfig":
        """Apply FIELD_MEMORY_* environment variable overrides."""
        env_map = {
            "FIELD_MEMORY_STORE_PATH": ("store_path", str),
            "FIELD_MEMORY_SPATIAL_TOLERANCE": ("spatial_tolerance", float),
            "FIELD_MEMORY_SPATIAL_WEIGHT": ("spatial_weight", float),
            "FIELD_MEMORY_NAME_WEIGHT": ("name_weight", float),
            "FIELD_MEMORY_SIMILARITY_THRESHOLD": ("similarity_threshold", float),
            "FIELD_MEMORY_MIN_SPATIAL_SCORE": ("min_spatial_score", float),
            "FIELD_MEMORY_MIN_STRUCTURAL_SCORE": ("min_structural_score", float),
            "FIELD_MEMORY_DRIFT_THRESHOLD": ("drift_threshold", float),
            "FIELD_MEMORY_MIN_DRIFTING_RATIO": ("min_drifting_ratio", float),
            "FIELD_MEMORY_DECAY_FACTOR": ("decay_factor", float),
        }
        for env_var, (attr, cast_fn) in env_map.items():
            value = os.environ.get(env_var)
            if value is not None:
                try:
                    setattr(config, attr, cast_fn(value))
                except (ValueError, TypeError):
                    pass
        return config

    def to_dict(self) -> dict:
        """Export config as dictionary."""
        return {
            "store_path": self.store_path,
            "spatial_tolerance": self.spatial_tolerance,
            "spatial_weight": self.spatial_weight,
            "name_weight": self.name_weight,
            "similarity_threshold": self.similarity_threshold,
            "min_spatial_score": self.min_spatial_score,
            "min_structural_score": self.min_structural_score,
            "drift_threshold": self.drift_threshold,
            "min_drifting_ratio": self.min_drifting_ratio,
            "decay_factor": self.decay_factor,
        }
