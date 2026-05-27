# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Integration tests: end-to-end flow (record → stats → drift → export → import).

Tests the full TemplateMemory facade with all new modules integrated.
"""

from dataclasses import dataclass
from typing import List

import pytest

from field_memory.facade import TemplateMemory

# --- Mock document objects ---


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


def make_invoice_doc():
    """Create a standard invoice document."""
    return make_doc(
        [
            ("Invoice Number", 0.05, 0.05, 0.20, 0.03, 1),
            ("Date", 0.70, 0.05, 0.15, 0.03, 1),
            ("Total Amount", 0.60, 0.85, 0.25, 0.03, 1),
            ("Customer Name", 0.05, 0.15, 0.30, 0.03, 1),
        ]
    )


def make_slightly_varied_invoice():
    """Create an invoice with slight positional variation (no drift)."""
    return make_doc(
        [
            ("Invoice Number", 0.06, 0.05, 0.20, 0.03, 1),
            ("Date", 0.70, 0.06, 0.15, 0.03, 1),
            ("Total Amount", 0.61, 0.85, 0.25, 0.03, 1),
            ("Customer Name", 0.05, 0.16, 0.30, 0.03, 1),
        ]
    )


def make_drifted_invoice():
    """Create an invoice with significant positional drift."""
    return make_doc(
        [
            ("Invoice Number", 0.50, 0.50, 0.20, 0.03, 1),  # moved far
            ("Date", 0.10, 0.80, 0.15, 0.03, 1),  # moved far
            ("Total Amount", 0.05, 0.05, 0.25, 0.03, 1),  # moved far
            ("Customer Name", 0.60, 0.60, 0.30, 0.03, 1),  # moved far
        ]
    )


def make_invoice_with_new_field():
    """Create an invoice with an extra field not in the template."""
    return make_doc(
        [
            ("Invoice Number", 0.05, 0.05, 0.20, 0.03, 1),
            ("Date", 0.70, 0.05, 0.15, 0.03, 1),
            ("Total Amount", 0.60, 0.85, 0.25, 0.03, 1),
            ("Customer Name", 0.05, 0.15, 0.30, 0.03, 1),
            ("Tax ID", 0.05, 0.25, 0.20, 0.03, 1),  # new field
        ]
    )


class TestEndToEndIntegration:
    """End-to-end integration test: record → stats → drift → export → import."""

    def test_full_workflow(self, tmp_path):
        """Test the complete workflow through the facade."""
        memory = TemplateMemory(
            store_path=tmp_path,
            decay_factor=0.95,
            drift_threshold=0.1,
        )

        # Step 1: Record several documents using batch_record
        documents = [make_invoice_doc() for _ in range(5)]
        documents.append(make_slightly_varied_invoice())

        batch_result = memory.batch_record(documents, template_id="invoice-001")

        assert batch_result.total_count == 6
        assert batch_result.success_count == 6
        assert batch_result.failure_count == 0
        for item in batch_result.results:
            assert item.status == "success"
            assert item.template_id == "invoice-001"

        # Step 2: Get stats and verify health grade
        stats = memory.get_stats("invoice-001")

        assert stats.template_id == "invoice-001"
        assert stats.field_count == 4
        assert stats.sample_count == 6
        assert stats.mean_confidence == pytest.approx(0.95, abs=0.01)
        assert stats.overall_health_grade in (
            "excellent",
            "good",
            "developing",
            "insufficient",
        )
        # With 6 samples and 0.95 confidence, should be "good"
        assert stats.overall_health_grade == "good"

        # Step 3: Get field stability
        stability = memory.get_field_stability("invoice-001")

        assert len(stability) == 4
        assert "Invoice Number" in stability
        assert "Date" in stability
        assert "Total Amount" in stability
        assert "Customer Name" in stability
        # All stability scores should be in [0.0, 1.0]
        for score in stability.values():
            assert 0.0 <= score <= 1.0

        # Step 4: Detect drift on a normal document (should not drift)
        normal_doc = make_slightly_varied_invoice()
        drift_report = memory.detect_drift(normal_doc, "invoice-001")

        assert drift_report.template_id == "invoice-001"
        # Slight variation should not trigger drift
        assert drift_report.overall_drift_score < 0.1

        # Step 5: Detect drift on a significantly drifted document
        drifted_doc = make_drifted_invoice()
        drift_report_drifted = memory.detect_drift(drifted_doc, "invoice-001")

        assert drift_report_drifted.is_drifting is True
        assert drift_report_drifted.overall_drift_score > 0.1
        assert len(drift_report_drifted.drifting_fields) > 0

        # Step 6: Detect new fields
        new_field_doc = make_invoice_with_new_field()
        drift_report_new = memory.detect_drift(new_field_doc, "invoice-001")

        assert "tax id" in drift_report_new.new_fields

        # Step 7: Export as JSON
        json_export = memory.export_template("invoice-001", fmt="json")

        assert isinstance(json_export, dict)
        assert json_export["template_id"] == "invoice-001"
        assert "fields" in json_export
        assert json_export["sample_count"] == 6

        # Step 8: Export as CSV
        csv_export = memory.export_template("invoice-001", fmt="csv")

        assert isinstance(csv_export, str)
        assert "field_name" in csv_export
        assert "Invoice Number" in csv_export

        # Step 9: Import into a fresh instance and verify
        memory2 = TemplateMemory(store_path=tmp_path / "fresh")
        imported_id = memory2.import_template(json_export)

        assert imported_id == "invoice-001"

        # Verify imported template matches
        imported_stats = memory2.get_stats(imported_id)
        assert imported_stats.field_count == stats.field_count
        assert imported_stats.sample_count == stats.sample_count

    def test_system_summary_after_multiple_templates(self, tmp_path):
        """Test system summary with multiple templates recorded."""
        memory = TemplateMemory(store_path=tmp_path, drift_threshold=0.1)

        # Record invoice documents
        for _ in range(6):
            memory.record(make_invoice_doc(), template_id="invoice")

        # Record a different template type
        form_doc = make_doc(
            [
                ("First Name", 0.05, 0.10, 0.30, 0.03, 1),
                ("Last Name", 0.05, 0.20, 0.30, 0.03, 1),
                ("Email", 0.05, 0.30, 0.30, 0.03, 1),
            ]
        )
        for _ in range(3):
            memory.record(form_doc, template_id="form")

        summary = memory.get_system_summary()

        assert summary.total_template_count == 2
        assert summary.total_documents_processed == 9
        assert summary.most_active_template == "invoice"
        assert len(summary.templates_ranked) == 2
        # First ranked should be invoice (6 samples > 3 samples)
        assert summary.templates_ranked[0]["template_id"] == "invoice"
        assert summary.templates_ranked[1]["template_id"] == "form"

    def test_drift_on_nonexistent_template_raises(self, tmp_path):
        """Detect drift raises ValueError for missing template."""
        memory = TemplateMemory(store_path=tmp_path)
        doc = make_invoice_doc()

        with pytest.raises(ValueError, match="Template not found"):
            memory.detect_drift(doc, "nonexistent")

    def test_export_nonexistent_template_raises(self, tmp_path):
        """Export raises ValueError for missing template."""
        memory = TemplateMemory(store_path=tmp_path)

        with pytest.raises(ValueError, match="Template not found"):
            memory.export_template("nonexistent", fmt="json")

    def test_export_unsupported_format_raises(self, tmp_path):
        """Export raises ValueError for unsupported format."""
        memory = TemplateMemory(store_path=tmp_path)
        memory.record(make_invoice_doc(), template_id="test")

        with pytest.raises(ValueError, match="Unsupported format"):
            memory.export_template("test", fmt="xml")

    def test_import_invalid_data_raises(self, tmp_path):
        """Import raises ValueError for invalid data."""
        memory = TemplateMemory(store_path=tmp_path)

        with pytest.raises(ValueError):
            memory.import_template({"invalid": "data"})

    def test_batch_record_with_mixed_results(self, tmp_path):
        """Batch record handles mix of valid and invalid documents."""
        memory = TemplateMemory(store_path=tmp_path)

        valid_doc = make_invoice_doc()
        invalid_doc = Document(pages=[Page(key_values=[])])

        result = memory.batch_record(
            [valid_doc, invalid_doc, valid_doc],
            template_id="mixed",
        )

        assert result.total_count == 3
        assert result.success_count == 2
        assert result.failure_count == 1
        assert result.results[0].status == "success"
        assert result.results[1].status == "failed"
        assert result.results[2].status == "success"

    def test_get_stats_nonexistent_raises(self, tmp_path):
        """get_stats raises ValueError for missing template."""
        memory = TemplateMemory(store_path=tmp_path)

        with pytest.raises(ValueError, match="Template not found"):
            memory.get_stats("nonexistent")

    def test_get_field_stability_nonexistent_raises(self, tmp_path):
        """get_field_stability raises ValueError for missing template."""
        memory = TemplateMemory(store_path=tmp_path)

        with pytest.raises(ValueError, match="Template not found"):
            memory.get_field_stability("nonexistent")

    def test_record_then_stats_single_document(self, tmp_path):
        """Record a single document and verify stats reflect it."""
        memory = TemplateMemory(store_path=tmp_path)

        memory.record(make_invoice_doc(), template_id="single")
        stats = memory.get_stats("single")

        assert stats.sample_count == 1
        assert stats.field_count == 4
        assert stats.overall_health_grade == "insufficient"
