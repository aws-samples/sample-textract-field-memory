# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for ClusterStore file operations.

Tests cover:
- save/load roundtrip
- load returns None for non-existent and malformed files
- delete removes files and handles non-existent files gracefully
- list_clusters returns all template_ids
- append_record creates/updates clusters correctly
- caching behavior (hit, invalidation on save/delete, clear_cache)
"""

import json
import logging

from field_memory.cluster_models import ClusterData, MembershipRecord
from field_memory.cluster_store import ClusterStore


def _make_record(
    doc_id: str = "doc-1",
    template_id: str = "template-a",
    recorded_at: str = "2024-01-01T00:00:00Z",
    confidence: float = 0.95,
    metadata=None,
) -> MembershipRecord:
    """Helper to create a MembershipRecord for testing."""
    return MembershipRecord(
        doc_id=doc_id,
        template_id=template_id,
        recorded_at=recorded_at,
        confidence=confidence,
        metadata=metadata,
    )


def _make_cluster(
    template_id: str = "template-a",
    records=None,
    created_at: str = "2024-01-01T00:00:00Z",
    updated_at: str = "2024-01-01T00:00:00Z",
) -> ClusterData:
    """Helper to create a ClusterData for testing."""
    if records is None:
        records = [_make_record(template_id=template_id)]
    return ClusterData(
        template_id=template_id,
        records=records,
        created_at=created_at,
        updated_at=updated_at,
    )


class TestSaveAndLoadRoundtrip:
    """Test save_cluster and load_cluster roundtrip."""

    def test_save_and_load_roundtrip(self, tmp_path):
        """Saving a cluster and loading it back preserves all data."""
        store = ClusterStore(tmp_path)
        cluster = _make_cluster()

        store.save_cluster("template-a", cluster)
        store.clear_cache()  # Force disk read
        loaded = store.load_cluster("template-a")

        assert loaded is not None
        assert loaded.template_id == "template-a"
        assert len(loaded.records) == 1
        assert loaded.records[0].doc_id == "doc-1"
        assert loaded.records[0].confidence == 0.95
        assert loaded.created_at == "2024-01-01T00:00:00Z"
        assert loaded.updated_at == "2024-01-01T00:00:00Z"

    def test_save_and_load_with_metadata(self, tmp_path):
        """Roundtrip preserves record metadata."""
        store = ClusterStore(tmp_path)
        record = _make_record(metadata={"source": "scan", "page": "1"})
        cluster = _make_cluster(records=[record])

        store.save_cluster("template-a", cluster)
        store.clear_cache()
        loaded = store.load_cluster("template-a")

        assert loaded is not None
        assert loaded.records[0].metadata == {"source": "scan", "page": "1"}

    def test_save_and_load_with_none_metadata(self, tmp_path):
        """Roundtrip preserves None metadata."""
        store = ClusterStore(tmp_path)
        record = _make_record(metadata=None)
        cluster = _make_cluster(records=[record])

        store.save_cluster("template-a", cluster)
        store.clear_cache()
        loaded = store.load_cluster("template-a")

        assert loaded is not None
        assert loaded.records[0].metadata is None

    def test_save_and_load_multiple_records(self, tmp_path):
        """Roundtrip preserves multiple records in order."""
        store = ClusterStore(tmp_path)
        records = [
            _make_record(doc_id="doc-1", recorded_at="2024-01-01T00:00:00Z"),
            _make_record(doc_id="doc-2", recorded_at="2024-01-02T00:00:00Z"),
            _make_record(doc_id="doc-3", recorded_at="2024-01-03T00:00:00Z"),
        ]
        cluster = _make_cluster(records=records, updated_at="2024-01-03T00:00:00Z")

        store.save_cluster("template-a", cluster)
        store.clear_cache()
        loaded = store.load_cluster("template-a")

        assert loaded is not None
        assert len(loaded.records) == 3
        assert [r.doc_id for r in loaded.records] == ["doc-1", "doc-2", "doc-3"]


class TestLoadClusterNonExistent:
    """Test load_cluster returns None for non-existent template_id."""

    def test_load_returns_none_for_missing_file(self, tmp_path):
        """Loading a non-existent cluster returns None."""
        store = ClusterStore(tmp_path)
        result = store.load_cluster("does-not-exist")
        assert result is None


class TestLoadClusterMalformedJSON:
    """Test load_cluster returns None for malformed JSON files."""

    def test_load_returns_none_for_invalid_json(self, tmp_path, caplog):
        """Malformed JSON file returns None and logs a warning."""
        store = ClusterStore(tmp_path)
        filepath = store._get_filepath("bad-cluster")
        filepath.write_text("not valid json {{{", encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            result = store.load_cluster("bad-cluster")

        assert result is None
        assert "Failed to load cluster" in caplog.text

    def test_load_returns_none_for_missing_keys(self, tmp_path, caplog):
        """JSON missing required keys returns None and logs a warning."""
        store = ClusterStore(tmp_path)
        filepath = store._get_filepath("incomplete")
        # Valid JSON but missing template_id key
        filepath.write_text(json.dumps({"records": []}), encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            result = store.load_cluster("incomplete")

        assert result is None
        assert "Failed to load cluster" in caplog.text

    def test_load_returns_none_for_invalid_record_data(self, tmp_path, caplog):
        """JSON with invalid record data returns None and logs a warning."""
        store = ClusterStore(tmp_path)
        filepath = store._get_filepath("bad-records")
        data = {
            "template_id": "bad-records",
            "records": [
                {
                    "doc_id": "",
                    "template_id": "x",
                    "recorded_at": "t",
                    "confidence": 0.5,
                }
            ],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        filepath.write_text(json.dumps(data), encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            result = store.load_cluster("bad-records")

        assert result is None
        assert "Failed to load cluster" in caplog.text


class TestDeleteCluster:
    """Test delete_cluster removes the file."""

    def test_delete_removes_file(self, tmp_path):
        """Deleting an existing cluster removes the JSON file."""
        store = ClusterStore(tmp_path)
        cluster = _make_cluster()
        store.save_cluster("template-a", cluster)

        filepath = store._get_filepath("template-a")
        assert filepath.exists()

        store.delete_cluster("template-a")
        assert not filepath.exists()

    def test_delete_nonexistent_does_not_raise(self, tmp_path):
        """Deleting a non-existent cluster doesn't raise an exception."""
        store = ClusterStore(tmp_path)
        # Should not raise
        store.delete_cluster("nonexistent-template")


