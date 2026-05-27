# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
textract-field-memory — Analytics & Monitoring Demo
=====================================================

Demonstrates the analytics, drift detection, batch processing,
and export/import capabilities.

Usage:
    cd textract-field-memory
    pip install -e .
    python examples/analytics_demo.py
"""

import random
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

from field_memory import TemplateMemory


# =============================================================================
# Mock document objects
# =============================================================================

@dataclass
class Word:
    """A single word token."""

    text: str


@dataclass
class BBox:
    """Bounding box with normalized coordinates."""

    x: float
    y: float
    width: float
    height: float


@dataclass
class KeyValue:
    """A key-value pair extracted from a document."""

    key: List[Word]
    bbox: BBox
    page: int
    confidence: float = 0.95


@dataclass
class Page:
    """A single page of a document."""

    key_values: List[KeyValue]


@dataclass
class Document:
    """A multi-page document."""

    pages: List[Page]


# =============================================================================
# Document generators
# =============================================================================

def make_employment_form(variation: float = 0.0) -> Document:
    """Simulate an employment form with optional positional jitter."""
    def jitter(v):
        if variation:
            return max(0.001, min(0.95, v + random.uniform(-variation, variation)))  # nosec B311
        return v

    fields = [
        ("Employee Name", 0.05, 0.08, 0.35, 0.03),
        ("Date of Birth", 0.05, 0.14, 0.20, 0.03),
        ("SSN", 0.05, 0.20, 0.15, 0.03),
        ("Address", 0.05, 0.26, 0.45, 0.03),
        ("City", 0.05, 0.32, 0.20, 0.03),
        ("State", 0.30, 0.32, 0.10, 0.03),
        ("Zip Code", 0.45, 0.32, 0.12, 0.03),
        ("Phone Number", 0.05, 0.38, 0.20, 0.03),
        ("Email", 0.05, 0.44, 0.30, 0.03),
        ("Position Applied For", 0.05, 0.50, 0.30, 0.03),
        ("Start Date", 0.05, 0.56, 0.15, 0.03),
        ("Salary Expected", 0.30, 0.56, 0.15, 0.03),
    ]
    kvs = [
        KeyValue(
            key=[Word(w) for w in name.split()],
            bbox=BBox(jitter(x), jitter(y), w, h),
            page=1,
            confidence=random.uniform(0.88, 0.99)  # nosec B311,
        )
        for name, x, y, w, h in fields
    ]
    return Document(pages=[Page(key_values=kvs)])


def make_invoice(variation: float = 0.0) -> Document:
    """Simulate an invoice document."""
    def jitter(v):
        if variation:
            return max(0.001, min(0.95, v + random.uniform(-variation, variation)))  # nosec B311
        return v

    fields = [
        ("Invoice Number", 0.60, 0.05, 0.20, 0.03),
        ("Invoice Date", 0.60, 0.10, 0.15, 0.03),
        ("Due Date", 0.60, 0.15, 0.15, 0.03),
        ("Bill To", 0.05, 0.20, 0.30, 0.03),
        ("Ship To", 0.45, 0.20, 0.30, 0.03),
        ("Subtotal", 0.60, 0.70, 0.15, 0.03),
        ("Tax", 0.60, 0.75, 0.15, 0.03),
        ("Total", 0.60, 0.80, 0.15, 0.03),
    ]
    kvs = [
        KeyValue(
            key=[Word(w) for w in name.split()],
            bbox=BBox(jitter(x), jitter(y), w, h),
            page=1,
            confidence=random.uniform(0.88, 0.99)  # nosec B311,
        )
        for name, x, y, w, h in fields
    ]
    return Document(pages=[Page(key_values=kvs)])


def make_drifted_form() -> Document:
    """Simulate an employment form where fields have shifted positions."""
    fields = [
        ("Employee Name", 0.10, 0.12, 0.35, 0.03),   # shifted right+down
        ("Date of Birth", 0.10, 0.18, 0.20, 0.03),   # shifted right+down
        ("SSN", 0.10, 0.24, 0.15, 0.03),             # shifted right+down
        ("Address", 0.10, 0.30, 0.45, 0.03),         # shifted right+down
        ("City", 0.10, 0.36, 0.20, 0.03),            # shifted right+down
        ("State", 0.35, 0.36, 0.10, 0.03),           # shifted right+down
        ("Zip Code", 0.50, 0.36, 0.12, 0.03),        # shifted right+down
        ("Phone Number", 0.10, 0.42, 0.20, 0.03),    # shifted right+down
        ("Email", 0.10, 0.48, 0.30, 0.03),           # shifted right+down
        ("Position Applied For", 0.10, 0.54, 0.30, 0.03),
        ("Start Date", 0.10, 0.60, 0.15, 0.03),
        ("Salary Expected", 0.35, 0.60, 0.15, 0.03),
        ("Emergency Contact", 0.10, 0.66, 0.30, 0.03),  # NEW field
    ]
    kvs = [
        KeyValue(
            key=[Word(w) for w in name.split()],
            bbox=BBox(x, y, w, h),
            page=1,
            confidence=random.uniform(0.90, 0.98)  # nosec B311,
        )
        for name, x, y, w, h in fields
    ]
    return Document(pages=[Page(key_values=kvs)])


# =============================================================================
# Demo
# =============================================================================

def main():
    """Run the analytics and monitoring demo."""
    random.seed(42)

    print("""
