# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Data models for the Document Cluster Tracking system.

This module defines the core data structures used to track document-to-template
cluster membership, including membership records, cluster data, and statistics.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MembershipRecord:
    """A record of a single document's assignment to a template cluster.

    Attributes:
        doc_id: Unique identifier for the document (user-provided or auto-generated UUID4).
        template_id: The template this document was assigned to.
        recorded_at: ISO 8601 timestamp of when the document was recorded.
        confidence: Match confidence score when assigned (0.0-1.0).
                   1.0 for explicit template_id assignment.
        metadata: Optional user-provided key-value metadata (e.g., source filename).
                  Maximum 20 key-value pairs if provided.
    """

    doc_id: str
    template_id: str
    recorded_at: str
    confidence: float
    metadata: Optional[Dict[str, str]] = None

    def __post_init__(self):
        """Validate all fields after initialization."""
        if not isinstance(self.doc_id, str) or not self.doc_id:
            raise ValueError(f"doc_id must be a non-empty string, got: {self.doc_id!r}")
        if not isinstance(self.template_id, str) or not self.template_id:
            raise ValueError(
                f"template_id must be a non-empty string, got: {self.template_id!r}"
            )
        if not isinstance(self.confidence, (int, float)):
            raise ValueError(
                f"confidence must be a float in [0.0, 1.0], got: {self.confidence!r}"
            )
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got: {self.confidence}"
            )
        if self.metadata is not None:
            if not isinstance(self.metadata, dict):
                raise ValueError(
                    f"metadata must be a dict or None, got: {type(self.metadata).__name__}"
                )
            if len(self.metadata) > 20:
                raise ValueError(
                    f"metadata cannot exceed 20 keys, got: {len(self.metadata)}"
                )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this record to a dictionary for JSON persistence.

        Returns:
            Dictionary containing all field values.
        """
        return {
            "doc_id": self.doc_id,
            "template_id": self.template_id,
            "recorded_at": self.recorded_at,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MembershipRecord":
        """Reconstruct a MembershipRecord from a dictionary.

        Args:
            data: Dictionary containing record field values.

        Returns:
            A new MembershipRecord instance with all field values preserved.
        """
        return cls(
            doc_id=data["doc_id"],
            template_id=data["template_id"],
            recorded_at=data["recorded_at"],
            confidence=data["confidence"],
            metadata=data.get("metadata"),
        )


@dataclass
class ClusterData:
    """Persistent storage model for all membership records in a template cluster.

    Attributes:
        template_id: The template this cluster belongs to.
        records: Ordered list of membership records (oldest first).
        created_at: ISO timestamp when first record was added.
        updated_at: ISO timestamp when last record was added.
    """

    template_id: str
    records: List[MembershipRecord] = field(default_factory=list)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def __post_init__(self):
        """Validate fields after initialization."""
        if not isinstance(self.template_id, str) or not self.template_id:
            raise ValueError(
                f"template_id must be a non-empty string, got: {self.template_id!r}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize this cluster data to a dictionary for JSON persistence.

        Returns:
            Dictionary containing all field values, with nested
            MembershipRecords serialized via their to_dict() method.
        """
        return {
            "template_id": self.template_id,
            "records": [record.to_dict() for record in self.records],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClusterData":
        """Reconstruct a ClusterData from a dictionary.

        Args:
            data: Dictionary containing cluster data field values,
                  with nested records as dictionaries.

        Returns:
            A new ClusterData instance with all field values preserved,
            including deserialized MembershipRecords.
        """
        records = [
            MembershipRecord.from_dict(record_data)
            for record_data in data.get("records", [])
        ]
        return cls(
            template_id=data["template_id"],
            records=records,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


@dataclass
class ClusterStats:
    """Computed statistics for a template cluster.

    This is a read-only model representing aggregate statistics computed
    from cluster membership records. It is not persisted directly.

    Attributes:
        template_id: The template this cluster belongs to.
        member_count: Total number of documents in this cluster.
        oldest_record: ISO 8601 timestamp of the first document recorded,
                      or None if the cluster is empty.
        newest_record: ISO 8601 timestamp of the most recent document recorded,
                      or None if the cluster is empty.
        mean_confidence: Average match confidence across all members (0.0 if empty).
        min_confidence: Lowest match confidence in the cluster (0.0 if empty).
        max_confidence: Highest match confidence in the cluster (0.0 if empty).
    """

    template_id: str
    member_count: int
    oldest_record: Optional[str]
    newest_record: Optional[str]
    mean_confidence: float
    min_confidence: float
    max_confidence: float
