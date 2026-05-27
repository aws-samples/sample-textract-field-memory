# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for the export/import module."""

import csv
import io
from dataclasses import dataclass
from typing import List

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from field_memory.export import TemplateExporter
from field_memory.models import FieldLocationMap, FieldRegion
from field_memory.store import TemplateStore

# --- Hypothesis Strategies for generating valid FieldLocationMaps ---


def bbox_strategy():
    """Generate valid bounding boxes where x+width <= 1.0 and y+height <= 1.0."""
    return st.fixed_dictionaries(
        {
            "x": st.floats(min_value=0.0, max_value=0.49),
            "y": st.floats(min_value=0.0, max_value=0.49),
            "width": st.floats(min_value=0.01, max_value=0.5),
            "height": st.floats(min_value=0.01, max_value=0.5),
        }
    ).filter(lambda b: b["x"] + b["width"] <= 1.0 and b["y"] + b["height"] <= 1.0)


def field_region_strategy(field_name=None):
    """Generate a valid FieldRegion."""
    if field_name is None:
        name_st = st.text(
            alphabet=st.characters(whitelist_categories=("L", "N", "Zs")),
            min_size=1,
            max_size=20,
        ).filter(lambda s: s.strip())
    else:
        name_st = st.just(field_name)

    return st.builds(
        FieldRegion,
        field_name=name_st,
        page=st.integers(min_value=1, max_value=5),
        bbox=bbox_strategy(),
        confidence=st.floats(min_value=0.0, max_value=1.0),
        occurrence_count=st.integers(min_value=1, max_value=100),
    )


def field_location_map_strategy():
    """Generate a valid FieldLocationMap with 1-5 fields, each with 1-3 regions."""
    return st.text(
        alphabet=st.characters(whitelist_categories=("L", "N")),
        min_size=1,
        max_size=20,
    ).flatmap(
        lambda tid: st.builds(
            _build_flm,
            template_id=st.just(tid),
            page_count=st.integers(min_value=1, max_value=5),
            sample_count=st.integers(min_value=1, max_value=100),
            num_fields=st.integers(min_value=1, max_value=5),
        )
    )


def _build_flm(template_id, page_count, sample_count, num_fields):
    """Build a FieldLocationMap with generated fields."""
    import random
    import string

    fields = {}
    for i in range(num_fields):
        field_name = f"Field{i}"
        # Generate 1-3 regions per field
        num_regions = random.randint(1, 3)
        regions = []
        for _ in range(num_regions):
            x = random.uniform(0.0, 0.49)
            y = random.uniform(0.0, 0.49)
            w = random.uniform(0.01, min(0.5, 1.0 - x))
            h = random.uniform(0.01, min(0.5, 1.0 - y))
            regions.append(
                FieldRegion(
                    field_name=field_name,
                    page=random.randint(1, page_count),
                    bbox={"x": x, "y": y, "width": w, "height": h},
                    confidence=random.uniform(0.0, 1.0),
                    occurrence_count=random.randint(1, 50),
                )
            )
        fields[field_name] = regions

    return FieldLocationMap(
        template_id=template_id,
        fields=fields,
        page_count=page_count,
        sample_count=sample_count,
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-02T00:00:00Z",
    )


# --- Property-Based Tests ---


