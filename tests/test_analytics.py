# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for the Analytics Module.

Tasks 3.6-3.11: Property-based and example-based tests for TemplateAnalytics.
"""

import tempfile
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from field_memory.analytics import (
    SystemSummary,
    TemplateAnalytics,
    TemplateHealthReport,
)
from field_memory.models import FieldLocationMap, FieldRegion
from field_memory.store import TemplateStore

# --- Strategies ---


@st.composite
def bbox_strategy(draw):
    """Generate a valid bounding box dict with coordinates in [0, 1]."""
    x = draw(st.floats(min_value=0.01, max_value=0.5))
    y = draw(st.floats(min_value=0.01, max_value=0.5))
    width = draw(st.floats(min_value=0.01, max_value=0.49))
    height = draw(st.floats(min_value=0.01, max_value=0.49))
    assume(x + width <= 1.0)
    assume(y + height <= 1.0)
    return {"x": x, "y": y, "width": width, "height": height}


@st.composite
def field_region_strategy(draw, field_name=None):
    """Generate a valid FieldRegion."""
    name = field_name or draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"), whitelist_characters="_"
            ),
            min_size=1,
            max_size=10,
        )
    )
    bbox = draw(bbox_strategy())
    confidence = draw(st.floats(min_value=0.0, max_value=1.0))
    occurrence_count = draw(st.integers(min_value=1, max_value=100))
    return FieldRegion(
        field_name=name,
        page=1,
        bbox=bbox,
        confidence=confidence,
        occurrence_count=occurrence_count,
    )


@st.composite
def field_location_map_strategy(draw, min_fields=1, max_fields=5):
    """Generate a valid FieldLocationMap with random fields and regions."""
    num_fields = draw(st.integers(min_value=min_fields, max_value=max_fields))
    template_id = draw(
        st.text(
            alphabet=st.characters(
                whitelist_categories=("L", "N"), whitelist_characters="_-"
            ),
            min_size=1,
            max_size=15,
        )
    )
    sample_count = draw(st.integers(min_value=1, max_value=50))

    fields = {}
    for i in range(num_fields):
        field_name = f"field_{i}"
        num_regions = draw(st.integers(min_value=1, max_value=3))
        regions = []
        for _ in range(num_regions):
            region = draw(field_region_strategy(field_name=field_name))
            regions.append(region)
        fields[field_name] = regions

    flm = FieldLocationMap(
        template_id=template_id,
        fields=fields,
        sample_count=sample_count,
    )
    return flm


# --- Helpers ---


def make_store_with_templates(templates):
    """Create a temporary TemplateStore and save the given templates."""
    tmp_dir = tempfile.mkdtemp()
    store = TemplateStore(Path(tmp_dir))
    for flm in templates:
        store.save(flm.template_id, flm)
    return store


def make_simple_flm(
    template_id, field_name, confidence=0.9, sample_count=1, occurrence_count=1
):
    """Create a simple FieldLocationMap with one field region."""
    region = FieldRegion(
        field_name=field_name,
        page=1,
        bbox={"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04},
        confidence=confidence,
        occurrence_count=occurrence_count,
    )
    flm = FieldLocationMap(template_id=template_id, sample_count=sample_count)
    flm.add_field(field_name, region)
    return flm


# --- Task 3.6: Property test - health grade is always one of four values ---


class TestHealthGradeProperty:
    """Property-based test: health grade is always one of four values for any valid input.

    **Validates: Requirements 1.3**
    """

    @given(
        mean_confidence=st.floats(min_value=0.0, max_value=1.0),
        sample_count=st.integers(min_value=1, max_value=1000),
    )
    @settings(max_examples=500, deadline=None)
    def test_health_grade_always_valid(self, mean_confidence, sample_count):
        """For any valid mean_confidence in [0.0, 1.0] and sample_count >= 1,
        the health grade is always one of exactly four values."""
        tmp_dir = tempfile.mkdtemp()
        store = TemplateStore(Path(tmp_dir))
        analytics = TemplateAnalytics(store)

        valid_grades = {"excellent", "good", "developing", "insufficient"}
        grade = analytics._compute_health_grade(mean_confidence, sample_count)

        assert grade in valid_grades, (
            f"Health grade '{grade}' is not one of {valid_grades}. "
            f"Inputs: mean_confidence={mean_confidence}, sample_count={sample_count}"
        )


# --- Task 3.7: Property test - mean_confidence equals arithmetic mean ---


class TestMeanConfidenceProperty:
    """Property-based test: mean_confidence equals arithmetic mean of all region confidences.

    **Validates: Requirements 1.4**
    """

    @given(flm=field_location_map_strategy(min_fields=1, max_fields=5))
    @settings(max_examples=300, deadline=None)
    def test_mean_confidence_is_arithmetic_mean(self, flm):
        """The computed mean_confidence equals sum(confidences) / count(confidences)."""
        store = make_store_with_templates([flm])
        analytics = TemplateAnalytics(store)

        report = analytics.get_template_stats(flm.template_id)

        # Compute expected mean manually
        all_confidences = []
        for regions in flm.fields.values():
            for region in regions:
                all_confidences.append(region.confidence)

        if not all_confidences:
            expected_mean = 0.0
        else:
            expected_mean = sum(all_confidences) / len(all_confidences)

        assert (
            abs(report.mean_confidence - expected_mean) < 1e-9
        ), f"mean_confidence {report.mean_confidence} != expected {expected_mean}"


# --- Task 3.8: Property test - field stability scores are always in [0.0, 1.0] ---


class TestFieldStabilityBoundsProperty:
    """Property-based test: field stability scores are always in [0.0, 1.0].

    **Validates: Requirements 2.2**
    """

    @given(flm=field_location_map_strategy(min_fields=1, max_fields=5))
    @settings(max_examples=300, deadline=None)
    def test_stability_scores_bounded(self, flm):
        """Every field stability score is in [0.0, 1.0] for any valid FieldLocationMap."""
        store = make_store_with_templates([flm])
        analytics = TemplateAnalytics(store)

        stability_scores = analytics.get_field_stability(flm.template_id)

        for field_name, score in stability_scores.items():
            assert 0.0 <= score <= 1.0, (
                f"Stability score for '{field_name}' is {score}, "
                f"which is outside [0.0, 1.0]"
            )


# --- Task 3.9: Property test - system summary counts are consistent ---


class TestSystemSummaryConsistencyProperty:
    """Property-based test: system summary counts are consistent (grade counts sum to total).

    **Validates: Requirements 5.1**
    """

    @given(
        num_templates=st.integers(min_value=1, max_value=8),
        data=st.data(),
    )
    @settings(max_examples=200, deadline=None)
    def test_grade_counts_sum_to_total(self, num_templates, data):
        """The sum of templates_by_health_grade values equals total_template_count."""
        templates = []
        for i in range(num_templates):
            confidence = data.draw(st.floats(min_value=0.0, max_value=1.0))
            sample_count = data.draw(st.integers(min_value=1, max_value=50))
            flm = make_simple_flm(
                template_id=f"template_{i}",
                field_name=f"field_{i}",
                confidence=confidence,
                sample_count=sample_count,
            )
            templates.append(flm)

        store = make_store_with_templates(templates)
        analytics = TemplateAnalytics(store)

        summary = analytics.get_system_summary()

        # Grade counts sum to total
        grade_sum = sum(summary.templates_by_health_grade.values())
        assert grade_sum == summary.total_template_count, (
            f"Sum of grade counts ({grade_sum}) != total_template_count "
            f"({summary.total_template_count})"
        )

        # total_documents_processed equals sum of sample_counts
        expected_docs = sum(flm.sample_count for flm in templates)
        assert summary.total_documents_processed == expected_docs, (
            f"total_documents_processed ({summary.total_documents_processed}) != "
            f"expected ({expected_docs})"
        )


# --- Task 3.10: Property test - templates_ranked is sorted by sample_count descending ---


class TestTemplatesRankedSortProperty:
    """Property-based test: templates_ranked is sorted by sample_count descending.

    **Validates: Requirements 5.3**
    """

    @given(
        num_templates=st.integers(min_value=1, max_value=8),
        data=st.data(),
    )
    @settings(max_examples=200, deadline=None)
    def test_templates_ranked_sorted_descending(self, num_templates, data):
        """templates_ranked is sorted by sample_count in non-increasing order."""
        templates = []
        for i in range(num_templates):
            confidence = data.draw(st.floats(min_value=0.0, max_value=1.0))
            sample_count = data.draw(st.integers(min_value=1, max_value=100))
            flm = make_simple_flm(
                template_id=f"template_{i}",
                field_name=f"field_{i}",
                confidence=confidence,
                sample_count=sample_count,
            )
            templates.append(flm)

        store = make_store_with_templates(templates)
        analytics = TemplateAnalytics(store)

        summary = analytics.get_system_summary()

        # Verify sorted by sample_count descending
        sample_counts = [t["sample_count"] for t in summary.templates_ranked]
        for i in range(1, len(sample_counts)):
            assert sample_counts[i] <= sample_counts[i - 1], (
                f"templates_ranked not sorted descending at index {i}: "
                f"{sample_counts[i]} > {sample_counts[i - 1]}"
            )


# --- Task 3.11: Example tests ---


class TestAnalyticsExamples:
    """Example-based tests for analytics edge cases.

    Tests:
    - Missing template raises ValueError for get_template_stats and get_field_stability
    - Single-observation field gets stability score of 0.5
    - Empty store returns zeroed SystemSummary with most_active_template=None
    """

    def test_missing_template_raises_valueerror_get_template_stats(self):
        """get_template_stats raises ValueError for a non-existent template."""
        tmp_dir = tempfile.mkdtemp()
        store = TemplateStore(Path(tmp_dir))
        analytics = TemplateAnalytics(store)

        with pytest.raises(ValueError, match="Template not found"):
            analytics.get_template_stats("nonexistent_template")

    def test_missing_template_raises_valueerror_get_field_stability(self):
        """get_field_stability raises ValueError for a non-existent template."""
        tmp_dir = tempfile.mkdtemp()
        store = TemplateStore(Path(tmp_dir))
        analytics = TemplateAnalytics(store)

        with pytest.raises(ValueError, match="Template not found"):
            analytics.get_field_stability("nonexistent_template")

    def test_single_observation_field_gets_0_5_stability(self):
        """A field with occurrence_count=1 and a single region gets stability 0.5."""
        flm = make_simple_flm(
            template_id="single_obs",
            field_name="Name",
            confidence=0.9,
            sample_count=1,
            occurrence_count=1,
        )
        store = make_store_with_templates([flm])
        analytics = TemplateAnalytics(store)

        stability = analytics.get_field_stability("single_obs")
        assert (
            stability["Name"] == 0.5
        ), f"Expected stability 0.5 for single-observation field, got {stability['Name']}"

    def test_empty_store_returns_zeroed_summary(self):
        """An empty store returns a SystemSummary with all zeroes and None most_active."""
        tmp_dir = tempfile.mkdtemp()
        store = TemplateStore(Path(tmp_dir))
        analytics = TemplateAnalytics(store)

        summary = analytics.get_system_summary()

        assert summary.total_template_count == 0
        assert summary.total_documents_processed == 0
        assert summary.most_active_template is None
        assert summary.templates_ranked == []
        assert summary.templates_by_health_grade == {}
