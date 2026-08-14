from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from nextgen_memory.execution_ledger import (
    AppendOnlyExecutionLedger,
    ExecutionEventKind,
    ExecutionLedgerConflictError,
    ExecutionLedgerValidationError,
    ExecutionOutcome,
    ExecutionStatus,
)

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
SOURCE_ID = UUID("63d09b05-fb44-5022-b1c8-4970c1e11723")
NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)
REQUEST_HASH = "a" * 64
OUTPUT_HASH = "b" * 64
DIGEST = "c" * 64


def begin(ledger: AppendOnlyExecutionLedger, **overrides):
    values = {
        "space_id": SPACE_ID,
        "source_id": SOURCE_ID,
        "repository_key": "leon36000/NextGen-Memory",
        "branch": "feat/execution-ledger-v0",
        "base_revision": "4ad4b9c7",
        "task_key": "execution-ledger",
        "started_at": NOW,
        "idempotency_key": "run:execution-ledger:001",
        "request_hash": REQUEST_HASH,
        "metadata": {"policy_version": "execution-ledger-v0"},
    }
    values.update(overrides)
    return ledger.begin(**values)


def append_test(ledger: AppendOnlyExecutionLedger, run_id: UUID, **overrides):
    values = {
        "run_id": run_id,
        "kind": ExecutionEventKind.TEST,
        "outcome": ExecutionOutcome.SUCCESS,
        "action_key": "pytest.execution-ledger",
        "started_at": NOW + timedelta(seconds=1),
        "idempotency_key": "event:test:001",
        "output_hash": OUTPUT_HASH,
    }
    values.update(overrides)
    return ledger.append(**values)


def test_begin_is_idempotent_and_creates_a_tamper_evident_start_event() -> None:
    ledger = AppendOnlyExecutionLedger()

    first = begin(ledger)
    second = begin(ledger)
    event = ledger.events(first.run_id)[0]

    assert first == second
    assert event.sequence == 1
    assert event.previous_event_id is None
    assert event.kind is ExecutionEventKind.RUN_STARTED
    assert event.outcome is ExecutionOutcome.UNKNOWN
    assert len(event.content_hash) == len(event.event_hash) == 64
    assert ledger.status(first.run_id) is ExecutionStatus.RUNNING


def test_reusing_run_idempotency_key_with_different_content_fails_closed() -> None:
    ledger = AppendOnlyExecutionLedger()
    begin(ledger)

    with pytest.raises(ExecutionLedgerConflictError, match="idempotency"):
        begin(ledger, base_revision="different")


def test_event_chain_is_contiguous_idempotent_and_terminal() -> None:
    ledger = AppendOnlyExecutionLedger()
    run = begin(ledger)

    event = append_test(
        ledger,
        run.run_id,
        ended_at=NOW + timedelta(seconds=2),
        backend_ref="raw-traces:execution-ledger:test-001",
    )
    assert append_test(
        ledger,
        run.run_id,
        ended_at=NOW + timedelta(seconds=2),
        backend_ref="raw-traces:execution-ledger:test-001",
    ) == event
    completed = ledger.complete(
        run.run_id,
        started_at=NOW + timedelta(seconds=3),
        idempotency_key="event:complete:001",
    )

    assert event.sequence == 2
    assert event.previous_event_id == ledger.events(run.run_id)[0].event_id
    assert event.event_hash != event.content_hash
    assert completed.sequence == 3
    assert ledger.status(run.run_id) is ExecutionStatus.COMPLETED
    with pytest.raises(ExecutionLedgerConflictError, match="terminal"):
        ledger.append(
            run_id=run.run_id,
            kind=ExecutionEventKind.OBSERVATION,
            outcome=ExecutionOutcome.UNKNOWN,
            action_key="repository.after-terminal",
            started_at=NOW + timedelta(seconds=4),
            idempotency_key="event:late:001",
        )


def test_event_idempotency_conflict_is_rejected() -> None:
    ledger = AppendOnlyExecutionLedger()
    run = begin(ledger)
    append_test(ledger, run.run_id)

    with pytest.raises(ExecutionLedgerConflictError, match="idempotency"):
        append_test(
            ledger,
            run.run_id,
            outcome=ExecutionOutcome.FAILURE,
            action_key="pytest.execution-ledger.changed",
            output_hash="d" * 64,
        )


def test_metadata_is_safe_deeply_immutable_and_finite() -> None:
    ledger = AppendOnlyExecutionLedger()
    metadata = {"nested": {"policy": "v1"}, "labels": ["safe"]}
    run = begin(ledger, idempotency_key="run:metadata", metadata=metadata)
    metadata["nested"]["policy"] = "mutated"
    metadata["labels"].append("mutated")

    assert run.metadata["nested"]["policy"] == "v1"
    assert run.metadata["labels"] == ("safe",)
    with pytest.raises(TypeError):
        run.metadata["nested"]["policy"] = "blocked"
    with pytest.raises(ExecutionLedgerValidationError, match="forbidden metadata key"):
        begin(
            ledger,
            idempotency_key="run:unsafe",
            metadata={"nested": {"stdout": "raw model output"}},
        )
    with pytest.raises(ExecutionLedgerValidationError, match="finite JSON number"):
        begin(
            ledger,
            idempotency_key="run:nan",
            metadata={"quality": float("nan")},
        )


def test_artifacts_are_idempotent_and_linked_to_an_event() -> None:
    ledger = AppendOnlyExecutionLedger()
    run = begin(ledger)
    event = append_test(ledger, run.run_id)
    kwargs = {
        "run_id": run.run_id,
        "event_id": event.event_id,
        "ordinal": 1,
        "role": "test_report",
        "artifact_key": "pytest:execution-ledger",
        "artifact_type": "test_report",
        "backend_ref": "raw-traces:execution-ledger:pytest",
        "digest_algorithm": "sha256",
        "digest": DIGEST,
    }

    first = ledger.attach_artifact(**kwargs)
    assert ledger.attach_artifact(**kwargs) == first
    assert ledger.artifacts(run.run_id) == (first,)
    with pytest.raises(ExecutionLedgerConflictError, match="artifact ordinal"):
        ledger.attach_artifact(**{**kwargs, "artifact_key": "pytest:changed"})