class TestJsonRoundTripProperty:
    """Property test: JSON export/import round-trip produces equivalent FieldLocationMap.

    **Validates: Requirements 6.5, 6.6**

    For any valid FieldLocationMap, exporting to JSON and importing back
    produces a FieldLocationMap with identical attributes.
    """

    @given(
        template_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
        page_count=st.integers(min_value=1, max_value=5),
        sample_count=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=50, deadline=None)
    def test_json_round_trip(
        self, tmp_path_factory, template_id, page_count, sample_count
    ):
        """Export then import produces equivalent FieldLocationMap."""
        tmp_path = tmp_path_factory.mktemp("export")
        store = TemplateStore(tmp_path)

        # Build a FieldLocationMap with deterministic fields
        flm = FieldLocationMap(
            template_id=template_id,
            page_count=page_count,
            sample_count=sample_count,
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-02T00:00:00Z",
            fields={
                "TestField": [
                    FieldRegion(
                        field_name="TestField",
                        page=1,
                        bbox={"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1},
                        confidence=0.95,
                        occurrence_count=5,
                    )
                ]
            },
        )

        store.save(template_id, flm)
        exporter = TemplateExporter(store)

        # Export to JSON
        exported = exporter.export_json(template_id)

        # Import into a fresh store
        tmp_path2 = tmp_path_factory.mktemp("import")
        store2 = TemplateStore(tmp_path2)
        exporter2 = TemplateExporter(store2)
        imported_id = exporter2.import_json(exported)

        # Verify round-trip
        assert imported_id == template_id
        imported_flm = store2.load(imported_id)
        assert imported_flm is not None
        assert imported_flm.template_id == flm.template_id
        assert imported_flm.page_count == flm.page_count
        assert imported_flm.sample_count == flm.sample_count
        assert imported_flm.created_at == flm.created_at
        assert imported_flm.updated_at == flm.updated_at
        assert set(imported_flm.fields.keys()) == set(flm.fields.keys())

        for field_name in flm.fields:
            orig_regions = flm.fields[field_name]
            imported_regions = imported_flm.fields[field_name]
            assert len(imported_regions) == len(orig_regions)
            for orig, imp in zip(orig_regions, imported_regions):
                assert imp.field_name == orig.field_name
                assert imp.page == orig.page
                assert abs(imp.bbox["x"] - orig.bbox["x"]) < 1e-10
                assert abs(imp.bbox["y"] - orig.bbox["y"]) < 1e-10
                assert abs(imp.bbox["width"] - orig.bbox["width"]) < 1e-10
                assert abs(imp.bbox["height"] - orig.bbox["height"]) < 1e-10
                assert abs(imp.confidence - orig.confidence) < 1e-10
                assert imp.occurrence_count == orig.occurrence_count


# --- Example-Based Tests ---


class TestExportExampleTests:
    """Example tests for export/import edge cases.

    **Validates: Requirements 6.3, 6.5**
    """

    def test_invalid_import_raises_valueerror(self, tmp_path):
        """Importing invalid data raises ValueError."""
        store = TemplateStore(tmp_path)
        exporter = TemplateExporter(store)

        # Missing required keys
        with pytest.raises(ValueError):
            exporter.import_json({})

        # Missing template_id
        with pytest.raises(ValueError):
            exporter.import_json(
                {
                    "page_count": 1,
                    "sample_count": 1,
                    "fields": {},
                }
            )

        # Invalid page_count
        with pytest.raises(ValueError):
            exporter.import_json(
                {
                    "template_id": "test",
                    "page_count": 0,
                    "sample_count": 1,
                    "fields": {},
                }
            )

        # Invalid sample_count
        with pytest.raises(ValueError):
            exporter.import_json(
                {
                    "template_id": "test",
                    "page_count": 1,
                    "sample_count": 0,
                    "fields": {},
                }
            )

    def test_csv_has_correct_headers(self, tmp_path):
        """CSV export has the expected header row."""
        store = TemplateStore(tmp_path)
        flm = FieldLocationMap(
            template_id="test-csv",
            page_count=1,
            sample_count=5,
            fields={
                "Employee Name": [
                    FieldRegion(
                        field_name="Employee Name",
                        page=1,
                        bbox={"x": 0.05, "y": 0.10, "width": 0.35, "height": 0.03},
                        confidence=0.95,
                        occurrence_count=10,
                    )
                ]
            },
        )
        store.save("test-csv", flm)
        exporter = TemplateExporter(store)

        csv_output = exporter.export_csv("test-csv")
        reader = csv.reader(io.StringIO(csv_output))
        headers = next(reader)

        expected_headers = [
            "field_name",
            "page",
            "x",
            "y",
            "width",
            "height",
            "confidence",
            "occurrence_count",
        ]
        assert headers == expected_headers

    def test_csv_data_rows(self, tmp_path):
        """CSV export contains correct data rows."""
        store = TemplateStore(tmp_path)
        flm = FieldLocationMap(
            template_id="test-csv",
            page_count=1,
            sample_count=5,
            fields={
                "Employee Name": [
                    FieldRegion(
                        field_name="Employee Name",
                        page=1,
                        bbox={"x": 0.05, "y": 0.10, "width": 0.35, "height": 0.03},
                        confidence=0.95,
                        occurrence_count=10,
                    )
                ]
            },
        )
        store.save("test-csv", flm)
        exporter = TemplateExporter(store)

        csv_output = exporter.export_csv("test-csv")
        reader = csv.reader(io.StringIO(csv_output))
        next(reader)  # skip header
        row = next(reader)

        assert row[0] == "Employee Name"
        assert row[1] == "1"
        assert float(row[2]) == pytest.approx(0.05)
        assert float(row[3]) == pytest.approx(0.10)
        assert float(row[4]) == pytest.approx(0.35)
        assert float(row[5]) == pytest.approx(0.03)
        assert float(row[6]) == pytest.approx(0.95)
        assert row[7] == "10"

    def test_missing_template_raises_valueerror_for_json_export(self, tmp_path):
        """Exporting a non-existent template raises ValueError."""
        store = TemplateStore(tmp_path)
        exporter = TemplateExporter(store)

        with pytest.raises(ValueError, match="Template not found"):
            exporter.export_json("nonexistent")

    def test_missing_template_raises_valueerror_for_csv_export(self, tmp_path):
        """Exporting a non-existent template as CSV raises ValueError."""
        store = TemplateStore(tmp_path)
        exporter = TemplateExporter(store)

        with pytest.raises(ValueError, match="Template not found"):
            exporter.export_csv("nonexistent")

    def test_json_export_matches_to_dict(self, tmp_path):
        """JSON export produces the same output as FieldLocationMap.to_dict()."""
        store = TemplateStore(tmp_path)
        flm = FieldLocationMap(
            template_id="test-json",
            page_count=1,
            sample_count=3,
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-02T00:00:00Z",
            fields={
                "Name": [
                    FieldRegion(
                        field_name="Name",
                        page=1,
                        bbox={"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1},
                        confidence=0.9,
                        occurrence_count=3,
                    )
                ]
            },
        )
        store.save("test-json", flm)
        exporter = TemplateExporter(store)

        exported = exporter.export_json("test-json")
        expected = flm.to_dict()
        assert exported == expected

    def test_import_valid_json(self, tmp_path):
        """Importing valid JSON stores the template and returns template_id."""
        store = TemplateStore(tmp_path)
        exporter = TemplateExporter(store)

        data = {
            "template_id": "imported-form",
            "page_count": 1,
            "sample_count": 5,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
            "fields": {
                "Name": [
                    {
                        "field_name": "Name",
                        "page": 1,
                        "bbox": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.1},
                        "confidence": 0.9,
                        "occurrence_count": 5,
                    }
                ]
            },
        }

        result_id = exporter.import_json(data)
        assert result_id == "imported-form"

        # Verify it was stored
        loaded = store.load("imported-form")
        assert loaded is not None
        assert loaded.template_id == "imported-form"
        assert loaded.page_count == 1
        assert loaded.sample_count == 5
