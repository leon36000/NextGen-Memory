"""Append-only, tamper-evident execution ledger contracts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Any
from uuid import UUID, uuid5

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTION_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")
_DIGEST_ALGORITHM_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{16,128}$")
_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALPHANUMERIC = re.compile(r"[^A-Za-z0-9]+")
_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "api_key",
        "argv",
        "command",
        "command_text",
        "diff",
        "env",
        "environment",
        "password",
        "patch",
        "patch_text",
        "prompt",
        "query",
        "query_text",
        "raw",
        "raw_payload",
        "secret",
        "stderr",
        "stdout",
        "token",
    }
)
_FORBIDDEN_METADATA_COMPACT = frozenset(
    key.replace("_", "") for key in _FORBIDDEN_METADATA_KEYS
)
_ALLOWED_ARTIFACT_ROLES = frozenset(
    {
        "material",
        "product",
        "modified",
        "deleted",
        "observed",
        "log",
        "byproduct",
        "test_report",
    }
)


class ExecutionLedgerConflictError(ValueError):
    """Immutable content conflicts with an existing idempotency key."""


class ExecutionLedgerValidationError(ValueError):
    """Execution content violates a ledger contract."""


class ExecutionEventKind(StrEnum):
    RUN_STARTED = "run_started"
    OBSERVATION = "observation"
    COMMAND = "command"
    FILE_CHANGE = "file_change"
    TEST = "test"
    BUILD = "build"
    CHECKPOINT = "checkpoint"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_CANCELLED = "run_cancelled"


class ExecutionOutcome(StrEnum):
    UNKNOWN = "unknown"
    SUCCESS = "success"
    FAILURE = "failure"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ExecutionStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ExecutionRun:
    run_id: UUID
    space_id: UUID
    source_id: UUID
    repository_key: str
    branch: str | None
    base_revision: str | None
    task_key: str | None
    session_key: str | None
    started_at: datetime
    idempotency_key: str
    request_hash: str
    content_hash: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    event_id: UUID
    space_id: UUID
    run_id: UUID
    sequence: int
    previous_event_id: UUID | None
    kind: ExecutionEventKind
    outcome: ExecutionOutcome
    action_key: str
    started_at: datetime
    ended_at: datetime | None
    command_fingerprint: str | None
    input_hash: str | None
    output_hash: str | None
    backend_ref: str | None
    idempotency_key: str
    content_hash: str
    event_hash: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ExecutionEventKind):
            raise ExecutionLedgerValidationError("kind must be an ExecutionEventKind")
        if not isinstance(self.outcome, ExecutionOutcome):
            raise ExecutionLedgerValidationError("outcome must be an ExecutionOutcome")
        if self.sequence <= 0:
            raise ExecutionLedgerValidationError("sequence must be positive")
        if self.sequence == 1:
            if (
                self.previous_event_id is not None
                or self.kind is not ExecutionEventKind.RUN_STARTED
            ):
                raise ExecutionLedgerValidationError(
                    "first execution event must be run_started without a predecessor"
                )
        elif self.previous_event_id is None or self.kind is ExecutionEventKind.RUN_STARTED:
            raise ExecutionLedgerValidationError(
                "non-initial events require a predecessor and cannot be run_started"
            )
        _require_aware("started_at", self.started_at)
        if self.ended_at is not None:
            _require_aware("ended_at", self.ended_at)
            if self.ended_at < self.started_at:
                raise ExecutionLedgerValidationError(
                    "ended_at cannot precede started_at"
                )
        terminal_outcome = _terminal_outcome(self.kind)
        if terminal_outcome is not None:
            if self.outcome is not terminal_outcome:
                raise ExecutionLedgerValidationError(
                    "terminal execution outcome mismatch"
                )
            if self.ended_at is None:
                raise ExecutionLedgerValidationError(
                    "terminal execution events require ended_at"
                )
        if (
            self.kind is ExecutionEventKind.RUN_STARTED
            and self.outcome is not ExecutionOutcome.UNKNOWN
        ):
            raise ExecutionLedgerValidationError(
                "run_started must use unknown outcome"
            )
        if _ACTION_RE.fullmatch(self.action_key) is None or not self.idempotency_key.strip():
            raise ExecutionLedgerValidationError(
                "action_key or event idempotency_key is invalid"
            )
        for name, value in (
            ("command_fingerprint", self.command_fingerprint),
            ("input_hash", self.input_hash),
            ("output_hash", self.output_hash),
            ("content_hash", self.content_hash),
            ("event_hash", self.event_hash),
        ):
            _require_hash(name, value)
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


@dataclass(frozen=True, slots=True)
class ExecutionArtifact:
    artifact_id: UUID
    space_id: UUID
    run_id: UUID
    event_id: UUID
    ordinal: int
    role: str
    artifact_key: str
    artifact_type: str
    memory_id: UUID | None
    backend_ref: str | None
    digest_algorithm: str | None
    digest: str | None
    content_hash: str
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        _thaw_json(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _hash_payload(payload: Mapping[str, Any]) -> str:
    return _sha256(_canonical_json(payload))


def _require_aware(name: str, value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ExecutionLedgerValidationError(f"{name} must be timezone-aware")


def _require_hash(name: str, value: str | None) -> None:
    if value is not None and _HASH_RE.fullmatch(value) is None:
        raise ExecutionLedgerValidationError(
            f"{name} must be a lowercase SHA-256 hex digest"
        )


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _normalize_metadata_key(key: str) -> str:
    with_acronyms = _ACRONYM_BOUNDARY.sub("_", key.strip())
    with_boundaries = _CAMEL_CASE_BOUNDARY.sub("_", with_acronyms)
    return _NON_ALPHANUMERIC.sub("_", with_boundaries).strip("_").lower()


def _metadata_key_is_forbidden(key: str) -> bool:
    normalized = _normalize_metadata_key(key)
    if normalized in _FORBIDDEN_METADATA_KEYS:
        return True
    compact = normalized.replace("_", "")
    if compact in _FORBIDDEN_METADATA_COMPACT:
        return True
    segments = {segment for segment in normalized.split("_") if segment}
    return bool(segments & _FORBIDDEN_METADATA_KEYS)


def _freeze_metadata(metadata: Mapping[str, Any] | None) -> Mapping[str, Any]:
    source: Any = {} if metadata is None else metadata
    frozen = _freeze_json(source, set(), "metadata")
    if not isinstance(frozen, Mapping):
        raise ExecutionLedgerValidationError("metadata must be a JSON object")
    if len(_canonical_json(frozen).encode("utf-8")) > 8192:
        raise ExecutionLedgerValidationError("metadata exceeds 8192 bytes")
    return frozen


def _freeze_json(value: Any, active_ids: set[int], path: str) -> Any:
    if isinstance(value, Mapping):
        identity = id(value)
        if identity in active_ids:
            raise ExecutionLedgerValidationError(f"cyclic metadata at {path}")
        active_ids.add(identity)
        try:
            frozen: dict[str, Any] = {}
            normalized_keys: set[str] = set()
            for key, nested in value.items():
                if not isinstance(key, str):
                    raise ExecutionLedgerValidationError(
                        "metadata keys must be strings"
                    )
                stored_key = key.strip()
                if not stored_key:
                    raise ExecutionLedgerValidationError(
                        f"metadata key must not be empty at {path}"
                    )
                normalized_key = _normalize_metadata_key(stored_key)
                if not normalized_key:
                    raise ExecutionLedgerValidationError(
                        f"metadata key normalizes to empty: {path}.{stored_key}"
                    )
                if stored_key in frozen or normalized_key in normalized_keys:
                    raise ExecutionLedgerValidationError(
                        f"duplicate metadata key after normalization: {path}.{stored_key}"
                    )
                if _metadata_key_is_forbidden(stored_key):
                    raise ExecutionLedgerValidationError(
                        f"forbidden metadata key: {stored_key}"
                    )
                normalized_keys.add(normalized_key)
                frozen[stored_key] = _freeze_json(
                    nested, active_ids, f"{path}.{stored_key}"
                )
            return MappingProxyType(frozen)
        finally:
            active_ids.remove(identity)
    if isinstance(value, (list, tuple)):
        identity = id(value)
        if identity in active_ids:
            raise ExecutionLedgerValidationError(f"cyclic metadata at {path}")
        active_ids.add(identity)
        try:
            return tuple(
                _freeze_json(nested, active_ids, f"{path}[{index}]")
                for index, nested in enumerate(value)
            )
        finally:
            active_ids.remove(identity)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ExecutionLedgerValidationError(
                "metadata floats must be finite"
            )
        return value
    raise ExecutionLedgerValidationError(
        f"unsupported metadata value at {path}: {type(value).__name__}"
    )


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(nested) for nested in value]
    return value


def _terminal_outcome(kind: ExecutionEventKind) -> ExecutionOutcome | None:
    return {
        ExecutionEventKind.RUN_COMPLETED: ExecutionOutcome.SUCCESS,
        ExecutionEventKind.RUN_FAILED: ExecutionOutcome.FAILURE,
        ExecutionEventKind.RUN_CANCELLED: ExecutionOutcome.CANCELLED,
    }.get(kind)


def _event_payload(event: ExecutionEvent) -> dict[str, Any]:
    return {
        "event_id": str(event.event_id),
        "space_id": str(event.space_id),
        "run_id": str(event.run_id),
        "sequence": event.sequence,
        "previous_event_id": (
            str(event.previous_event_id) if event.previous_event_id else None
        ),
        "kind": event.kind.value,
        "outcome": event.outcome.value,
        "action_key": event.action_key,
        "started_at": event.started_at.isoformat(),
        "ended_at": event.ended_at.isoformat() if event.ended_at else None,
        "command_fingerprint": event.command_fingerprint,
        "input_hash": event.input_hash,
        "output_hash": event.output_hash,
        "backend_ref": event.backend_ref,
        "idempotency_key": event.idempotency_key,
        "metadata": event.metadata,
    }


class AppendOnlyExecutionLedger:
    """In-memory reference for the durable Neon execution ledger."""

    def __init__(self) -> None:
        self._runs: dict[UUID, ExecutionRun] = {}
        self._run_idempotency: dict[tuple[UUID, str], ExecutionRun] = {}
        self._events: dict[UUID, list[ExecutionEvent]] = {}
        self._event_idempotency: dict[tuple[UUID, str], ExecutionEvent] = {}
        self._artifacts: dict[UUID, list[ExecutionArtifact]] = {}
        self._artifact_ordinals: dict[
            tuple[UUID, int], ExecutionArtifact
        ] = {}

    def begin(
        self,
        *,
        space_id: UUID,
        source_id: UUID,
        repository_key: str,
        started_at: datetime,
        idempotency_key: str,
        request_hash: str,
        branch: str | None = None,
        base_revision: str | None = None,
        task_key: str | None = None,
        session_key: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionRun:
        _require_aware("started_at", started_at)
        _require_hash("request_hash", request_hash)
        repository_key = repository_key.strip()
        idempotency_key = idempotency_key.strip()
        if not repository_key or not idempotency_key:
            raise ExecutionLedgerValidationError(
                "repository_key and run idempotency_key are required"
            )
        frozen_metadata = _freeze_metadata(metadata)
        run_id = uuid5(space_id, f"execution-run:{idempotency_key}")
        payload = {
            "run_id": str(run_id),
            "space_id": str(space_id),
            "source_id": str(source_id),
            "repository_key": repository_key,
            "branch": _normalize_optional(branch),
            "base_revision": _normalize_optional(base_revision),
            "task_key": _normalize_optional(task_key),
            "session_key": _normalize_optional(session_key),
            "started_at": started_at.isoformat(),
            "idempotency_key": idempotency_key,
            "request_hash": request_hash,
            "metadata": frozen_metadata,
        }
        candidate = ExecutionRun(
            run_id=run_id,
            space_id=space_id,
            source_id=source_id,
            repository_key=repository_key,
            branch=_normalize_optional(branch),
            base_revision=_normalize_optional(base_revision),
            task_key=_normalize_optional(task_key),
            session_key=_normalize_optional(session_key),
            started_at=started_at,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            content_hash=_hash_payload(payload),
            metadata=frozen_metadata,
        )
        key = (space_id, idempotency_key)
        existing = self._run_idempotency.get(key)
        if existing is not None:
            if existing.run_id != candidate.run_id or existing.content_hash != candidate.content_hash:
                raise ExecutionLedgerConflictError(
                    "run idempotency_key was reused with different immutable content"
                )
            return existing
        self._runs[run_id] = candidate
        self._run_idempotency[key] = candidate
        self._events[run_id] = []
        self._artifacts[run_id] = []

        self._append start_event with input_hash = run request_hash.
        return candidate
