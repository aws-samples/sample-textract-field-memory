# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Core logic for tracking document-to-template cluster assignments.

This module provides the ClusterTracker class which manages membership
recording, statistics computation, membership queries, and document
history tracking across template clusters.
"""

import datetime
from typing import Dict, List, Optional

from field_memory.cluster_models import ClusterStats, MembershipRecord
from field_memory.cluster_store import ClusterStore


class ClusterTracker:
    """Tracks document-to-template cluster assignments.

    Provides methods to record new membership entries, compute aggregate
    statistics, query membership with pagination, look up document history
    across clusters, and remove individual membership records.
    """

    def __init__(self, store: ClusterStore) -> None:
        """Initialize the ClusterTracker.

        Args:
            store: The ClusterStore instance used for persisting membership data.
        """
        self._store = store

    def track_membership(
        self,
        doc_id: str,
        template_id: str,
        confidence: float,
        metadata: Optional[Dict[str, str]] = None,
    ) -> MembershipRecord:
        """Record a document's assignment to a template cluster.

        Creates a MembershipRecord with a UTC timestamp and persists it
        to the cluster store. All inputs are validated before any state
        mutation occurs.

        Args:
            doc_id: Unique identifier for the document.
            template_id: The template this document was assigned to.
            confidence: Match confidence score in [0.0, 1.0].
            metadata: Optional key-value metadata (max 20 keys).

        Returns:
            The created MembershipRecord.

        Raises:
            ValueError: If any input is invalid (empty doc_id/template_id,
                       confidence outside [0.0, 1.0], metadata exceeds 20 keys).
        """
        # Step 1: Validate inputs
        if not doc_id or not isinstance(doc_id, str):
            raise ValueError(f"doc_id must be a non-empty string, got: {doc_id!r}")
        if not template_id or not isinstance(template_id, str):
            raise ValueError(
                f"template_id must be a non-empty string, got: {template_id!r}"
            )
        if not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0:
            raise ValueError(f"confidence must be in [0.0, 1.0], got: {confidence}")
        if metadata is not None and len(metadata) > 20:
            raise ValueError(f"metadata cannot exceed 20 keys, got: {len(metadata)}")

        # Step 2: Generate timestamp
        recorded_at = datetime.datetime.utcnow().isoformat() + "Z"

        # Step 3: Create record
        record = MembershipRecord(
            doc_id=doc_id,
            template_id=template_id,
            recorded_at=recorded_at,
            confidence=confidence,
            metadata=metadata,
        )

        # Step 4: Persist
        self._store.append_record(template_id, record)

        # Step 5: Return
        return record

    def remove_member(self, template_id: str, doc_id: str) -> bool:
        """Remove all membership records for a document from a template cluster.

        Filters out all records matching the given doc_id and persists the
        updated cluster. Records not matching doc_id are preserved.

        Args:
            template_id: The template cluster to remove the document from.
            doc_id: The document identifier to remove.

        Returns:
            True if at least one record was removed, False if no matching
            record was found or the cluster doesn't exist.
        """
        cluster = self._store.load_cluster(template_id)

        if cluster is None or not cluster.records:
            return False

        original_length = len(cluster.records)
        cluster.records = [r for r in cluster.records if r.doc_id != doc_id]

        if len(cluster.records) == original_length:
            return False

        self._store.save_cluster(template_id, cluster)
        return True

    def get_stats(self, template_id: str) -> ClusterStats:
        """Compute aggregate statistics for a template cluster.

        Loads the cluster data and computes member count, oldest/newest
        timestamps, and mean/min/max confidence in a single pass through
        the records.

        Args:
            template_id: The template cluster to compute stats for.

        Returns:
            A ClusterStats object with computed aggregates. Returns
            zero-valued stats if the cluster is empty or doesn't exist.
        """
        cluster = self._store.load_cluster(template_id)

        if cluster is None or not cluster.records:
            return ClusterStats(
                template_id=template_id,
                member_count=0,
                oldest_record=None,
                newest_record=None,
                mean_confidence=0.0,
                min_confidence=0.0,
                max_confidence=0.0,
            )

        records = cluster.records
        member_count = len(records)

        # Records are ordered oldest-first
        oldest_record = records[0].recorded_at
        newest_record = records[-1].recorded_at

        # Compute confidence statistics in single pass
        confidence_sum = 0.0
        min_conf = 1.0
        max_conf = 0.0

        for record in records:
            confidence_sum += record.confidence
            min_conf = min(min_conf, record.confidence)
            max_conf = max(max_conf, record.confidence)

        mean_confidence = confidence_sum / member_count

        # Clamp mean to [min, max] to account for floating-point rounding
        mean_confidence = max(min_conf, min(mean_confidence, max_conf))

        return ClusterStats(
            template_id=template_id,
            member_count=member_count,
            oldest_record=oldest_record,
            newest_record=newest_record,
            mean_confidence=mean_confidence,
            min_confidence=min_conf,
            max_confidence=max_conf,
        )

    def get_document_history(self, doc_id: str) -> List[MembershipRecord]:
        """Find all cluster assignments for a specific document across all templates.

        Scans all known clusters for MembershipRecords matching the given doc_id,
        collects them, and returns them sorted by recorded_at in ascending order.

        Args:
            doc_id: The document identifier to search for.

        Returns:
            A list of MembershipRecords matching the doc_id, sorted by
            recorded_at ascending. Returns an empty list if the doc_id
            has never been recorded in any cluster.
        """
        all_matches: List[MembershipRecord] = []

        for cluster_template_id in self._store.list_clusters():
            cluster = self._store.load_cluster(cluster_template_id)
            if cluster is None:
                continue
            for record in cluster.records:
                if record.doc_id == doc_id:
                    all_matches.append(record)

        # Sort by timestamp ascending
        all_matches.sort(key=lambda r: r.recorded_at)
        return all_matches

    def get_members(
        self,
        template_id: str,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[MembershipRecord]:
        """Query cluster members with optional pagination.

        Returns membership records for the given template in insertion order
        (oldest first), with optional limit and offset for pagination.

        Args:
            template_id: The template cluster to query.
            limit: Maximum number of records to return. If None, returns all
                   records from offset onward. Must be positive if provided.
            offset: Number of records to skip from the beginning. Must be
                    non-negative. Defaults to 0.

        Returns:
            List of MembershipRecords in insertion order. Returns an empty
            list if the template_id has no cluster data.

        Raises:
            ValueError: If limit is not positive (when provided) or offset
                       is negative.
        """
        # Validate pagination parameters
        if limit is not None and limit <= 0:
            raise ValueError(f"limit must be a positive integer, got: {limit}")
        if offset < 0:
            raise ValueError(f"offset must be non-negative, got: {offset}")

        # Load cluster data
        cluster = self._store.load_cluster(template_id)
        if cluster is None:
            return []

        # Apply pagination slice
        records = cluster.records
        if limit is None:
            return records[offset:]
        return records[offset : offset + limit]
