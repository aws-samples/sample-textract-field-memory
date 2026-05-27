# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Property-based tests for Document Cluster Tracking models and validation.

Tests correctness properties from the design document using Hypothesis.
"""

import os
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from field_memory.cluster_models import MembershipRecord
from field_memory.cluster_store import ClusterStore
from field_memory.cluster_tracker import ClusterTracker

# --- Strategies ---

# Strategy for generating empty doc_id strings (Property 12: invalid doc_id)
empty_doc_id_strategy = st.just("")

# Strategy for confidence values outside [0.0, 1.0]
invalid_confidence_strategy = st.one_of(
    st.floats(max_value=-0.001, allow_nan=False, allow_infinity=False),
    st.floats(min_value=1.001, allow_nan=False, allow_infinity=False),
)

# Strategy for metadata with more than 20 keys
oversized_metadata_strategy = st.dictionaries(
    keys=st.text(
        min_size=1, max_size=10, alphabet=st.characters(whitelist_categories=("L", "N"))
    ),
    values=st.text(min_size=1, max_size=10),
    min_size=21,
    max_size=30,
)

# Valid values for fields that are NOT being tested as invalid
valid_template_id_strategy = st.text(
    min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))
)
valid_doc_id_strategy = st.text(
    min_size=1, max_size=20, alphabet=st.characters(whitelist_categories=("L", "N"))
)
valid_confidence_strategy = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)
valid_recorded_at_strategy = st.just("2024-01-15T10:30:00Z")


# --- Property 12: Invalid Inputs Rejected Without State Mutation ---


class TestProperty12InvalidInputsRejected:
    """Property 12: Invalid Inputs Rejected Without State Mutation

    *For any* invalid input (empty doc_id, confidence outside [0.0, 1.0],
    metadata with >20 keys), the ClusterTracker raises a ValueError and
    no MembershipRecord is persisted — the cluster state remains unchanged.

    **Validates: Requirements 8.1, 8.2, 8.3**
    """

    @given(
        template_id=valid_template_id_strategy,
        confidence=valid_confidence_strategy,
    )
    @settings(max_examples=50)
    def test_empty_doc_id_raises_valueerror_membership_record(
        self, template_id, confidence
    ):
        """Empty string doc_id raises ValueError from MembershipRecord.

        **Validates: Requirements 8.1**
        """
        with pytest.raises(ValueError):
            MembershipRecord(
                doc_id="",
                template_id=template_id,
                recorded_at="2024-01-15T10:30:00Z",
                confidence=confidence,
                metadata=None,
            )

    @given(
        template_id=valid_template_id_strategy,
        confidence=valid_confidence_strategy,
    )
    @settings(max_examples=50)
    def test_empty_doc_id_raises_valueerror_cluster_tracker(
        self, template_id, confidence
    ):
        """Empty string doc_id raises ValueError from ClusterTracker.track_membership
        and no state mutation occurs.

        **Validates: Requirements 8.1**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            # Verify directory is empty before
            files_before = set(os.listdir(tmp_dir))

            with pytest.raises(ValueError):
                tracker.track_membership(
                    doc_id="",
                    template_id=template_id,
                    confidence=confidence,
                    metadata=None,
                )

            # Verify no state mutation: no files written
            files_after = set(os.listdir(tmp_dir))
            assert files_before == files_after

            # Verify cluster has no records
            cluster = store.load_cluster(template_id)
            assert cluster is None

    @given(
        doc_id=valid_doc_id_strategy,
        template_id=valid_template_id_strategy,
        confidence=invalid_confidence_strategy,
    )
    @settings(max_examples=50)
    def test_invalid_confidence_raises_valueerror_membership_record(
        self, doc_id, template_id, confidence
    ):
        """Confidence outside [0.0, 1.0] raises ValueError from MembershipRecord.

        **Validates: Requirements 8.2**
        """
        with pytest.raises(ValueError):
            MembershipRecord(
                doc_id=doc_id,
                template_id=template_id,
                recorded_at="2024-01-15T10:30:00Z",
                confidence=confidence,
                metadata=None,
            )

    @given(
        doc_id=valid_doc_id_strategy,
        template_id=valid_template_id_strategy,
        confidence=invalid_confidence_strategy,
    )
    @settings(max_examples=50)
    def test_invalid_confidence_raises_valueerror_cluster_tracker(
        self, doc_id, template_id, confidence
    ):
        """Confidence outside [0.0, 1.0] raises ValueError from ClusterTracker.track_membership
        and no state mutation occurs.

        **Validates: Requirements 8.2**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            files_before = set(os.listdir(tmp_dir))

            with pytest.raises(ValueError):
                tracker.track_membership(
                    doc_id=doc_id,
                    template_id=template_id,
                    confidence=confidence,
                    metadata=None,
                )

            # Verify no state mutation
            files_after = set(os.listdir(tmp_dir))
            assert files_before == files_after

            cluster = store.load_cluster(template_id)
            assert cluster is None

    @given(
        doc_id=valid_doc_id_strategy,
        template_id=valid_template_id_strategy,
        confidence=valid_confidence_strategy,
        metadata=oversized_metadata_strategy,
    )
    @settings(max_examples=50)
    def test_oversized_metadata_raises_valueerror_membership_record(
        self, doc_id, template_id, confidence, metadata
    ):
        """Metadata with >20 keys raises ValueError from MembershipRecord.

        **Validates: Requirements 8.3**
        """
        with pytest.raises(ValueError):
            MembershipRecord(
                doc_id=doc_id,
                template_id=template_id,
                recorded_at="2024-01-15T10:30:00Z",
                confidence=confidence,
                metadata=metadata,
            )

    @given(
        doc_id=valid_doc_id_strategy,
        template_id=valid_template_id_strategy,
        confidence=valid_confidence_strategy,
        metadata=oversized_metadata_strategy,
    )
    @settings(max_examples=50)
    def test_oversized_metadata_raises_valueerror_cluster_tracker(
        self, doc_id, template_id, confidence, metadata
    ):
        """Metadata with >20 keys raises ValueError from ClusterTracker.track_membership
        and no state mutation occurs.

        **Validates: Requirements 8.3**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            files_before = set(os.listdir(tmp_dir))

            with pytest.raises(ValueError):
                tracker.track_membership(
                    doc_id=doc_id,
                    template_id=template_id,
                    confidence=confidence,
                    metadata=metadata,
                )

            # Verify no state mutation
            files_after = set(os.listdir(tmp_dir))
            assert files_before == files_after

            cluster = store.load_cluster(template_id)
            assert cluster is None