class TestListClusters:
    """Test list_clusters returns all template_ids."""

    def test_list_clusters_empty_directory(self, tmp_path):
        """Empty store returns empty list."""
        store = ClusterStore(tmp_path)
        assert store.list_clusters() == []

    def test_list_clusters_returns_all_ids(self, tmp_path):
        """Returns all template_ids from stored cluster files."""
        store = ClusterStore(tmp_path)
        store.save_cluster("alpha", _make_cluster(template_id="alpha"))
        store.save_cluster("beta", _make_cluster(template_id="beta"))
        store.save_cluster("gamma", _make_cluster(template_id="gamma"))

        result = store.list_clusters()
        assert sorted(result) == ["alpha", "beta", "gamma"]

    def test_list_clusters_ignores_non_cluster_files(self, tmp_path):
        """Non-cluster JSON files are not included in the list."""
        store = ClusterStore(tmp_path)
        store.save_cluster("my-template", _make_cluster(template_id="my-template"))
        # Create a non-cluster file in the same directory
        (tmp_path / "template_other.json").write_text("{}", encoding="utf-8")

        result = store.list_clusters()
        assert result == ["my-template"]


class TestAppendRecord:
    """Test append_record creates and updates clusters."""

    def test_append_record_creates_cluster_on_first_call(self, tmp_path):
        """First append_record creates a new cluster with created_at set."""
        store = ClusterStore(tmp_path)
        record = _make_record(
            doc_id="first-doc",
            template_id="new-template",
            recorded_at="2024-06-15T10:00:00Z",
        )

        store.append_record("new-template", record)

        loaded = store.load_cluster("new-template")
        assert loaded is not None
        assert len(loaded.records) == 1
        assert loaded.records[0].doc_id == "first-doc"
        assert loaded.created_at == "2024-06-15T10:00:00Z"
        assert loaded.updated_at == "2024-06-15T10:00:00Z"

    def test_append_record_on_existing_cluster(self, tmp_path):
        """Appending to existing cluster adds record and updates updated_at."""
        store = ClusterStore(tmp_path)
        first_record = _make_record(
            doc_id="doc-1",
            template_id="existing",
            recorded_at="2024-01-01T00:00:00Z",
        )
        store.append_record("existing", first_record)

        second_record = _make_record(
            doc_id="doc-2",
            template_id="existing",
            recorded_at="2024-06-15T12:00:00Z",
        )
        store.append_record("existing", second_record)

        loaded = store.load_cluster("existing")
        assert loaded is not None
        assert len(loaded.records) == 2
        assert loaded.records[0].doc_id == "doc-1"
        assert loaded.records[1].doc_id == "doc-2"
        # created_at stays at first record's time
        assert loaded.created_at == "2024-01-01T00:00:00Z"
        # updated_at reflects second record's time
        assert loaded.updated_at == "2024-06-15T12:00:00Z"


class TestCachingBehavior:
    """Test caching: cache hits, invalidation on save/delete, and clear_cache."""

    def test_second_load_returns_cached_object(self, tmp_path):
        """Second load returns same object from cache (cache hit)."""
        store = ClusterStore(tmp_path)
        cluster = _make_cluster()
        store.save_cluster("template-a", cluster)
        store.clear_cache()  # Clear so first load populates cache from disk

        first_load = store.load_cluster("template-a")
        second_load = store.load_cluster("template-a")

        # Same object identity means it came from cache
        assert first_load is second_load

    def test_save_updates_cache(self, tmp_path):
        """Saving a cluster updates the cache entry."""
        store = ClusterStore(tmp_path)
        cluster1 = _make_cluster(records=[_make_record(doc_id="doc-1")])
        store.save_cluster("template-a", cluster1)

        # Save a new version
        cluster2 = _make_cluster(
            records=[_make_record(doc_id="doc-1"), _make_record(doc_id="doc-2")]
        )
        store.save_cluster("template-a", cluster2)

        # Load should get the updated version from cache (no disk read needed)
        loaded = store.load_cluster("template-a")
        assert loaded is not None
        assert len(loaded.records) == 2

    def test_delete_invalidates_cache(self, tmp_path):
        """Deleting a cluster removes it from cache."""
        store = ClusterStore(tmp_path)
        cluster = _make_cluster()
        store.save_cluster("template-a", cluster)

        # Verify it's in cache
        assert "template-a" in store._cache

        store.delete_cluster("template-a")

        # Cache should no longer have it
        assert "template-a" not in store._cache
        # And load should return None
        assert store.load_cluster("template-a") is None

    def test_clear_cache_empties_all(self, tmp_path):
        """clear_cache removes all cached entries."""
        store = ClusterStore(tmp_path)
        store.save_cluster("t1", _make_cluster(template_id="t1"))
        store.save_cluster("t2", _make_cluster(template_id="t2"))
        store.save_cluster("t3", _make_cluster(template_id="t3"))

        # All should be in cache after save
        assert "t1" in store._cache
        assert "t2" in store._cache
        assert "t3" in store._cache

        store.clear_cache()

        assert store._cache == {}
