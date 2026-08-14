"""Immutable state-resolution and projection contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from json import dumps
from types import MappingProxyType
from typing import Any
from uuid import UUID


class StateVerdict(StrEnum):
    KEEP = "KEEP"
    SUPERSEDE = "SUPERSEDE"
    INVALIDATE = "INVALIDATE"
    UNKNOWN = "UNKNOWN"
    QUARANTINE = "QUARANTINE"


class StateStatus(StrEnum):
    ACTIVE = "active"
    UNKNOWN = "unknown"
    STALE = "stale"
    QUARANTINED = "quarantined"


class StateReplayError(ValueError):
    """Raised when an append-only resolution history is internally inconsistent."""


@dataclass(frozen=True, slots=True)
class StateResolutionEvent:
    """One immutable decision about a current-state slot."""

    resolution_id: UUID
    space_id: UUID
    slot_key: str
    slot_version: int
    idempotency_key: str
    candidate_node_id: UUID | None
    previous_node_id: UUID | None
    verdict: StateVerdict
    resolver: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    evidence_node_ids: tuple[UUID, ...] = ()
    reasoning: Mapping[str, Any] = field(default_factory=dict)
    legacy_metadata: bool = False

    def __post_init__(self) -> None:
        slot_key = self.slot_key.strip()
        idempotency_key = self.idempotency_key.strip()
        resolver = self.resolver.strip()
        if not slot_key:
            raise ValueError("slot_key must not be empty")
        if self.slot_version <= 0:
            raise ValueError("slot_version must be greater than zero")
        if not idempotency_key:
            raise ValueError("idempotency_key must not be empty")
        if not resolver:
            raise ValueError("resolver must not be empty")
        if self.created_at.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")

        supplied_evidence_node_ids = tuple(self.evidence_node_ids)
        if len(set(supplied_evidence_node_ids)) != len(supplied_evidence_node_ids):
            raise ValueError("evidence_node_ids must be unique")
        evidence_node_ids = tuple(sorted(supplied_evidence_node_ids, key=lambda node: node.int))

        if self.verdict is StateVerdict.KEEP and self.candidate_node_id is None:
            raise ValueError("KEEP requires candidate_node_id")
        if self.verdict is StateVerdict.SUPERSEDE:
            if self.candidate_node_id is None:
                raise ValueError("SUPERSEDE requires candidate_node_id")
            if self.previous_node_id is None:
                raise ValueError("SUPERSEDE requires previous_node_id")
            if self.candidate_node_id == self.previous_node_id:
                raise ValueError("SUPERSEDE candidate_node_id must differ from previous_node_id")
        if self.verdict is StateVerdict.INVALIDATE:
            if self.candidate_node_id is not None:
                raise ValueError("INVALIDATE does not accept candidate_node_id")
            if self.previous_node_id is None:
                raise ValueError("INVALIDATE requires previous_node_id")
        if self.verdict is StateVerdict.UNKNOWN and self.candidate_node_id is not None:
            raise ValueError("UNKNOWN does not accept candidate_node_id")
        if self.verdict is StateVerdict.QUARANTINE and self.candidate_node_id is None:
            raise ValueError("QUARANTINE requires candidate_node_id")

        object.__setattr__(self, "slot_key", slot_key)
        object.__setattr__(self, "idempotency_key", idempotency_key)
        object.__setattr__(self, "resolver", resolver)
        object.__setattr__(self, "evidence_node_ids", evidence_node_ids)
        object.__setattr__(self, "reasoning", MappingProxyType(dict(self.reasoning)))

    @property
    def logical_fingerprint(self) -> str:
        """Hash the logical write while excluding transport identity and arrival time."""

        payload = {
            "space_id": str(self.space_id),
            "slot_key": self.slot_key,
            "slot_version": self.slot_version,
            "idempotency_key": self.idempotency_key,
            "candidate_node_id": (
                str(self.candidate_node_id) if self.candidate_node_id is not None else None
            ),
            "previous_node_id": (
                str(self.previous_node_id) if self.previous_node_id is not None else None
            ),
            "verdict": self.verdict.value,
            "resolver": self.resolver,
            "evidence_node_ids": [str(node_id) for node_id in self.evidence_node_ids],
            "reasoning": dict(self.reasoning),
            "legacy_metadata": self.legacy_metadata,
        }
        encoded = dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return sha256(encoded.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "resolution_id": str(self.resolution_id),
            "space_id": str(self.space_id),
            "slot_key": self.slot_key,
            "slot_version": self.slot_version,
            "idempotency_key": self.idempotency_key,
            "candidate_node_id": (
                str(self.candidate_node_id) if self.candidate_node_id is not None else None
            ),
            "previous_node_id": (
                str(self.previous_node_id) if self.previous_node_id is not None else None
            ),
            "verdict": self.verdict.value,
            "resolver": self.resolver,
            "evidence_node_ids": [str(node_id) for node_id in self.evidence_node_ids],
            "reasoning": dict(self.reasoning),
            "created_at": self.created_at.isoformat(),
            "legacy_metadata": self.legacy_metadata,
        }


@dataclass(frozen=True, slots=True)
class StateProjection:
    """Rebuildable current-state cache produced solely from resolution events."""

    space_id: UUID
    slot_key: str
    current_node_id: UUID | None
    status: StateStatus
    version: int
    last_resolution_id: UUID
    last_created_at: datetime
    quarantined_node_ids: frozenset[UUID] = field(default_factory=frozenset)
    last_idempotency_key: str | None = field(default=None, repr=False)
    last_event_fingerprint: str | None = field(default=None, repr=False)
    last_event_legacy_metadata: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        slot_key = self.slot_key.strip()
        if not slot_key:
            raise ValueError("slot_key must not be empty")
        if self.version <= 0:
            raise ValueError("version must be greater than zero")
        if self.last_created_at.utcoffset() is None:
            raise ValueError("last_created_at must be timezone-aware")
        if self.last_idempotency_key is not None and not self.last_idempotency_key.strip():
            raise ValueError("last_idempotency_key must not be empty")
        if self.status is StateStatus.ACTIVE and self.current_node_id is None:
            raise ValueError("active state requires current_node_id")
        if self.status is not StateStatus.ACTIVE and self.current_node_id is not None:
            raise ValueError("non-active state cannot expose current_node_id")
        if self.last_event_fingerprint is not None and len(self.last_event_fingerprint) != 64:
            raise ValueError("last_event_fingerprint must be a SHA-256 digest")

        quarantined = frozenset(self.quarantined_node_ids)
        if self.current_node_id in quarantined:
            raise ValueError("current_node_id cannot also be quarantined")
        object.__setattr__(self, "slot_key", slot_key)
        object.__setattr__(self, "quarantined_node_ids", quarantined)

    def to_dict(self) -> dict[str, Any]:
        return {
            "space_id": str(self.space_id),
            "slot_key": self.slot_key,
            "current_node_id": (
                str(self.current_node_id) if self.current_node_id is not None else None
            ),
            "status": self.status.value,
            "version": self.version,
            "last_resolution_id": str(self.last_resolution_id),
            "last_idempotency_key": self.last_idempotency_key,
            "last_created_at": self.last_created_at.isoformat(),
            "quarantined_node_ids": sorted(
                str(node_id) for node_id in self.quarantined_node_ids
            ),
            "last_event_legacy_metadata": self.last_event_legacy_metadata,
        }


@dataclass(frozen=True, slots=True)
class StoredStateSlot:
    """Mutable database projection read for independent replay verification."""

    space_id: UUID
    slot_key: str
    current_node_id: UUID | None
    status: StateStatus
    resolution_id: UUID | None
    version: int
    last_idempotency_key: str | None = None
    quarantined_node_ids: frozenset[UUID] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        slot_key = self.slot_key.strip()
        if not slot_key:
            raise ValueError("slot_key must not be empty")
        if self.version < 0:
            raise ValueError("version must not be negative")
        if self.version > 0 and self.resolution_id is None:
            raise ValueError("versioned stored state requires resolution_id")
        if self.last_idempotency_key is not None and not self.last_idempotency_key.strip():
            raise ValueError("last_idempotency_key must not be empty")
        quarantined = frozenset(self.quarantined_node_ids)
        object.__setattr__(self, "slot_key", slot_key)
        object.__setattr__(self, "quarantined_node_ids", quarantined)

    def to_dict(self) -> dict[str, Any]:
        return {
            "space_id": str(self.space_id),
            "slot_key": self.slot_key,
            "current_node_id": (
                str(self.current_node_id) if self.current_node_id is not None else None
            ),
            "status": self.status.value,
            "resolution_id": (
                str(self.resolution_id) if self.resolution_id is not None else None
            ),
            "version": self.version,
            "last_idempotency_key": self.last_idempotency_key,
            "quarantined_node_ids": sorted(
                str(node_id) for node_id in self.quarantined_node_ids
            ),
        }


@dataclass(frozen=True, slots=True)
class StateProjectionVerification:
    projection: StateProjection
    stored_slot: StoredStateSlot
    mismatches: tuple[str, ...]

    @property
    def matches(self) -> bool:
        return not self.mismatches

    def to_dict(self) -> dict[str, Any]:
        return {
            "matches": self.matches,
            "mismatches": list(self.mismatches),
            "projection": self.projection.to_dict(),
            "stored_slot": self.stored_slot.to_dict(),
        }


ProjectionVerification = StateProjectionVerification
