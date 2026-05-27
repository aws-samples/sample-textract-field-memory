# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Analytics module for template health reporting and system-wide statistics.

Provides statistical summaries, health grading, field stability scoring,
and cross-template aggregate analytics.
"""

from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from field_memory.models import FieldRegion
from field_memory.store import TemplateStore


@dataclass
class TemplateHealthReport:  # pylint: disable=too-many-instance-attributes
    """Health report for a single template.

    Attributes:
        template_id: The template identifier.
        field_count: Number of unique field names in the template.
        sample_count: Number of documents used to build this template.
        mean_confidence: Arithmetic mean of all region confidences.
        min_confidence: Minimum confidence across all regions.
        max_confidence: Maximum confidence across all regions.
        created_at: ISO timestamp when template was first created.
        updated_at: ISO timestamp when template was last updated.
        overall_health_grade: One of "excellent", "good", "developing", "insufficient".
    """

    template_id: str
    field_count: int
    sample_count: int
    mean_confidence: float
    min_confidence: float
    max_confidence: float
    created_at: Optional[str]
    updated_at: Optional[str]
    overall_health_grade: str


@dataclass
class SystemSummary:
    """Aggregate statistics across all stored templates.

    Attributes:
        total_template_count: Number of templates in the store.
        total_documents_processed: Sum of all template sample_counts.
        mean_template_health_grade: Most common health grade (mode).
        templates_by_health_grade: Count of templates per health grade.
        most_active_template: Template with highest sample_count.
        templates_ranked: Templates sorted by sample_count descending.
    """

    total_template_count: int
    total_documents_processed: int
    mean_template_health_grade: str
    templates_by_health_grade: Dict[str, int]
    most_active_template: Optional[str]
    templates_ranked: List[Dict[str, Any]]


class TemplateAnalytics:
    """Computes analytics and health metrics for stored templates."""

    def __init__(self, store: TemplateStore):
        self._store = store

    def get_template_stats(self, template_id: str) -> TemplateHealthReport:
        """Compute health report for a single template.

        Args:
            template_id: The template to analyze.

        Returns:
            A TemplateHealthReport with computed statistics.

        Raises:
            ValueError: If the template_id does not exist in the store.
        """
        flm = self._store.load(template_id)
        if flm is None:
            raise ValueError(f"Template not found: {template_id}")

        # Collect all confidences from all regions
        all_confidences: List[float] = []
        for regions in flm.fields.values():
            for region in regions:
                all_confidences.append(region.confidence)

        field_count = len(flm.fields)
        sample_count = flm.sample_count

        if not all_confidences:
            mean_confidence = 0.0
            min_confidence = 0.0
            max_confidence = 0.0
        else:
            mean_confidence = sum(all_confidences) / len(all_confidences)
            min_confidence = min(all_confidences)
            max_confidence = max(all_confidences)

        overall_health_grade = self._compute_health_grade(mean_confidence, sample_count)

        return TemplateHealthReport(
            template_id=template_id,
            field_count=field_count,
            sample_count=sample_count,
            mean_confidence=mean_confidence,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            created_at=flm.created_at,
            updated_at=flm.updated_at,
            overall_health_grade=overall_health_grade,
        )

    def get_field_stability(self, template_id: str) -> Dict[str, float]:
        """Compute stability score per field.

        Stability is derived from positional variance of a field's regions.
        Higher scores indicate more consistent positioning.

        Args:
            template_id: The template to analyze.

        Returns:
            Dictionary mapping field names to stability scores in [0.0, 1.0].

        Raises:
            ValueError: If the template_id does not exist in the store.
        """
        flm = self._store.load(template_id)
        if flm is None:
            raise ValueError(f"Template not found: {template_id}")

        stability_scores: Dict[str, float] = {}
        for field_name, regions in flm.fields.items():
            stability_scores[field_name] = self._compute_field_stability_score(regions)

        return stability_scores

    def get_system_summary(self) -> SystemSummary:
        """Compute cross-template aggregate statistics.

        Returns:
            A SystemSummary with counts, grades, and rankings across all templates.
        """
        all_templates = self._store.load_all()

        if not all_templates:
            return SystemSummary(
                total_template_count=0,
                total_documents_processed=0,
                mean_template_health_grade="insufficient",
                templates_by_health_grade={},
                most_active_template=None,
                templates_ranked=[],
            )

        # Compute stats for each template
        template_stats: List[Dict[str, Any]] = []
        grades: List[str] = []

        for flm in all_templates:
            all_confidences: List[float] = []
            for regions in flm.fields.values():
                for region in regions:
                    all_confidences.append(region.confidence)

            mean_conf = (
                sum(all_confidences) / len(all_confidences) if all_confidences else 0.0
            )
            grade = self._compute_health_grade(mean_conf, flm.sample_count)
            grades.append(grade)

            template_stats.append(
                {
                    "template_id": flm.template_id,
                    "sample_count": flm.sample_count,
                    "health_grade": grade,
                }
            )

        total_template_count = len(all_templates)
        total_documents_processed = sum(flm.sample_count for flm in all_templates)

        # Mean health grade = mode (most common), first alphabetically if tied
        grade_counts = Counter(grades)
        max_count = max(grade_counts.values())
        tied_grades = sorted(g for g, c in grade_counts.items() if c == max_count)
        mean_template_health_grade = tied_grades[0]

        # Templates by health grade
        templates_by_health_grade = dict(grade_counts)

        # Most active template (highest sample_count, first alphabetically if tied)
        max_sample_count = max(s["sample_count"] for s in template_stats)
        tied_active = sorted(
            (
                s["template_id"]
                for s in template_stats
                if s["sample_count"] == max_sample_count
            )
        )
        most_active_template = tied_active[0]

        # Templates ranked by sample_count descending
        templates_ranked = sorted(
            template_stats, key=lambda s: (-s["sample_count"], s["template_id"])
        )

        return SystemSummary(
            total_template_count=total_template_count,
            total_documents_processed=total_documents_processed,
            mean_template_health_grade=mean_template_health_grade,
            templates_by_health_grade=templates_by_health_grade,
            most_active_template=most_active_template,
            templates_ranked=templates_ranked,
        )

    def _compute_health_grade(self, mean_confidence: float, sample_count: int) -> str:
        """Classify template health based on confidence and sample maturity.

        Args:
            mean_confidence: Arithmetic mean of all region confidences.
            sample_count: Number of documents used to build the template.

        Returns:
            One of "excellent", "good", "developing", "insufficient".
        """
        if mean_confidence > 0.9 and sample_count > 10:
            return "excellent"
        if mean_confidence > 0.7 and sample_count > 5:
            return "good"
        if 2 <= sample_count <= 5:
            return "developing"
        return "insufficient"

    def _compute_field_stability_score(self, regions: List[FieldRegion]) -> float:
        """Compute stability from positional variance of regions.

        For single-observation fields (occurrence_count == 1 on all regions
        and only one region), returns 0.5.

        Args:
            regions: List of FieldRegion objects for a single field.

        Returns:
            Stability score in [0.0, 1.0].
        """
        if not regions:
            return 0.5

        # Check if this is a single-observation field
        if len(regions) == 1 and regions[0].occurrence_count == 1:
            return 0.5

        # Compute centers for each region
        centers = []
        for region in regions:
            cx = region.bbox["x"] + region.bbox["width"] / 2.0
            cy = region.bbox["y"] + region.bbox["height"] / 2.0
            centers.append((cx, cy))

        # Compute mean center
        mean_cx = sum(c[0] for c in centers) / len(centers)
        mean_cy = sum(c[1] for c in centers) / len(centers)

        # Compute variance (mean of squared Euclidean distances from mean center)
        variance = sum(
            (cx - mean_cx) ** 2 + (cy - mean_cy) ** 2 for cx, cy in centers
        ) / len(centers)

        # Normalize: stability = 1.0 - variance / max_variance, clamped to [0, 1]
        max_variance = 0.5
        stability = max(0.0, min(1.0, 1.0 - variance / max_variance))
        return stability
