from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

import nextgen_memory
from nextgen_memory.state import (
    StateProjectionVerification,
    StateReplayError,
    StateResolutionEvent,
    StateStatus,
    StateVerdict,
    StoredStateSlot,
    apply_state_resolution,
    replay_state,
    replay_state_slots,
    verify_state_projection,
)

SPACE = UUID("11111111-1111-1111-1111-111111111111")
OTHER_SPACE = UUID("22222222-2222-2222-2222-222222222222")
NODE_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
NODE_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
NODE_C = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
BASE_TIME = datetime(2026, 8, 14, 5, 0, tzinfo=UTC)


def event(
    number: int,
    verdict: StateVerdict,
    *,
    candidate: UUID | None = None,
    previous: UUID | None = None,
    space_id: UUID = SPACE,
    slot_key: str = "project.phase",
    slot_version: int | None = None,
    idempotency_key: str | None = None,
    created_at: datetime | None = None,
) -> StateResolutionEvent:
    version = number if slot_version is None else slot_version
    return StateResolutionEvent(
        resolution_id=UUID(f"00000000-0000-0000-0000-{number:012d}"),
        space_id=space_id,
        slot_key=slot_key,
        slot_version=version,
        idempotency_key=(
            idempotency_key or f"{space_id}:{slot_key}:v{version}"
        ),
        candidate_node_id=candidate,
        previous_node_id=previous,
        verdict=verdict,
        resolver="verified-runtime",
        evidence_node_ids=(candidate,) if candidate is not None else (),
        reasoning={"test_event": number},
        created_at=created_at or BASE_TIME + timedelta(seconds=number),
    )


def test_resolution_event_defaults_to_timezone_aware_creation_time() -> None:
    resolution = StateResolutionEvent(
        resolution_id=UUID("00000000-0000-0000-0000-000000000099"),
        space_id=SPACE,
        slot_key="project.phase",
        slot_version=1,
        idempotency_key="project.phase:v1:default-time",
        candidate_node_id=NODE_A,
        previous_node_id=None,
        verdict=StateVerdict.KEEP,
        resolver="verified-runtime",
    )

    assert resolution.created_at.utcoffset() is not None


def test_resolution_contract_rejects_invalid_shapes_and_naive_time() -> None:
    with pytest.raises(ValueError, match="candidate_node_id"):
        event(1, StateVerdict.KEEP)
    with pytest.raises(ValueError, match="previous_node_id"):
        event(1, StateVerdict.SUPERSEDE, candidate=NODE_B)
    with pytest.raises(ValueError, match="candidate_node_id"):
        event(1, StateVerdict.INVALIDATE, candidate=NODE_A, previous=NODE_A)
    with pytest.raises(ValueError, match="timezone-aware"):
        event(
            1,
            StateVerdict.KEEP,
            candidate=NODE_A,
            created_at=datetime(2026, 8, 14, 5, 0),
        )


def test_initial_keep_creates_active_projection() -> None:
    projection = replay_state([event(1, StateVerdict.KEEP, candidate=NODE_A)])

    assert projection.current_node_id == NODE_A
    assert projection.status is StateStatus.ACTIVE
    assert projection.version == 1
    assert projection.last_resolution_id == UUID(
        "00000000-0000-0000-0000-000000000001"
    )
    assert projection.quarantined_node_ids == frozenset()


def test_supersede_then_invalidate_reconstructs_stale_state() -> None:
    projection = replay_state(
        [
            event(1, StateVerdict.KEEP, candidate=NODE_A),
            event(2, StateVerdict.SUPERSEDE, candidate=NODE_B, previous=NODE_A),
            event(3, StateVerdict.INVALIDATE, previous=NODE_B),
        ]
    )

    assert projection.current_node_id is None
    assert projection.status is StateStatus.STALE
    assert projection.version == 3


def test_unknown_requires_expected_previous_value_when_state_is_active() -> None:
    first = apply_state_resolution(None, event(1, StateVerdict.KEEP, candidate=NODE_A))

    with pytest.raises(StateReplayError, match="previous_node_id"):
        apply_state_resolution(first, event(2, StateVerdict.UNKNOWN))

    unknown = apply_state_resolution(
        first,
        event(2, StateVerdict.UNKNOWN, previous=NODE_A),
    )
    assert unknown.current_node_id is None
    assert unknown.status is StateStatus.UNKNOWN


def test_keep_preserves_active_value_when_candidate_is_rejected() -> None:
    first = apply_state_resolution(None, event(1, StateVerdict.KEEP, candidate=NODE_A))

    kept = apply_state_resolution(
        first,
        event(2, StateVerdict.KEEP, candidate=NODE_B, previous=NODE_A),
    )

    assert kept.current_node_id == NODE_A
    assert kept.status is StateStatus.ACTIVE
    assert kept.version == 2


