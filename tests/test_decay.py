# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for confidence decay in FieldLocationMap.merge().

Task 2.6: Example-based tests for decay behavior.
Task 2.7: Property-based test for monotonic weight reduction.
"""

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from field_memory.models import FieldLocationMap, FieldRegion

# --- Helpers ---


def make_flm(
    template_id: str,
    field_name: str,
    bbox: dict,
    confidence: float = 0.9,
    occurrence_count: int = 1,
) -> FieldLocationMap:
    """Create a simple FieldLocationMap with one field region."""
    region = FieldRegion(
        field_name=field_name,
        page=1,
        bbox=dict(bbox),
        confidence=confidence,
        occurrence_count=occurrence_count,
    )
    flm = FieldLocationMap(template_id=template_id)
    flm.add_field(field_name, region)
    return flm


# --- Task 2.6: Example-based tests ---


class TestDecayExamples:
    """Example-based tests for decay_factor behavior."""

    def test_decay_1_0_matches_current_behavior(self):
        """With decay_factor=1.0, merge produces the same weighted average as (n*old + new)/(n+1)."""
        bbox_old = {"x": 0.10, "y": 0.20, "width": 0.30, "height": 0.04}
        bbox_new = {"x": 0.12, "y": 0.22, "width": 0.28, "height": 0.05}

        # Build a template with occurrence_count=5
        flm = make_flm("t1", "Name", bbox_old, confidence=0.9, occurrence_count=5)

        # Build the new observation
        other = make_flm("t1", "Name", bbox_new, confidence=0.8)

        # Merge with decay=1.0 (no decay)
        flm.merge(other, tolerance=1.0, decay_factor=1.0)

        region = flm.get_field_region("Name")
        n = 5  # original occurrence_count
        # Expected: (n * old + new) / (n + 1)
        expected_x = (n * 0.10 + 0.12) / (n + 1)
        expected_y = (n * 0.20 + 0.22) / (n + 1)
        expected_w = (n * 0.30 + 0.28) / (n + 1)
        expected_h = (n * 0.04 + 0.05) / (n + 1)
        expected_conf = (n * 0.9 + 0.8) / (n + 1)

        assert abs(region.bbox["x"] - expected_x) < 1e-9
        assert abs(region.bbox["y"] - expected_y) < 1e-9
        assert abs(region.bbox["width"] - expected_w) < 1e-9
        assert abs(region.bbox["height"] - expected_h) < 1e-9
        assert abs(region.confidence - expected_conf) < 1e-9
        assert region.occurrence_count == 6

    def test_decay_less_than_1_gives_new_observation_more_influence(self):
        """With decay_factor<1.0, the new observation has MORE influence than with decay=1.0."""
        bbox_old = {"x": 0.10, "y": 0.20, "width": 0.30, "height": 0.04}
        bbox_new = {"x": 0.20, "y": 0.30, "width": 0.25, "height": 0.05}

        # Create two identical starting templates
        flm_no_decay = make_flm(
            "t1", "Name", dict(bbox_old), confidence=0.9, occurrence_count=5
        )
        flm_with_decay = make_flm(
            "t1", "Name", dict(bbox_old), confidence=0.9, occurrence_count=5
        )

        other_no_decay = make_flm("t1", "Name", dict(bbox_new), confidence=0.8)
        other_with_decay = make_flm("t1", "Name", dict(bbox_new), confidence=0.8)

        # Merge without decay
        flm_no_decay.merge(other_no_decay, tolerance=1.0, decay_factor=1.0)
        # Merge with decay
        flm_with_decay.merge(other_with_decay, tolerance=1.0, decay_factor=0.8)

        region_no_decay = flm_no_decay.get_field_region("Name")
        region_with_decay = flm_with_decay.get_field_region("Name")

        # With decay, the result should be closer to the new observation (bbox_new)
        # because old weight is reduced. The new bbox_new has x=0.20, which is larger.
        # So with decay, x should be closer to 0.20 (larger) than without decay.
        assert region_with_decay.bbox["x"] > region_no_decay.bbox["x"]
        assert region_with_decay.bbox["y"] > region_no_decay.bbox["y"]
        # Confidence: new is 0.8 (lower), so with decay result is closer to 0.8 (lower)
        assert region_with_decay.confidence < region_no_decay.confidence

    def test_invalid_decay_factor_too_low(self):
        """decay_factor=0.3 raises ValueError."""
        flm = make_flm("t1", "Name", {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04})
        other = make_flm(
            "t1", "Name", {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04}
        )

        with pytest.raises(ValueError, match="decay_factor must be in"):
            flm.merge(other, tolerance=1.0, decay_factor=0.3)

    def test_invalid_decay_factor_too_high(self):
        """decay_factor=1.5 raises ValueError."""
        flm = make_flm("t1", "Name", {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04})
        other = make_flm(
            "t1", "Name", {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04}
        )

        with pytest.raises(ValueError, match="decay_factor must be in"):
            flm.merge(other, tolerance=1.0, decay_factor=1.5)

    def test_invalid_decay_factor_negative(self):
        """decay_factor=-0.1 raises ValueError."""
        flm = make_flm("t1", "Name", {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04})
        other = make_flm(
            "t1", "Name", {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.04}
        )

        with pytest.raises(ValueError, match="decay_factor must be in"):
            flm.merge(other, tolerance=1.0, decay_factor=-0.1)


# --- Task 2.7: Property-based test ---


# Strategy for valid bounding boxes (must fit within [0, 1] normalized space)
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


class TestDecayMonotonicProperty:
    """Property-based test: decay reduces effective weight monotonically.

    **Validates: Requirements 7.1, 7.2**
    """

    @given(
        decay_factor=st.floats(min_value=0.5, max_value=0.99),
        initial_bbox=bbox_strategy(),
        merge_bboxes=st.lists(bbox_strategy(), min_size=2, max_size=5),
        initial_confidence=st.floats(min_value=0.1, max_value=1.0),
    )
    @settings(max_examples=200, deadline=None)
    def test_decay_reduces_effective_weight_monotonically(
        self, decay_factor, initial_bbox, merge_bboxes, initial_confidence
    ):
        """After each successive merge with decay<1.0, the effective weight of the
        original observation should be strictly less than before (monotonically decreasing).

        We verify this by checking that the influence of the original bbox diminishes:
        each merge moves the result further from the original position (closer to the
        new observations), meaning the original's effective weight is decreasing.
        """
        # Use a fixed "probe" observation far from the initial to measure influence
        # The idea: merge the same new observation repeatedly. Each time, the result
        # should move closer to the new observation because the old weight decays.
        probe_bbox = {"x": 0.50, "y": 0.50, "width": 0.10, "height": 0.10}
        probe_confidence = 0.5

        # Start with the initial template
        flm = make_flm(
            "t1",
            "Field",
            dict(initial_bbox),
            confidence=initial_confidence,
            occurrence_count=1,
        )

        # Track the distance from the probe after each merge
        # The effective weight of the original decreases, so the position should
        # move toward the probe with each merge.
        distances_from_probe = []

        for _ in range(len(merge_bboxes)):
            other = make_flm(
                "t1", "Field", dict(probe_bbox), confidence=probe_confidence
            )
            flm.merge(other, tolerance=10.0, decay_factor=decay_factor)

            region = flm.get_field_region("Field")
            cx = region.bbox["x"] + region.bbox["width"] / 2
            cy = region.bbox["y"] + region.bbox["height"] / 2
            probe_cx = probe_bbox["x"] + probe_bbox["width"] / 2
            probe_cy = probe_bbox["y"] + probe_bbox["height"] / 2
            dist = ((cx - probe_cx) ** 2 + (cy - probe_cy) ** 2) ** 0.5
            distances_from_probe.append(dist)

        # With decay < 1.0, each successive merge should bring us closer to the probe
        # (distance should be monotonically decreasing)
        for i in range(1, len(distances_from_probe)):
            assert distances_from_probe[i] <= distances_from_probe[i - 1] + 1e-9, (
                f"Distance to probe should decrease monotonically with decay. "
                f"Step {i}: {distances_from_probe[i]} > {distances_from_probe[i-1]}"
            )
