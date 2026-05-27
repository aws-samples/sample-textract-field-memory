# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Cluster membership persistence store.

Stores one JSON file per template cluster, following the same pattern as
TemplateStore. Files are named cluster_{sanitized_template_id}.json and
stored in the same directory as template files.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from field_memory.cluster_models import ClusterData, MembershipRecord
from field_memory.store import _sanitize_template_id

logger = logging.getLogger(__name__)


class ClusterStore:
    """Persists and retrieves cluster membership data as JSON files."""

    def __init__(self, store_path: Path) -> None:
        """Initialize the ClusterStore.

        Args:
            store_path: Directory path where cluster JSON files are stored.
                       This should be the same store_path used by TemplateStore.
        """
        self._cache: Dict[str, ClusterData] = {}
        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)

    def _get_filepath(self, template_id: str) -> Path:
        """Get the filesystem path for a cluster file.

        Args:
            template_id: The template identifier.

        Returns:
            Path to the cluster JSON file.
        """
        return self.store_path / f"cluster_{_sanitize_template_id(template_id)}.json"

    def save_cluster(self, template_id: str, cluster: ClusterData) -> None:
        """Serialize and save ClusterData to a JSON file.

        Args:
            template_id: The template identifier.
            cluster: The ClusterData to persist.
        """
        filepath = self._get_filepath(template_id)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(cluster.to_dict(), f, indent=2, ensure_ascii=False)
        self._cache[template_id] = cluster

    def append_record(self, template_id: str, record: MembershipRecord) -> None:
        """Append a membership record to the cluster file.

        Loads the existing ClusterData for the template (or creates a new one
        if none exists), appends the record, updates timestamps, and saves.

        - Sets `created_at` on first record insertion only.
        - Updates `updated_at` on every insertion.

        Args:
            template_id: The template identifier.
            record: The MembershipRecord to append.
        """
        cluster = self.load_cluster(template_id)

        if cluster is None:
            cluster = ClusterData(
                template_id=template_id,
                records=[],
                created_at=record.recorded_at,
                updated_at=record.recorded_at,
            )

        cluster.records.append(record)
        cluster.updated_at = record.recorded_at
        self.save_cluster(template_id, cluster)

    def load_cluster(self, template_id: str) -> Optional[ClusterData]:
        """Load ClusterData from a JSON file.

        Args:
            template_id: The template identifier.

        Returns:
            ClusterData if the file exists and is valid JSON, None otherwise.
            Logs a warning if the file is malformed.
        """
        if template_id in self._cache:
            return self._cache[template_id]
        filepath = self._get_filepath(template_id)
        if not filepath.exists():
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            cluster = ClusterData.from_dict(data)
            self._cache[template_id] = cluster
            return cluster
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            logger.warning("Failed to load cluster '%s': %s", template_id, e)
            return None

    def delete_cluster(self, template_id: str) -> None:
        """Remove a cluster JSON file.

        Args:
            template_id: The template identifier whose cluster file to delete.
        """
        self._cache.pop(template_id, None)
        try:
            self._get_filepath(template_id).unlink()
        except FileNotFoundError:
            pass

    def list_clusters(self) -> List[str]:
        """List all template_ids that have cluster files.

        Globs for cluster_*.json files and extracts template_ids by
        stripping the 'cluster_' prefix and '.json' suffix.

        Returns:
            List of template_ids (sanitized form) that have cluster data.
        """
        results: List[str] = []
        for filepath in sorted(self.store_path.glob("cluster_*.json")):
            # Strip "cluster_" prefix and ".json" suffix to get the sanitized template_id
            stem = filepath.stem  # e.g., "cluster_my_template"
            template_id = stem[len("cluster_") :]  # e.g., "my_template"
            if template_id:
                results.append(template_id)
        return results

    def clear_cache(self) -> None:
        """Remove all cached entries."""
        self._cache.clear()
