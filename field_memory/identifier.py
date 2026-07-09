# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Template identification. Determines which stored template matches a document."""

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, List, Optional

from field_memory.matcher import SpatialMatcher
from field_memory.models import FieldLocationMap
from field_memory.utils import normalize_field_name

logger = logging.getLogger(__name__)


@dataclass
class TemplateMatch:
    """Result of template identification."""

    template_id: str
    similarity_score: float
    field_overlap_ratio: float
    spatial_similarity: float


class TemplateIdentifier:
    """Identifies which stored template best matches a given document.

    Combined score uses both structural (name) and spatial (position) similarity.
    Both components must meet minimum thresholds to accept a match, preventing
    documents with correct field names but wrong positions from passing.

    Args:
        similarity_threshold: Minimum combined score to accept a match.
        spatial_weight: Weight for spatial similarity in combined score (0.0-1.0).
        name_weight: Weight for structural/name similarity (1.0 - spatial_weight).
        min_spatial_score: Minimum spatial score required (below this = heavy penalty).
        min_structural_score: Minimum structural score required.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.7,
        spatial_weight: float = 0.6,
        name_weight: float = 0.4,
        min_spatial_score: float = 0.4,
        min_structural_score: float = 0.3,
    ):
        self.similarity_threshold = similarity_threshold
        self.spatial_weight = spatial_weight
        self.name_weight = name_weight
        self.min_spatial_score = min_spatial_score
        self.min_structural_score = min_structural_score
        self._spatial_matcher = SpatialMatcher()

    def identify(
        self, document: Any, stored_templates: List[FieldLocationMap]
    ) -> Optional[TemplateMatch]:
        """Return the best matching template above threshold, or None."""
        if not stored_templates:
            return None

        doc_field_names = self._extract_field_names(document)
        best_match: Optional[TemplateMatch] = None
        best_score = -1.0
        best_structural = -1.0

        for template in stored_templates:
            try:
                structural_sim = self.compute_structural_similarity(
                    list(doc_field_names), template
                )
                spatial_sim = self.compute_spatial_similarity(document, template)

                # Both components must meet minimum bar
                # This prevents docs with correct names but wrong positions from passing
                if (
                    structural_sim < self.min_structural_score
                    or spatial_sim < self.min_spatial_score
                ):
                    combined = min(structural_sim, spatial_sim) * 0.5
                else:
                    combined = (
                        self.name_weight * structural_sim
                        + self.spatial_weight * spatial_sim
                    )

                is_better = combined > best_score or (
                    combined == best_score and structural_sim > best_structural
                )
                if is_better:
                    best_score = combined
                    best_structural = structural_sim
                    best_match = TemplateMatch(
                        template_id=template.template_id,
                        similarity_score=combined,
                        field_overlap_ratio=structural_sim,
                        spatial_similarity=spatial_sim,
                    )
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning(
                    "Skipping template '%s': %s",
                    getattr(template, "template_id", "?"),
                    e,
                )
                continue

        if best_match and best_match.similarity_score >= self.similarity_threshold:
            return best_match
        return None

    def compute_structural_similarity(
        self, doc_field_names: List[str], template: FieldLocationMap
    ) -> float:
        """Jaccard similarity of field name sets (case-insensitive, normalized)."""
        doc_set = set(normalize_field_name(name).lower() for name in doc_field_names)
        template_set = set(
            normalize_field_name(name).lower() for name in template.fields.keys()
        )
        if not doc_set and not template_set:
            return 0.0
        intersection = doc_set & template_set
        union = doc_set | template_set
        return len(intersection) / len(union)

    def compute_spatial_similarity(
        self, document: Any, template: FieldLocationMap
    ) -> float:
        """Mean spatial score across shared fields. 0.0 if no shared fields."""
        doc_fields: dict = {}
        for page in document.pages:
            for kv in page.key_values:
                key_text = normalize_field_name(
                    " ".join([w.text for w in kv.key])
                ).lower()
                if key_text and key_text not in doc_fields:
                    doc_fields[key_text] = {
                        "x": kv.bbox.x,
                        "y": kv.bbox.y,
                        "width": kv.bbox.width,
                        "height": kv.bbox.height,
                    }

        template_fields: dict = {}
        for field_name, regions in template.fields.items():
            lower_name = normalize_field_name(field_name).lower()
            if regions and lower_name not in template_fields:
                best_region = max(regions, key=lambda r: r.occurrence_count)
                template_fields[lower_name] = best_region.bbox

        shared_names = set(doc_fields.keys()) & set(template_fields.keys())
        if not shared_names:
            return 0.0

        scores = [
            self._spatial_matcher.compute_spatial_score(
                doc_fields[name], template_fields[name]
            )
            for name in shared_names
        ]
        return max(0.0, min(1.0, sum(scores) / len(scores)))

    def compute_signature(self, document: Any) -> str:
        """Generate a template_id from the document's field names."""
        field_names = sorted(self._extract_field_names(document))
        joined = "|".join(field_names)
        hash_hex = hashlib.md5(
            joined.encode("utf-8"), usedforsecurity=False
        ).hexdigest()[:8]

        slug_parts = []
        for name in field_names[:3]:
            words = name.split()
            if words:
                slug_word = "".join(c for c in words[0] if c.isalnum()).lower()
                if slug_word:
                    slug_parts.append(slug_word)

        if slug_parts:
            return f"{'-'.join(slug_parts)}-{hash_hex}"
        return f"template-{hash_hex}"

    def _extract_field_names(self, document: Any) -> set:
        field_names = set()
        for page in document.pages:
            for kv in page.key_values:
                key_text = normalize_field_name(
                    " ".join([w.text for w in kv.key])
                ).lower()
                if key_text:
                    field_names.add(key_text)
        return field_names
