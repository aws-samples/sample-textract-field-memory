# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Unit tests for MembershipRecord validation and serialization."""

import pytest

from field_memory.cluster_models import MembershipRecord


class TestMembershipRecordConstruction:
    """Tests for valid and invalid MembershipRecord construction."""

    def test_valid_construction_all_fields(self):
        """Valid MembershipRecord construction with all fields populated."""
        record = MembershipRecord(
            doc_id="doc-001",
            template_id="template-abc",
            recorded_at="2024-01-15T10:30:00Z",
            confidence=0.85,
            metadata={"source": "upload", "filename": "invoice.pdf"},
        )
        assert record.doc_id == "doc-001"
        assert record.template_id == "template-abc"
        assert record.recorded_at == "2024-01-15T10:30:00Z"
        assert record.confidence == 0.85
        assert record.metadata == {"source": "upload", "filename": "invoice.pdf"}

    def test_valid_construction_none_metadata(self):
        """Valid construction with metadata as None (default)."""
        record = MembershipRecord(
            doc_id="doc-002",
            template_id="tmpl-xyz",
            recorded_at="2024-06-01T00:00:00Z",
            confidence=1.0,
        )
        assert record.metadata is None

    def test_valid_construction_boundary_confidence_zero(self):
        """Confidence of exactly 0.0 is valid."""
        record = MembershipRecord(
            doc_id="doc-003",
            template_id="tmpl-1",
            recorded_at="2024-01-01T00:00:00Z",
            confidence=0.0,
        )
        assert record.confidence == 0.0

    def test_valid_construction_boundary_confidence_one(self):
        """Confidence of exactly 1.0 is valid."""
        record = MembershipRecord(
            doc_id="doc-004",
            template_id="tmpl-2",
            recorded_at="2024-01-01T00:00:00Z",
            confidence=1.0,
        )
        assert record.confidence == 1.0

    def test_valueerror_empty_doc_id(self):
        """ValueError raised on empty doc_id string."""
        with pytest.raises(ValueError, match="doc_id must be a non-empty string"):
            MembershipRecord(
                doc_id="",
                template_id="tmpl-1",
                recorded_at="2024-01-01T00:00:00Z",
                confidence=0.5,
            )

    def test_valueerror_non_string_doc_id(self):
        """ValueError raised on non-string doc_id."""
        with pytest.raises(ValueError, match="doc_id must be a non-empty string"):
            MembershipRecord(
                doc_id=123,
                template_id="tmpl-1",
                recorded_at="2024-01-01T00:00:00Z",
                confidence=0.5,
            )

    def test_valueerror_empty_template_id(self):
        """ValueError raised on empty template_id string."""
        with pytest.raises(ValueError, match="template_id must be a non-empty string"):
            MembershipRecord(
                doc_id="doc-1",
                template_id="",
                recorded_at="2024-01-01T00:00:00Z",
                confidence=0.5,
            )

    def test_valueerror_confidence_below_zero(self):
        """ValueError raised on confidence < 0.0."""
        with pytest.raises(ValueError, match="confidence must be in"):
            MembershipRecord(
                doc_id="doc-1",
                template_id="tmpl-1",
                recorded_at="2024-01-01T00:00:00Z",
                confidence=-0.1,
            )

    def test_valueerror_confidence_above_one(self):
        """ValueError raised on confidence > 1.0."""
        with pytest.raises(ValueError, match="confidence must be in"):
            MembershipRecord(
                doc_id="doc-1",
                template_id="tmpl-1",
                recorded_at="2024-01-01T00:00:00Z",
                confidence=1.01,
            )

    def test_valueerror_metadata_too_many_keys(self):
        """ValueError raised on metadata with more than 20 keys."""
        big_metadata = {f"key_{i}": f"value_{i}" for i in range(21)}
        with pytest.raises(ValueError, match="metadata cannot exceed 20 keys"):
            MembershipRecord(
                doc_id="doc-1",
                template_id="tmpl-1",
                recorded_at="2024-01-01T00:00:00Z",
                confidence=0.5,
                metadata=big_metadata,
            )


class TestMembershipRecordSerialization:
    """Tests for to_dict() and from_dict() serialization."""

    def test_to_dict_returns_expected_dictionary(self):
        """to_dict() returns dictionary with all expected fields and values."""
        record = MembershipRecord(
            doc_id="doc-100",
            template_id="tmpl-200",
            recorded_at="2024-03-20T14:00:00Z",
            confidence=0.92,
            metadata={"batch": "morning"},
        )
        result = record.to_dict()
        assert result == {
            "doc_id": "doc-100",
            "template_id": "tmpl-200",
            "recorded_at": "2024-03-20T14:00:00Z",
            "confidence": 0.92,
            "metadata": {"batch": "morning"},
        }

    def test_to_dict_with_none_metadata(self):
        """to_dict() includes None for metadata when not set."""
        record = MembershipRecord(
            doc_id="doc-1",
            template_id="tmpl-1",
            recorded_at="2024-01-01T00:00:00Z",
            confidence=0.5,
        )
        result = record.to_dict()
        assert result["metadata"] is None

    def test_from_dict_reconstructs_equivalent_record(self):
        """from_dict() reconstructs an equivalent MembershipRecord from a dict."""
        data = {
            "doc_id": "doc-abc",
            "template_id": "tmpl-xyz",
            "recorded_at": "2024-05-10T08:15:30Z",
            "confidence": 0.77,
            "metadata": {"origin": "scan"},
        }
        record = MembershipRecord.from_dict(data)
        assert record.doc_id == "doc-abc"
        assert record.template_id == "tmpl-xyz"
        assert record.recorded_at == "2024-05-10T08:15:30Z"
        assert record.confidence == 0.77
        assert record.metadata == {"origin": "scan"}

    def test_roundtrip_with_metadata(self):
        """Round-trip: from_dict(record.to_dict()) == record with metadata."""
        original = MembershipRecord(
            doc_id="doc-rt-1",
            template_id="tmpl-rt-1",
            recorded_at="2024-07-04T12:00:00Z",
            confidence=0.63,
            metadata={"env": "prod", "region": "us-east-1"},
        )
        reconstructed = MembershipRecord.from_dict(original.to_dict())
        assert reconstructed == original

    def test_roundtrip_with_none_metadata(self):
        """Round-trip: from_dict(record.to_dict()) == record with None metadata."""
        original = MembershipRecord(
            doc_id="doc-rt-2",
            template_id="tmpl-rt-2",
            recorded_at="2024-08-01T00:00:00Z",
            confidence=1.0,
            metadata=None,
        )
        reconstructed = MembershipRecord.from_dict(original.to_dict())
        assert reconstructed == original
        assert reconstructed.metadata is None

    def test_roundtrip_preserves_boundary_confidence(self):
        """Round-trip preserves confidence boundary values (0.0 and 1.0)."""
        for confidence in [0.0, 1.0]:
            original = MembershipRecord(
                doc_id="doc-boundary",
                template_id="tmpl-boundary",
                recorded_at="2024-01-01T00:00:00Z",
                confidence=confidence,
            )
            reconstructed = MembershipRecord.from_dict(original.to_dict())
            assert reconstructed == original
