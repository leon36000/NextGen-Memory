from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from nextgen_memory.execution_ledger import (
    AppendOnlyExecutionLedger,
    ExecutionEvent,
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


def direct_event(**overrides) -> ExecutionEvent:
    values = {
        "event_id": UUID("10000000-0000-0000-0000-000000000001"),
        "space_id": SPACE_ID,
        "run_id": UUID("20000000-0000-0000-0000-000000000001"),
        "sequence": 1,
        "previous_event_id": None,
        "kind": ExecutionEventKind.RUN_STARTED,
        "outcome": ExecutionOutcome.UNKNOWN,
        "action_key": "run.start",
        "started_at": NOW,
        "ended_at": None,
        "command_fingerprint": None,
        "input_hash": REQUEST_HASH,
        "output_hash": None,
        "backend_ref": None,
        "idempotency_key": "event:direct:001",
        "content_hash": "1" * 64,
        "event_hash": "2" * 64,
        "metadata": {},
    }
    values.update(overrides)
    return ExecutionEvent(**values)


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


@pytest.mark.parametrize(
    ("method_name", "expected_status"),
    [
        ("fail", ExecutionStatus.FAILED),
        ("cancel", ExecutionStatus.CANCELLED),
    ],
)
def test_non_success_terminal_states_are_explicit_and_idempotent(
    method_name: str,
    expected_status: ExecutionStatus,
) -> None:
    ledger = AppendOnlyExecutionLedger()
    run = begin(ledger, idempotency_key=f"run:{method_name}")
    method = getattr(ledger, method_name)
    kwargs = {
        "run_id": run.run_id,
        "started_at": NOW + timedelta(seconds=3),
        "idempotency_key": f"event:{method_name}:001",
    }

    first = method(**kwargs)
    second = method(**kwargs)

    assert first == second
    assert ledger.status(run.run_id) is expected_status


def test_append_rejects_non_enum_kind_and_outcome_with_validation_error() -> None:
    ledger = AppendOnlyExecutionLedger()
    run = begin(ledger)

    with pytest.raises(ExecutionLedgerValidationError, match="kind"):
        ledger.append(
            run_id=run.run_id,
            kind="test",
            outcome=ExecutionOutcome.SUCCESS,
            action_key="pytest.execution-ledger",
            started_at=NOW + timedelta(seconds=1),
            idempotency_key="event:bad-kind",
        )
    with pytest.raises(ExecutionLedgerValidationError, match="outcome"):
        ledger.append(
            run_id=run.run_id,
            kind=ExecutionEventKind.TEST,
            outcome="success",
            action_key="pytest.execution-ledger",
            started_at=NOW + timedelta(seconds=1),
            idempotency_key="event:bad-outcome",
        )


def test_execution_event_contract_rejects_semantically_invalid_shapes() -> None:
    with pytest.raises(ExecutionLedgerValidationError, match="first execution event"):
        direct_event(kind=ExecutionEventKind.TEST)
    with pytest.raises(ExecutionLedgerValidationError, match="terminal execution outcome"):
        direct_event(
            sequence=2,
            previous_event_id=UUID("10000000-0000-0000-0000-000000000000"),
            kind=ExecutionEventKind.RUN_COMPLETED,
            outcome=ExecutionOutcome.FAILURE,
            ended_at=NOW,
        )
    with pytest.raises(ExecutionLedgerValidationError, match="require ended_at"):
        direct_event(
            sequence=2,
            previous_event_id=UUID("10000000-0000-0000-0000-000000000000"),
            kind=ExecutionEventKind.RUN_FAILED,
            outcome=ExecutionOutcome.FAILURE,
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


@pytest.mark.parametrize(
    "forbidden_key",
    [
        "access token",
        "api.token",
        "accessToken",
        "query text",
        "APIKey",
        "stdOut",
        "queryText",
        "rawPayload",
        "commandText",
    ],
)
def test_metadata_rejects_forbidden_segments_across_common_key_styles(
    forbidden_key: str,
) -> None:
    ledger = AppendOnlyExecutionLedger()

    with pytest.raises(ExecutionLedgerValidationError, match="forbidden metadata key"):
        begin(
            ledger,
            idempotency_key=f"run:forbidden-style:{forbidden_key}",
            metadata={forbidden_key: "sensitive"},
        )


def test_metadata_rejects_keys_that_normalize_to_empty() -> None:
    ledger = AppendOnlyExecutionLedger()

    with pytest.raises(ExecutionLedgerValidationError, match="metadata key"):
        begin(
            ledger,
            idempotency_key="run:empty-normalized-key",
            metadata={"!!!": "invalid"},
        )


def test_metadata_rejects_keys_that_collide_after_normalization() -> None:
    ledger = AppendOnlyExecutionLedger()

    with pytest.raises(ExecutionLedgerValidationError, match="duplicate metadata key"):
        begin(
            ledger,
            idempotency_key="run:metadata-key-collision",
            metadata={"policy": "v1", " policy ": "v2"},
        )


def test_empty_non_mapping_metadata_is_not_silently_coerced() -> None:
    ledger = AppendOnlyExecutionLedger()

    with pytest.raises(ExecutionLedgerValidationError, match="JSON object"):
        begin(
            ledger,
            idempotency_key="run:empty-list-metadata",
            metadata=[],
        )


def test_cyclic_metadata_is_rejected_as_non_json() -> None:
    ledger = AppendOnlyExecutionLedger()
    metadata: dict[str, object] = {}
    metadata["cycle"] = metadata

    with pytest.raises(ExecutionLedgerValidationError, match="cyclic metadata"):
        begin(
            ledger,
            idempotency_key="run:cyclic-metadata",
            metadata=metadata,
        )


def test_verify_chain_recomputes_content_hash_and_event_identity() -> None:
    ledger = AppendOnlyExecutionLedger()
    run = begin(ledger)
    append_test(ledger, run.run_id)

    assert ledger.verify_chain(run.run_id) is True

    original = ledger.events(run.run_id)[1]
    ledger._events[run.run_id][1] = replace(
        original,
        action_key="pytest.execution-ledger.tampered",
    )
    assert ledger.verify_chain(run.run_id) is False

    ledger._events[run.run_id][1] = replace(
        original,
        event_id=UUID("30000000-0000-0000-0000-000000000001"),
    )
    assert ledger.verify_chain(run.run_id) is False


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
