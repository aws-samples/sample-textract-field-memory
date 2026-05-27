# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Property-based tests for ClusterTracker.

Tests correctness properties from the design document using Hypothesis.
"""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from field_memory.cluster_models import ClusterStats, MembershipRecord
from field_memory.cluster_store import ClusterStore
from field_memory.cluster_tracker import ClusterTracker

# --- Strategies ---

# Non-empty alphanumeric strings for IDs (safe for filesystem usage)
safe_id_strategy = st.text(
    min_size=1,
    max_size=20,
    alphabet=st.characters(whitelist_categories=("L", "N")),
)

# Confidence floats in [0.0, 1.0]
valid_confidence_strategy = st.floats(
    min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False
)


# --- Property 1: Membership Completeness ---


class TestProperty1MembershipCompleteness:
    """Property 1: Membership Completeness

    *For any* doc_id, template_id, and confidence in [0.0, 1.0], after calling
    track_membership(doc_id, template_id, confidence), calling get_members(template_id)
    should contain exactly one record with that doc_id and confidence value.

    **Validates: Requirements 1.1, 1.2, 1.4, 1.5**
    """

    @given(
        doc_id=safe_id_strategy,
        template_id=safe_id_strategy,
        confidence=valid_confidence_strategy,
    )
    @settings(max_examples=100)
    def test_track_membership_creates_exactly_one_record(
        self, doc_id, template_id, confidence
    ):
        """After track_membership, get_members contains exactly one record
        with the correct doc_id and confidence.

        **Validates: Requirements 1.1, 1.2, 1.4, 1.5**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            # Act: track a single membership
            tracker.track_membership(
                doc_id=doc_id,
                template_id=template_id,
                confidence=confidence,
                metadata=None,
            )

            # Assert: get_members returns exactly one record
            members = tracker.get_members(template_id)
            assert len(members) == 1, f"Expected exactly 1 member, got {len(members)}"

            # Assert: the record has the correct doc_id and confidence
            record = members[0]
            assert record.doc_id == doc_id
            assert record.confidence == confidence
            assert record.template_id == template_id


# --- Property 3: Temporal Ordering ---


