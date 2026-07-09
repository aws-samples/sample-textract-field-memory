# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""TemplateMemory facade — main entry point for field location memory."""

import datetime
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from field_memory.analytics import (
    SystemSummary,
    TemplateAnalytics,
    TemplateHealthReport,
)
from field_memory.batch import BatchProcessor, BatchResult
from field_memory.cluster_models import ClusterStats, MembershipRecord
from field_memory.cluster_store import ClusterStore
from field_memory.cluster_tracker import ClusterTracker
from field_memory.config import FieldMemoryConfig
from field_memory.drift import DriftDetector, DriftReport
from field_memory.export import TemplateExporter
from field_memory.identifier import TemplateIdentifier, TemplateMatch
from field_memory.matcher import FieldMatch, SpatialMatcher
from field_memory.models import FieldLocationMap, FieldRegion
from field_memory.store import TemplateStore


class TemplateMemory:  # pylint: disable=too-many-instance-attributes
    """Main interface for field location memory.

    Records templates from documents and uses them for spatial field lookup.

    Args:
        store_path: Directory for template JSON files. Default: ~/.field_memory/templates
        spatial_tolerance: Position tolerance (0.05 = 5%). Default: 0.05
        similarity_threshold: Min score to match a template. Default: 0.7
        spatial_weight: Weight for spatial scoring. Default: 0.6
        name_weight: Weight for name matching. Default: 0.4
        decay_factor: Decay factor for confidence weighting. Default: 0.95
        drift_threshold: Threshold for drift detection. Default: 0.03
    """

    def __init__(  # pylint: disable=too-many-positional-arguments
        self,
        store_path: Path = Path.home() / ".field_memory" / "templates",
        spatial_tolerance: float = 0.05,
        similarity_threshold: float = 0.7,
        spatial_weight: float = 0.6,
        name_weight: float = 0.4,
        decay_factor: float = 0.95,
        drift_threshold: float = 0.03,
    ):
        self.store = TemplateStore(store_path)
        self.identifier = TemplateIdentifier(
            similarity_threshold,
            spatial_weight=spatial_weight,
            name_weight=name_weight,
        )
        self.matcher = SpatialMatcher(spatial_tolerance, spatial_weight, name_weight)
        self.spatial_tolerance = spatial_tolerance
        self.decay_factor = decay_factor
        self.drift_threshold = drift_threshold

        # Cluster tracking subsystem
        self._cluster_store = ClusterStore(store_path)
        self._cluster_tracker = ClusterTracker(self._cluster_store)

        # Analytics, drift, batch, and export subsystems
        self._analytics = TemplateAnalytics(self.store)
        self._drift_detector = DriftDetector(drift_threshold, min_drifting_ratio=0.2)
        self._batch_processor = BatchProcessor(self)
        self._exporter = TemplateExporter(self.store)

    @classmethod
    def from_config(
        cls,
        config: Optional["FieldMemoryConfig"] = None,
        config_path: Optional[str] = None,
    ) -> "TemplateMemory":
        """Create TemplateMemory from a config object or file.

        Args:
            config: A FieldMemoryConfig instance. If None, auto-loads from file/env.
            config_path: Path to config file. Only used if config is None.

        Returns:
            Configured TemplateMemory instance.

        Example:
            # Auto-discover config file
            memory = TemplateMemory.from_config()

            # From explicit path
            memory = TemplateMemory.from_config(config_path="./my_config.yaml")

            # From config object
            cfg = FieldMemoryConfig(spatial_weight=0.8, drift_threshold=0.02)
            memory = TemplateMemory.from_config(cfg)
        """
        if config is None:
            config = FieldMemoryConfig.load(config_path)
        return cls(
            store_path=Path(config.store_path),
            spatial_tolerance=config.spatial_tolerance,
            similarity_threshold=config.similarity_threshold,
            spatial_weight=config.spatial_weight,
            name_weight=config.name_weight,
            decay_factor=config.decay_factor,
            drift_threshold=config.drift_threshold,
        )

    def record(  # pylint: disable=too-many-branches
        self,
        document: Any,
        template_id: Optional[str] = None,
        doc_id: Optional[str] = None,
    ) -> str:
        """Record field locations from a processed document.

        The document must have: document.pages[].key_values[]
        Each key_value must have: .key (list with .text), .bbox (.x,.y,.width,.height), .page

        Args:
            document: A processed document with pages and key-value fields.
            template_id: Optional explicit template to assign the document to.
            doc_id: Optional document identifier. Auto-generates UUID4 if None.

        Returns the template_id used.
        Raises ValueError if document has no key-value fields.
        """
        # Auto-generate doc_id if not provided
        doc_id = doc_id or str(uuid.uuid4())

        key_values = []
        for page in document.pages:
            for kv in page.key_values:
                key_values.append(kv)

        if not key_values:
            raise ValueError("No key-value fields found in document")

        now_ts = datetime.datetime.utcnow().isoformat() + "Z"
        field_location_map = FieldLocationMap(
            template_id="placeholder",
            page_count=len(document.pages),
            created_at=now_ts,
        )

        for kv in key_values:
            key_text = " ".join([w.text for w in kv.key]).strip()
            if not key_text:
                continue
            bbox_dict = {
                "x": kv.bbox.x,
                "y": kv.bbox.y,
                "width": kv.bbox.width,
                "height": kv.bbox.height,
            }
            region = FieldRegion(
                field_name=key_text,
                page=kv.page,
                bbox=bbox_dict,
                confidence=kv.confidence if hasattr(kv, "confidence") else 1.0,
            )
            field_location_map.add_field(key_text, region)

        if template_id is not None:
            existing = self.store.load(template_id)
            if existing is not None:
                field_location_map.template_id = template_id
                existing.merge(
                    field_location_map, self.spatial_tolerance, self.decay_factor
                )
                self.store.save(template_id, existing)
            else:
                field_location_map.template_id = template_id
                self.store.save(template_id, field_location_map)
            # Explicit template_id → confidence = 1.0
            self._cluster_tracker.track_membership(doc_id, template_id, confidence=1.0)
        else:
            stored_templates = self.store.load_all()
            match = self.identifier.identify(document, stored_templates)
            if match is not None:
                template_id = match.template_id
                field_location_map.template_id = template_id
                existing = self.store.load(template_id)
                if existing is not None:
                    existing.merge(
                        field_location_map,
                        self.spatial_tolerance,
                        self.decay_factor,
                    )
                    self.store.save(template_id, existing)
                else:
                    self.store.save(template_id, field_location_map)
                # Matched template → confidence = match.similarity_score
                self._cluster_tracker.track_membership(
                    doc_id, template_id, confidence=match.similarity_score
                )
            else:
                template_id = self.identifier.compute_signature(document)
                field_location_map.template_id = template_id
                self.store.save(template_id, field_location_map)
                # New template (no prior match) → confidence = 1.0
                self._cluster_tracker.track_membership(
                    doc_id, template_id, confidence=1.0
                )

        return template_id

    def locate(
        self, document: Any, field_name: str, page: Optional[int] = None
    ) -> List[FieldMatch]:
        """Locate a field using spatial memory. Returns [] if no template matches."""
        stored_templates = self.store.load_all()
        match = self.identifier.identify(document, stored_templates)
        if match is None:
            return []
        field_location_map = self.store.load(match.template_id)
        if field_location_map is None:
            return []
        return self.matcher.find_field(field_name, document, field_location_map, page)

    def identify_template(self, document: Any) -> Optional[TemplateMatch]:
        """Identify which stored template best matches the document."""
        return self.identifier.identify(document, self.store.load_all())

    def get_template(self, template_id: str) -> Optional[FieldLocationMap]:
        """Load a stored template."""
        return self.store.load(template_id)

    def list_templates(self) -> List[str]:
        """List all stored template IDs."""
        return self.store.list_templates()

    def delete_template(self, template_id: str) -> None:
        """Delete a stored template and its associated cluster membership data."""
        self.store.delete(template_id)
        self._cluster_store.delete_cluster(template_id)

    # --- Cluster tracking query methods ---

    def get_cluster_members(
        self,
        template_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[MembershipRecord]:
        """Query documents belonging to a template cluster with pagination.

        Args:
            template_id: The template cluster to query.
            limit: Maximum number of records to return. None for all.
            offset: Number of records to skip from the start.

        Returns:
            List of MembershipRecords in insertion order (oldest first).

        Raises:
            ValueError: If limit is non-positive or offset is negative.
        """
        return self._cluster_tracker.get_members(template_id, limit, offset)

    def get_cluster_stats(self, template_id: str) -> ClusterStats:
        """Get aggregate statistics for a template cluster.

        Args:
            template_id: The template cluster to compute stats for.

        Returns:
            ClusterStats with member count, confidence stats, and timestamps.
        """
        return self._cluster_tracker.get_stats(template_id)

    def get_document_history(self, doc_id: str) -> List[MembershipRecord]:
        """Look up all cluster assignments for a specific document.

        Args:
            doc_id: The document identifier to search for.

        Returns:
            List of MembershipRecords sorted by recorded_at ascending.
        """
        return self._cluster_tracker.get_document_history(doc_id)

    def remove_cluster_member(self, template_id: str, doc_id: str) -> bool:
        """Remove a specific document from a template cluster.

        Args:
            template_id: The template cluster to remove from.
            doc_id: The document identifier to remove.

        Returns:
            True if the document was found and removed, False otherwise.
        """
        return self._cluster_tracker.remove_member(template_id, doc_id)

    # --- Analytics methods ---

    def get_stats(self, template_id: str) -> TemplateHealthReport:
        """Get health statistics for a template.

        Args:
            template_id: The template to analyze.

        Returns:
            TemplateHealthReport with computed statistics.

        Raises:
            ValueError: If the template_id does not exist.
        """
        return self._analytics.get_template_stats(template_id)

    def get_field_stability(self, template_id: str) -> Dict[str, float]:
        """Get per-field stability scores for a template.

        Args:
            template_id: The template to analyze.

        Returns:
            Dictionary mapping field names to stability scores in [0.0, 1.0].

        Raises:
            ValueError: If the template_id does not exist.
        """
        return self._analytics.get_field_stability(template_id)

    def get_system_summary(self) -> SystemSummary:
        """Get aggregate statistics across all stored templates.

        Returns:
            SystemSummary with counts, grades, and rankings.
        """
        return self._analytics.get_system_summary()

    # --- Drift detection ---

    def detect_drift(self, document: Any, template_id: str) -> DriftReport:
        """Detect positional drift of document fields against a stored template.

        Args:
            document: A document object with pages[].key_values[].
            template_id: The template to compare against.

        Returns:
            DriftReport with per-field drift scores and new/missing fields.

        Raises:
            ValueError: If the template_id does not exist.
        """
        template = self.store.load(template_id)
        if template is None:
            raise ValueError(f"Template not found: {template_id}")
        return self._drift_detector.detect(document, template)

    # --- Batch processing ---

    def batch_record(
        self, documents: List[Any], template_id: Optional[str] = None
    ) -> BatchResult:
        """Process multiple documents in a single call with error isolation.

        Args:
            documents: List of document objects to process.
            template_id: Optional template_id to use for all documents.

        Returns:
            BatchResult with counts and per-document results.
        """
        return self._batch_processor.record_batch(documents, template_id)

    # --- Export/Import ---

    def export_template(self, template_id: str, fmt: str = "json") -> Any:
        """Export a template in the specified format.

        Args:
            template_id: The template to export.
            fmt: Export format - "json" or "csv".

        Returns:
            Dict for JSON format, string for CSV format.

        Raises:
            ValueError: If template not found or unsupported format.
        """
        if fmt == "json":
            return self._exporter.export_json(template_id)
        if fmt == "csv":
            return self._exporter.export_csv(template_id)
        raise ValueError(f"Unsupported format: {fmt}")

    def import_template(self, data: Dict[str, Any]) -> str:
        """Import a template from a JSON dictionary.

        Args:
            data: Dictionary containing template data.

        Returns:
            The template_id of the imported template.

        Raises:
            ValueError: If the data is invalid.
        """
        return self._exporter.import_json(data)