def test_stale_previous_pointer_is_rejected() -> None:
    with pytest.raises(StateReplayError, match="expected current node"):
        replay_state(
            [
                event(1, StateVerdict.KEEP, candidate=NODE_A),
                event(2, StateVerdict.SUPERSEDE, candidate=NODE_B, previous=NODE_C),
            ]
        )


def test_quarantining_non_current_candidate_preserves_current_state() -> None:
    projection = replay_state(
        [
            event(1, StateVerdict.KEEP, candidate=NODE_A),
            event(2, StateVerdict.QUARANTINE, candidate=NODE_B, previous=NODE_A),
        ]
    )

    assert projection.current_node_id == NODE_A
    assert projection.status is StateStatus.ACTIVE
    assert projection.quarantined_node_ids == frozenset({NODE_B})


def test_quarantining_current_candidate_removes_it() -> None:
    projection = replay_state(
        [
            event(1, StateVerdict.KEEP, candidate=NODE_A),
            event(2, StateVerdict.QUARANTINE, candidate=NODE_A, previous=NODE_A),
        ]
    )

    assert projection.current_node_id is None
    assert projection.status is StateStatus.QUARANTINED
    assert projection.quarantined_node_ids == frozenset({NODE_A})


def test_quarantined_candidate_cannot_be_reactivated() -> None:
    with pytest.raises(StateReplayError, match="quarantined"):
        replay_state(
            [
                event(1, StateVerdict.KEEP, candidate=NODE_A),
                event(2, StateVerdict.QUARANTINE, candidate=NODE_B, previous=NODE_A),
                event(3, StateVerdict.SUPERSEDE, candidate=NODE_B, previous=NODE_A),
            ]
        )


def test_replay_rejects_mixed_space_or_slot_histories() -> None:
    with pytest.raises(StateReplayError, match="same space and slot"):
        replay_state(
            [
                event(1, StateVerdict.KEEP, candidate=NODE_A),
                event(
                    2,
                    StateVerdict.KEEP,
                    candidate=NODE_B,
                    space_id=OTHER_SPACE,
                    slot_version=1,
                ),
            ]
        )
    with pytest.raises(StateReplayError, match="same space and slot"):
        replay_state(
            [
                event(1, StateVerdict.KEEP, candidate=NODE_A),
                event(
                    2,
                    StateVerdict.KEEP,
                    candidate=NODE_B,
                    slot_key="project.storage",
                    slot_version=1,
                ),
            ]
        )


def test_replay_state_slots_groups_independent_histories() -> None:
    projections = replay_state_slots(
        [
            event(1, StateVerdict.KEEP, candidate=NODE_A),
            event(
                2,
                StateVerdict.KEEP,
                candidate=NODE_B,
                slot_key="project.storage",
                slot_version=1,
            ),
            event(
                3,
                StateVerdict.SUPERSEDE,
                candidate=NODE_C,
                previous=NODE_A,
                slot_version=2,
            ),
        ]
    )

    assert set(projections) == {
        (SPACE, "project.phase"),
        (SPACE, "project.storage"),
    }
    assert projections[(SPACE, "project.phase")].current_node_id == NODE_C
    assert projections[(SPACE, "project.phase")].version == 2
    assert projections[(SPACE, "project.storage")].current_node_id == NODE_B


def test_stored_projection_validates_structural_identity_but_allows_semantic_drift() -> None:
    with pytest.raises(ValueError, match="slot_key"):
        StoredStateSlot(
            space_id=SPACE,
            slot_key=" ",
            current_node_id=None,
            status=StateStatus.UNKNOWN,
            resolution_id=None,
            version=0,
        )
    with pytest.raises(ValueError, match="version"):
        StoredStateSlot(
            space_id=SPACE,
            slot_key="project.phase",
            current_node_id=None,
            status=StateStatus.UNKNOWN,
            resolution_id=None,
            version=-1,
        )
    with pytest.raises(ValueError, match="resolution_id"):
        StoredStateSlot(
            space_id=SPACE,
            slot_key="project.phase",
            current_node_id=NODE_A,
            status=StateStatus.ACTIVE,
            resolution_id=None,
            version=1,
        )
    with pytest.raises(ValueError, match="last_idempotency_key"):
        StoredStateSlot(
            space_id=SPACE,
            slot_key="project.phase",
            current_node_id=NODE_A,
            status=StateStatus.ACTIVE,
            resolution_id=UUID("00000000-0000-0000-0000-000000000001"),
            version=1,
            last_idempotency_key=" ",
        )