class TestProperty3TemporalOrdering:
    """Property 3: Temporal Ordering.

    *For any* sequence of documents recorded into a cluster, get_members()
    returns MembershipRecords in insertion order (oldest recorded_at first),
    and get_document_history() returns results sorted by recorded_at ascending.

    **Validates: Requirements 2.1, 4.2**
    """

    @given(
        doc_ids=st.lists(safe_id_strategy, min_size=2, max_size=10),
        template_id=safe_id_strategy,
        confidences=st.lists(valid_confidence_strategy, min_size=2, max_size=10),
    )
    @settings(max_examples=50)
    def test_get_members_returns_insertion_order(
        self, doc_ids, template_id, confidences
    ):
        """get_members returns records in insertion order for a single cluster.

        For any sequence of doc_ids tracked to the same template_id,
        get_members returns them in the order they were inserted.

        **Validates: Requirements 2.1**
        """
        # Ensure equal lengths
        size = min(len(doc_ids), len(confidences))
        doc_ids = doc_ids[:size]
        confidences = confidences[:size]

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            # Track members with incrementing timestamps to guarantee ordering
            base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            inserted_records = []

            for i, (doc_id, confidence) in enumerate(zip(doc_ids, confidences)):
                # Create record with a strictly incrementing timestamp
                recorded_at = (
                    (base_time + timedelta(seconds=i))
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                record = MembershipRecord(
                    doc_id=doc_id,
                    template_id=template_id,
                    recorded_at=recorded_at,
                    confidence=confidence,
                    metadata=None,
                )
                store.append_record(template_id, record)
                inserted_records.append(record)

            # get_members should return in insertion order
            members = tracker.get_members(template_id)

            assert len(members) == len(inserted_records)
            for actual, expected in zip(members, inserted_records):
                assert actual.doc_id == expected.doc_id
                assert actual.recorded_at == expected.recorded_at
                assert actual.confidence == expected.confidence

    @given(
        doc_id=safe_id_strategy,
        template_ids=st.lists(safe_id_strategy, min_size=2, max_size=5, unique=True),
        confidences=st.lists(valid_confidence_strategy, min_size=2, max_size=5),
    )
    @settings(max_examples=50)
    def test_get_document_history_sorted_by_recorded_at(
        self, doc_id, template_ids, confidences
    ):
        """get_document_history returns records sorted by recorded_at ascending.

        For a doc_id tracked to multiple templates, get_document_history
        returns them sorted by recorded_at ascending regardless of the
        order in which clusters are scanned.

        **Validates: Requirements 4.2**
        """
        # Ensure equal lengths
        size = min(len(template_ids), len(confidences))
        template_ids = template_ids[:size]
        confidences = confidences[:size]

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            # Insert the same doc_id into multiple clusters with
            # incrementing timestamps
            base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
            expected_timestamps = []

            for i, (tmpl_id, confidence) in enumerate(zip(template_ids, confidences)):
                recorded_at = (
                    (base_time + timedelta(seconds=i))
                    .isoformat()
                    .replace("+00:00", "Z")
                )
                record = MembershipRecord(
                    doc_id=doc_id,
                    template_id=tmpl_id,
                    recorded_at=recorded_at,
                    confidence=confidence,
                    metadata=None,
                )
                store.append_record(tmpl_id, record)
                expected_timestamps.append(recorded_at)

            # get_document_history should return sorted by recorded_at
            history = tracker.get_document_history(doc_id)

            assert len(history) == len(template_ids)

            # Verify sorted by recorded_at ascending
            timestamps = [r.recorded_at for r in history]
            assert timestamps == sorted(timestamps)

            # Verify all expected timestamps are present
            assert sorted(timestamps) == sorted(expected_timestamps)

            # Verify all records belong to the correct doc_id
            for record in history:
                assert record.doc_id == doc_id


# --- Property 4: Pagination Completeness ---


class TestProperty4PaginationCompleteness:
    """Property 4: Pagination Completeness.

    For any cluster with N records and any positive page_size, iterating
    through all pages (offset=0, page_size, 2*page_size, ...) and
    concatenating results gives exactly the same list as get_members
    with no pagination.

    **Validates: Requirements 2.2, 2.3, 2.5**
    """

    @given(
        template_id=safe_id_strategy,
        num_records=st.integers(min_value=1, max_value=20),
        page_size=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=200)
    def test_pagination_union_equals_full_list(
        self, template_id, num_records, page_size
    ):
        """Union of all pages equals the complete list without
        duplicates or omissions.

        For any cluster with N records and any positive page_size,
        iterating through all pages and concatenating results gives
        exactly the same list as get_members with no pagination.

        **Validates: Requirements 2.2, 2.3, 2.5**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            # Track num_records membership records
            for i in range(num_records):
                tracker.track_membership(
                    doc_id=f"doc_{i}",
                    template_id=template_id,
                    confidence=0.5,
                )

            # Get full list (no pagination)
            full_list = tracker.get_members(template_id)

            # Paginate through all records
            paginated_records = []
            offset = 0
            while True:
                page = tracker.get_members(template_id, limit=page_size, offset=offset)
                if not page:
                    break
                # Each page must not exceed page_size
                assert len(page) <= page_size
                paginated_records.extend(page)
                offset += page_size

            # Union of all pages equals the complete list
            assert len(paginated_records) == len(full_list)
            assert paginated_records == full_list

    @given(
        template_id=safe_id_strategy,
        num_records=st.integers(min_value=1, max_value=20),
        page_size=st.integers(min_value=1, max_value=10),
    )
    @settings(max_examples=200)
    def test_no_duplicates_across_pages(self, template_id, num_records, page_size):
        """Pagination produces no duplicate records across pages.

        **Validates: Requirements 2.2, 2.3, 2.5**
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            # Track num_records membership records
            for i in range(num_records):
                tracker.track_membership(
                    doc_id=f"doc_{i}",
                    template_id=template_id,
                    confidence=0.5,
                )

            # Paginate through all records
            all_doc_ids = []
            offset = 0
            while True:
                page = tracker.get_members(template_id, limit=page_size, offset=offset)
                if not page:
                    break
                all_doc_ids.extend(r.doc_id for r in page)
                offset += page_size

            # No duplicates: set of doc_ids should have same length
            assert len(all_doc_ids) == len(set(all_doc_ids))
            assert len(all_doc_ids) == num_records


# --- Property 5: Stats Accuracy ---


class TestProperty5StatsAccuracy:
    """Property 5: Stats Accuracy.

    For any non-empty cluster, get_stats returns:
    - member_count == number of records
    - mean_confidence == sum(confidences) / len(confidences) (within float tolerance)
    - oldest_record == first record's recorded_at
    - newest_record == last record's recorded_at

    **Validates: Requirements 3.1, 3.2, 3.3**
    """

    @given(confidences=st.lists(valid_confidence_strategy, min_size=1, max_size=20))
    @settings(max_examples=200)
    def test_stats_accuracy(self, confidences: list):
        """For any non-empty cluster, stats accurately reflect the records.

        member_count == len(records), mean_confidence == arithmetic mean,
        oldest_record == first record's recorded_at, newest_record == last
        record's recorded_at.

        **Validates: Requirements 3.1, 3.2, 3.3**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ClusterStore(Path(tmpdir))
            tracker = ClusterTracker(store)

            template_id = "stats-test-template"

            # Track membership for each confidence value
            records = []
            for i, conf in enumerate(confidences):
                record = tracker.track_membership(
                    doc_id=f"doc-{i}",
                    template_id=template_id,
                    confidence=conf,
                )
                records.append(record)

            # Get stats
            stats = tracker.get_stats(template_id)

            # Assert member_count == number of records
            assert stats.member_count == len(
                confidences
            ), f"Expected member_count={len(confidences)}, got {stats.member_count}"

            # Assert mean_confidence == arithmetic mean (within float tolerance)
            expected_mean = sum(confidences) / len(confidences)
            assert abs(stats.mean_confidence - expected_mean) < 1e-9, (
                f"Expected mean_confidence ~= {expected_mean}, "
                f"got {stats.mean_confidence}"
            )

            # Assert oldest_record == first record's recorded_at
            assert stats.oldest_record == records[0].recorded_at, (
                f"Expected oldest_record={records[0].recorded_at}, "
                f"got {stats.oldest_record}"
            )

            # Assert newest_record == last record's recorded_at
            assert stats.newest_record == records[-1].recorded_at, (
                f"Expected newest_record={records[-1].recorded_at}, "
                f"got {stats.newest_record}"
            )


# --- Property 7: Document History Completeness ---


class TestProperty7DocumentHistoryCompleteness:
    """Property 7: Document History Completeness.

    *For any* doc_id recorded into multiple clusters, get_document_history(doc_id)
    returns all MembershipRecords matching that doc_id across all template clusters,
    and no records for other doc_ids are included.

    **Validates: Requirements 4.1**
    """

    @given(
        doc_id=safe_id_strategy,
        template_ids=st.lists(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
            ),
            min_size=2,
            max_size=5,
            unique=True,
        ),
        confidences=st.lists(valid_confidence_strategy, min_size=2, max_size=5),
    )
    @settings(max_examples=100)
    def test_document_history_returns_all_records_for_doc_id(
        self, doc_id, template_ids, confidences
    ):
        """For a doc_id recorded into N unique clusters, get_document_history(doc_id)
        returns exactly N records, all with matching doc_id.

        **Validates: Requirements 4.1**
        """
        # Ensure equal lengths
        size = min(len(template_ids), len(confidences))
        template_ids = template_ids[:size]
        confidences = confidences[:size]

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            # Record the same doc_id into each unique cluster
            for tmpl_id, confidence in zip(template_ids, confidences):
                tracker.track_membership(
                    doc_id=doc_id,
                    template_id=tmpl_id,
                    confidence=confidence,
                )

            # get_document_history should return exactly N records
            history = tracker.get_document_history(doc_id)

            assert (
                len(history) == size
            ), f"Expected {size} history records, got {len(history)}"

            # All records must have the matching doc_id
            for record in history:
                assert (
                    record.doc_id == doc_id
                ), f"Expected doc_id={doc_id!r}, got {record.doc_id!r}"

    @given(
        doc_ids=st.lists(safe_id_strategy, min_size=2, max_size=2, unique=True),
        template_ids=st.lists(
            st.text(
                min_size=1,
                max_size=20,
                alphabet=st.sampled_from("abcdefghijklmnopqrstuvwxyz0123456789"),
            ),
            min_size=2,
            max_size=5,
            unique=True,
        ),
        confidences=st.lists(valid_confidence_strategy, min_size=2, max_size=5),
    )
    @settings(max_examples=100)
    def test_document_history_excludes_other_doc_ids(
        self, doc_ids, template_ids, confidences
    ):
        """get_document_history(doc_id) does not include records for other doc_ids.

        When multiple doc_ids are recorded into clusters, querying for one doc_id
        must not return records belonging to a different doc_id.

        **Validates: Requirements 4.1**
        """
        doc_id = doc_ids[0]
        other_doc_id = doc_ids[1]

        # Ensure equal lengths
        size = min(len(template_ids), len(confidences))
        template_ids = template_ids[:size]
        confidences = confidences[:size]

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            # Record doc_id into all clusters
            for tmpl_id, confidence in zip(template_ids, confidences):
                tracker.track_membership(
                    doc_id=doc_id,
                    template_id=tmpl_id,
                    confidence=confidence,
                )

            # Record other_doc_id into the first cluster
            tracker.track_membership(
                doc_id=other_doc_id,
                template_id=template_ids[0],
                confidence=0.5,
            )

            # get_document_history for doc_id must NOT include other_doc_id
            history = tracker.get_document_history(doc_id)

            assert (
                len(history) == size
            ), f"Expected {size} history records for doc_id, got {len(history)}"

            for record in history:
                assert record.doc_id == doc_id, (
                    f"Found record with doc_id={record.doc_id!r}, "
                    f"expected only doc_id={doc_id!r}"
                )

            # Also verify other_doc_id history is separate
            other_history = tracker.get_document_history(other_doc_id)
            assert len(other_history) == 1
            assert other_history[0].doc_id == other_doc_id


# --- Property 9: Removal of Non-Existent Member is Idempotent ---


class TestProperty9RemovalIdempotency:
    """Property 9: Removal of Non-Existent Member is Idempotent.

    *For any* cluster with N records, removing a doc_id that doesn't exist
    in the cluster returns False and the membership list remains unchanged
    (same records, same order).

    **Validates: Requirements 5.2**
    """

    @given(
        doc_ids=st.lists(safe_id_strategy, min_size=1, max_size=10, unique=True),
        template_id=safe_id_strategy,
        confidences=st.lists(valid_confidence_strategy, min_size=1, max_size=10),
        nonexistent_doc_id=safe_id_strategy,
    )
    @settings(max_examples=100)
    def test_remove_nonexistent_member_returns_false_and_no_change(
        self, doc_ids, template_id, confidences, nonexistent_doc_id
    ):
        """Removing a doc_id not in the cluster returns False and leaves
        membership unchanged.

        For any cluster with N records, attempting to remove a doc_id that
        doesn't exist in the cluster returns False and the membership list
        remains unchanged (same records, same order).

        **Validates: Requirements 5.2**
        """
        # Ensure equal lengths
        size = min(len(doc_ids), len(confidences))
        doc_ids = doc_ids[:size]
        confidences = confidences[:size]

        # Ensure nonexistent_doc_id is actually not in the cluster
        if nonexistent_doc_id in doc_ids:
            nonexistent_doc_id = "ZZZZ_not_in_cluster_" + nonexistent_doc_id

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            # Populate the cluster with records
            for doc_id, confidence in zip(doc_ids, confidences):
                tracker.track_membership(
                    doc_id=doc_id,
                    template_id=template_id,
                    confidence=confidence,
                )

            # Capture membership before removal attempt
            members_before = tracker.get_members(template_id)

            # Attempt to remove a non-existent doc_id
            result = tracker.remove_member(template_id, nonexistent_doc_id)

            # Assert: returns False
            assert result is False, (
                f"Expected False when removing non-existent doc_id "
                f"'{nonexistent_doc_id}', got {result}"
            )

            # Assert: membership is unchanged (same records, same order)
            members_after = tracker.get_members(template_id)

            assert len(members_after) == len(members_before), (
                f"Expected {len(members_before)} members after removal "
                f"attempt, got {len(members_after)}"
            )

            for before, after in zip(members_before, members_after):
                assert before.doc_id == after.doc_id
                assert before.template_id == after.template_id
                assert before.recorded_at == after.recorded_at
                assert before.confidence == after.confidence
                assert before.metadata == after.metadata


# --- Property 6: Confidence Bounds Invariant ---


class TestProperty6ConfidenceBoundsInvariant:
    """Property 6: Confidence Bounds Invariant.

    For any non-empty cluster (1-20 records with confidence in [0.0, 1.0]),
    get_stats returns stats where min_confidence <= mean_confidence <= max_confidence.

    **Validates: Requirements 3.4**
    """

    @given(confidences=st.lists(valid_confidence_strategy, min_size=1, max_size=20))
    @settings(max_examples=200)
    def test_confidence_bounds_invariant(self, confidences: list):
        """For any non-empty cluster, min_confidence <= mean_confidence <= max_confidence.

        Uses Hypothesis to generate clusters with varying confidence values
        and asserts the bounds invariant holds.

        **Validates: Requirements 3.4**
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            store = ClusterStore(Path(tmpdir))
            tracker = ClusterTracker(store)

            template_id = "bounds-test-template"

            # Track membership for each confidence value
            for i, conf in enumerate(confidences):
                tracker.track_membership(
                    doc_id=f"doc-{i}",
                    template_id=template_id,
                    confidence=conf,
                )

            # Get stats
            stats = tracker.get_stats(template_id)

            # Assert the bounds invariant
            assert stats.min_confidence <= stats.mean_confidence, (
                f"min_confidence ({stats.min_confidence}) > "
                f"mean_confidence ({stats.mean_confidence})"
            )
            assert stats.mean_confidence <= stats.max_confidence, (
                f"mean_confidence ({stats.mean_confidence}) > "
                f"max_confidence ({stats.max_confidence})"
            )


# --- Property 13: Idempotent Stats ---


class TestProperty13IdempotentStats:
    """Property 13: Idempotent Stats.

    *For any* non-empty cluster, calling get_stats() multiple times (e.g., 3 times)
    produces identical results — no side effects occur.

    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """

    @given(
        num_records=st.integers(min_value=1, max_value=15),
        confidences=st.lists(valid_confidence_strategy, min_size=1, max_size=15),
    )
    @settings(max_examples=200)
    def test_get_stats_idempotent(self, num_records: int, confidences: list):
        """For any non-empty cluster, calling get_stats() 3 times produces
        identical results without side effects.

        Uses Hypothesis to generate 1-15 records, calls get_stats 3 times,
        and asserts all results are equal.

        **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
        """
        # Ensure we use the correct number of records
        size = min(num_records, len(confidences))
        confidences = confidences[:size]

        with tempfile.TemporaryDirectory() as tmpdir:
            store = ClusterStore(Path(tmpdir))
            tracker = ClusterTracker(store)

            template_id = "idempotent-stats-template"

            # Track membership for each confidence value
            for i, conf in enumerate(confidences):
                tracker.track_membership(
                    doc_id=f"doc-{i}",
                    template_id=template_id,
                    confidence=conf,
                )

            # Call get_stats 3 times
            stats1 = tracker.get_stats(template_id)
            stats2 = tracker.get_stats(template_id)
            stats3 = tracker.get_stats(template_id)

            # Assert all three calls produce identical results
            assert stats1.member_count == stats2.member_count == stats3.member_count, (
                f"member_count differs across calls: "
                f"{stats1.member_count}, {stats2.member_count}, {stats3.member_count}"
            )
            assert (
                stats1.oldest_record == stats2.oldest_record == stats3.oldest_record
            ), (
                f"oldest_record differs across calls: "
                f"{stats1.oldest_record}, {stats2.oldest_record}, {stats3.oldest_record}"
            )
            assert (
                stats1.newest_record == stats2.newest_record == stats3.newest_record
            ), (
                f"newest_record differs across calls: "
                f"{stats1.newest_record}, {stats2.newest_record}, {stats3.newest_record}"
            )
            assert (
                stats1.mean_confidence
                == stats2.mean_confidence
                == stats3.mean_confidence
            ), (
                f"mean_confidence differs across calls: "
                f"{stats1.mean_confidence}, {stats2.mean_confidence}, {stats3.mean_confidence}"
            )
            assert (
                stats1.min_confidence == stats2.min_confidence == stats3.min_confidence
            ), (
                f"min_confidence differs across calls: "
                f"{stats1.min_confidence}, {stats2.min_confidence}, {stats3.min_confidence}"
            )
            assert (
                stats1.max_confidence == stats2.max_confidence == stats3.max_confidence
            ), (
                f"max_confidence differs across calls: "
                f"{stats1.max_confidence}, {stats2.max_confidence}, {stats3.max_confidence}"
            )


# --- Property 8: Removal Completeness ---


class TestProperty8RemovalCompleteness:
    """Property 8: Removal Completeness.

    For any cluster with N records, after remove_member(template_id, doc_id)
    returns True, get_members(template_id) doesn't contain any record with
    that doc_id, and get_document_history(doc_id) doesn't include records
    from that template_id.

    **Validates: Requirements 5.1, 5.3**
    """

    @given(
        template_id=safe_id_strategy,
        num_records=st.integers(min_value=2, max_value=10),
        remove_index=st.integers(min_value=0, max_value=9),
    )
    @settings(max_examples=100)
    def test_removed_doc_not_in_get_members(
        self, template_id, num_records, remove_index
    ):
        """After remove_member returns True, the removed doc_id no longer
        appears in get_members for that cluster.

        For any cluster with 2-10 records, pick one to remove. After
        removal, get_members must not contain any record with that doc_id.

        **Validates: Requirements 5.1, 5.3**
        """
        # Ensure remove_index is valid for the generated num_records
        remove_index = remove_index % num_records

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            # Generate unique doc_ids for the cluster
            doc_ids = [f"doc_{i}" for i in range(num_records)]

            # Track all members
            for doc_id in doc_ids:
                tracker.track_membership(
                    doc_id=doc_id,
                    template_id=template_id,
                    confidence=0.8,
                )

            # Pick a doc_id to remove
            removed_doc_id = doc_ids[remove_index]

            # Remove the member
            result = tracker.remove_member(template_id, removed_doc_id)
            assert result is True, (
                f"Expected remove_member to return True for existing doc_id "
                f"'{removed_doc_id}'"
            )

            # Assert removed doc_id no longer in get_members
            members = tracker.get_members(template_id)
            member_doc_ids = [r.doc_id for r in members]
            assert removed_doc_id not in member_doc_ids, (
                f"doc_id '{removed_doc_id}' should not appear in "
                f"get_members after removal, but found in: {member_doc_ids}"
            )

            # Assert remaining members are preserved
            assert len(members) == num_records - 1

    @given(
        template_id=safe_id_strategy,
        num_records=st.integers(min_value=2, max_value=10),
        remove_index=st.integers(min_value=0, max_value=9),
    )
    @settings(max_examples=100)
    def test_removed_doc_not_in_get_document_history_for_cluster(
        self, template_id, num_records, remove_index
    ):
        """After remove_member returns True, get_document_history(doc_id)
        does not include records from that template_id.

        For any cluster with 2-10 records, pick one to remove. After
        removal, get_document_history for the removed doc_id must not
        contain any record with the removed cluster's template_id.

        **Validates: Requirements 5.1, 5.3**
        """
        # Ensure remove_index is valid for the generated num_records
        remove_index = remove_index % num_records

        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ClusterStore(Path(tmp_dir))
            tracker = ClusterTracker(store)

            # Generate unique doc_ids for the cluster
            doc_ids = [f"doc_{i}" for i in range(num_records)]

            # Track all members
            for doc_id in doc_ids:
                tracker.track_membership(
                    doc_id=doc_id,
                    template_id=template_id,
                    confidence=0.8,
                )

            # Pick a doc_id to remove
            removed_doc_id = doc_ids[remove_index]

            # Remove the member
            result = tracker.remove_member(template_id, removed_doc_id)
            assert result is True

            # Assert get_document_history doesn't include records from
            # the removed cluster's template_id
            history = tracker.get_document_history(removed_doc_id)
            history_template_ids = [r.template_id for r in history]
            assert template_id not in history_template_ids, (
                f"template_id '{template_id}' should not appear in "
                f"get_document_history for removed doc_id "
                f"'{removed_doc_id}', but found in: {history_template_ids}"
            )
