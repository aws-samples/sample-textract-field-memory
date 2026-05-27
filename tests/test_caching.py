# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for TemplateStore caching behavior."""

from pathlib import Path

import pytest

from field_memory.models import FieldLocationMap, FieldRegion
from field_memory.store import TemplateStore


def _make_field_location_map(template_id: str = "test-template") -> FieldLocationMap:
    """Create a simple FieldLocationMap for testing."""
    flm = FieldLocationMap(
        template_id=template_id,
        page_count=1,
        sample_count=3,
    )
    flm.add_field(
        "Employee Name",
        FieldRegion(
            field_name="Employee Name",
            page=1,
            bbox={"x": 0.05, "y": 0.10, "width": 0.35, "height": 0.03},
            confidence=0.95,
            occurrence_count=3,
        ),
    )
    flm.add_field(
        "Date of Birth",
        FieldRegion(
            field_name="Date of Birth",
            page=1,
            bbox={"x": 0.05, "y": 0.20, "width": 0.20, "height": 0.03},
            confidence=0.92,
            occurrence_count=3,
        ),
    )
    return flm


class TestCacheMissAndHit:
    def test_cache_miss_on_first_load(self, tmp_path):
        """First load reads from disk and populates cache."""
        store = TemplateStore(tmp_path)
        flm = _make_field_location_map("form-a")
        store.save("form-a", flm)

        # Cache was invalidated by save, so it should be empty
        assert "form-a" not in store._cache

        # Load triggers a disk read and populates cache
        result = store.load("form-a")
        assert result is not None
        assert result.template_id == "form-a"
        assert "form-a" in store._cache

    def test_cache_hit_on_second_load(self, tmp_path):
        """Second load serves from cache without reading disk."""
        store = TemplateStore(tmp_path)
        flm = _make_field_location_map("form-b")
        store.save("form-b", flm)

        # First load populates cache
        first_result = store.load("form-b")
        assert "form-b" in store._cache

        # Verify the cached object is the same reference on second load
        second_result = store.load("form-b")
        assert second_result is first_result


class TestCacheInvalidationOnSave:
    def test_save_removes_cache_entry(self, tmp_path):
        """Saving a template invalidates its cache entry."""
        store = TemplateStore(tmp_path)
        flm = _make_field_location_map("form-c")
        store.save("form-c", flm)

        # Load to populate cache
        store.load("form-c")
        assert "form-c" in store._cache

        # Save again should invalidate cache
        updated_flm = _make_field_location_map("form-c")
        store.save("form-c", updated_flm)
        assert "form-c" not in store._cache

    def test_save_only_invalidates_target_template(self, tmp_path):
        """Saving one template does not affect cache of other templates."""
        store = TemplateStore(tmp_path)
        flm_a = _make_field_location_map("form-a")
        flm_b = _make_field_location_map("form-b")
        store.save("form-a", flm_a)
        store.save("form-b", flm_b)

        # Load both to populate cache
        store.load("form-a")
        store.load("form-b")
        assert "form-a" in store._cache
        assert "form-b" in store._cache

        # Save form-a, only form-a should be invalidated
        store.save("form-a", flm_a)
        assert "form-a" not in store._cache
        assert "form-b" in store._cache


class TestCacheInvalidationOnDelete:
    def test_delete_removes_cache_entry(self, tmp_path):
        """Deleting a template removes its cache entry."""
        store = TemplateStore(tmp_path)
        flm = _make_field_location_map("form-d")
        store.save("form-d", flm)

        # Load to populate cache
        store.load("form-d")
        assert "form-d" in store._cache

        # Delete should remove from cache
        store.delete("form-d")
        assert "form-d" not in store._cache

    def test_delete_nonexistent_does_not_error(self, tmp_path):
        """Deleting a template not in cache does not raise."""
        store = TemplateStore(tmp_path)
        assert "nonexistent" not in store._cache
        store.delete("nonexistent")  # Should not raise


class TestLoadAllPopulatesCache:
    def test_load_all_populates_cache(self, tmp_path):
        """load_all populates cache for all templates."""
        store = TemplateStore(tmp_path)
        flm_a = _make_field_location_map("form-a")
        flm_b = _make_field_location_map("form-b")
        store.save("form-a", flm_a)
        store.save("form-b", flm_b)

        # Cache should be empty after saves
        assert "form-a" not in store._cache
        assert "form-b" not in store._cache

        # load_all should populate cache for both
        results = store.load_all()
        assert len(results) == 2
        assert "form-a" in store._cache
        assert "form-b" in store._cache

    def test_load_all_cached_templates_match(self, tmp_path):
        """Templates cached by load_all are the same objects returned."""
        store = TemplateStore(tmp_path)
        flm = _make_field_location_map("form-x")
        store.save("form-x", flm)

        results = store.load_all()
        cached = store._cache["form-x"]
        assert cached is results[0]


class TestClearCache:
    def test_clear_cache_removes_all_entries(self, tmp_path):
        """clear_cache removes all cached entries."""
        store = TemplateStore(tmp_path)
        flm_a = _make_field_location_map("form-a")
        flm_b = _make_field_location_map("form-b")
        store.save("form-a", flm_a)
        store.save("form-b", flm_b)

        # Populate cache
        store.load("form-a")
        store.load("form-b")
        assert len(store._cache) == 2

        # Clear cache
        store.clear_cache()
        assert len(store._cache) == 0
        assert "form-a" not in store._cache
        assert "form-b" not in store._cache

    def test_clear_cache_does_not_delete_files(self, tmp_path):
        """clear_cache only clears memory, files remain on disk."""
        store = TemplateStore(tmp_path)
        flm = _make_field_location_map("form-persist")
        store.save("form-persist", flm)
        store.load("form-persist")

        store.clear_cache()
        assert "form-persist" not in store._cache

        # Template should still be loadable from disk
        result = store.load("form-persist")
        assert result is not None
        assert result.template_id == "form-persist"
