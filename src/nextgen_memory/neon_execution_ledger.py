"""Driver-independent Neon persistence for the append-only execution ledger."""

from __future__ import annotations

import json
import re
from collections.abc import ContextManager, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from .execution_ledger import (
    ExecutionArtifact,
    ExecutionEvent,
    ExecutionEventKind,
    ExecutionRun,
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class NeonExecutionLedgerError(RuntimeError):
    """Base error for the durable execution-ledger adapter."""


class NeonExecutionLedgerValidationError(NeonExecutionLedgerError, ValueError):
    """The Python bundle is not structurally safe to persist."""


class NeonExecutionLedgerInvariantError(NeonExecutionLedgerError):
    """Neon returned state that disagrees with canonical Python evidence."""


class CursorProtocol(Protocol):
    def fetchone(self) -> Any | None: ...

    def fetchall(self) -> list[Any]: ...


class ConnectionProtocol(Protocol):
    def transaction(self) -> ContextManager[Any]: ...

    def execute(self, sql: str, params: dict[str, Any]) -> CursorProtocol: ...


INSERT_RUN_SQL = """
INSERT INTO ngm.execution_runs (
  id, space_id, source_id, repository_key, branch, base_revision,
  task_key, session_key, started_at, idempotency_key, request_hash,
  content_hash, metadata
) VALUES (
  %(id)s, %(space_id)s, %(source_id)s, %(repository_key)s, %(branch)s,
  %(base_revision)s, %(task_key)s, %(session_key)s, %(started_at)s,
  %(idempotency_key)s, %(request_hash)s, %(content_hash)s,
  %(metadata)s::jsonb
)
ON CONFLICT (space_id, idempotency_key) DO UPDATE
SET content_hash = ngm.assert_same_execution_payload(
  ngm.execution_runs.id,
  EXCLUDED.id,
  ngm.execution_runs.content_hash,
  EXCLUDED.content_hash,
  'execution_run'
)
RETURNING id, content_hash, (xmax = 0) AS inserted
""".strip()

INSERT_EVENT_SQL = """
INSERT INTO ngm.execution_events (
  id, space_id, run_id, sequence, previous_event_id, kind, outcome,
  action_key, started_at, ended_at, command_fingerprint, input_hash,
  output_hash, backend_ref, idempotency_key, content_hash, metadata
) VALUES (
  %(id)s, %(space_id)s, %(run_id)s, %(sequence)s, %(previous_event_id)s,
  %(kind)s, %(outcome)s, %(action_key)s, %(started_at)s, %(ended_at)s,
  %(command_fingerprint)s, %(input_hash)s, %(output_hash)s, %(backend_ref)s,
  %(idempotency_key)s, %(content_hash)s, %(metadata)s::jsonb
)
ON CONFLICT (space_id, run_id, idempotency_key) DO UPDATE
SET content_hash = ngm.assert_same_execution_payload(
  ngm.execution_events.id,
  EXCLUDED.id,
  ngm.execution_events.content_hash,
  EXCLUDED.content_hash,
  'execution_event'
)
RETURNING
  id,
  content_hash,
  storage_content_hash,
  event_hash,
  (xmax = 0) AS inserted
""".strip()

INSERT_ARTIFACT_SQL = """
INSERT INTO ngm.execution_artifacts (
  id, space_id, run_id, event_id, ordinal, role, artifact_key,
  artifact_type, memory_id, backend_ref, digest_algorithm, digest,
  content_hash, metadata
) VALUES (
  %(id)s, %(space_id)s, %(run_id)s, %(event_id)s, %(ordinal)s,
  %(role)s, %(artifact_key)s, %(artifact_type)s, %(memory_id)s,
  %(backend_ref)s, %(digest_algorithm)s, %(digest)s, %(content_hash)s,
  %(metadata)s::jsonb
)
ON CONFLICT (space_id, event_id, ordinal) DO UPDATE
SET content_hash = ngm.assert_same_execution_payload(
  ngm.execution_artifacts.id,
  EXCLUDED.id,
  ngm.execution_artifacts.content_hash,
  EXCLUDED.content_hash,
  'execution_artifact'
)
RETURNING id, content_hash, (xmax = 0) AS inserted
""".strip()

VERIFY_RUN_SQL = """
SELECT
  heads.head_event_id,
  heads.head_sequence,
  heads.head_event_hash,
  heads.status,
  (
    SELECT count(*)::bigint
    FROM ngm.execution_chain_drift AS drift
    WHERE drift.space_id = %(space_id)s
      AND drift.run_id = %(run_id)s
  ) AS drift_count
FROM ngm.execution_run_heads AS heads
WHERE heads.space_id = %(space_id)s
  AND heads.run_id = %(run_id)s
""".strip()


@dataclass(frozen=True, slots=True)
class WriteReceipt:
    record_id: UUID
    content_hash: str
    inserted: bool


@dataclass(frozen=True, slots=True)
class EventWriteReceipt(WriteReceipt):
    storage_content_hash: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class RunVerification:
    space_id: UUID
    run_id: UUID
    head_event_id: UUID
    head_sequence: int
    head_event_hash: str
    status: str
    drift_count: int

    @property
    def matches(self) -> bool:
        return self.drift_count == 0


@dataclass(frozen=True, slots=True)
class BundleWriteResult:
    run: WriteReceipt
    events: tuple[EventWriteReceipt, ...]
    artifacts: tuple[WriteReceipt, ...]
    verification: RunVerification


class NeonExecutionLedgerAdapter:
    """Persist canonical execution evidence through a structural DB protocol."""

    def __init__(self, connection: ConnectionProtocol) -> None:
        self._connection = connection

    def persist_run(self, run: ExecutionRun) -> WriteReceipt:
        row = self._execute_one(
            INSERT_RUN_SQL,
            {
                "id": run.run_id,
                "space_id": run.space_id,
                "source_id": run.source_id,
                "repository_key": run.repository_key,
                "branch": run.branch,
                "base_revision": run.base_revision,
                "task_key": run.task_key,
                "session_key": run.session_key,
                "started_at": run.started_at,
                "idempotency_key": run.idempotency_key,
                "request_hash": run.request_hash,
                "content_hash": run.content_hash,
                "metadata": _metadata_json(run.metadata),
            },
            "execution run",
        )
        receipt = WriteReceipt(
            record_id=_uuid_value(row, "id", 0),
            content_hash=_string_value(row, "content_hash", 1),
            inserted=_bool_value(row, "inserted", 2),
        )
        self._require_identity(run.run_id, run.content_hash, receipt, "execution run")
        return receipt

    def persist_event(self, event: ExecutionEvent) -> EventWriteReceipt:
        row = self._execute_one(
            INSERT_EVENT_SQL,
            {
                "id": event.event_id,
                "space_id": event.space_id,
                "run_id": event.run_id,
                "sequence": event.sequence,
                "previous_event_id": event.previous_event_id,
                "kind": event.kind.value,
                "outcome": event.outcome.value,
                "action_key": event.action_key,
                "started_at": event.started_at,
                "ended_at": event.ended_at,
                "command_fingerprint": event.command_fingerprint,
                "input_hash": event.input_hash,
                "output_hash": event.output_hash,
                "backend_ref": event.backend_ref,
                "idempotency_key": event.idempotency_key,
                "content_hash": event.content_hash,
                "metadata": _metadata_json(event.metadata),
            },
            "execution event",
        )
        receipt = EventWriteReceipt(
            record_id=_uuid_value(row, "id", 0),
            content_hash=_string_value(row, "content_hash", 1),
            storage_content_hash=_hash_value(row, "storage_content_hash", 2),
            event_hash=_hash_value(row, "event_hash", 3),
            inserted=_bool_value(row, "inserted", 4),
        )
        self._require_identity(event.event_id, event.content_hash, receipt, "execution event")
        if receipt.event_hash != event.event_hash:
            raise NeonExecutionLedgerInvariantError(
                "Neon event_hash disagrees with canonical Python execution evidence"
            )
        return receipt

    def persist_artifact(self, artifact: ExecutionArtifact) -> WriteReceipt:
        row = self._execute_one(
            INSERT_ARTIFACT_SQL,
            {
                "id": artifact.artifact_id,
                "space_id": artifact.space_id,
                "run_id": artifact.run_id,
                "event_id": artifact.event_id,
                "ordinal": artifact.ordinal,
                "role": artifact.role,
                "artifact_key": artifact.artifact_key,
                "artifact_type": artifact.artifact_type,
                "memory_id": artifact.memory_id,
                "backend_ref": artifact.backend_ref,
                "digest_algorithm": artifact.digest_algorithm,
                "digest": artifact.digest,
                "content_hash": artifact.content_hash,
                "metadata": _metadata_json(artifact.metadata),
            },
            "execution artifact",
        )
        receipt = WriteReceipt(
            record_id=_uuid_value(row, "id", 0),
            content_hash=_string_value(row, "content_hash", 1),
            inserted=_bool_value(row, "inserted", 2),
        )
        self._require_identity(
            artifact.artifact_id,
            artifact.content_hash,
            receipt,
            "execution artifact",
        )
        return receipt

    def persist_bundle(
        self,
        run: ExecutionRun,
        events: Iterable[ExecutionEvent],
        artifacts: Iterable[ExecutionArtifact],
    ) -> BundleWriteResult:
        ordered_events, ordered_artifacts = _validate_bundle(run, events, artifacts)
        with self._connection.transaction():
            run_receipt = self.persist_run(run)
            event_receipts = tuple(
                self.persist_event(event) for event in ordered_events
            )
            artifact_receipts = tuple(
                self.persist_artifact(artifact) for artifact in ordered_artifacts
            )
            verification = self.verify_run(run.space_id, run.run_id)
            expected_head = ordered_events[-1]
            if not verification.matches:
                raise NeonExecutionLedgerInvariantError(
                    f"Neon execution chain contains {verification.drift_count} drift row(s)"
                )
            if (
                verification.head_event_id != expected_head.event_id
                or verification.head_sequence != expected_head.sequence
                or verification.head_event_hash != expected_head.event_hash
            ):
                raise NeonExecutionLedgerInvariantError(
                    "Neon execution head disagrees with the canonical Python bundle"
                )
            return BundleWriteResult(
                run=run_receipt,
                events=event_receipts,
                artifacts=artifact_receipts,
                verification=verification,
            )

    def verify_run(self, space_id: UUID, run_id: UUID) -> RunVerification:
        row = self._execute_one(
            VERIFY_RUN_SQL,
            {"space_id": space_id, "run_id": run_id},
            "execution run head",
        )
        return RunVerification(
            space_id=space_id,
            run_id=run_id,
            head_event_id=_uuid_value(row, "head_event_id", 0),
            head_sequence=_int_value(row, "head_sequence", 1),
            head_event_hash=_hash_value(row, "head_event_hash", 2),
            status=_string_value(row, "status", 3),
            drift_count=_int_value(row, "drift_count", 4),
        )

    def _execute_one(
        self,
        sql: str,
        params: dict[str, Any],
        description: str,
    ) -> Any:
        row = self._connection.execute(sql, params).fetchone()
        if row is None:
            raise NeonExecutionLedgerInvariantError(
                f"Neon returned no {description} row"
            )
        return row

    @staticmethod
    def _require_identity(
        expected_id: UUID,
        expected_hash: str,
        receipt: WriteReceipt,
        description: str,
    ) -> None:
        if receipt.record_id != expected_id:
            raise NeonExecutionLedgerInvariantError(
                f"Neon {description} ID disagrees with canonical Python evidence"
            )
        if receipt.content_hash != expected_hash:
            raise NeonExecutionLedgerInvariantError(
                f"Neon {description} content_hash disagrees with canonical Python evidence"
            )


def _validate_bundle(
    run: ExecutionRun,
    events: Iterable[ExecutionEvent],
    artifacts: Iterable[ExecutionArtifact],
) -> tuple[tuple[ExecutionEvent, ...], tuple[ExecutionArtifact, ...]]:
    ordered_events = tuple(sorted(events, key=lambda event: event.sequence))
    if not ordered_events:
        raise NeonExecutionLedgerValidationError(
            "execution bundle requires at least one event"
        )

    event_ids: set[UUID] = set()
    event_sequences: dict[UUID, int] = {}
    previous: ExecutionEvent | None = None
    for expected_sequence, event in enumerate(ordered_events, start=1):
        if event.space_id != run.space_id or event.run_id != run.run_id:
            raise NeonExecutionLedgerValidationError(
                "execution event scope or run does not match the bundle run"
            )
        if event.sequence != expected_sequence:
            raise NeonExecutionLedgerValidationError(
                f"execution event sequence must be contiguous at {expected_sequence}"
            )
        expected_previous = previous.event_id if previous is not None else None
        if event.previous_event_id != expected_previous:
            raise NeonExecutionLedgerValidationError(
                "execution event predecessor does not match bundle order"
            )
        if previous is not None and previous.kind in {
            ExecutionEventKind.RUN_COMPLETED,
            ExecutionEventKind.RUN_FAILED,
            ExecutionEventKind.RUN_CANCELLED,
        }:
            raise NeonExecutionLedgerValidationError(
                "execution bundle contains an event after terminal state"
            )
        event_ids.add(event.event_id)
        event_sequences[event.event_id] = event.sequence
        previous = event

    first = ordered_events[0]
    if (
        first.kind is not ExecutionEventKind.RUN_STARTED
        or first.input_hash != run.request_hash
        or first.started_at != run.started_at
    ):
        raise NeonExecutionLedgerValidationError(
            "first execution event does not bind to the bundle run"
        )

    ordered_artifacts = tuple(
        sorted(
            artifacts,
            key=lambda artifact: (
                event_sequences.get(artifact.event_id, 2**63),
                artifact.ordinal,
                artifact.artifact_id.int,
            ),
        )
    )
    seen_ordinals: set[tuple[UUID, int]] = set()
    for artifact in ordered_artifacts:
        if artifact.run_id != run.run_id:
            raise NeonExecutionLedgerValidationError(
                "execution artifact run does not match the bundle run"
            )
        if artifact.space_id != run.space_id:
            raise NeonExecutionLedgerValidationError(
                "execution artifact scope does not match the bundle run"
            )
        if artifact.event_id not in event_ids:
            raise NeonExecutionLedgerValidationError(
                "execution artifact references an event outside the bundle"
            )
        identity = (artifact.event_id, artifact.ordinal)
        if identity in seen_ordinals:
            raise NeonExecutionLedgerValidationError(
                "execution artifact ordinal is duplicated for an event"
            )
        seen_ordinals.add(identity)

    return ordered_events, ordered_artifacts


def _metadata_json(metadata: Mapping[str, Any]) -> str:
    return json.dumps(
        _thaw_json(metadata),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(nested) for nested in value]
    if isinstance(value, list):
        return [_thaw_json(nested) for nested in value]
    return value


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, Mapping):
        if key not in row:
            raise NeonExecutionLedgerInvariantError(
                f"Neon result is missing required column {key}"
            )
        return row[key]
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
        try:
            return row[index]
        except IndexError as error:
            raise NeonExecutionLedgerInvariantError(
                f"Neon result is missing positional column {index}"
            ) from error
    raise NeonExecutionLedgerInvariantError("Neon result row has an unsupported shape")


