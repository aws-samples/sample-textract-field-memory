# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Export/Import module for template data in JSON and CSV formats."""

import csv
import io
from typing import Any, Dict

from field_memory.models import FieldLocationMap
from field_memory.store import TemplateStore


class TemplateExporter:
    """Exports and imports template data in JSON and CSV formats.

    Supports round-trip JSON export/import and CSV export for
    interoperability with external systems.
    """

    def __init__(self, store: TemplateStore):
        """Initialize with a TemplateStore instance.

        Args:
            store: The template store for loading and saving templates.
        """
        self._store = store

    def export_json(self, template_id: str) -> Dict[str, Any]:
        """Export template as a JSON-serializable dictionary.

        Uses the same schema as the store (FieldLocationMap.to_dict()).

        Args:
            template_id: The template to export.

        Returns:
            Dictionary representation of the template.

        Raises:
            ValueError: If the template is not found.
        """
        flm = self._store.load(template_id)
        if flm is None:
            raise ValueError(f"Template not found: {template_id}")
        return flm.to_dict()

    def export_csv(self, template_id: str) -> str:
        """Export template fields as a CSV string.

        Columns: field_name, page, x, y, width, height, confidence, occurrence_count

        Args:
            template_id: The template to export.

        Returns:
            CSV-formatted string with header row and one row per FieldRegion.

        Raises:
            ValueError: If the template is not found.
        """
        flm = self._store.load(template_id)
        if flm is None:
            raise ValueError(f"Template not found: {template_id}")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "field_name",
                "page",
                "x",
                "y",
                "width",
                "height",
                "confidence",
                "occurrence_count",
            ]
        )

        for _field_name, regions in flm.fields.items():
            for region in regions:
                writer.writerow(
                    [
                        region.field_name,
                        region.page,
                        region.bbox["x"],
                        region.bbox["y"],
                        region.bbox["width"],
                        region.bbox["height"],
                        region.confidence,
                        region.occurrence_count,
                    ]
                )

        return output.getvalue()

    def import_json(self, data: Dict[str, Any]) -> str:
        """Import a template from a JSON dictionary.

        Validates the data using FieldLocationMap.from_dict() and stores it.

        Args:
            data: Dictionary containing template data with required keys:
                  template_id, page_count, sample_count, fields.

        Returns:
            The template_id of the imported template.

        Raises:
            ValueError: If the data is invalid or missing required keys.
        """
        try:
            flm = FieldLocationMap.from_dict(data)
        except (ValueError, KeyError, TypeError) as e:
            raise ValueError(f"Invalid template data: {e}") from e

        self._store.save(flm.template_id, flm)
        return flm.template_id