╔══════════════════════════════════════════════════════════════╗
║   textract-field-memory — Analytics & Monitoring Demo        ║
╚══════════════════════════════════════════════════════════════╝
""")

    with tempfile.TemporaryDirectory() as tmp:
        memory = TemplateMemory(
            store_path=Path(tmp),
            similarity_threshold=0.5,
            decay_factor=0.95,
            drift_threshold=0.1,
        )

        # ─────────────────────────────────────────────────────────────
        # STEP 1: Train templates with batch processing
        # ─────────────────────────────────────────────────────────────
        print("─── Step 1: Batch Processing ───────────────────────────────\n")

        # Create batches of documents
        emp_batch = [make_employment_form(variation=0.01) for _ in range(15)]
        inv_batch = [make_invoice(variation=0.01) for _ in range(8)]

        print("  Processing 15 employment forms in batch...")
        emp_result = memory.batch_record(emp_batch, template_id="employment-form")
        print(f"    Success: {emp_result.success_count}/{emp_result.total_count}")
        print(f"    Failures: {emp_result.failure_count}")

        print("\n  Processing 8 invoices in batch...")
        inv_result = memory.batch_record(inv_batch, template_id="invoice")
        print(f"    Success: {inv_result.success_count}/{inv_result.total_count}")
        print(f"    Failures: {inv_result.failure_count}")

        # Batch with a bad document mixed in
        print("\n  Processing batch with one invalid document...")
        mixed_batch = [
            make_employment_form(variation=0.01),
            Document(pages=[Page(key_values=[])]),  # empty — will fail
            make_employment_form(variation=0.01),
        ]
        mixed_result = memory.batch_record(mixed_batch, template_id="employment-form")
        print(f"    Success: {mixed_result.success_count}/{mixed_result.total_count}")
        print(f"    Failures: {mixed_result.failure_count}")
        for item in mixed_result.results:
            if item.status == "failed":
                print(f"    Doc {item.index} failed: {item.error}")

        # ─────────────────────────────────────────────────────────────
        # STEP 2: Template Health Reports
        # ─────────────────────────────────────────────────────────────
        print("\n─── Step 2: Template Health Reports ────────────────────────\n")

        emp_stats = memory.get_stats("employment-form")
        print(f"  employment-form:")
        print(f"    Health grade:    {emp_stats.overall_health_grade}")
        print(f"    Fields:          {emp_stats.field_count}")
        print(f"    Samples:         {emp_stats.sample_count}")
        print(f"    Mean confidence: {emp_stats.mean_confidence:.4f}")
        print(f"    Min confidence:  {emp_stats.min_confidence:.4f}")
        print(f"    Max confidence:  {emp_stats.max_confidence:.4f}")

        inv_stats = memory.get_stats("invoice")
        print(f"\n  invoice:")
        print(f"    Health grade:    {inv_stats.overall_health_grade}")
        print(f"    Fields:          {inv_stats.field_count}")
        print(f"    Samples:         {inv_stats.sample_count}")
        print(f"    Mean confidence: {inv_stats.mean_confidence:.4f}")

        # ─────────────────────────────────────────────────────────────
        # STEP 3: Field Stability Scoring
        # ─────────────────────────────────────────────────────────────
        print("\n─── Step 3: Field Stability Scores ─────────────────────────\n")

        stability = memory.get_field_stability("employment-form")
        print(f"  {'Field':<25} {'Stability':>10}")
        print(f"  {'─' * 25} {'─' * 10}")
        for field_name, score in sorted(
            stability.items(), key=lambda x: x[1], reverse=True
        ):
            indicator = "✓" if score > 0.8 else "⚠️" if score > 0.5 else "✗"
            print(f"  {field_name:<25} {score:>8.3f}  {indicator}")

        # ─────────────────────────────────────────────────────────────
        # STEP 4: Drift Detection
        # ─────────────────────────────────────────────────────────────
        print("\n─── Step 4: Drift Detection ────────────────────────────────\n")

        # Normal document — no drift expected
        normal_doc = make_employment_form(variation=0.01)
        normal_drift = memory.detect_drift(normal_doc, "employment-form")
        print(f"  Normal document:")
        print(f"    Overall drift: {normal_drift.overall_drift_score:.4f}")
        print(f"    Is drifting:   {normal_drift.is_drifting}")

        # Drifted document — fields have shifted
        drifted_doc = make_drifted_form()
        drifted_drift = memory.detect_drift(drifted_doc, "employment-form")
        print(f"\n  Drifted document (fields shifted right+down):")
        print(f"    Overall drift: {drifted_drift.overall_drift_score:.4f}")
        print(f"    Is drifting:   {drifted_drift.is_drifting}")
        if drifted_drift.drifting_fields:
            print(f"    Drifting fields ({len(drifted_drift.drifting_fields)}):")
            for field in drifted_drift.drifting_fields[:5]:
                # Find the drift score for this field
                for fd in drifted_drift.field_drifts:
                    if fd.field_name == field:
                        print(f"      • {field}: {fd.drift_score:.4f}")
                        break
        if drifted_drift.new_fields:
            print(f"    New fields: {drifted_drift.new_fields}")
        if drifted_drift.missing_fields:
            print(f"    Missing fields: {drifted_drift.missing_fields}")

        # ─────────────────────────────────────────────────────────────
        # STEP 5: System-Wide Summary
        # ─────────────────────────────────────────────────────────────
        print("\n─── Step 5: System-Wide Summary ────────────────────────────\n")

        summary = memory.get_system_summary()
        print(f"  Total templates:        {summary.total_template_count}")
        print(f"  Documents processed:    {summary.total_documents_processed}")
        print(f"  Overall health:         {summary.mean_template_health_grade}")
        print(f"  Most active template:   {summary.most_active_template}")
        print(f"\n  Templates by health grade:")
        for grade, count in summary.templates_by_health_grade.items():
            print(f"    {grade}: {count}")
        print(f"\n  Templates ranked by activity:")
        for t in summary.templates_ranked:
            print(
                f"    {t['template_id']:<20} "
                f"samples={t['sample_count']:<4} "
                f"grade={t['health_grade']}"
            )

        # ─────────────────────────────────────────────────────────────
        # STEP 6: Export & Import
        # ─────────────────────────────────────────────────────────────
        print("\n─── Step 6: Export & Import ─────────────────────────────────\n")

        # Export as JSON
        json_data = memory.export_template("employment-form", fmt="json")
        print(f"  JSON export keys: {list(json_data.keys())}")
        print(f"  Template ID: {json_data['template_id']}")
        print(f"  Fields: {len(json_data['fields'])}")

        # Export as CSV
        csv_data = memory.export_template("employment-form", fmt="csv")
        csv_lines = csv_data.strip().split("\n")
        print(f"\n  CSV export: {len(csv_lines)} lines (1 header + {len(csv_lines)-1} data rows)")
        print(f"  Header: {csv_lines[0]}")
        print(f"  First row: {csv_lines[1]}")

        # Import into a fresh memory instance
        memory2 = TemplateMemory(
            store_path=Path(tmp) / "imported",
            similarity_threshold=0.5,
        )
        imported_id = memory2.import_template(json_data)
        print(f"\n  Imported template: '{imported_id}'")
        imported_template = memory2.get_template(imported_id)
        print(f"  Verified: {len(imported_template.fields)} fields, "
              f"sample_count={imported_template.sample_count}")

        # ─────────────────────────────────────────────────────────────
        # STEP 7: Confidence Decay in Action
        # ─────────────────────────────────────────────────────────────
        print("\n─── Step 7: Confidence Decay ───────────────────────────────\n")

        # Show how decay affects template over many merges
        decay_memory = TemplateMemory(
            store_path=Path(tmp) / "decay_test",
            similarity_threshold=0.5,
            decay_factor=0.95,
        )

        # Record initial document
        initial_doc = make_employment_form(variation=0.0)
        decay_memory.record(initial_doc, template_id="decay-test")

        t = decay_memory.get_template("decay-test")
        initial_count = t.fields["Employee Name"][0].occurrence_count
        print(f"  Initial occurrence_count: {initial_count}")

        # Record 14 more documents (weight should approximately halve)
        for _ in range(14):
            decay_memory.record(
                make_employment_form(variation=0.005),
                template_id="decay-test",
            )

        t = decay_memory.get_template("decay-test")
        final_count = t.fields["Employee Name"][0].occurrence_count
        print(f"  After 14 merges: occurrence_count = {final_count}")
        print(f"  (With decay=0.95, old observations lose ~50% weight over 14 merges)")

        # Compare with no-decay
        no_decay_memory = TemplateMemory(
            store_path=Path(tmp) / "no_decay_test",
            similarity_threshold=0.5,
            decay_factor=1.0,
        )
        no_decay_memory.record(initial_doc, template_id="no-decay-test")
        for _ in range(14):
            no_decay_memory.record(
                make_employment_form(variation=0.005),
                template_id="no-decay-test",
            )
        t_no_decay = no_decay_memory.get_template("no-decay-test")
        no_decay_count = t_no_decay.fields["Employee Name"][0].occurrence_count
        print(f"  Without decay (factor=1.0): occurrence_count = {no_decay_count}")

        # ─────────────────────────────────────────────────────────────
        # Summary
        # ─────────────────────────────────────────────────────────────
        print("""
╔══════════════════════════════════════════════════════════════╗
║  Analytics Demo Complete                                     ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  What you saw:                                               ║
║  1. Batch processing with error isolation                    ║
║  2. Template health reports (grades, confidence stats)       ║
║  3. Field stability scoring (per-field reliability)          ║
║  4. Drift detection (template change monitoring)             ║
║  5. System-wide analytics dashboard                          ║
║  6. Export/Import (JSON and CSV)                             ║
║  7. Confidence decay (adaptive template learning)            ║
║                                                              ║
║  Production usage:                                           ║
║                                                              ║
║    # Daily health check                                      ║
║    summary = memory.get_system_summary()                     ║
║    for t in summary.templates_ranked:                        ║
║        if t["health_grade"] == "insufficient":               ║
║            alert(f"Template {t['template_id']} needs help")  ║
║                                                              ║
║    # Drift monitoring                                        ║
║    drift = memory.detect_drift(doc, template_id)             ║
║    if drift.is_drifting:                                     ║
║        alert(f"Template changing: {drift.drifting_fields}")  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
