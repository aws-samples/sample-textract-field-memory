# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
textract-field-memory — Working Demo
=====================================

Run this demo with no dependencies other than the field_memory package itself.
No AWS credentials, no Textract calls, no external libraries needed.

Usage:
    cd textract-field-memory
    pip install -e .
    python examples/demo.py
"""

import random
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List

from field_memory import TemplateMemory, FieldMatch, TemplateMatch


# =============================================================================
# Mock document objects (simulates what Textract/textractor produces)
# =============================================================================

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


# =============================================================================
# Document generators (simulates different form types)
# =============================================================================

def make_employment_form(variation: float = 0.0) -> Document:
    """Simulate an employment form with optional positional jitter."""
    def j(v):
        return max(0.001, min(0.95, v + random.uniform(-variation, variation)))  # nosec B311 if variation else v

    fields = [
        ("Employee Name",       0.05, 0.08, 0.35, 0.03),
        ("Date of Birth",       0.05, 0.14, 0.20, 0.03),
        ("SSN",                 0.05, 0.20, 0.15, 0.03),
        ("Address",             0.05, 0.26, 0.45, 0.03),
        ("City",                0.05, 0.32, 0.20, 0.03),
        ("State",               0.30, 0.32, 0.10, 0.03),
        ("Zip Code",            0.45, 0.32, 0.12, 0.03),
        ("Phone Number",        0.05, 0.38, 0.20, 0.03),
        ("Email",               0.05, 0.44, 0.30, 0.03),
        ("Position Applied For",0.05, 0.50, 0.30, 0.03),
        ("Start Date",          0.05, 0.56, 0.15, 0.03),
        ("Salary Expected",     0.30, 0.56, 0.15, 0.03),
    ]
    kvs = [
        KeyValue(
            key=[Word(w) for w in name.split()],
            bbox=BBox(j(x), j(y), w, h),
            page=1,
            confidence=random.uniform(0.88, 0.99)  # nosec B311,
        )
        for name, x, y, w, h in fields
    ]
    return Document(pages=[Page(key_values=kvs)])


def make_invoice(variation: float = 0.0) -> Document:
    """Simulate an invoice document."""
    def j(v):
        return max(0.001, min(0.95, v + random.uniform(-variation, variation)))  # nosec B311 if variation else v

    fields = [
        ("Invoice Number", 0.60, 0.05, 0.20, 0.03),
        ("Invoice Date",   0.60, 0.10, 0.15, 0.03),
        ("Due Date",       0.60, 0.15, 0.15, 0.03),
        ("Bill To",        0.05, 0.20, 0.30, 0.03),
        ("Ship To",        0.45, 0.20, 0.30, 0.03),
        ("Subtotal",       0.60, 0.70, 0.15, 0.03),
        ("Tax",            0.60, 0.75, 0.15, 0.03),
        ("Total",          0.60, 0.80, 0.15, 0.03),
    ]
    kvs = [
        KeyValue(
            key=[Word(w) for w in name.split()],
            bbox=BBox(j(x), j(y), w, h),
            page=1,
            confidence=random.uniform(0.88, 0.99)  # nosec B311,
        )
        for name, x, y, w, h in fields
    ]
    return Document(pages=[Page(key_values=kvs)])


# =============================================================================
# Demo
# =============================================================================

def main():
    random.seed(42)

    print("""
