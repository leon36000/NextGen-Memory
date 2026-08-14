from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from nextgen_memory.state import (
    StateReplayError,
    StateResolutionEvent,
    StateStatus,
    StateVerdict,
    apply_state_resolution,
    replay_state,
    replay_state_slots,
)

SPACE = UUID("11111111-1111-1111-1111-111111111111")
NODE_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
NODE_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
BASE_TIME = datetime(2026, 8, 14, 8, 0, tzinfo=UTC)


def resolution(
    number: int,
    *,
    version: int,
    verdict: StateVerdict,
    candidate: UUID | None,
    previous: UUID | None,
    idempotency_key: str | None = None,
    created_at: datetime | None = None,
    slot_key: str = "project.phase",
) -> StateResolutionEvent:
    return StateResolutionEvent(
        resolution_id=UUID(f"00000000-0000-0000-0000-{number:012d}"),
        space_id=SPACE,
        slot_key=slot_key,
        slot_version=version,
        idempotency_key=(
            idempotency_key if idempotency_key is not None else f"{slot_key}:v{version}"
        ),
        candidate_node_id=candidate,
        previous_node_id=previous,
        verdict=verdict,
        resolver="verified-runtime",
        created_at=created_at or BASE_TIME + timedelta(seconds=number),
    )


def test_slot_version_and_idempotency_key_are_required() -> None:
    with pytest.raises(ValueError, match="slot_version"):
        resolution(
            1,
            version=0,
            verdict=StateVerdict.KEEP,
            candidate=NODE_A,
            previous=None,
        )
    with pytest.raises(ValueError, match="idempotency_key"):
        resolution(
            1,
            version=1,
            verdict=StateVerdict.KEEP,
            candidate=NODE_A,
            previous=None,
            idempotency_key=" ",
        )


def test_replay_uses_explicit_slot_version_not_timestamp_order() -> None:
    first = resolution(
        1,
        version=1,
        verdict=StateVerdict.KEEP,
        candidate=NODE_A,
        previous=None,
        created_at=BASE_TIME + timedelta(hours=1),
    )
    second = resolution(
        2,
        version=2,
        verdict=StateVerdict.SUPERSEDE,
        candidate=NODE_B,
        previous=NODE_A,
        created_at=BASE_TIME,
    )

    projection = replay_state([second, first])

    assert projection.current_node_id == NODE_B
    assert projection.version == 2
    assert projection.last_resolution_id == second.resolution_id


def test_gap_and_duplicate_slot_versions_fail_closed() -> None:
    first = resolution(
        1,
        version=1,
        verdict=StateVerdict.KEEP,
        candidate=NODE_A,
        previous=None,
    )
    gap = resolution(
        3,
        version=3,
        verdict=StateVerdict.SUPERSEDE,
        candidate=NODE_B,
        previous=NODE_A,
    )
    duplicate = resolution(
        2,
        version=1,
        verdict=StateVerdict.KEEP,
        candidate=NODE_B,
        previous=None,
        idempotency_key="project.phase:other-v1",
    )

    with pytest.raises(StateReplayError, match="expected slot version"):
        replay_state([first, gap])
    with pytest.raises(StateReplayError, match="duplicate slot_version"):
        replay_state([first, duplicate])


def test_exact_retry_is_idempotent_but_conflicting_resolution_id_is_rejected() -> None:
    first = resolution(
        1,
        version=1,
        verdict=StateVerdict.KEEP,
        candidate=NODE_A,
        previous=None,
    )

    assert replay_state([first, first]).current_node_id == NODE_A
    assert apply_state_resolution(replay_state([first]), first) == replay_state([first])

    conflicting = StateResolutionEvent(
        resolution_id=first.resolution_id,
        space_id=first.space_id,
        slot_key=first.slot_key,
        slot_version=first.slot_version,
        idempotency_key=first.idempotency_key,
        candidate_node_id=NODE_B,
        previous_node_id=None,
        verdict=StateVerdict.KEEP,
        resolver="verified-runtime",
        created_at=first.created_at,
    )
    with pytest.raises(StateReplayError, match="duplicate resolution_id"):
        replay_state([first, conflicting])


def test_idempotency_retry_with_new_resolution_id_deduplicates_matching_payload() -> None:
    first = resolution(
        1,
        version=1,
        verdict=StateVerdict.KEEP,
        candidate=NODE_A,
        previous=None,
    )
    retry = StateResolutionEvent(
        resolution_id=UUID("00000000-0000-0000-0000-000000000099"),
        space_id=first.space_id,
        slot_key=first.slot_key,
        slot_version=first.slot_version,
        idempotency_key=first.idempotency_key,
        candidate_node_id=first.candidate_node_id,
        previous_node_id=first.previous_node_id,
        verdict=first.verdict,
        resolver=first.resolver,
        evidence_node_ids=first.evidence_node_ids,
        reasoning=first.reasoning,
        created_at=first.created_at + timedelta(seconds=10),
    )
    conflicting = StateResolutionEvent(
        resolution_id=UUID("00000000-0000-0000-0000-000000000100"),
        space_id=first.space_id,
        slot_key=first.slot_key,
        slot_version=first.slot_version,
        idempotency_key=first.idempotency_key,
        candidate_node_id=NODE_B,
        previous_node_id=None,
        verdict=StateVerdict.KEEP,
        resolver=first.resolver,
        created_at=first.created_at,
    )

    assert replay_state([retry, first]).current_node_id == NODE_A
    with pytest.raises(StateReplayError, match="idempotency_key"):
        replay_state([first, conflicting])


