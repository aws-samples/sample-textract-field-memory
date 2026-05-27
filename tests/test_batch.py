# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for the batch processing module."""

from dataclasses import dataclass
from typing import List, Optional

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from field_memory.batch import BatchItemResult, BatchProcessor, BatchResult
from field_memory.facade import TemplateMemory

# --- Mock objects (same pattern as test_field_memory.py) ---


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


def make_valid_doc():
    """Create a simple valid document for testing."""
    return make_doc([("Employee Name", 0.05, 0.10, 0.35, 0.03, 1)])


def make_invalid_doc():
    """Create a document that will fail processing (no key-value fields)."""
    return Document(pages=[Page(key_values=[])])


# --- Property-Based Tests ---


class TestBatchResultCountsProperty:
    """Property test: batch result counts are consistent.

    **Validates: Requirements 4.1, 4.3**

    For any batch of N documents:
    - total_count == N
    - success_count + failure_count == total_count
    - len(results) == total_count
    """

    @given(
        num_valid=st.integers(min_value=0, max_value=10),
        num_invalid=st.integers(min_value=0, max_value=10),
    )
    @settings(max_examples=50, deadline=None)
    def test_batch_counts_consistent(self, tmp_path_factory, num_valid, num_invalid):
        tmp_path = tmp_path_factory.mktemp("batch")
        memory = TemplateMemory(store_path=tmp_path)
        processor = BatchProcessor(memory)

        documents = []
        for _ in range(num_valid):
            documents.append(make_valid_doc())
        for _ in range(num_invalid):
            documents.append(make_invalid_doc())

        result = processor.record_batch(documents, template_id="test")

        total = num_valid + num_invalid
        assert result.total_count == total
        assert result.success_count + result.failure_count == result.total_count
        assert len(result.results) == result.total_count


class TestBatchTemplateIdProperty:
    """Property test: template_id applied to all successful results when provided.

    **Validates: Requirements 4.4**

    When a template_id is provided to record_batch, all successful results
    should have that template_id.
    """

    @given(
        num_docs=st.integers(min_value=1, max_value=10),
        template_id=st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=20,
        ),
    )
    @settings(max_examples=30, deadline=None)
    def test_template_id_applied_to_all_successes(
        self, tmp_path_factory, num_docs, template_id
    ):
        tmp_path = tmp_path_factory.mktemp("batch")
        memory = TemplateMemory(store_path=tmp_path)
        processor = BatchProcessor(memory)

        documents = [make_valid_doc() for _ in range(num_docs)]
        result = processor.record_batch(documents, template_id=template_id)

        for item in result.results:
            if item.status == "success":
                assert item.template_id == template_id


# --- Example-Based Tests ---


class TestBatchExampleTests:
    """Example tests for batch processing edge cases.

    **Validates: Requirements 4.2, 4.6**
    """

    def test_failed_document_does_not_stop_batch(self, tmp_path):
        """A failed document in the middle doesn't prevent others from processing."""
        memory = TemplateMemory(store_path=tmp_path)
        processor = BatchProcessor(memory)

        documents = [
            make_valid_doc(),
            make_invalid_doc(),  # This will fail
            make_valid_doc(),
        ]

        result = processor.record_batch(documents, template_id="test")

        assert result.total_count == 3
        assert result.success_count == 2
        assert result.failure_count == 1

        assert result.results[0].status == "success"
        assert result.results[1].status == "failed"
        assert result.results[1].error is not None
        assert result.results[2].status == "success"

    def test_empty_batch_returns_zero_counts(self, tmp_path):
        """An empty document list returns zero counts and empty results."""
        memory = TemplateMemory(store_path=tmp_path)
        processor = BatchProcessor(memory)

        result = processor.record_batch([], template_id="test")

        assert result.total_count == 0
        assert result.success_count == 0
        assert result.failure_count == 0
        assert result.results == []

    def test_all_successful_batch(self, tmp_path):
        """All valid documents produce all-success results."""
        memory = TemplateMemory(store_path=tmp_path)
        processor = BatchProcessor(memory)

        documents = [make_valid_doc() for _ in range(3)]
        result = processor.record_batch(documents, template_id="form")

        assert result.total_count == 3
        assert result.success_count == 3
        assert result.failure_count == 0
        for item in result.results:
            assert item.status == "success"
            assert item.template_id == "form"

    def test_all_failed_batch(self, tmp_path):
        """All invalid documents produce all-failed results."""
        memory = TemplateMemory(store_path=tmp_path)
        processor = BatchProcessor(memory)

        documents = [make_invalid_doc() for _ in range(3)]
        result = processor.record_batch(documents, template_id="form")

        assert result.total_count == 3
        assert result.success_count == 0
        assert result.failure_count == 3
        for item in result.results:
            assert item.status == "failed"
            assert item.template_id is None

    def test_result_indices_match_input_order(self, tmp_path):
        """Result indices correspond to input document positions."""
        memory = TemplateMemory(store_path=tmp_path)
        processor = BatchProcessor(memory)

        documents = [make_valid_doc(), make_invalid_doc(), make_valid_doc()]
        result = processor.record_batch(documents, template_id="test")

        for i, item in enumerate(result.results):
            assert item.index == i