╔══════════════════════════════════════════════════════════════╗
║         textract-field-memory — Working Demo                 ║
╚══════════════════════════════════════════════════════════════╝
""")

    with tempfile.TemporaryDirectory() as tmp:
        memory = TemplateMemory(store_path=Path(tmp), similarity_threshold=0.5)

        # ─────────────────────────────────────────────────────────────
        # STEP 1: Record templates
        # ─────────────────────────────────────────────────────────────
        print("─── Step 1: Record Templates ───────────────────────────────\n")
        print("  Training on 5 employment forms and 5 invoices...\n")

        for i in range(5):
            memory.record(make_employment_form(variation=0.01), template_id="employment-form")
            memory.record(make_invoice(variation=0.01), template_id="invoice")

        emp_template = memory.get_template("employment-form")
        inv_template = memory.get_template("invoice")

        print(f"  employment-form: {len(emp_template.fields)} fields, {emp_template.sample_count} samples")
        print(f"  invoice:         {len(inv_template.fields)} fields, {inv_template.sample_count} samples")
        print(f"  Templates stored: {memory.list_templates()}")

        # ─────────────────────────────────────────────────────────────
        # STEP 2: Identify document type
        # ─────────────────────────────────────────────────────────────
        print("\n─── Step 2: Auto-Identify Document Type ────────────────────\n")

        new_emp = make_employment_form(variation=0.02)
        new_inv = make_invoice(variation=0.02)

        match = memory.identify_template(new_emp)
        print(f"  New employment form → '{match.template_id}'")
        print(f"    similarity: {match.similarity_score:.3f}")
        print(f"    field overlap: {match.field_overlap_ratio:.3f}")
        print(f"    spatial match: {match.spatial_similarity:.3f}")

        match = memory.identify_template(new_inv)
        print(f"\n  New invoice → '{match.template_id}'")
        print(f"    similarity: {match.similarity_score:.3f}")
        print(f"    field overlap: {match.field_overlap_ratio:.3f}")
        print(f"    spatial match: {match.spatial_similarity:.3f}")

        # ─────────────────────────────────────────────────────────────
        # STEP 3: Locate fields with spatial scoring
        # ─────────────────────────────────────────────────────────────
        print("\n─── Step 3: Locate Fields (Spatial + Name Scoring) ─────────\n")

        doc = make_employment_form(variation=0.02)
        fields_to_find = ["Employee Name", "SSN", "Phone Number", "Start Date", "Email"]

        print(f"  {'Field':<22} {'Score':>7} {'Spatial':>9} {'In Region':>10}")
        print(f"  {'─'*22} {'─'*7} {'─'*9} {'─'*10}")

        for field_name in fields_to_find:
            matches = memory.locate(doc, field_name)
            if matches:
                m = matches[0]
                found_name = " ".join(w.text for w in m.key_value.key)
                print(f"  {field_name:<22} {m.combined_score:>6.3f} {m.spatial_score:>8.3f} {'✓' if m.within_expected_region else '✗':>9}")

        # ─────────────────────────────────────────────────────────────
        # STEP 4: Anomaly detection
        # ─────────────────────────────────────────────────────────────
        print("\n─── Step 4: Anomaly Detection ──────────────────────────────\n")
        print("  Normal document:")

        normal = make_employment_form(variation=0.01)
        matches = memory.locate(normal, "Employee Name")
        if matches:
            print(f"    Employee Name → spatial={matches[0].spatial_score:.3f}, in_region={matches[0].within_expected_region}")

        print("\n  Anomalous document (Employee Name moved to bottom-right):")

        # Create a document where Employee Name is in the wrong spot
        anomalous_fields = [
            ("Employee Name", 0.65, 0.85, 0.25, 0.03),  # WRONG position
            ("Date of Birth", 0.05, 0.14, 0.20, 0.03),
            ("SSN",           0.05, 0.20, 0.15, 0.03),
            ("Address",       0.05, 0.26, 0.45, 0.03),
            ("Phone Number",  0.05, 0.38, 0.20, 0.03),
            ("Email",         0.05, 0.44, 0.30, 0.03),
            ("Start Date",    0.05, 0.56, 0.15, 0.03),
        ]
        anomalous_kvs = [
            KeyValue(key=[Word(w) for w in name.split()], bbox=BBox(x, y, w, h), page=1)
            for name, x, y, w, h in anomalous_fields
        ]
        anomalous = Document(pages=[Page(key_values=anomalous_kvs)])

        matches = memory.locate(anomalous, "Employee Name")
        if matches:
            m = matches[0]
            print(f"    Employee Name → spatial={m.spatial_score:.3f}, in_region={m.within_expected_region}")
            print(f"    ⚠️  Low spatial score + in_region=False → ANOMALY DETECTED")

        # ─────────────────────────────────────────────────────────────
        # STEP 5: Template refinement
        # ─────────────────────────────────────────────────────────────
        print("\n─── Step 5: Template Refinement ────────────────────────────\n")

        print("  Recording 20 more employment forms...")
        for _ in range(20):
            memory.record(make_employment_form(variation=0.015), template_id="employment-form")

        t = memory.get_template("employment-form")
        print(f"  Template now has {t.sample_count} samples\n")

        print(f"  {'Field':<25} {'Observed':>9} {'Position (x, y)':>18}")
        print(f"  {'─'*25} {'─'*9} {'─'*18}")
        for field_name in ["Employee Name", "SSN", "Phone Number", "Start Date", "Email"]:
            if field_name in t.fields:
                r = t.fields[field_name][0]
                print(f"  {field_name:<25} {r.occurrence_count:>6}x   ({r.bbox['x']:.4f}, {r.bbox['y']:.4f})")

        # ─────────────────────────────────────────────────────────────
        # STEP 6: Template management
        # ─────────────────────────────────────────────────────────────
        print("\n─── Step 6: Template Management ────────────────────────────\n")

        print(f"  Stored templates: {memory.list_templates()}")
        memory.delete_template("invoice")
        print(f"  After deleting 'invoice': {memory.list_templates()}")

        # ─────────────────────────────────────────────────────────────
        # Summary
        # ─────────────────────────────────────────────────────────────
        print(f"""
╔══════════════════════════════════════════════════════════════╗
║  Demo Complete                                               ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  What you saw:                                               ║
║  1. Template learning from synthetic documents               ║
║  2. Auto document type identification by spatial layout      ║
║  3. Field location with spatial + name scoring               ║
║  4. Anomaly detection (field in unexpected position)         ║
║  5. Template refinement (precision improves over time)       ║
║  6. Template management (list, delete)                       ║
║                                                              ║
║  To use with real Textract output:                           ║
║                                                              ║
║    from textractor.parsers import response_parser            ║
║    from field_memory import TemplateMemory                   ║
║                                                              ║
║    document = response_parser.parse(textract_json)           ║
║    memory = TemplateMemory()                                 ║
║    memory.record(document)                                   ║
║    matches = memory.locate(document, "Employee Name")        ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")


if __name__ == "__main__":
    main()
