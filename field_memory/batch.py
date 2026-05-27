# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Batch processing module for processing multiple documents in a single call."""

from dataclasses import dataclass
from typing import Any, List, Optional


@dataclass
class BatchItemResult:
    """Result for a single document in a batch operation.

    Attributes:
        index: Position of the document in the input list.
        template_id: The template_id assigned (None if failed).
        status: Either "success" or "failed".
        error: Error message if status is "failed", None otherwise.
    """

    index: int
    template_id: Optional[str]
    status: str  # "success" or "failed"
    error: Optional[str] = None


@dataclass
class BatchResult:
    """Aggregate result for a batch processing operation.

    Attributes:
        total_count: Number of documents in the batch.
        success_count: Number of documents processed successfully.
        failure_count: Number of documents that failed.
        results: Per-document results in input order.
    """

    total_count: int
    success_count: int
    failure_count: int
    results: List[BatchItemResult]


class BatchProcessor:
    """Processes multiple documents in a single call with error isolation.

    Each document is processed independently so that a failure in one
    does not affect the others.
    """

    def __init__(self, memory: Any):
        """Initialize with a TemplateMemory instance.

        Args:
            memory: A TemplateMemory facade instance used for recording.
        """
        self._memory = memory

    def record_batch(
        self, documents: List[Any], template_id: Optional[str] = None
    ) -> BatchResult:
        """Process multiple documents, isolating failures.

        Each document is processed in a try/except block so that one
        failure does not stop the rest of the batch.

        Args:
            documents: List of document objects to process.
            template_id: Optional template_id to use for all documents.

        Returns:
            BatchResult with counts and per-document results.
        """
        if not documents:
            return BatchResult(
                total_count=0,
                success_count=0,
                failure_count=0,
                results=[],
            )

        results: List[BatchItemResult] = []

        for i, doc in enumerate(documents):
            try:
                tid = self._memory.record(doc, template_id=template_id)
                results.append(
                    BatchItemResult(
                        index=i,
                        template_id=tid,
                        status="success",
                        error=None,
                    )
                )
            except Exception as e:  # pylint: disable=broad-exception-caught
                results.append(
                    BatchItemResult(
                        index=i,
                        template_id=None,
                        status="failed",
                        error=str(e),
                    )
                )

        success_count = sum(1 for r in results if r.status == "success")
        failure_count = sum(1 for r in results if r.status == "failed")

        return BatchResult(
            total_count=len(documents),
            success_count=success_count,
            failure_count=failure_count,
            results=results,
        )
