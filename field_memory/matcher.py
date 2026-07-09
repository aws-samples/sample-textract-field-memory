# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Spatial matching for the Field Location Memory system.

Uses a combination of spatial proximity (IoU + distance) and name
similarity (normalized Levenshtein) to score and rank candidate
KeyValue entities against expected field regions.
"""

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from field_memory.utils import normalize_field_name


@dataclass
class FieldMatch:
    """A field match result with spatial confidence."""

    key_value: Any
    spatial_score: float
    name_score: float
    combined_score: float
    within_expected_region: bool


def _levenshtein_distance(s: str, t: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s) < len(t):
        return _levenshtein_distance(t, s)  # pylint: disable=arguments-out-of-order
    if len(t) == 0:
        return len(s)
    previous_row = list(range(len(t) + 1))
    for i, c1 in enumerate(s):
        current_row = [i + 1]
        for j, c2 in enumerate(t):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (0 if c1 == c2 else 1)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]


def _normalized_name_similarity(a: str, b: str) -> float:
    """Normalized name similarity. 1.0 = identical, 0.0 = completely different."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    max_len = max(len(a), len(b))
    distance = _levenshtein_distance(a, b)
    return 1.0 - (distance / max_len)


class SpatialMatcher:
    """Matches fields using stored spatial location data."""

    def __init__(
        self,
        spatial_tolerance: float = 0.05,
        spatial_weight: float = 0.6,
        name_weight: float = 0.4,
    ):
        self.spatial_tolerance = spatial_tolerance
        self.spatial_weight = spatial_weight
        self.name_weight = name_weight

    def expand_region(
        self, bbox: Dict[str, float], tolerance: float
    ) -> Dict[str, float]:
        """Expand a bounding box by tolerance, clamped to [0.0, 1.0]."""
        if tolerance < 0:
            raise ValueError(f"tolerance must be non-negative, got: {tolerance}")
        if tolerance == 0:
            return {
                "x": bbox["x"],
                "y": bbox["y"],
                "width": bbox["width"],
                "height": bbox["height"],
            }
        new_x = max(0.0, bbox["x"] - tolerance)
        new_y = max(0.0, bbox["y"] - tolerance)
        new_width = min(1.0 - new_x, bbox["width"] + 2 * tolerance)
        new_height = min(1.0 - new_y, bbox["height"] + 2 * tolerance)
        return {"x": new_x, "y": new_y, "width": new_width, "height": new_height}

    def compute_spatial_score(
        self, candidate_bbox: Dict[str, float], expected_region: Dict[str, float]
    ) -> float:
        """Score how well a candidate's position matches expected. Returns [0.0, 1.0]."""
        c_area = candidate_bbox["width"] * candidate_bbox["height"]
        e_area = expected_region["width"] * expected_region["height"]
        if c_area <= 0 or e_area <= 0:
            return 0.0

        ix1 = max(candidate_bbox["x"], expected_region["x"])
        iy1 = max(candidate_bbox["y"], expected_region["y"])
        ix2 = min(
            candidate_bbox["x"] + candidate_bbox["width"],
            expected_region["x"] + expected_region["width"],
        )
        iy2 = min(
            candidate_bbox["y"] + candidate_bbox["height"],
            expected_region["y"] + expected_region["height"],
        )
        intersection_area = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        union_area = c_area + e_area - intersection_area
        iou = intersection_area / union_area if union_area > 0 else 0.0

        c_cx = candidate_bbox["x"] + candidate_bbox["width"] / 2.0
        c_cy = candidate_bbox["y"] + candidate_bbox["height"] / 2.0
        e_cx = expected_region["x"] + expected_region["width"] / 2.0
        e_cy = expected_region["y"] + expected_region["height"] / 2.0
        euclidean_distance = math.sqrt((c_cx - e_cx) ** 2 + (c_cy - e_cy) ** 2)
        distance_score = max(0.0, 1.0 - euclidean_distance / math.sqrt(2))

        if iou > 0:
            return 0.7 * iou + 0.3 * distance_score
        # No overlap at all — heavy penalty. Use distance_score squared
        # to make non-overlapping fields score much lower
        return distance_score * distance_score * 0.5

    def find_field(
        self,
        field_name: str,
        document: Any,
        field_location_map: Any,
        page: Optional[int] = None,
    ) -> List[FieldMatch]:
        """Find a field in the document using stored spatial data."""
        expected_region = field_location_map.get_field_region(field_name, page)
        candidates = []
        target_pages = (
            [page] if page is not None else list(range(1, len(document.pages) + 1))
        )
        for p in target_pages:
            for kv in document.pages[p - 1].key_values:
                candidates.append(kv)
        return self.rank_candidates(candidates, field_name, expected_region)

    def rank_candidates(
        self, candidates: List[Any], field_name: str, expected_region: Optional[Any]
    ) -> List[FieldMatch]:
        """Score and sort candidates by combined spatial + name similarity."""
        matches = []
        for candidate in candidates:
            key_text = normalize_field_name(" ".join([w.text for w in candidate.key]))
            name_score = _normalized_name_similarity(
                field_name.lower(), key_text.lower()
            )

            if expected_region is not None:
                candidate_bbox = {
                    "x": candidate.bbox.x,
                    "y": candidate.bbox.y,
                    "width": candidate.bbox.width,
                    "height": candidate.bbox.height,
                }
                spatial_score = self.compute_spatial_score(
                    candidate_bbox, expected_region.bbox
                )
            else:
                spatial_score = 0.0

            combined_score = (
                self.spatial_weight * spatial_score + self.name_weight * name_score
            )

            within_region = False
            if expected_region is not None:
                expanded = self.expand_region(
                    expected_region.bbox, self.spatial_tolerance
                )
                cx = candidate.bbox.x + candidate.bbox.width / 2.0
                cy = candidate.bbox.y + candidate.bbox.height / 2.0
                within_region = (
                    expanded["x"] <= cx <= expanded["x"] + expanded["width"]
                    and expanded["y"] <= cy <= expanded["y"] + expanded["height"]
                )

            matches.append(
                FieldMatch(
                    key_value=candidate,
                    spatial_score=spatial_score,
                    name_score=name_score,
                    combined_score=combined_score,
                    within_expected_region=within_region,
                )
            )

        matches.sort(key=lambda m: m.combined_score, reverse=True)
        return matches
