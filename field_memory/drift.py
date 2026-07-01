# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Drift Detection Module for the Field Location Memory system.

This module detects when document field positions have shifted (drifted)
relative to a stored template baseline. It computes per-field drift scores
and identifies new/missing fields.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from field_memory.models import FieldLocationMap
from field_memory.utils import normalize_field_name


@dataclass
class FieldDriftResult:
    """Result of drift analysis for a single field.

    Attributes:
        field_name: The name of the field analyzed.
        drift_score: Normalized drift score in [0.0, 1.0].
        is_drifting: Whether the field exceeds the drift threshold.
        observed_center: The (cx, cy) center of the field in the document.
        expected_center: The (cx, cy) center of the field in the template.
    """

    field_name: str
    drift_score: float
    is_drifting: bool
    observed_center: Tuple[float, float]
    expected_center: Tuple[float, float]


@dataclass
class DriftReport:
    """Complete drift analysis report for a document against a template.

    Attributes:
        template_id: The template that was compared against.
        overall_drift_score: Mean drift score of shared fields (0.0 if none).
        is_drifting: True if any field's drift_score exceeds the threshold.
        field_drifts: Per-field drift results for shared fields.
        drifting_fields: Names of fields that exceed the drift threshold.
        new_fields: Fields in the document but not in the template.
        missing_fields: Fields in the template but not in the document.
    """

    template_id: str
    overall_drift_score: float
    is_drifting: bool
    field_drifts: List[FieldDriftResult] = field(default_factory=list)
    drifting_fields: List[str] = field(default_factory=list)
    new_fields: List[str] = field(default_factory=list)
    missing_fields: List[str] = field(default_factory=list)


class DriftDetector:
    """Detects positional drift of document fields relative to a stored template.

    Args:
        drift_threshold: The threshold above which a field is considered drifting.
                        Default is 0.1. Must be in [0.0, 1.0].
    """

    def __init__(self, drift_threshold: float = 0.1):
        self.drift_threshold = drift_threshold

    def detect(self, document: Any, template: FieldLocationMap) -> DriftReport:
        """Compare document field positions against stored template.

        Extracts field names and bounding boxes from the document, compares
        them against the template's stored positions, and computes drift scores.

        Args:
            document: A document object with pages[].key_values[].key[].text
                     and .bbox.x/.y/.width/.height attributes.
            template: The FieldLocationMap to compare against.

        Returns:
            A DriftReport with per-field drift scores and new/missing field lists.
        """
        # Step 1: Extract document field names (case-insensitive) with their bboxes
        doc_fields: Dict[str, Dict[str, float]] = {}
        for page in document.pages:
            for kv in page.key_values:
                field_name = normalize_field_name(
                    " ".join(word.text for word in kv.key)
                )
                field_name_lower = field_name.lower()
                bbox = {
                    "x": kv.bbox.x,
                    "y": kv.bbox.y,
                    "width": kv.bbox.width,
                    "height": kv.bbox.height,
                }
                doc_fields[field_name_lower] = bbox

        # Step 2: Get template field names (case-insensitive)
        template_fields: Dict[str, str] = {}  # lower -> original name
        for field_name in template.fields:
            template_fields[field_name.lower()] = field_name

        # Step 3: Determine shared, new, and missing fields
        doc_field_names = set(doc_fields.keys())
        template_field_names = set(template_fields.keys())

        shared_fields = doc_field_names & template_field_names
        new_fields_set = doc_field_names - template_field_names
        missing_fields_set = template_field_names - doc_field_names

        # Step 4: Compute drift for shared fields
        field_drifts: List[FieldDriftResult] = []
        drifting_fields: List[str] = []

        for field_name_lower in sorted(shared_fields):
            observed_bbox = doc_fields[field_name_lower]
            # Get the best region from the template (highest occurrence_count)
            original_name = template_fields[field_name_lower]
            template_region = template.get_field_region(original_name)

            if template_region is None:
                continue

            expected_bbox = template_region.bbox
            drift_score = self._compute_field_drift(observed_bbox, expected_bbox)

            observed_cx = observed_bbox["x"] + observed_bbox["width"] / 2
            observed_cy = observed_bbox["y"] + observed_bbox["height"] / 2
            expected_cx = expected_bbox["x"] + expected_bbox["width"] / 2
            expected_cy = expected_bbox["y"] + expected_bbox["height"] / 2

            is_field_drifting = drift_score > self.drift_threshold

            result = FieldDriftResult(
                field_name=original_name,
                drift_score=drift_score,
                is_drifting=is_field_drifting,
                observed_center=(observed_cx, observed_cy),
                expected_center=(expected_cx, expected_cy),
            )
            field_drifts.append(result)

            if is_field_drifting:
                drifting_fields.append(original_name)

        # Step 5: Compute overall drift score (mean of shared field drift scores)
        if field_drifts:
            overall_drift_score = sum(fd.drift_score for fd in field_drifts) / len(
                field_drifts
            )
        else:
            overall_drift_score = 0.0

        # Step 6: Determine overall is_drifting flag
        is_drifting = len(drifting_fields) > 0

        # Build new_fields and missing_fields lists using original names where possible
        new_fields_list = sorted(new_fields_set)
        missing_fields_list = sorted(template_fields[f] for f in missing_fields_set)

        return DriftReport(
            template_id=template.template_id,
            overall_drift_score=overall_drift_score,
            is_drifting=is_drifting,
            field_drifts=field_drifts,
            drifting_fields=drifting_fields,
            new_fields=new_fields_list,
            missing_fields=missing_fields_list,
        )

    def _compute_field_drift(
        self, observed_bbox: Dict[str, float], expected_bbox: Dict[str, float]
    ) -> float:
        """Compute normalized Euclidean distance between bbox centers.

        The distance is normalized by sqrt(2), which is the maximum possible
        distance between two points in the [0,1]x[0,1] coordinate space.

        Args:
            observed_bbox: The bounding box from the document.
            expected_bbox: The bounding box from the template.

        Returns:
            A drift score in [0.0, 1.0].
        """
        observed_cx = observed_bbox["x"] + observed_bbox["width"] / 2
        observed_cy = observed_bbox["y"] + observed_bbox["height"] / 2
        expected_cx = expected_bbox["x"] + expected_bbox["width"] / 2
        expected_cy = expected_bbox["y"] + expected_bbox["height"] / 2

        distance = math.sqrt(
            (observed_cx - expected_cx) ** 2 + (observed_cy - expected_cy) ** 2
        )
        drift_score = distance / math.sqrt(2)

        # Clamp to [0.0, 1.0] for safety (should already be bounded for valid inputs)
        return max(0.0, min(1.0, drift_score))
