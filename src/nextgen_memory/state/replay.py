"""Pure deterministic replay and stored-projection verification."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from .models import (
    StateProjection,
    StateProjectionVerification,
    StateReplayError,
    StateResolutionEvent,
    StateStatus,
    StateVerdict,
    StoredStateSlot,
)


def apply_state_resolution(
    projection: StateProjection | None,
    event: StateResolutionEvent,
) -> StateProjection:
    """Apply one resolution or return the prior projection for an exact retry."""

    if projection is not None:
        if projection.space_id != event.space_id or projection.slot_key != event.slot_key:
            raise StateReplayError("resolution events must target the same space and slot")
        if event.resolution_id == projection.last_resolution_id:
            if _is_projection_retry(projection, event):
                return projection
            raise StateReplayError("duplicate resolution_id has conflicting payload")
        if event.idempotency_key == projection.last_idempotency_key:
            if _is_projection_retry(projection, event):
                return projection
            raise StateReplayError("idempotency_key was reused with conflicting payload")

    expected_version = (projection.version if projection is not None else 0) + 1
    if event.slot_version != expected_version:
        raise StateReplayError(
            f"expected slot version {expected_version}, received {event.slot_version}"
        )

    current_node_id = projection.current_node_id if projection is not None else None
    current_status = projection.status if projection is not None else StateStatus.UNKNOWN
    quarantined = set(projection.quarantined_node_ids if projection is not None else ())

    _require_expected_previous(current_node_id, event)

    if event.verdict is StateVerdict.KEEP:
        if current_node_id is None:
            candidate = event.candidate_node_id
            assert candidate is not None
            if candidate in quarantined:
                raise StateReplayError("quarantined candidate cannot become current")
            current_node_id = candidate
            current_status = StateStatus.ACTIVE
    elif event.verdict is StateVerdict.SUPERSEDE:
        candidate = event.candidate_node_id
        assert candidate is not None
        if candidate in quarantined:
            raise StateReplayError("quarantined candidate cannot become current")
        current_node_id = candidate
        current_status = StateStatus.ACTIVE
    elif event.verdict is StateVerdict.INVALIDATE:
        current_node_id = None
        current_status = StateStatus.STALE
    elif event.verdict is StateVerdict.UNKNOWN:
        current_node_id = None
        current_status = StateStatus.UNKNOWN
    elif event.verdict is StateVerdict.QUARANTINE:
        candidate = event.candidate_node_id
        assert candidate is not None
        quarantined.add(candidate)
        if current_node_id == candidate:
            current_node_id = None
            current_status = StateStatus.QUARANTINED
        elif current_node_id is None:
            current_status = StateStatus.QUARANTINED

    return StateProjection(
        space_id=event.space_id,
        slot_key=event.slot_key,
        current_node_id=current_node_id,
        status=current_status,
        version=event.slot_version,
        last_resolution_id=event.resolution_id,
        last_created_at=event.created_at,
        quarantined_node_ids=frozenset(quarantined),
        last_idempotency_key=event.idempotency_key,
        last_event_fingerprint=event.logical_fingerprint,
        last_event_legacy_metadata=event.legacy_metadata,
    )


def replay_state(events: Iterable[StateResolutionEvent]) -> StateProjection:
    """Replay one slot by explicit version after validating retries and gaps."""

    canonical = _canonicalize_events(events)
    if not canonical:
        raise StateReplayError("at least one resolution event is required")

    first = canonical[0]
    if any(
        event.space_id != first.space_id or event.slot_key != first.slot_key
        for event in canonical[1:]
    ):
        raise StateReplayError("resolution events must target the same space and slot")

    _validate_slot_versions(canonical)
    projection: StateProjection | None = None
    for event in sorted(canonical, key=lambda item: item.slot_version):
        projection = apply_state_resolution(projection, event)
    assert projection is not None
    return projection


def replay_state_slots(
    events: Iterable[StateResolutionEvent],
) -> dict[tuple[UUID, str], StateProjection]:
    """Replay multiple independent slot histories with globally unique event identities."""

    canonical = _canonicalize_events(events)
    grouped: dict[tuple[UUID, str], list[StateResolutionEvent]] = defaultdict(list)
    for event in canonical:
        grouped[(event.space_id, event.slot_key)].append(event)
    return {key: replay_state(history) for key, history in grouped.items()}


def verify_state_projection(
    events: Iterable[StateResolutionEvent],
    stored_slot: StoredStateSlot,
) -> StateProjectionVerification:
    """Compare an independently replayed projection with the mutable stored slot."""

    projection = replay_state(events)
    if projection.space_id != stored_slot.space_id or projection.slot_key != stored_slot.slot_key:
        raise StateReplayError("stored slot must target the replayed space and slot")

    mismatches: list[str] = []
    if projection.current_node_id != stored_slot.current_node_id:
        mismatches.append("current_node_id")
    if projection.status is not stored_slot.status:
        mismatches.append("status")
    if projection.version != stored_slot.version:
        mismatches.append("version")
    if projection.last_resolution_id != stored_slot.resolution_id:
        mismatches.append("resolution_id")
    if not (
        projection.last_event_legacy_metadata
        and stored_slot.last_idempotency_key is None
    ) and projection.last_idempotency_key != stored_slot.last_idempotency_key:
        mismatches.append("last_idempotency_key")
    if projection.quarantined_node_ids != stored_slot.quarantined_node_ids:
        mismatches.append("quarantined_node_ids")

    return StateProjectionVerification(
        projection=projection,
        stored_slot=stored_slot,
        mismatches=tuple(mismatches),
    )


def _canonicalize_events(
    events: Iterable[StateResolutionEvent],
) -> list[StateResolutionEvent]:
    by_resolution_id: dict[UUID, StateResolutionEvent] = {}

    for event in events:
        existing_by_id = by_resolution_id.get(event.resolution_id)
        if existing_by_id is not None:
            if existing_by_id.logical_fingerprint != event.logical_fingerprint:
                raise StateReplayError("duplicate resolution_id has conflicting payload")
            if event.created_at < existing_by_id.created_at:
                by_resolution_id[event.resolution_id] = event
            continue
        by_resolution_id[event.resolution_id] = event

    by_idempotency: dict[tuple[UUID, str], StateResolutionEvent] = {}
    for event in by_resolution_id.values():
        idempotency_identity = (event.space_id, event.idempotency_key)
        existing_by_key = by_idempotency.get(idempotency_identity)
        if existing_by_key is not None:
            if existing_by_key.logical_fingerprint != event.logical_fingerprint:
                raise StateReplayError("idempotency_key was reused with conflicting payload")
            if (event.created_at, event.resolution_id.int) < (
                existing_by_key.created_at,
                existing_by_key.resolution_id.int,
            ):
                by_idempotency[idempotency_identity] = event
            continue
        by_idempotency[idempotency_identity] = event

    canonical_ids = {event.resolution_id for event in by_idempotency.values()}
    return [
        event
        for event in by_resolution_id.values()
        if event.resolution_id in canonical_ids
    ]


def _validate_slot_versions(events: Iterable[StateResolutionEvent]) -> None:
    ordered = sorted(events, key=lambda event: (event.slot_version, event.resolution_id.int))
    seen_versions: set[int] = set()
    for expected, event in enumerate(ordered, start=1):
        if event.slot_version in seen_versions:
            raise StateReplayError(f"duplicate slot_version {event.slot_version}")
        seen_versions.add(event.slot_version)
        if event.slot_version != expected:
            raise StateReplayError(
                f"expected slot version {expected}, received {event.slot_version}"
            )


def _is_projection_retry(
    projection: StateProjection,
    event: StateResolutionEvent,
) -> bool:
    return (
        event.slot_version == projection.version
        and event.idempotency_key == projection.last_idempotency_key
        and event.logical_fingerprint == projection.last_event_fingerprint
    )


def _require_expected_previous(
    current_node_id: UUID | None,
    event: StateResolutionEvent,
) -> None:
    if current_node_id is None:
        if event.previous_node_id is not None:
            raise StateReplayError(
                "previous_node_id was provided but the projection has no current node"
            )
        return
    if event.previous_node_id is None:
        raise StateReplayError("previous_node_id is required when state is active")
    if event.previous_node_id != current_node_id:
        raise StateReplayError(
            f"previous_node_id does not match expected current node {current_node_id}"
        )
