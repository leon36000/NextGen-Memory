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
            raise ExecutionLedgerValidationError(
                "kind must be an ExecutionEventKind"
            )
        if not isinstance(self.outcome, ExecutionOutcome):
            raise ExecutionLedgerValidationError(
                "outcome must be an ExecutionOutcome"
            )
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
        elif (
            self.previous_event_id is None
            or self.kind is ExecutionEventKind.RUN_STARTED
        ):
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
        if (
            _ACTION_RE.fullmatch(self.action_key) is None
            or not self.idempotency_key.strip()
        ):
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


def _freeze_metadata(
    metadata: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
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
                        "duplicate metadata key after normalization: "
                        f"{path}.{stored_key}"
                    )
                if _metadata_key_is_forbidden(stored_key):
                    raise ExecutionLedgerValidationError(
                        f"forbidden metadata key: {stored_key}"
                    )
                normalized_keys.add(normalized_key)
                frozen[stored_key] = _freeze_json(
                    nested,
                    active_ids,
                    f"{path}.{stored_key}",
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
                "metadata numbers must be finite JSON numbers"
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
        self._run_keys: dict[tuple[UUID, str], UUID] = {}
        self._events: dict[UUID, list[ExecutionEvent]] = {}
        self._event_keys: dict[tuple[UUID, str], ExecutionEvent] = {}
        self._artifacts: dict[UUID, list[ExecutionArtifact]] = {}
        self._artifact_ordinals: dict[tuple[UUID, int], ExecutionArtifact] = {}

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
        repository_key = repository_key.strip()
        idempotency_key = idempotency_key.strip()
        if not repository_key or not idempotency_key:
            raise ExecutionLedgerValidationError(
                "repository_key and idempotency_key are required"
            )
        _require_aware("started_at", started_at)
        _require_hash("request_hash", request_hash)
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
            branch=payload["branch"],
            base_revision=payload["base_revision"],
            task_key=payload["task_key"],
            session_key=payload["session_key"],
            started_at=started_at,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            content_hash=_hash_payload(payload),
            metadata=frozen_metadata,
        )
        key = (space_id, idempotency_key)
        existing_id = self._run_keys.get(key)
        if existing_id is not None:
            existing = self._runs[existing_id]
            if existing.content_hash != candidate.content_hash:
                raise ExecutionLedgerConflictError(
                    "run idempotency key was reused with different immutable content"
                )
            return existing

        self._runs[run_id] = candidate
        self._run_keys[key] = run_id
        self._events[run_id] = []
        self._artifacts[run_id] = []
        self._append_event(
            run=candidate,
            kind=ExecutionEventKind.RUN_STARTED,
            outcome=ExecutionOutcome.UNKNOWN,
            action_key="run.start",
            started_at=started_at,
            ended_at=None,
            idempotency_key=f"{idempotency_key}:started",
            command_fingerprint=None,
            input_hash=request_hash,
            output_hash=None,
            backend_ref=None,
            metadata={},
        )
        return candidate

    def append(
        self,
        *,
        run_id: UUID,
        kind: ExecutionEventKind,
        outcome: ExecutionOutcome,
        action_key: str,
        started_at: datetime,
        idempotency_key: str,
        ended_at: datetime | None = None,
        command_fingerprint: str | None = None,
        input_hash: str | None = None,
        output_hash: str | None = None,
        backend_ref: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionEvent:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"unknown run_id {run_id}")
        if not isinstance(kind, ExecutionEventKind):
            raise ExecutionLedgerValidationError(
                "kind must be an ExecutionEventKind"
            )
        if not isinstance(outcome, ExecutionOutcome):
            raise ExecutionLedgerValidationError(
                "outcome must be an ExecutionOutcome"
            )
        if kind is ExecutionEventKind.RUN_STARTED:
            raise ExecutionLedgerValidationError(
                "run_started can only be created by begin"
            )
        return self._append_event(
            run=run,
            kind=kind,
            outcome=outcome,
            action_key=action_key,
            started_at=started_at,
            ended_at=ended_at,
            idempotency_key=idempotency_key,
            command_fingerprint=command_fingerprint,
            input_hash=input_hash,
            output_hash=output_hash,
            backend_ref=backend_ref,
            metadata=metadata,
        )

    def _append_event(
        self,
        *,
        run: ExecutionRun,
        kind: ExecutionEventKind,
        outcome: ExecutionOutcome,
        action_key: str,
        started_at: datetime,
        ended_at: datetime | None,
        idempotency_key: str,
        command_fingerprint: str | None,
        input_hash: str | None,
        output_hash: str | None,
        backend_ref: str | None,
        metadata: Mapping[str, Any] | None,
    ) -> ExecutionEvent:
        action_key = action_key.strip()
        idempotency_key = idempotency_key.strip()
        if _ACTION_RE.fullmatch(action_key) is None or not idempotency_key:
            raise ExecutionLedgerValidationError(
                "action_key or event idempotency_key is invalid"
            )
        _require_aware("started_at", started_at)
        if ended_at is not None:
            _require_aware("ended_at", ended_at)
            if ended_at < started_at:
                raise ExecutionLedgerValidationError(
                    "ended_at cannot precede started_at"
                )
        for name, value in (
            ("command_fingerprint", command_fingerprint),
            ("input_hash", input_hash),
            ("output_hash", output_hash),
        ):
            _require_hash(name, value)

        events = self._events[run.run_id]
        existing = self._event_keys.get((run.run_id, idempotency_key))
        previous = events[-1] if events else None
        sequence = existing.sequence if existing is not None else len(events) + 1
        previous_id = (
            existing.previous_event_id
            if existing is not None
            else previous.event_id if previous is not None else None
        )
        backend_ref = _normalize_optional(backend_ref)
        frozen_metadata = _freeze_metadata(metadata)
        event_id = uuid5(run.run_id, f"execution-event:{idempotency_key}")
        payload = {
            "event_id": str(event_id),
            "space_id": str(run.space_id),
            "run_id": str(run.run_id),
            "sequence": sequence,
            "previous_event_id": str(previous_id) if previous_id else None,
            "kind": kind.value,
            "outcome": outcome.value,
            "action_key": action_key,
            "started_at": started_at.isoformat(),
            "ended_at": ended_at.isoformat() if ended_at else None,
            "command_fingerprint": command_fingerprint,
            "input_hash": input_hash,
            "output_hash": output_hash,
            "backend_ref": backend_ref,
            "idempotency_key": idempotency_key,
            "metadata": frozen_metadata,
        }
        content_hash = _hash_payload(payload)
        if existing is not None:
            if existing.content_hash != content_hash:
                raise ExecutionLedgerConflictError(
                    "event idempotency key was reused with different immutable content"
                )
            return existing

        if previous is not None and _terminal_outcome(previous.kind) is not None:
            raise ExecutionLedgerConflictError(
                "cannot append after a terminal execution event"
            )
        if started_at < run.started_at or (
            previous is not None and started_at < previous.started_at
        ):
            raise ExecutionLedgerValidationError(
                "execution event time must be non-decreasing"
            )
        expected = _terminal_outcome(kind)
        if expected is not None and outcome is not expected:
            raise ExecutionLedgerValidationError(
                "terminal execution outcome mismatch"
            )
        if kind is ExecutionEventKind.RUN_STARTED:
            if sequence != 1 or outcome is not ExecutionOutcome.UNKNOWN:
                raise ExecutionLedgerValidationError(
                    "run_started must be first with unknown outcome"
                )
            if input_hash != run.request_hash:
                raise ExecutionLedgerValidationError(
                    "run_started input_hash must equal request_hash"
                )

        previous_hash = previous.event_hash if previous is not None else ""
        candidate = ExecutionEvent(
            event_id=event_id,
            space_id=run.space_id,
            run_id=run.run_id,
            sequence=sequence,
            previous_event_id=previous_id,
            kind=kind,
            outcome=outcome,
            action_key=action_key,
            started_at=started_at,
            ended_at=ended_at,
            command_fingerprint=command_fingerprint,
            input_hash=input_hash,
            output_hash=output_hash,
            backend_ref=backend_ref,
            idempotency_key=idempotency_key,
            content_hash=content_hash,
            event_hash=_sha256(f"{previous_hash}:{content_hash}"),
            metadata=frozen_metadata,
        )
        events.append(candidate)
        self._event_keys[(run.run_id, idempotency_key)] = candidate
        return candidate

    def complete(
        self,
        run_id: UUID,
        *,
        started_at: datetime,
        idempotency_key: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionEvent:
        return self.append(
            run_id=run_id,
            kind=ExecutionEventKind.RUN_COMPLETED,
            outcome=ExecutionOutcome.SUCCESS,
            action_key="run.complete",
            started_at=started_at,
            ended_at=started_at,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )

    def fail(
        self,
        run_id: UUID,
        *,
        started_at: datetime,
        idempotency_key: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionEvent:
        return self.append(
            run_id=run_id,
            kind=ExecutionEventKind.RUN_FAILED,
            outcome=ExecutionOutcome.FAILURE,
            action_key="run.fail",
            started_at=started_at,
            ended_at=started_at,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )

    def cancel(
        self,
        run_id: UUID,
        *,
        started_at: datetime,
        idempotency_key: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionEvent:
        return self.append(
            run_id=run_id,
            kind=ExecutionEventKind.RUN_CANCELLED,
            outcome=ExecutionOutcome.CANCELLED,
            action_key="run.cancel",
            started_at=started_at,
            ended_at=started_at,
            idempotency_key=idempotency_key,
            metadata=metadata,
        )

    def attach_artifact(
        self,
        *,
        run_id: UUID,
        event_id: UUID,
        ordinal: int,
        role: str,
        artifact_key: str,
        artifact_type: str,
        memory_id: UUID | None = None,
        backend_ref: str | None = None,
        digest_algorithm: str | None = None,
        digest: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ExecutionArtifact:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"unknown run_id {run_id}")
        if not any(event.event_id == event_id for event in self._events[run_id]):
            raise ExecutionLedgerValidationError(
                "artifact event_id does not belong to run"
            )
        if ordinal <= 0:
            raise ExecutionLedgerValidationError(
                "artifact ordinal must be positive"
            )
        role = role.strip()
        artifact_key = artifact_key.strip()
        artifact_type = artifact_type.strip()
        backend_ref = _normalize_optional(backend_ref)
        if role not in _ALLOWED_ARTIFACT_ROLES:
            raise ExecutionLedgerValidationError("artifact role is not allowed")
        if not artifact_key or not artifact_type:
            raise ExecutionLedgerValidationError(
                "artifact_key and artifact_type are required"
            )
        if memory_id is None and backend_ref is None:
            raise ExecutionLedgerValidationError(
                "artifact requires memory_id or backend_ref"
            )
        if (digest_algorithm is None) != (digest is None):
            raise ExecutionLedgerValidationError(
                "digest_algorithm and digest must be supplied together"
            )
        if digest_algorithm is not None:
            digest_algorithm = digest_algorithm.strip().lower()
            digest = digest.strip().lower() if digest is not None else None
            if _DIGEST_ALGORITHM_RE.fullmatch(digest_algorithm) is None:
                raise ExecutionLedgerValidationError("invalid digest_algorithm")
            if digest is None or _DIGEST_RE.fullmatch(digest) is None:
                raise ExecutionLedgerValidationError("invalid artifact digest")

        frozen_metadata = _freeze_metadata(metadata)
        artifact_id = uuid5(event_id, f"execution-artifact:{ordinal}")
        payload = {
            "artifact_id": str(artifact_id),
            "space_id": str(run.space_id),
            "run_id": str(run_id),
            "event_id": str(event_id),
            "ordinal": ordinal,
            "role": role,
            "artifact_key": artifact_key,
            "artifact_type": artifact_type,
            "memory_id": str(memory_id) if memory_id else None,
            "backend_ref": backend_ref,
            "digest_algorithm": digest_algorithm,
            "digest": digest,
            "metadata": frozen_metadata,
        }
        candidate = ExecutionArtifact(
            artifact_id=artifact_id,
            space_id=run.space_id,
            run_id=run_id,
            event_id=event_id,
            ordinal=ordinal,
            role=role,
            artifact_key=artifact_key,
            artifact_type=artifact_type,
            memory_id=memory_id,
            backend_ref=backend_ref,
            digest_algorithm=digest_algorithm,
            digest=digest,
            content_hash=_hash_payload(payload),
            metadata=frozen_metadata,
        )
        key = (event_id, ordinal)
        existing = self._artifact_ordinals.get(key)
        if existing is not None:
            if existing.content_hash != candidate.content_hash:
                raise ExecutionLedgerConflictError(
                    "artifact ordinal was reused with different immutable content"
                )
            return existing
        self._artifact_ordinals[key] = candidate
        self._artifacts[run_id].append(candidate)
        return candidate

    def events(self, run_id: UUID) -> tuple[ExecutionEvent, ...]:
        if run_id not in self._runs:
            raise KeyError(f"unknown run_id {run_id}")
        return tuple(self._events[run_id])

    def artifacts(self, run_id: UUID) -> tuple[ExecutionArtifact, ...]:
        if run_id not in self._runs:
            raise KeyError(f"unknown run_id {run_id}")
        return tuple(self._artifacts[run_id])

    def verify_chain(self, run_id: UUID) -> bool:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(f"unknown run_id {run_id}")
        previous: ExecutionEvent | None = None
        for expected_sequence, event in enumerate(
            self._events[run_id], start=1
        ):
            if event.sequence != expected_sequence:
                return False
            expected_previous_id = previous.event_id if previous is not None else None
            if event.previous_event_id != expected_previous_id:
                return False
            expected_event_id = uuid5(
                run.run_id,
                f"execution-event:{event.idempotency_key}",
            )
            if event.event_id != expected_event_id:
                return False
            if _hash_payload(_event_payload(event)) != event.content_hash:
                return False
            previous_hash = previous.event_hash if previous is not None else ""
            if _sha256(f"{previous_hash}:{event.content_hash}") != event.event_hash:
                return False
            if previous is not None and event.started_at < previous.started_at:
                return False
            if previous is not None and _terminal_outcome(previous.kind) is not None:
                return False
            previous = event
        return bool(previous)

    def status(self, run_id: UUID) -> ExecutionStatus:
        latest = self.events(run_id)[-1]
        return {
            ExecutionEventKind.RUN_COMPLETED: ExecutionStatus.COMPLETED,
            ExecutionEventKind.RUN_FAILED: ExecutionStatus.FAILED,
            ExecutionEventKind.RUN_CANCELLED: ExecutionStatus.CANCELLED,
        }.get(latest.kind, ExecutionStatus.RUNNING)
