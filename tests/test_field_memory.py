# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""End-to-end tests for the field_memory package."""

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pytest

from field_memory import (
    FieldLocationMap,
    FieldMatch,
    FieldRegion,
    TemplateMatch,
    TemplateMemory,
)

# --- Mock objects (simulates what Textract/textractor produces) ---


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
    max_pg = max(pages_dict.keys())
    pages = [Page(key_values=pages_dict.get(p, [])) for p in range(1, max_pg + 1)]
    return Document(pages=pages)


class TestTemplateMemoryRecordAndLocate:
    def test_record_and_locate(self, tmp_path):
        memory = TemplateMemory(store_path=tmp_path)
        doc = make_doc(
            [
                ("Employee Name", 0.05, 0.10, 0.35, 0.03, 1),
                ("Date of Birth", 0.05, 0.20, 0.20, 0.03, 1),
            ]
        )
        tid = memory.record(doc, template_id="form")
        assert tid == "form"

        matches = memory.locate(doc, "Employee Name")
        assert len(matches) > 0
        assert matches[0].combined_score > 0.5
        assert matches[0].within_expected_region is True

    def test_record_no_fields_raises(self, tmp_path):
        memory = TemplateMemory(store_path=tmp_path)
        doc = Document(pages=[Page(key_values=[])])
        with pytest.raises(ValueError, match="No key-value fields"):
            memory.record(doc)

    def test_template_refinement(self, tmp_path):
        memory = TemplateMemory(store_path=tmp_path)
        for _ in range(5):
            doc = make_doc([("Name", 0.05, 0.10, 0.30, 0.03, 1)])
            memory.record(doc, template_id="form")
        t = memory.get_template("form")
        assert t.sample_count == 5

    def test_locate_empty_returns_empty(self, tmp_path):
        memory = TemplateMemory(store_path=tmp_path)
        doc = make_doc([("Name", 0.05, 0.10, 0.30, 0.03, 1)])
        assert memory.locate(doc, "Name") == []


class TestTemplateIdentification:
    def test_identify_correct_template(self, tmp_path):
        memory = TemplateMemory(store_path=tmp_path, similarity_threshold=0.5)
        doc1 = make_doc(
            [
                ("Employee Name", 0.05, 0.10, 0.35, 0.03, 1),
                ("SSN", 0.05, 0.20, 0.20, 0.03, 1),
            ]
        )
        doc2 = make_doc(
            [
                ("Invoice Number", 0.60, 0.05, 0.20, 0.03, 1),
                ("Total", 0.60, 0.80, 0.15, 0.03, 1),
            ]
        )
        memory.record(doc1, template_id="employment")
        memory.record(doc2, template_id="invoice")

        match = memory.identify_template(doc1)
        assert match is not None
        assert match.template_id == "employment"

        match = memory.identify_template(doc2)
        assert match is not None
        assert match.template_id == "invoice"

    def test_identify_no_match(self, tmp_path):
        memory = TemplateMemory(store_path=tmp_path, similarity_threshold=0.9)
        memory.record(
            make_doc([("Name", 0.05, 0.10, 0.30, 0.03, 1)]), template_id="form"
        )
        unknown = make_doc([("Totally Different", 0.50, 0.50, 0.20, 0.03, 1)])
        assert memory.identify_template(unknown) is None


class TestAnomalyDetection:
    def test_field_in_wrong_position(self, tmp_path):
        memory = TemplateMemory(store_path=tmp_path, similarity_threshold=0.4)
        # Train: field at top-left
        doc = make_doc(
            [
                ("Employee Name", 0.05, 0.10, 0.35, 0.03, 1),
                ("SSN", 0.05, 0.20, 0.20, 0.03, 1),
            ]
        )
        memory.record(doc, template_id="form")

        # Test: same fields but "Employee Name" moved to bottom-right
        anomalous = make_doc(
            [
                ("Employee Name", 0.70, 0.85, 0.25, 0.03, 1),
                ("SSN", 0.05, 0.20, 0.20, 0.03, 1),
            ]
        )
        matches = memory.locate(anomalous, "Employee Name")
        # The match at (0.70, 0.85) should have low spatial score
        best = matches[0]
        assert best.spatial_score < 0.5
        assert best.within_expected_region is False


class TestTemplateManagement:
    def test_list_and_delete(self, tmp_path):
        memory = TemplateMemory(store_path=tmp_path)
        doc = make_doc([("Name", 0.05, 0.10, 0.30, 0.03, 1)])
        memory.record(doc, template_id="test-template")

        assert "test-template" in memory.list_templates()
        memory.delete_template("test-template")
        assert "test-template" not in memory.list_templates()

    def test_get_template(self, tmp_path):
        memory = TemplateMemory(store_path=tmp_path)
        doc = make_doc([("Name", 0.05, 0.10, 0.30, 0.03, 1)])
        memory.record(doc, template_id="my-form")

        t = memory.get_template("my-form")
        assert t is not None
        assert t.template_id == "my-form"
        assert "Name" in t.fields

    def test_get_nonexistent_returns_none(self, tmp_path):
        memory = TemplateMemory(store_path=tmp_path)
        assert memory.get_template("nope") is None