def _uuid_value(row: Any, key: str, index: int) -> UUID:
    value = _row_value(row, key, index)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as error:
        raise NeonExecutionLedgerInvariantError(
            f"Neon column {key} is not a UUID"
        ) from error


def _string_value(row: Any, key: str, index: int) -> str:
    value = _row_value(row, key, index)
    if not isinstance(value, str) or not value:
        raise NeonExecutionLedgerInvariantError(
            f"Neon column {key} is not a non-empty string"
        )
    return value


def _hash_value(row: Any, key: str, index: int) -> str:
    value = _string_value(row, key, index)
    if _HASH_RE.fullmatch(value) is None:
        raise NeonExecutionLedgerInvariantError(
            f"Neon column {key} is not a lowercase SHA-256 digest"
        )
    return value


def _bool_value(row: Any, key: str, index: int) -> bool:
    value = _row_value(row, key, index)
    if not isinstance(value, bool):
        raise NeonExecutionLedgerInvariantError(
            f"Neon column {key} is not boolean"
        )
    return value


def _int_value(row: Any, key: str, index: int) -> int:
    value = _row_value(row, key, index)
    if isinstance(value, bool) or not isinstance(value, int):
        raise NeonExecutionLedgerInvariantError(
            f"Neon column {key} is not an integer"
        )
    return value
