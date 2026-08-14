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


def begin(ledger: AppendOnlyExecutionLedger):
    return ledger.begin(
        space_id=SPACE_ID,
        source_id=SOURCE_ID,
        repository_key="leon36000/NextGen-Memory",
        branch="feat/execution-ledger-v0",
        base_revision="4ad4b9c7",
        task_key="execution-ledger",
        started_at=NOW,
        idempotency_key="run:execution-ledger:001",
        request_hash=REQUEST_HASH,
        metadata={"policy_version": "execution-ledger-v0"},
    )


def test_begin_is_idempotent_and_creates_a_tamper_evident_start_event() -> None:
    ledger = AppendOnlyExecutionLedger()

    first = begin(ledger)
    second = begin(ledger)
    events = ledger.events(first.run_id)

    assert first == second
    assert len(events) == 1
    assert events[0].sequence == 1
    assert events[0].previous_event_id is None
    assert events[0].kind is ExecutionEventKind.RUN_STARTED
    assert events[0].outcome is ExecutionOutcome.UNKNOWN
    assert len(events[0].content_hash) == 64
    assert len(events[0].event_hash) == 64
    assert ledger.status(first.run_id) is ExecutionStatus.RUNNING


def test_reusing_run_idempotency_key_with_different_content_fails_closed() -> None:
    ledger = AppendOnlyExecutionLedger()
    begin(ledger)

    with pytest.raises(ExecutionLedgerConflictError, match="idempotency"):
        ledger.begin(
            space_id=SPACE_ID,
            source_id=SOURCE_ID,
            repository_key="leon36000/NextGen-Memory",
            branch="feat/execution-ledger-v0",
            base_revision="DIFFERENT",
            task_key="execution-ledger",
            started_at=NOW,
            idempotency_key="run:execution-ledger:001",
            request_hash=REQUEST_HASH,
        )


def test_event_chain_is_contiguous_idempotent_and_terminal() -> None:
    ledger = AppendOnlyExecutionLedger()
    run = begin(ledger)

    test_event = ledger.append(
        run_id=run.run_id,
        kind=ExecutionEventKind.TEST,
        outcome=ExecutionOutcome.SUCCESS,
        action_key="pytest.execution-ledger",
        started_at=NOW + timedelta(seconds=1),
        ended_at=NOW + timedelta(seconds=2),
        idempotency_key="event:test:001",
        output_hash=OUTPUT_HASH,
        backend_ref="raw-traces:execution-ledger:test-001",
    )
    repeated = ledger.append(
        run_id=run.run_id,
        kind=ExecutionEventKind.TEST,
        outcome=ExecutionOutcome.SUCCESS,
        action_key="pytest.execution-ledger",
        started_at=NOW + timedelta(seconds=1),
        ended_at=NOW + timedelta(seconds=2),
        idempotency_key="event:test:001",
        output_hash=OUTPUT_HASH,
        backend_ref="raw-traces:execution-ledger:test-001",
    )
    completed = ledger.complete(
        run.run_id,
        started_at=NOW + timedelta(seconds=3),
        idempotency_key="event:complete:001",
    )

    assert repeated == test_event
    assert test_event.sequence == 2
    assert test_event.previous_event_id == ledger.events(run.run_id)[0].event_id
    assert test_event.event_hash != test_event.content_hash
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
    ledger.append(
        run_id=run.run_id,
        kind=ExecutionEventKind.TEST,
        outcome=ExecutionOutcome.SUCCESS,
        action_key="pytest.execution-ledger",
        started_at=NOW + timedlta(seconds=1),
        idempotency_key="event:test:001",
        output_hash=OUTPUT_HASH,
    )

    with pytest.raises(ExecutionLedgerConflictError, match="idempotency"):
        ledger.append(
            run_id=run.run_id,
            kind=ExecutionEventKind.TEST,
            outcome=ExecutionOutcome.FAILURE,
            action_key="pytest.execution-ledger.changed",
            started_at=NOW + timedelta(seconds=1),
            idempotency_key="event:test:001",
            output_hash="d" * 64,
        )


def test_metadata_rejects_raw_sensitive_payloads_recursively() -> None:
    ledger = AppendOnlyExecutionLedger()

    with pytest.raises(ExecutionLedgerValidationError, match="forbidden metadata key"):
        ledger.begin(
            space_id=SPACE_ID,
            source_id=SOURCE_ID,
            repository_key="leon36000/NextGen-Memory",
            started_at=NOW,
            idempotency_key="run:unsafe:001",
            request_hash=REQUEST_HASH,
            metadata={"nested": {"stdout": "raw model output"}},
        )


def test_artifacts_are_immutable_idempotent_and_linked_to_an_event() -> None:
    ledger = AppendOnlyExecutionLedger()
    run = begin(ledger)
    event = ledger.append(
        run_id=run.run_id,
        kind=ExecutionEventKind.TEST,
        outcome=ExecutionOutcome.SUCCESS,
        action_key="pytest.execution-ledger",
        started_at=NOW + timedelta(seconds=1),
        idempotency_key="event:test:001",
        output_hash=OUTPUT_HASH,
    )

    first = ledger.attach_artifact(
        run_id=run.run_id,
        event_id=event.event_id,
        ordinal=1,
        role="test_report",
        artifact_key="pytest:execution-ledger",
        artifact_type="test_report",
        backend_ref="raw-traces:execution-ledger:pytest",
        digest_algorithm="sha256",
        digest=DIGEST,
    )
    second = ledger.attach_artifact(
        run_id=run.run_id,
        event_id=event.event_id,
        ordinal=1,
        role="test_report",
        artifact_key="pytest:execution-ledger",
        artifact_type="test_report",
        backend_ref="raw-traces:execution-ledger:pytest",
        digest_algorithm="sha256",
        digest=DIGEST,
    )

    assert first == second
    assert ledger.artifacts(run.run_id) == (first,)
    with pytest.raises(ExecutionLedgerConflictError, match="artifact ordinal"):
        ledger.attach_artifact(
            run_id=run.run_id,
            event_id=event.event_id,
            ordinal=1,
            role="test_report",
            artifact_key="pytest:changed",
            artifact_type="test_report",
            backend_ref="raw-traces:execution-ledger:pytest",
            digest_algorithm="sha256",
            digest=DIGEST,
        )


def test_metadata_is_deeply_immutable_and_detached_from_caller() -> None:
    ledger = AppendOnlyExecutionLedger()
    metadata = {"nested": {"policy": "v1"}, "labels": ["safe"]}

    run = ledger.begin(
        space_id=SPACE_ID,
        source_id=SOURCE_ID,
        repository_key="leon36000/NextGen-Memory",
        started_at=NOW,
        idempotency_key="run:metadata:immutable",
        request_hash=REQUEST_HASH,
        metadata=metadata,
    )
    metadata["nested"]["policy"] = "mutated"
    metadata["labels"].append("mutated")

    assert run.metadata["nested"]["policy"] == "v1"
    assert run.metadata["labels"] == ("safe",)
    with pytest.raises(TypeError):
        run.metadata["nested"]["policy"] = "blocked"


def test_metadata_rejects_non_finite_numbers() -> None:
    ledger = AppendOnlyExecutionLedger()

    with pytest.raises(ExecutionLedgerValidationError, match="finite JSON number"):
        ledger.begin(
            space_id=SPACE_ID,
            source_id=SOURCE_ID,
            repository_key="leon36000/NextGen-Memory",
            started_at=NOW,
            idempotency_key="run:metadata:nan",
            request_hash=REQUEST_HASH,
            metadata={"quality": float("nan")},
        )
