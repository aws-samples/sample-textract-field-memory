# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Integration tests: full record-and-query workflow with cluster tracking.

Tests the TemplateMemory facade integration with cluster membership tracking,
covering explicit doc_id, auto-generated UUID4, and mixed usage scenarios.

Validates: Requirements 1.1, 1.2, 2.1, 7.1, 7.2, 7.3
"""

import re
from dataclasses import dataclass
from typing import List

from hypothesis import given, settings
from hypothesis import strategies as st

from field_memory.facade import TemplateMemory

# --- Mock document objects (matching existing test patterns) ---

UUID4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


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


def make_receipt_doc():
    """Create a receipt document with different fields."""
    return make_doc(
        [
            ("Store Name", 0.10, 0.05, 0.30, 0.03, 1),
            ("Receipt Number", 0.10, 0.15, 0.25, 0.03, 1),
            ("Amount Paid", 0.10, 0.80, 0.20, 0.03, 1),
        ]
    )


class TestRecordWithExplicitDocId:
    """Test record with explicit doc_id → get_cluster_members → verify membership.

    Validates: Requirement 1.1 - explicit doc_id creates MembershipRecord in cluster.
    Validates: Requirement 2.1 - get_cluster_members returns records in insertion order.
    """

    def test_record_explicit_doc_id_appears_in_cluster(self, tmp_path):
        """Record a document with explicit doc_id and verify it appears in cluster members."""
        memory = TemplateMemory(store_path=tmp_path)
        doc = make_invoice_doc()

        template_id = memory.record(doc, template_id="invoice-tpl", doc_id="doc-001")

        members = memory.get_cluster_members(template_id)
        assert len(members) == 1
        assert members[0].doc_id == "doc-001"
        assert members[0].template_id == "invoice-tpl"
        assert members[0].confidence == 1.0

    def test_record_multiple_explicit_doc_ids_all_tracked(self, tmp_path):
        """Record multiple documents with explicit doc_ids and verify all tracked."""
        memory = TemplateMemory(store_path=tmp_path)

        doc_ids = ["doc-alpha", "doc-beta", "doc-gamma"]
        for doc_id in doc_ids:
            memory.record(make_invoice_doc(), template_id="inv-tpl", doc_id=doc_id)

        members = memory.get_cluster_members("inv-tpl")
        assert len(members) == 3
        recorded_ids = [m.doc_id for m in members]
        assert recorded_ids == doc_ids  # insertion order preserved

    def test_explicit_doc_id_with_explicit_template_has_confidence_1(self, tmp_path):
        """When template_id is explicit, confidence should be 1.0.

        Validates: Requirement 1.1 - explicit doc_id with explicit template_id.
        """
        memory = TemplateMemory(store_path=tmp_path)
        doc = make_invoice_doc()

        memory.record(doc, template_id="tpl-explicit", doc_id="my-doc")

        members = memory.get_cluster_members("tpl-explicit")
        assert members[0].confidence == 1.0

    def test_explicit_doc_id_has_recorded_at_timestamp(self, tmp_path):
        """MembershipRecord should have a valid ISO 8601 recorded_at timestamp."""
        memory = TemplateMemory(store_path=tmp_path)
        doc = make_invoice_doc()

        memory.record(doc, template_id="tpl-ts", doc_id="ts-doc")

        members = memory.get_cluster_members("tpl-ts")
        assert members[0].recorded_at is not None
        # Should end with Z (UTC)
        assert members[0].recorded_at.endswith("Z")


class TestRecordWithoutDocId:
    """Test record without doc_id → verify auto-generated UUID4 in cluster.

    Validates: Requirement 1.2 - auto-generate UUID4 when doc_id not provided.
    Validates: Requirement 7.1, 7.2 - backward compatibility.
    """

    def test_record_without_doc_id_generates_uuid4(self, tmp_path):
        """Record without doc_id should auto-generate a valid UUID4."""
        memory = TemplateMemory(store_path=tmp_path)
        doc = make_invoice_doc()

        template_id = memory.record(doc, template_id="auto-tpl")

        members = memory.get_cluster_members(template_id)
        assert len(members) == 1
        assert UUID4_PATTERN.match(members[0].doc_id) is not None

    def test_multiple_records_without_doc_id_generate_unique_uuids(self, tmp_path):
        """Each record call without doc_id should generate a unique UUID4."""
        memory = TemplateMemory(store_path=tmp_path)

        for _ in range(3):
            memory.record(make_invoice_doc(), template_id="multi-auto")

        members = memory.get_cluster_members("multi-auto")
        assert len(members) == 3

        doc_ids = [m.doc_id for m in members]
        # All should be valid UUID4
        for doc_id in doc_ids:
            assert UUID4_PATTERN.match(doc_id) is not None
        # All should be unique
        assert len(set(doc_ids)) == 3

    def test_record_without_doc_id_returns_same_template_id(self, tmp_path):
        """Backward compatibility: record without doc_id returns expected template_id.

        Validates: Requirement 7.2 - same template_id as pre-feature behavior.
        """
        memory = TemplateMemory(store_path=tmp_path)
        doc = make_invoice_doc()

        template_id = memory.record(doc, template_id="compat-tpl")

        assert template_id == "compat-tpl"

    def test_record_without_doc_id_and_without_template_id(self, tmp_path):
        """Record with neither doc_id nor template_id: auto-generates both.

        Validates: Requirement 7.1 - same matching behavior as existing implementation.
        Validates: Requirement 7.3 - accepts existing two-parameter signature.
        """
        memory = TemplateMemory(store_path=tmp_path)
        doc = make_invoice_doc()

        # First call creates a new template
        template_id = memory.record(doc)
        assert template_id is not None

        # The auto-generated doc_id should be in the cluster
        members = memory.get_cluster_members(template_id)
        assert len(members) == 1
        assert UUID4_PATTERN.match(members[0].doc_id) is not None


class TestMixedDocIdUsage:
    """Test mixed usage: some with doc_id, some without → all tracked correctly.

    Validates: Requirements 1.1, 1.2, 2.1, 7.1, 7.2, 7.3
    """

    def test_mixed_explicit_and_auto_doc_ids_in_same_cluster(self, tmp_path):
        """Mix of explicit and auto-generated doc_ids in the same cluster."""
        memory = TemplateMemory(store_path=tmp_path)

        # Record with explicit doc_id
        memory.record(make_invoice_doc(), template_id="mixed-tpl", doc_id="explicit-1")
        # Record without doc_id (auto-generate)
        memory.record(make_invoice_doc(), template_id="mixed-tpl")
        # Record with another explicit doc_id
        memory.record(make_invoice_doc(), template_id="mixed-tpl", doc_id="explicit-2")

        members = memory.get_cluster_members("mixed-tpl")
        assert len(members) == 3

        # First should be explicit
        assert members[0].doc_id == "explicit-1"
        # Second should be auto-generated UUID4
        assert UUID4_PATTERN.match(members[1].doc_id) is not None
        # Third should be explicit
        assert members[2].doc_id == "explicit-2"

    def test_mixed_doc_ids_across_different_clusters(self, tmp_path):
        """Mixed doc_ids across different template clusters are tracked independently."""
        memory = TemplateMemory(store_path=tmp_path)

        # Cluster 1: invoices with explicit doc_ids
        memory.record(make_invoice_doc(), template_id="invoices", doc_id="inv-001")
        memory.record(make_invoice_doc(), template_id="invoices", doc_id="inv-002")

        # Cluster 2: receipts with auto-generated doc_ids
        memory.record(make_receipt_doc(), template_id="receipts")
        memory.record(make_receipt_doc(), template_id="receipts")

        invoice_members = memory.get_cluster_members("invoices")
        receipt_members = memory.get_cluster_members("receipts")

        assert len(invoice_members) == 2
        assert len(receipt_members) == 2

        # Invoice cluster has explicit ids
        assert invoice_members[0].doc_id == "inv-001"
        assert invoice_members[1].doc_id == "inv-002"

        # Receipt cluster has auto-generated UUIDs
        for m in receipt_members:
            assert UUID4_PATTERN.match(m.doc_id) is not None

    def test_mixed_usage_preserves_insertion_order(self, tmp_path):
        """All records maintain insertion order regardless of doc_id source.

        Validates: Requirement 2.1 - insertion order (oldest first).
        """
        memory = TemplateMemory(store_path=tmp_path)

        memory.record(make_invoice_doc(), template_id="order-tpl", doc_id="first")
        memory.record(make_invoice_doc(), template_id="order-tpl")
        memory.record(make_invoice_doc(), template_id="order-tpl", doc_id="third")
        memory.record(make_invoice_doc(), template_id="order-tpl")
        memory.record(make_invoice_doc(), template_id="order-tpl", doc_id="fifth")

        members = memory.get_cluster_members("order-tpl")
        assert len(members) == 5

        # Verify order: explicit, auto, explicit, auto, explicit
        assert members[0].doc_id == "first"
        assert UUID4_PATTERN.match(members[1].doc_id) is not None
        assert members[2].doc_id == "third"
        assert UUID4_PATTERN.match(members[3].doc_id) is not None
        assert members[4].doc_id == "fifth"

    def test_mixed_usage_all_have_valid_timestamps(self, tmp_path):
        """All records (explicit and auto doc_id) have valid timestamps."""
        memory = TemplateMemory(store_path=tmp_path)

        memory.record(make_invoice_doc(), template_id="ts-tpl", doc_id="explicit")
        memory.record(make_invoice_doc(), template_id="ts-tpl")

        members = memory.get_cluster_members("ts-tpl")
        for member in members:
            assert member.recorded_at is not None
            assert member.recorded_at.endswith("Z")

    def test_empty_cluster_returns_empty_list(self, tmp_path):
        """Querying a non-existent cluster returns empty list.

        Validates: Requirement 2.1 edge case - no cluster data.
        """
        memory = TemplateMemory(store_path=tmp_path)

        members = memory.get_cluster_members("nonexistent-tpl")
        assert members == []


# --- Property 11: Backward Compatibility ---

# Strategy for generating field names (non-empty alpha strings)
field_name_strategy = st.text(
    min_size=2,
    max_size=15,
    alphabet=st.characters(whitelist_categories=("L",)),
)


@st.composite
def valid_bbox_strategy(draw):
    """Generate a valid bounding box where x+width <= 1.0 and y+height <= 1.0."""
    x = draw(
        st.floats(min_value=0.01, max_value=0.70, allow_nan=False, allow_infinity=False)
    )
    y = draw(
        st.floats(min_value=0.01, max_value=0.70, allow_nan=False, allow_infinity=False)
    )
    # Ensure x + width <= 1.0 and y + height <= 1.0
    max_width = min(0.25, 1.0 - x)
    max_height = min(0.25, 1.0 - y)
    width = draw(
        st.floats(
            min_value=0.02, max_value=max_width, allow_nan=False, allow_infinity=False
        )
    )
    height = draw(
        st.floats(
            min_value=0.02, max_value=max_height, allow_nan=False, allow_infinity=False
        )
    )
    return (x, y, width, height)


# Strategy for a document with 2-6 unique fields
@st.composite
def document_strategy(draw):
    """Generate a document with 2-6 fields with unique names and valid bboxes."""
    num_fields = draw(st.integers(min_value=2, max_value=6))
    # Generate unique field names
    names = draw(
        st.lists(
            field_name_strategy,
            min_size=num_fields,
            max_size=num_fields,
            unique=True,
        )
    )
    fields = []
    for name in names:
        x, y, width, height = draw(valid_bbox_strategy())
        fields.append((name, x, y, width, height, 1))
    return fields


class TestProperty11BackwardCompatibility:
    """Property 11: Backward Compatibility.

    *For any* document, calling record(document) without a doc_id parameter
    produces the same template_id result as the pre-feature implementation —
    the template matching and merging behavior is unchanged.

    The key assertion is that the presence/absence of doc_id doesn't affect
    which template the document gets assigned to.

    **Validates: Requirements 7.1, 7.2**
    """

    @given(fields=document_strategy())
    @settings(max_examples=50)
    def test_doc_id_does_not_affect_template_assignment(self, fields):
        """For any document, recording WITH and WITHOUT doc_id assigns to same template.

        1. Create a TemplateMemory with tmp_path
        2. Record a document WITH explicit template_id first (establishes template)
        3. Record the SAME document again WITHOUT doc_id
        4. Verify it gets matched to the same template_id (via template identification)
        5. The presence/absence of doc_id doesn't affect which template the document
           gets assigned to.

        **Validates: Requirements 7.1, 7.2**
        """
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            memory = TemplateMemory(store_path=Path(tmp_dir))
            doc = make_doc(fields)

            # Step 1: Record the document with an explicit template_id to establish it
            explicit_template_id = "established-template"
            result_with_template = memory.record(
                doc, template_id=explicit_template_id, doc_id="setup-doc"
            )
            assert result_with_template == explicit_template_id

            # Step 2: Record the same document WITHOUT doc_id (auto-generate)
            result_without_doc_id = memory.record(doc)

            # Step 3: Record the same document WITH a doc_id but no template_id
            result_with_doc_id = memory.record(doc, doc_id="test-doc-explicit")

            # Assert: Both calls (with and without doc_id) assign to the same template
            # The presence/absence of doc_id should not change template assignment
            assert result_without_doc_id == result_with_doc_id, (
                f"Template assignment differs based on doc_id presence: "
                f"without doc_id got '{result_without_doc_id}', "
                f"with doc_id got '{result_with_doc_id}'"
            )

    @given(fields=document_strategy())
    @settings(max_examples=50)
    def test_record_without_doc_id_matches_established_template(self, fields):
        """For any document, record() without doc_id produces same template_id
        as when the template was established.

        This verifies that the template matching behavior is unchanged by the
        cluster tracking feature - documents still get matched to the correct
        template regardless of whether doc_id is provided.

        **Validates: Requirements 7.1, 7.2**
        """
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            memory = TemplateMemory(store_path=Path(tmp_dir))
            doc = make_doc(fields)

            # Establish the template with explicit template_id
            established_id = "target-template"
            memory.record(doc, template_id=established_id)

            # Record same document without doc_id - should match established template
            matched_id = memory.record(doc)

            # The matched template should be the same as the established one
            assert matched_id == established_id, (
                f"Expected document to match established template '{established_id}', "
                f"but got '{matched_id}'"
            )
