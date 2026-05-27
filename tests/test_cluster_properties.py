# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Property-based tests for Document Cluster Tracking models."""

from hypothesis import given, settings
from hypothesis import strategies as st

from field_memory.cluster_models import MembershipRecord

# --- Strategies ---

# Non-empty text strings for doc_id and template_id
non_empty_text = st.text(min_size=1, max_size=100).filter(
    lambda s: s.strip() == s or len(s) > 0
)

# ISO format-like text strings for recorded_at
recorded_at_strategy = st.text(min_size=1, max_size=50)

# Confidence floats in [0.0, 1.0]
confidence_strategy = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)

# Metadata: either None or dictionaries with up to 20 string keys and string values
metadata_strategy = st.one_of(
    st.none(),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=50),
        values=st.text(max_size=100),
        max_size=20,
    ),
)

# Strategy for generating valid MembershipRecords
membership_record_strategy = st.builds(
    MembershipRecord,
    doc_id=st.text(min_size=1, max_size=100),
    template_id=st.text(min_size=1, max_size=100),
    recorded_at=recorded_at_strategy,
    confidence=confidence_strategy,
    metadata=metadata_strategy,
)


# --- Property Tests ---


class TestSerializationRoundTrip:
    """Property 2: Serialization Round-Trip.

    For any valid MembershipRecord, serializing to a dictionary via to_dict()
    and deserializing back via from_dict() produces an equivalent MembershipRecord
    with all field values preserved (including None metadata).

    **Validates: Requirements 9.2, 10.1, 10.2, 10.3**
    """

    @given(record=membership_record_strategy)
    @settings(max_examples=200)
    def test_serialization_round_trip(self, record: MembershipRecord):
        """For any valid MembershipRecord, from_dict(to_dict(record)) == record."""
        serialized = record.to_dict()
        deserialized = MembershipRecord.from_dict(serialized)

        assert deserialized == record
        assert deserialized.doc_id == record.doc_id
        assert deserialized.template_id == record.template_id
        assert deserialized.recorded_at == record.recorded_at
        assert deserialized.confidence == record.confidence
        assert deserialized.metadata == record.metadata