def test_projection_verification_reports_exact_mismatches() -> None:
    events = [
        event(1, StateVerdict.KEEP, candidate=NODE_A),
        event(2, StateVerdict.QUARANTINE, candidate=NODE_C, previous=NODE_A),
        event(3, StateVerdict.SUPERSEDE, candidate=NODE_B, previous=NODE_A),
    ]
    correct = StoredStateSlot(
        space_id=SPACE,
        slot_key="project.phase",
        current_node_id=NODE_B,
        status=StateStatus.ACTIVE,
        resolution_id=UUID("00000000-0000-0000-0000-000000000003"),
        version=3,
        last_idempotency_key=f"{SPACE}:project.phase:v3",
        quarantined_node_ids=frozenset({NODE_C}),
    )
    wrong = StoredStateSlot(
        space_id=SPACE,
        slot_key="project.phase",
        current_node_id=NODE_A,
        status=StateStatus.ACTIVE,
        resolution_id=UUID("00000000-0000-0000-0000-000000000001"),
        version=1,
        last_idempotency_key="wrong-key",
        quarantined_node_ids=frozenset(),
    )

    assert verify_state_projection(events, correct).matches is True

    verification = verify_state_projection(events, wrong)
    assert verification.matches is False
    assert verification.mismatches == (
        "current_node_id",
        "version",
        "resolution_id",
        "last_idempotency_key",
        "quarantined_node_ids",
    )


def test_projection_verification_rejects_different_slot_identity() -> None:
    stored = StoredStateSlot(
        space_id=SPACE,
        slot_key="project.storage",
        current_node_id=NODE_A,
        status=StateStatus.ACTIVE,
        resolution_id=UUID("00000000-0000-0000-0000-000000000001"),
        version=1,
    )

    with pytest.raises(StateReplayError, match="stored slot"):
        verify_state_projection(
            [event(1, StateVerdict.KEEP, candidate=NODE_A)],
            stored,
        )


def test_projection_is_json_ready() -> None:
    projection = replay_state([event(1, StateVerdict.KEEP, candidate=NODE_A)])

    assert projection.to_dict() == {
        "space_id": str(SPACE),
        "slot_key": "project.phase",
        "current_node_id": str(NODE_A),
        "status": "active",
        "version": 1,
        "last_resolution_id": "00000000-0000-0000-0000-000000000001",
        "last_idempotency_key": f"{SPACE}:project.phase:v1",
        "last_created_at": (BASE_TIME + timedelta(seconds=1)).isoformat(),
        "quarantined_node_ids": [],
        "last_event_legacy_metadata": False,
    }


def test_empty_replay_is_rejected() -> None:
    with pytest.raises(StateReplayError, match="at least one"):
        replay_state([])


def test_package_exports_state_replay_api() -> None:
    assert nextgen_memory.StateResolutionEvent is StateResolutionEvent
    assert nextgen_memory.StateProjectionVerification is StateProjectionVerification
    assert nextgen_memory.replay_state is replay_state
    assert nextgen_memory.verify_state_projection is verify_state_projection


def test_stored_slot_can_represent_corrupt_projection_for_diagnostics() -> None:
    stored = StoredStateSlot(
        space_id=SPACE,
        slot_key="project.phase",
        current_node_id=None,
        status=StateStatus.ACTIVE,
        resolution_id=UUID("00000000-0000-0000-0000-000000000001"),
        version=1,
        last_idempotency_key=f"{SPACE}:project.phase:v1",
    )

    verification = verify_state_projection(
        [event(1, StateVerdict.KEEP, candidate=NODE_A)],
        stored,
    )

    assert verification.matches is False
    assert verification.mismatches == ("current_node_id",)


def test_legacy_event_does_not_report_missing_stored_idempotency_as_drift() -> None:
    legacy = StateResolutionEvent(
        resolution_id=UUID("00000000-0000-0000-0000-000000000077"),
        space_id=SPACE,
        slot_key="project.legacy",
        slot_version=1,
        idempotency_key="legacy:00000000-0000-0000-0000-000000000077",
        candidate_node_id=NODE_A,
        previous_node_id=None,
        verdict=StateVerdict.KEEP,
        resolver="legacy-replay-view",
        created_at=BASE_TIME,
        legacy_metadata=True,
    )
    stored = StoredStateSlot(
        space_id=SPACE,
        slot_key="project.legacy",
        current_node_id=NODE_A,
        status=StateStatus.ACTIVE,
        resolution_id=legacy.resolution_id,
        version=1,
        last_idempotency_key=None,
    )

    verification = verify_state_projection([legacy], stored)

    assert verification.matches is True
    assert verification.mismatches == ()
