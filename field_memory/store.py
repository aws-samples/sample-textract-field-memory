# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Template persistence store. Saves/loads FieldLocationMaps as JSON files."""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional

from field_memory.models import FieldLocationMap

logger = logging.getLogger(__name__)


def _sanitize_template_id(template_id: str) -> str:
    """Make template_id filesystem-safe."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", template_id)


class TemplateStore:
    """Persists and retrieves FieldLocationMap data as JSON files."""

    def __init__(self, store_path: Path):
        self._cache: Dict[str, FieldLocationMap] = {}
        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)
        if not self.store_path.is_dir():
            raise OSError(f"Store path is not a directory: {self.store_path}")
        test_file = self.store_path / ".write_test"
        try:
            test_file.touch()
            test_file.unlink()
        except OSError as e:
            raise OSError(f"Store path is not writable: {self.store_path}") from e

    def _get_filepath(self, template_id: str) -> Path:
        return self.store_path / f"{_sanitize_template_id(template_id)}.json"

    def save(self, template_id: str, field_location_map: FieldLocationMap) -> None:
        filepath = self._get_filepath(template_id)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(field_location_map.to_dict(), f, indent=2, ensure_ascii=False)
        self._cache.pop(template_id, None)  # invalidate

    def load(self, template_id: str) -> Optional[FieldLocationMap]:
        if template_id in self._cache:
            return self._cache[template_id]
        filepath = self._get_filepath(template_id)
        if not filepath.exists():
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            field_location_map = FieldLocationMap.from_dict(data)
            self._cache[template_id] = field_location_map
            return field_location_map
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            logger.warning("Failed to load template '%s': %s", template_id, e)
            return None

    def load_all(self) -> List[FieldLocationMap]:
        results: List[FieldLocationMap] = []
        for filepath in sorted(self.store_path.glob("*.json")):
            if filepath.stem.startswith("cluster_"):
                continue
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                field_location_map = FieldLocationMap.from_dict(data)
                self._cache[field_location_map.template_id] = field_location_map
                results.append(field_location_map)
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                logger.warning("Skipping malformed template '%s': %s", filepath, e)
        return results

    def delete(self, template_id: str) -> None:
        self._cache.pop(template_id, None)  # invalidate cache
        try:
            self._get_filepath(template_id).unlink()
        except FileNotFoundError:
            pass

    def exists(self, template_id: str) -> bool:
        return self._get_filepath(template_id).exists()

    def list_templates(self) -> List[str]:
        return [
            fp.stem
            for fp in sorted(self.store_path.glob("*.json"))
            if not fp.stem.startswith("cluster_")
        ]

    def clear_cache(self) -> None:
        """Remove all cached entries."""
        self._cache.clear()