def test_duplicate_resolution_identity_is_global_across_slots() -> None:
    first = resolution(
        1,
        version=1,
        verdict=StateVerdict.KEEP,
        candidate=NODE_A,
        previous=None,
    )
    conflicting = StateResolutionEvent(
        resolution_id=first.resolution_id,
        space_id=SPACE,
        slot_key="project.storage",
        slot_version=1,
        idempotency_key="project.storage:v1",
        candidate_node_id=NODE_B,
        previous_node_id=None,
        verdict=StateVerdict.KEEP,
        resolver="verified-runtime",
        created_at=first.created_at,
    )

    with pytest.raises(StateReplayError, match="duplicate resolution_id"):
        replay_state_slots([first, conflicting])


def test_keep_records_rejected_candidate_without_replacing_active_state() -> None:
    projection = replay_state(
        [
            resolution(
                1,
                version=1,
                verdict=StateVerdict.KEEP,
                candidate=NODE_A,
                previous=None,
            ),
            resolution(
                2,
                version=2,
                verdict=StateVerdict.KEEP,
                candidate=NODE_B,
                previous=NODE_A,
            ),
        ]
    )

    assert projection.current_node_id == NODE_A
    assert projection.status is StateStatus.ACTIVE
    assert projection.version == 2


def test_evidence_order_does_not_change_idempotent_identity() -> None:
    first = StateResolutionEvent(
        resolution_id=UUID("00000000-0000-0000-0000-000000000201"),
        space_id=SPACE,
        slot_key="project.phase",
        slot_version=1,
        idempotency_key="project.phase:v1:evidence-set",
        candidate_node_id=NODE_A,
        previous_node_id=None,
        verdict=StateVerdict.KEEP,
        resolver="verified-runtime",
        evidence_node_ids=(NODE_A, NODE_B),
        created_at=BASE_TIME,
    )
    retry = StateResolutionEvent(
        resolution_id=UUID("00000000-0000-0000-0000-000000000202"),
        space_id=SPACE,
        slot_key="project.phase",
        slot_version=1,
        idempotency_key="project.phase:v1:evidence-set",
        candidate_node_id=NODE_A,
        previous_node_id=None,
        verdict=StateVerdict.KEEP,
        resolver="verified-runtime",
        evidence_node_ids=(NODE_B, NODE_A),
        created_at=BASE_TIME + timedelta(seconds=5),
    )

    projection = replay_state([retry, first])

    assert projection.current_node_id == NODE_A
    assert projection.version == 1


def test_idempotency_replay_keeps_earliest_logical_write_identity() -> None:
    original = StateResolutionEvent(
        resolution_id=UUID("00000000-0000-0000-0000-000000000099"),
        space_id=SPACE,
        slot_key="project.phase",
        slot_version=1,
        idempotency_key="project.phase:v1:earliest",
        candidate_node_id=NODE_A,
        previous_node_id=None,
        verdict=StateVerdict.KEEP,
        resolver="verified-runtime",
        created_at=BASE_TIME,
    )
    retry = StateResolutionEvent(
        resolution_id=UUID("00000000-0000-0000-0000-000000000001"),
        space_id=original.space_id,
        slot_key=original.slot_key,
        slot_version=original.slot_version,
        idempotency_key=original.idempotency_key,
        candidate_node_id=original.candidate_node_id,
        previous_node_id=original.previous_node_id,
        verdict=original.verdict,
        resolver=original.resolver,
        created_at=BASE_TIME + timedelta(minutes=1),
    )

    projection = replay_state([retry, original])

    assert projection.last_resolution_id == original.resolution_id
    assert projection.last_created_at == original.created_at


def test_duplicate_resolution_id_keeps_earliest_transport_timestamp() -> None:
    resolution_id = UUID("00000000-0000-0000-0000-000000000501")
    original = StateResolutionEvent(
        resolution_id=resolution_id,
        space_id=SPACE,
        slot_key="project.phase",
        slot_version=1,
        idempotency_key="project.phase:v1:same-resolution",
        candidate_node_id=NODE_A,
        previous_node_id=None,
        verdict=StateVerdict.KEEP,
        resolver="verified-runtime",
        created_at=BASE_TIME,
    )
    retry = StateResolutionEvent(
        resolution_id=resolution_id,
        space_id=original.space_id,
        slot_key=original.slot_key,
        slot_version=original.slot_version,
        idempotency_key=original.idempotency_key,
        candidate_node_id=original.candidate_node_id,
        previous_node_id=original.previous_node_id,
        verdict=original.verdict,
        resolver=original.resolver,
        created_at=BASE_TIME + timedelta(minutes=1),
    )

    forward = replay_state([original, retry])
    reverse = replay_state([retry, original])

    assert forward == reverse
    assert reverse.last_resolution_id == resolution_id
    assert reverse.last_created_at == original.created_at
