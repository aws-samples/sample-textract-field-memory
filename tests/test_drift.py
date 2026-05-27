# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for the Drift Detection Module.

Tasks 4.5-4.7: Property-based and example-based tests for DriftDetector.
"""

import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from field_memory.drift import DriftDetector, DriftReport, FieldDriftResult
from field_memory.models import FieldLocationMap, FieldRegion

# --- Mock document objects (same structure as test_field_memory.py) ---


@dataclass
class Word:
    text: str


@dataclass
class BBox:
    x: float
    y: float
    width: float
    height: float


@dataclass
class KeyValue:
    key: List[Word]
    bbox: BBox
    page: int
    confidence: float = 0.95


@dataclass
class Page:
    key_values: List[KeyValue]


@dataclass
class Document:
    pages: List[Page]


def make_doc(fields):
    """Create a Document from list of (name, x, y, w, h, page) tuples."""
    pages_dict = {}
    for name, x, y, w, h, pg in fields:
        if pg not in pages_dict:
            pages_dict[pg] = []
        pages_dict[pg].append(
            KeyValue(
                key=[Word(t) for t in name.split()],
                bbox=BBox(x, y, w, h),
                page=pg,
            )
        )
    max_pg = max(pages_dict.keys()) if pages_dict else 1
    pages = [Page(key_values=pages_dict.get(p, [])) for p in range(1, max_pg + 1)]
    return Document(pages=pages)


def make_template(template_id, fields_data):
    """Create a FieldLocationMap from list of (name, x, y, w, h) tuples.

    All fields are placed on page 1 with default confidence and occurrence_count.
    """
    flm = FieldLocationMap(template_id=template_id)
    for name, x, y, w, h in fields_data:
        region = FieldRegion(
            field_name=name,
            page=1,
            bbox={"x": x, "y": y, "width": w, "height": h},
            confidence=0.95,
            occurrence_count=5,
        )
        flm.add_field(name, region)
    return flm


# --- Strategies for property-based tests ---


@st.composite
def valid_bbox_strategy(draw):
    """Generate a valid bounding box with coordinates in [0, 1]."""
    x = draw(st.floats(min_value=0.01, max_value=0.49))
    y = draw(st.floats(min_value=0.01, max_value=0.49))
    width = draw(st.floats(min_value=0.01, max_value=0.49))
    height = draw(st.floats(min_value=0.01, max_value=0.49))
    assume(x + width <= 1.0)
    assume(y + height <= 1.0)
    return {"x": x, "y": y, "width": width, "height": height}


# --- Task 4.5: Property test - drift score is always in [0.0, 1.0] ---


class TestDriftScoreBoundsProperty:
    """Property-based test: drift score is always in [0.0, 1.0] for any valid bounding boxes.

    **Validates: Requirements 3.2**
    """

    @given(
        observed_bbox=valid_bbox_strategy(),
        expected_bbox=valid_bbox_strategy(),
    )
    @settings(max_examples=500, deadline=None)
    def test_drift_score_always_bounded(self, observed_bbox, expected_bbox):
        """For any two valid bounding boxes with coordinates in [0.0, 1.0],
        the computed drift score is always in [0.0, 1.0]."""
        detector = DriftDetector()
        drift_score = detector._compute_field_drift(observed_bbox, expected_bbox)

        assert 0.0 <= drift_score <= 1.0, (
            f"Drift score {drift_score} is outside [0.0, 1.0]. "
            f"Observed bbox: {observed_bbox}, Expected bbox: {expected_bbox}"
        )


# --- Task 4.6: Property test - field flagged as drifting iff drift_score > threshold ---


class TestDriftFlaggingProperty:
    """Property-based test: field flagged as drifting iff drift_score > threshold.

    **Validates: Requirements 3.3, 3.4**
    """

    @given(
        observed_bbox=valid_bbox_strategy(),
        expected_bbox=valid_bbox_strategy(),
        threshold=st.floats(min_value=0.0, max_value=1.0),
    )
    @settings(max_examples=500, deadline=None)
    def test_drift_flagging_consistent_with_threshold(
        self, observed_bbox, expected_bbox, threshold
    ):
        """A field is flagged as drifting if and only if its drift_score exceeds
        the configured threshold."""
        detector = DriftDetector(drift_threshold=threshold)
        drift_score = detector._compute_field_drift(observed_bbox, expected_bbox)

        # Create a document and template with a single shared field
        field_name = "TestField"
        doc = make_doc(
            [
                (
                    field_name,
                    observed_bbox["x"],
                    observed_bbox["y"],
                    observed_bbox["width"],
                    observed_bbox["height"],
                    1,
                )
            ]
        )
        template = make_template(
            "test_template",
            [
                (
                    field_name,
                    expected_bbox["x"],
                    expected_bbox["y"],
                    expected_bbox["width"],
                    expected_bbox["height"],
                )
            ],
        )

        report = detector.detect(doc, template)

        # Verify the field drift result
        assert len(report.field_drifts) == 1
        field_result = report.field_drifts[0]

        # Field is flagged as drifting iff drift_score > threshold
        expected_is_drifting = drift_score > threshold
        assert field_result.is_drifting == expected_is_drifting, (
            f"Field is_drifting={field_result.is_drifting} but expected "
            f"{expected_is_drifting} (drift_score={drift_score}, threshold={threshold})"
        )

        # Overall is_drifting is True iff drifting_fields is non-empty
        assert report.is_drifting == (len(report.drifting_fields) > 0), (
            f"report.is_drifting={report.is_drifting} but "
            f"drifting_fields={report.drifting_fields}"
        )

        # drifting_fields consistency
        if expected_is_drifting:
            assert field_name in report.drifting_fields
        else:
            assert field_name not in report.drifting_fields


# --- Task 4.7: Example tests ---


class TestDriftExamples:
    """Example-based tests for drift detection edge cases.

    Tests:
    - New fields are excluded from drift computation
    - Missing fields are listed in the report
    - Zero drift for identical positions
    """

    def test_new_fields_excluded_from_drift(self):
        """Fields in the document but not in the template are listed as new_fields
        and excluded from drift score computation."""
        # Template has only "Employee Name"
        template = make_template(
            "form",
            [
                ("Employee Name", 0.05, 0.10, 0.35, 0.03),
            ],
        )

        # Document has "Employee Name" + "New Field"
        doc = make_doc(
            [
                ("Employee Name", 0.05, 0.10, 0.35, 0.03, 1),
                ("New Field", 0.50, 0.50, 0.20, 0.03, 1),
            ]
        )

        detector = DriftDetector()
        report = detector.detect(doc, template)

        # "new field" should be in new_fields (case-insensitive)
        assert "new field" in report.new_fields
        # Only "Employee Name" should have a drift result
        assert len(report.field_drifts) == 1
        assert report.field_drifts[0].field_name == "Employee Name"
        # New field should NOT affect overall drift score
        assert report.overall_drift_score == 0.0

    def test_missing_fields_listed(self):
        """Fields in the template but not in the document are listed as missing_fields."""
        # Template has "Employee Name" and "Date of Birth"
        template = make_template(
            "form",
            [
                ("Employee Name", 0.05, 0.10, 0.35, 0.03),
                ("Date of Birth", 0.05, 0.20, 0.20, 0.03),
            ],
        )

        # Document only has "Employee Name"
        doc = make_doc(
            [
                ("Employee Name", 0.05, 0.10, 0.35, 0.03, 1),
            ]
        )

        detector = DriftDetector()
        report = detector.detect(doc, template)

        # "Date of Birth" should be in missing_fields
        assert "Date of Birth" in report.missing_fields
        # Only "Employee Name" should have a drift result
        assert len(report.field_drifts) == 1
        assert report.field_drifts[0].field_name == "Employee Name"

    def test_zero_drift_for_identical_positions(self):
        """When document fields are at the exact same positions as the template,
        drift scores should be 0.0."""
        template = make_template(
            "form",
            [
                ("Employee Name", 0.05, 0.10, 0.35, 0.03),
                ("Date of Birth", 0.05, 0.20, 0.20, 0.03),
            ],
        )

        doc = make_doc(
            [
                ("Employee Name", 0.05, 0.10, 0.35, 0.03, 1),
                ("Date of Birth", 0.05, 0.20, 0.20, 0.03, 1),
            ]
        )

        detector = DriftDetector()
        report = detector.detect(doc, template)

        # All drift scores should be 0.0
        assert report.overall_drift_score == 0.0
        assert report.is_drifting is False
        assert len(report.drifting_fields) == 0
        for field_drift in report.field_drifts:
            assert field_drift.drift_score == 0.0
            assert field_drift.is_drifting is False

    def test_high_drift_detected(self):
        """When a field moves significantly, it should be flagged as drifting."""
        template = make_template(
            "form",
            [
                ("Employee Name", 0.05, 0.10, 0.35, 0.03),
            ],
        )

        # Move the field to a very different position
        doc = make_doc(
            [
                ("Employee Name", 0.60, 0.80, 0.30, 0.03, 1),
            ]
        )

        detector = DriftDetector(drift_threshold=0.1)
        report = detector.detect(doc, template)

        assert report.is_drifting is True
        assert "Employee Name" in report.drifting_fields
        assert report.field_drifts[0].drift_score > 0.1

    def test_no_shared_fields_gives_zero_overall_drift(self):
        """When there are no shared fields, overall_drift_score is 0.0."""
        template = make_template(
            "form",
            [
                ("Employee Name", 0.05, 0.10, 0.35, 0.03),
            ],
        )

        doc = make_doc(
            [
                ("Totally Different", 0.50, 0.50, 0.20, 0.03, 1),
            ]
        )

        detector = DriftDetector()
        report = detector.detect(doc, template)

        assert report.overall_drift_score == 0.0
        assert len(report.field_drifts) == 0
        assert "totally different" in report.new_fields
        assert "Employee Name" in report.missing_fields
