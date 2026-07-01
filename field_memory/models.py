# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Data models for the Field Location Memory system.

This module defines the core data structures used to store and manage
spatial field location data for document templates.
"""

import datetime
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from field_memory.utils import normalize_field_name


@dataclass
class FieldRegion:
    """A recorded spatial region where a specific field was found.

    Stores the bounding box as a simple dict with normalized coordinates
    (x, y, width, height in [0.0, 1.0]) for easy serialization.

    Attributes:
        field_name: The name of the field (non-empty string).
        page: The page number where the field was found (>= 1).
        bbox: A dict with keys 'x', 'y', 'width', 'height' containing
              normalized coordinates in [0.0, 1.0].
        confidence: Confidence score for this field region in [0.0, 1.0].
        occurrence_count: Number of times this field has been observed
                         at this location (>= 1).
    """

    field_name: str
    page: int
    bbox: Dict[str, float]
    confidence: float
    occurrence_count: int = 1

    def __post_init__(self):  # pylint: disable=too-many-branches
        """Validate all fields after initialization."""
        if not isinstance(self.field_name, str) or not self.field_name:
            raise ValueError(
                f"field_name must be a non-empty string, got: {self.field_name!r}"
            )
        if not isinstance(self.page, int) or self.page < 1:
            raise ValueError(
                f"page must be a positive integer >= 1, got: {self.page!r}"
            )
        if not isinstance(self.bbox, dict):
            raise ValueError(f"bbox must be a dict, got: {type(self.bbox).__name__}")

        required_keys = {"x", "y", "width", "height"}
        missing_keys = required_keys - set(self.bbox.keys())
        if missing_keys:
            raise ValueError(f"bbox is missing required keys: {missing_keys}")

        x, y = self.bbox["x"], self.bbox["y"]
        width, height = self.bbox["width"], self.bbox["height"]

        if x < 0.0:
            raise ValueError(f"bbox 'x' must be >= 0.0, got: {x}")
        if y < 0.0:
            raise ValueError(f"bbox 'y' must be >= 0.0, got: {y}")
        if width <= 0.0:
            raise ValueError(f"bbox 'width' must be > 0.0, got: {width}")
        if height <= 0.0:
            raise ValueError(f"bbox 'height' must be > 0.0, got: {height}")
        if x + width > 1.0:
            raise ValueError(f"bbox 'x + width' must be <= 1.0, got: {x + width}")
        if y + height > 1.0:
            raise ValueError(f"bbox 'y + height' must be <= 1.0, got: {y + height}")

        if not isinstance(self.confidence, (int, float)):
            raise ValueError(
                f"confidence must be a float in [0.0, 1.0], got: {self.confidence!r}"
            )
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got: {self.confidence}"
            )

        if not isinstance(self.occurrence_count, int) or self.occurrence_count < 1:
            raise ValueError(
                f"occurrence_count must be an integer >= 1, got: {self.occurrence_count!r}"
            )


@dataclass
class FieldLocationMap:
    """Maps field names to their expected spatial regions across pages."""

    template_id: str
    fields: Dict[str, List[FieldRegion]] = field(default_factory=dict)
    page_count: int = 1
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    sample_count: int = 1

    def __post_init__(self):
        if not isinstance(self.template_id, str) or not self.template_id:
            raise ValueError(
                f"template_id must be a non-empty string, got: {self.template_id!r}"
            )
        if not isinstance(self.page_count, int) or self.page_count < 1:
            raise ValueError(
                f"page_count must be an integer >= 1, got: {self.page_count!r}"
            )
        if not isinstance(self.sample_count, int) or self.sample_count < 1:
            raise ValueError(
                f"sample_count must be an integer >= 1, got: {self.sample_count!r}"
            )

    def add_field(self, field_name: str, region: FieldRegion) -> None:
        if field_name not in self.fields:
            self.fields[field_name] = []
        self.fields[field_name].append(region)

    def get_field_region(
        self, field_name: str, page: Optional[int] = None
    ) -> Optional[FieldRegion]:
        # Try exact match first
        regions = self.fields.get(field_name)
        # If not found, try normalized match (handles "Employee Name:" vs "Employee Name")
        if not regions:
            normalized_query = normalize_field_name(field_name).lower()
            for stored_name, stored_regions in self.fields.items():
                if normalize_field_name(stored_name).lower() == normalized_query:
                    regions = stored_regions
                    break
        if not regions:
            return None
        if page is not None:
            matching = [r for r in regions if r.page == page]
        else:
            matching = regions
        if not matching:
            return None
        return max(matching, key=lambda r: r.occurrence_count)

    def get_all_fields_on_page(self, page: int) -> List[FieldRegion]:
        result: List[FieldRegion] = []
        for regions in self.fields.values():
            for region in regions:
                if region.page == page:
                    result.append(region)
        return result

    def merge(
        self, other: "FieldLocationMap", tolerance: float, decay_factor: float = 1.0
    ) -> None:
        if decay_factor < 0.5 or decay_factor > 1.0:
            raise ValueError(f"decay_factor must be in [0.5, 1.0], got: {decay_factor}")
        if self.template_id != other.template_id:
            raise ValueError(
                f"Cannot merge FieldLocationMaps with different template_ids: "
                f"{self.template_id!r} != {other.template_id!r}"
            )
        self.sample_count += 1
        self.updated_at = datetime.datetime.utcnow().isoformat() + "Z"

        for field_name, regions in other.fields.items():
            for new_region in regions:
                existing_regions = self.fields.get(field_name, [])
                merged = False
                for existing in existing_regions:
                    if existing.page != new_region.page:
                        continue
                    ex_cx = existing.bbox["x"] + existing.bbox["width"] / 2.0
                    ex_cy = existing.bbox["y"] + existing.bbox["height"] / 2.0
                    new_cx = new_region.bbox["x"] + new_region.bbox["width"] / 2.0
                    new_cy = new_region.bbox["y"] + new_region.bbox["height"] / 2.0
                    distance = math.sqrt((ex_cx - new_cx) ** 2 + (ex_cy - new_cy) ** 2)

                    if distance <= tolerance:
                        # Apply decay to existing weight
                        effective_count = max(
                            0.01,
                            existing.occurrence_count * decay_factor,
                        )
                        total_weight = effective_count + 1
                        existing.bbox["x"] = (
                            existing.bbox["x"] * effective_count + new_region.bbox["x"]
                        ) / total_weight
                        existing.bbox["y"] = (
                            existing.bbox["y"] * effective_count + new_region.bbox["y"]
                        ) / total_weight
                        existing.bbox["width"] = (
                            existing.bbox["width"] * effective_count
                            + new_region.bbox["width"]
                        ) / total_weight
                        existing.bbox["height"] = (
                            existing.bbox["height"] * effective_count
                            + new_region.bbox["height"]
                        ) / total_weight
                        existing.confidence = (
                            existing.confidence * effective_count
                            + new_region.confidence
                        ) / total_weight
                        existing.occurrence_count += 1
                        merged = True
                        break

                if not merged:
                    if field_name not in self.fields:
                        self.fields[field_name] = []
                    self.fields[field_name].append(new_region)

    def to_dict(self) -> Dict[str, Any]:
        serialized_fields: Dict[str, List[Dict[str, Any]]] = {}
        for field_name, regions in self.fields.items():
            serialized_fields[field_name] = [
                {
                    "field_name": region.field_name,
                    "page": region.page,
                    "bbox": dict(region.bbox),
                    "confidence": region.confidence,
                    "occurrence_count": region.occurrence_count,
                }
                for region in regions
            ]
        return {
            "template_id": self.template_id,
            "page_count": self.page_count,
            "sample_count": self.sample_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "fields": serialized_fields,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FieldLocationMap":
        required_keys = {"template_id", "page_count", "sample_count", "fields"}
        missing_keys = required_keys - set(data.keys())
        if missing_keys:
            raise ValueError(
                f"Missing required keys in FieldLocationMap data: {missing_keys}"
            )

        template_id = data["template_id"]
        if not isinstance(template_id, str) or not template_id:
            raise ValueError(
                f"template_id must be a non-empty string, got: {template_id!r}"
            )

        page_count = data["page_count"]
        if not isinstance(page_count, int) or page_count < 1:
            raise ValueError(f"page_count must be an integer >= 1, got: {page_count!r}")

        sample_count = data["sample_count"]
        if not isinstance(sample_count, int) or sample_count < 1:
            raise ValueError(
                f"sample_count must be an integer >= 1, got: {sample_count!r}"
            )

        fields_data = data["fields"]
        if not isinstance(fields_data, dict):
            raise ValueError(
                f"fields must be a dict, got: {type(fields_data).__name__}"
            )

        fields: Dict[str, List[FieldRegion]] = {}
        for field_name, region_list in fields_data.items():
            if not isinstance(region_list, list):
                raise ValueError(
                    f"Field '{field_name}' regions must be a list, got: {type(region_list).__name__}"
                )
            regions: List[FieldRegion] = []
            for region_data in region_list:
                regions.append(
                    FieldRegion(
                        field_name=region_data["field_name"],
                        page=region_data["page"],
                        bbox=region_data["bbox"],
                        confidence=region_data["confidence"],
                        occurrence_count=region_data.get("occurrence_count", 1),
                    )
                )
            fields[field_name] = regions

        return cls(
            template_id=template_id,
            fields=fields,
            page_count=page_count,
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            sample_count=sample_count,
        )
