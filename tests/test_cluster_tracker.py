# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for ClusterTracker methods.

Tests cover:
- track_membership creates correct records with timestamp and confidence
- track_membership generates ISO 8601 UTC timestamp in recorded_at
- get_members returns results in insertion order
- get_members with limit/offset paginates correctly
- get_members returns empty list for non-existent cluster
- get_stats returns zero-valued stats for empty cluster
- get_stats computes correct member_count, mean/min/max confidence, oldest/newest
- get_document_history finds records across multiple clusters
- get_document_history returns empty list for unknown doc_id
- get_document_history results are sorted by recorded_at ascending
- remove_member returns True when record exists and removes it
- remove_member returns False when record doesn't exist
- remove_member returns False for non-existent cluster
"""

import time
from datetime import datetime, timezone

from field_memory.cluster_models import ClusterStats, MembershipRecord
from field_memory.cluster_store import ClusterStore
from field_memory.cluster_tracker import ClusterTracker


def _make_tracker(tmp_path) -> ClusterTracker:
    """Helper to create a ClusterTracker with an isolated ClusterStore."""
    store = ClusterStore(tmp_path)
    return ClusterTracker(store)


class TestTrackMembership:
    """Test track_membership creates correct records."""

    def test_creates_record_with_correct_fields(self, tmp_path):
        """track_membership creates a MembershipRecord with correct doc_id, template_id, confidence."""
        tracker = _make_tracker(tmp_path)

        record = tracker.track_membership(
            doc_id="invoice-001",
            template_id="template-a",
            confidence=0.87,
        )

        assert record.doc_id == "invoice-001"
        assert record.template_id == "template-a"
        assert record.confidence == 0.87
        assert record.metadata is None

    def test_creates_record_with_metadata(self, tmp_path):
        """track_membership includes metadata when provided."""
        tracker = _make_tracker(tmp_path)

        record = tracker.track_membership(
            doc_id="doc-1",
            template_id="tmpl-x",
            confidence=0.95,
            metadata={"source": "scanner", "batch": "B01"},
        )

        assert record.metadata == {"source": "scanner", "batch": "B01"}

    def test_generates_iso8601_utc_timestamp(self, tmp_path):
        """track_membership generates a valid ISO 8601 UTC timestamp in recorded_at."""
        tracker = _make_tracker(tmp_path)

        before = datetime.now(timezone.utc)
        record = tracker.track_membership(
            doc_id="doc-ts",
            template_id="tmpl-ts",
            confidence=0.5,
        )
        after = datetime.now(timezone.utc)

        # Verify ISO 8601 format with Z suffix
        assert record.recorded_at.endswith("Z")

        # Parse the timestamp and verify it's within the expected window
        ts_str = record.recorded_at.rstrip("Z")
        recorded_dt = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
        assert before <= recorded_dt <= after

    def test_confidence_one_for_explicit_assignment(self, tmp_path):
        """track_membership stores confidence=1.0 correctly for explicit assignments."""
        tracker = _make_tracker(tmp_path)

        record = tracker.track_membership(
            doc_id="doc-explicit",
            template_id="explicit-tmpl",
            confidence=1.0,
        )

        assert record.confidence == 1.0

    def test_persists_record_to_store(self, tmp_path):
        """track_membership persists the record so it can be retrieved later."""
        tracker = _make_tracker(tmp_path)

        tracker.track_membership(
            doc_id="persisted-doc",
            template_id="persist-tmpl",
            confidence=0.72,
        )

        members = tracker.get_members("persist-tmpl")
        assert len(members) == 1
        assert members[0].doc_id == "persisted-doc"


class TestGetMembers:
    """Test get_members returns results in insertion order with pagination."""

    def test_returns_records_in_insertion_order(self, tmp_path):
        """get_members returns records in the order they were inserted (oldest first)."""
        tracker = _make_tracker(tmp_path)

        tracker.track_membership("doc-a", "cluster-1", 0.9)
        tracker.track_membership("doc-b", "cluster-1", 0.8)
        tracker.track_membership("doc-c", "cluster-1", 0.7)

        members = tracker.get_members("cluster-1")

        assert len(members) == 3
        assert members[0].doc_id == "doc-a"
        assert members[1].doc_id == "doc-b"
        assert members[2].doc_id == "doc-c"

    def test_pagination_with_limit(self, tmp_path):
        """get_members with limit returns at most limit records."""
        tracker = _make_tracker(tmp_path)

        for i in range(5):
            tracker.track_membership(f"doc-{i}", "cluster-pg", 0.5)

        result = tracker.get_members("cluster-pg", limit=3)

        assert len(result) == 3
        assert result[0].doc_id == "doc-0"
        assert result[1].doc_id == "doc-1"
        assert result[2].doc_id == "doc-2"

    def test_pagination_with_offset(self, tmp_path):
        """get_members with offset skips the first offset records."""
        tracker = _make_tracker(tmp_path)

        for i in range(5):
            tracker.track_membership(f"doc-{i}", "cluster-pg", 0.5)

        result = tracker.get_members("cluster-pg", offset=2)

        assert len(result) == 3
        assert result[0].doc_id == "doc-2"
        assert result[1].doc_id == "doc-3"
        assert result[2].doc_id == "doc-4"

    def test_pagination_with_limit_and_offset(self, tmp_path):
        """get_members with limit and offset returns the correct slice."""
        tracker = _make_tracker(tmp_path)

        for i in range(10):
            tracker.track_membership(f"doc-{i}", "cluster-pg", 0.5)

        result = tracker.get_members("cluster-pg", limit=3, offset=4)

        assert len(result) == 3
        assert result[0].doc_id == "doc-4"
        assert result[1].doc_id == "doc-5"
        assert result[2].doc_id == "doc-6"

    def test_returns_empty_list_for_nonexistent_cluster(self, tmp_path):
        """get_members returns an empty list for a template_id with no cluster data."""
        tracker = _make_tracker(tmp_path)

        result = tracker.get_members("nonexistent-template")

        assert result == []


class TestGetStats:
    """Test get_stats returns accurate aggregate statistics."""

    def test_returns_zero_stats_for_empty_cluster(self, tmp_path):
        """get_stats returns zero-valued stats for a cluster with no data."""
        tracker = _make_tracker(tmp_path)

        stats = tracker.get_stats("empty-cluster")

        assert stats.template_id == "empty-cluster"
        assert stats.member_count == 0
        assert stats.oldest_record is None
        assert stats.newest_record is None
        assert stats.mean_confidence == 0.0
        assert stats.min_confidence == 0.0
        assert stats.max_confidence == 0.0

    def test_computes_correct_stats_for_single_record(self, tmp_path):
        """get_stats computes correct stats for a cluster with one record."""
        tracker = _make_tracker(tmp_path)

        tracker.track_membership("doc-only", "single-cluster", 0.85)

        stats = tracker.get_stats("single-cluster")

        assert stats.template_id == "single-cluster"
        assert stats.member_count == 1
        assert stats.mean_confidence == 0.85
        assert stats.min_confidence == 0.85
        assert stats.max_confidence == 0.85
        assert stats.oldest_record is not None
        assert stats.newest_record is not None
        assert stats.oldest_record == stats.newest_record

    def test_computes_correct_member_count_and_confidence(self, tmp_path):
        """get_stats computes correct member_count, mean/min/max confidence, oldest/newest."""
        tracker = _make_tracker(tmp_path)

        # Insert multiple records with different confidences
        tracker.track_membership("doc-1", "stats-cluster", 0.6)
        time.sleep(0.01)  # Ensure different timestamps
        tracker.track_membership("doc-2", "stats-cluster", 0.8)
        time.sleep(0.01)
        tracker.track_membership("doc-3", "stats-cluster", 1.0)

        stats = tracker.get_stats("stats-cluster")

        assert stats.member_count == 3
        # mean = (0.6 + 0.8 + 1.0) / 3 = 0.8
        assert abs(stats.mean_confidence - 0.8) < 1e-9
        assert stats.min_confidence == 0.6
        assert stats.max_confidence == 1.0
        # oldest is the first record, newest is the last
        assert stats.oldest_record is not None
        assert stats.newest_record is not None
        assert stats.oldest_record <= stats.newest_record

    def test_confidence_bounds_invariant(self, tmp_path):
        """get_stats satisfies min <= mean <= max for any cluster."""
        tracker = _make_tracker(tmp_path)

        tracker.track_membership("doc-low", "bounds-cluster", 0.2)
        tracker.track_membership("doc-mid", "bounds-cluster", 0.5)
        tracker.track_membership("doc-high", "bounds-cluster", 0.9)

        stats = tracker.get_stats("bounds-cluster")

        assert stats.min_confidence <= stats.mean_confidence <= stats.max_confidence


class TestGetDocumentHistory:
    """Test get_document_history finds records across multiple clusters."""

    def test_finds_records_across_multiple_clusters(self, tmp_path):
        """get_document_history returns all records for a doc_id across clusters."""
        tracker = _make_tracker(tmp_path)

        tracker.track_membership("shared-doc", "cluster-alpha", 0.9)
        time.sleep(0.01)
        tracker.track_membership("shared-doc", "cluster-beta", 0.75)
        time.sleep(0.01)
        tracker.track_membership("shared-doc", "cluster-gamma", 0.85)
        # Other docs shouldn't appear
        tracker.track_membership("other-doc", "cluster-alpha", 0.5)

        history = tracker.get_document_history("shared-doc")

        assert len(history) == 3
        template_ids = [r.template_id for r in history]
        assert "cluster-alpha" in template_ids
        assert "cluster-beta" in template_ids
        assert "cluster-gamma" in template_ids
        # Ensure no other doc_ids included
        for record in history:
            assert record.doc_id == "shared-doc"

    def test_returns_empty_list_for_unknown_doc_id(self, tmp_path):
        """get_document_history returns an empty list for a doc_id not in any cluster."""
        tracker = _make_tracker(tmp_path)

        # Add some data so clusters exist
        tracker.track_membership("existing-doc", "some-cluster", 0.9)

        history = tracker.get_document_history("unknown-doc-id")

        assert history == []

    def test_results_sorted_by_recorded_at_ascending(self, tmp_path):
        """get_document_history results are sorted by recorded_at in ascending order."""
        tracker = _make_tracker(tmp_path)

        # Record into multiple clusters with small delays for distinct timestamps
        tracker.track_membership("sorted-doc", "cluster-z", 0.6)
        time.sleep(0.01)
        tracker.track_membership("sorted-doc", "cluster-a", 0.7)
        time.sleep(0.01)
        tracker.track_membership("sorted-doc", "cluster-m", 0.8)

        history = tracker.get_document_history("sorted-doc")

        assert len(history) == 3
        timestamps = [r.recorded_at for r in history]
        assert timestamps == sorted(timestamps)


class TestRemoveMember:
    """Test remove_member returns True/False correctly and removes records."""

    def test_returns_true_and_removes_record(self, tmp_path):
        """remove_member returns True when the record exists and removes it."""
        tracker = _make_tracker(tmp_path)

        tracker.track_membership("doc-to-remove", "rm-cluster", 0.9)
        tracker.track_membership("doc-to-keep", "rm-cluster", 0.8)

        result = tracker.remove_member("rm-cluster", "doc-to-remove")

        assert result is True
        members = tracker.get_members("rm-cluster")
        assert len(members) == 1
        assert members[0].doc_id == "doc-to-keep"

    def test_returns_false_when_doc_not_in_cluster(self, tmp_path):
        """remove_member returns False when doc_id doesn't exist in the cluster."""
        tracker = _make_tracker(tmp_path)

        tracker.track_membership("existing-doc", "rm-cluster", 0.9)

        result = tracker.remove_member("rm-cluster", "nonexistent-doc")

        assert result is False
        # Cluster unchanged
        members = tracker.get_members("rm-cluster")
        assert len(members) == 1
        assert members[0].doc_id == "existing-doc"

    def test_returns_false_for_nonexistent_cluster(self, tmp_path):
        """remove_member returns False for a cluster that doesn't exist."""
        tracker = _make_tracker(tmp_path)

        result = tracker.remove_member("no-such-cluster", "any-doc")

        assert result is False

    def test_removed_doc_not_in_document_history(self, tmp_path):
        """After removal, get_document_history no longer includes the removed record."""
        tracker = _make_tracker(tmp_path)

        tracker.track_membership("doc-hist", "cluster-1", 0.9)
        tracker.track_membership("doc-hist", "cluster-2", 0.8)

        # Remove from cluster-1
        tracker.remove_member("cluster-1", "doc-hist")

        history = tracker.get_document_history("doc-hist")
        # Only the cluster-2 record should remain
        assert len(history) == 1
        assert history[0].template_id == "cluster-2"
