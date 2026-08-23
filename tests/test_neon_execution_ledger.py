from __future__ import annotations

import json
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from nextgen_memory.execution_ledger import (
    AppendOnlyExecutionLedger,
    ExecutionEventKind,
    ExecutionOutcome,
)
from nextgen_memory.neon_execution_ledger import (
    NeonExecutionLedgerAdapter,
    NeonExecutionLedgerInvariantError,
    NeonExecutionLedgerValidationError,
)

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
SOURCE_ID = UUID("63d09b05-fb44-5022-b1c8-4970c1e11723")
NOW = datetime(2026, 8, 14, 20, 0, tzinfo=UTC)
REQUEST_HASH = "a" * 64
OUTPUT_HASH = "b" * 64
ARTIFACT_DIGEST = "c" * 64
STORAGE_HASH = "d" * 64


class FakeCursor:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def fetchone(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return list(self._rows)


class FakeTransaction(AbstractContextManager[None]):
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def __enter__(self) -> None:
        self.connection.transaction_entries += 1
        return None

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            self.connection.commits += 1
        else:
            self.connection.rollbacks += 1
        return False


class FakeConnection:
    def __init__(self, responses: list[list[Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.transaction_entries = 0
        self.commits = 0
        self.rollbacks = 0

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def execute(self, sql: str, params: dict[str, Any]) -> FakeCursor:
        self.calls.append((sql, dict(params)))
        if not self.responses:
            raise AssertionError("unexpected SQL execution")
        return FakeCursor(self.responses.pop(0))


def build_bundle():
    ledger = AppendOnlyExecutionLedger()
    run = ledger.begin(
        space_id=SPACE_ID,
        source_id=SOURCE_ID,
        repository_key="leon36000/NextGen-Memory",
        branch="feat/neon-execution-ledger-adapter-v0",
        base_revision="adapter-base",
        task_key="adapter-v0",
        session_key="test-session",
        started_at=NOW,
        idempotency_key="run:adapter:001",
        request_hash=REQUEST_HASH,
        metadata={"policy_version": "adapter-v0", "labels": ["safe"]},
    )
    test_event = ledger.append(
        run_id=run.run_id,
        kind=ExecutionEventKind.TEST,
        outcome=ExecutionOutcome.SUCCESS,
        action_key="pytest.adapter",
        started_at=NOW + timedelta(seconds=1),
        ended_at=NOW + timedelta(seconds=2),
        idempotency_key="event:test:adapter:001",
        output_hash=OUTPUT_HASH,
        backend_ref="raw-traces:adapter:pytest",
        metadata={"suite": "unit"},
    )
    artifact = ledger.attach_artifact(
        run_id=run.run_id,
        event_id=test_event.event_id,
        ordinal=1,
        role="test_report",
        artifact_key="pytest:adapter",
        artifact_type="test_report",
        backend_ref="raw-traces:adapter:report",
        digest_algorithm="sha256",
        digest=ARTIFACT_DIGEST,
        metadata={"format": "junit"},
    )
    ledger.complete(
        run.run_id,
        started_at=NOW + timedelta(seconds=3),
        idempotency_key="event:complete:adapter:001",
    )
    return run, ledger.events(run.run_id), (artifact,)


def responses_for_bundle(run, events, artifacts, *, inserted: bool = True):
    responses: list[list[dict[str, Any]]] = [
        [{"id": run.run_id, "content_hash": run.content_hash, "inserted": inserted}]
    ]
    for event in events:
        responses.append(
            [
                {
                    "id": event.event_id,
                    "content_hash": event.content_hash,
                    "storage_content_hash": STORAGE_HASH,
                    "event_hash": event.event_hash,
                    "inserted": inserted,
                }
            ]
        )
    for artifact in artifacts:
        responses.append(
            [
                {
                    "id": artifact.artifact_id,
                    "content_hash": artifact.content_hash,
                    "inserted": inserted,
                }
            ]
        )
    head = events[-1]
    responses.append(
        [
            {
                "head_event_id": head.event_id,
                "head_sequence": head.sequence,
                "head_event_hash": head.event_hash,
                "status": "completed",
                "drift_count": 0,
            }
        ]
    )
    return responses


def test_persist_bundle_uses_one_transaction_and_deterministic_write_order() -> None:
    run, events, artifacts = build_bundle()
    connection = FakeConnection(responses_for_bundle(run, events, artifacts))
    adapter = NeonExecutionLedgerAdapter(connection)

    result = adapter.persist_bundle(run, events, artifacts)

    assert connection.transaction_entries == 1
    assert connection.commits == 1
    assert connection.rollbacks == 0
    assert len(connection.calls) == 1 + len(events) + len(artifacts) + 1
    assert "INSERT INTO ngm.execution_runs" in connection.calls[0][0]
    assert all(
        "INSERT INTO ngm.execution_events" in connection.calls[index][0]
        for index in range(1, 1 + len(events))
    )
    assert "INSERT INTO ngm.execution_artifacts" in connection.calls[-2][0]
    assert "ngm.execution_chain_drift" in connection.calls[-1][0]
    assert result.run.inserted is True
    assert [receipt.record_id for receipt in result.events] == [
        event.event_id for event in events
    ]
    assert result.verification.matches is True


def test_metadata_is_sent_as_deterministic_json_not_driver_specific_objects() -> None:
    run, events, artifacts = build_bundle()
    connection = FakeConnection(responses_for_bundle(run, events, artifacts))
    adapter = NeonExecutionLedgerAdapter(connection)

    adapter.persist_bundle(run, events, artifacts)

    metadata_values = [
        params["metadata"]
        for sql, params in connection.calls
        if "INSERT INTO" in sql and "metadata" in params
    ]
    assert metadata_values
    assert all(isinstance(value, str) for value in metadata_values)
    assert all(json.loads(value) is not None for value in metadata_values)
    assert metadata_values[0] == '{"labels":["safe"],"policy_version":"adapter-v0"}'


def test_exact_replay_receipts_are_not_reported_as_new_inserts() -> None:
    run, events, artifacts = build_bundle()
    connection = FakeConnection(
        responses_for_bundle(run, events, artifacts, inserted=False)
    )

    result = NeonExecutionLedgerAdapter(connection).persist_bundle(
        run, events, artifacts
    )

    assert result.run.inserted is False
    assert all(receipt.inserted is False for receipt in result.events)
    assert all(receipt.inserted is False for receipt in result.artifacts)


def test_event_hash_mismatch_rolls_back_bundle() -> None:
    run, events, artifacts = build_bundle()
    responses = responses_for_bundle(run, events, artifacts)
    responses[2][0]["event_hash"] = "f" * 64
    connection = FakeConnection(responses)

    with pytest.raises(NeonExecutionLedgerInvariantError, match="event_hash"):
        NeonExecutionLedgerAdapter(connection).persist_bundle(
            run, events, artifacts
        )

    assert connection.commits == 0
    assert connection.rollbacks == 1


def test_canonical_content_hash_mismatch_rolls_back_bundle() -> None:
    run, events, artifacts = build_bundle()
    responses = responses_for_bundle(run, events, artifacts)
    responses[0][0]["content_hash"] = "0" * 64
    connection = FakeConnection(responses)

    with pytest.raises(NeonExecutionLedgerInvariantError, match="content_hash"):
        NeonExecutionLedgerAdapter(connection).persist_bundle(
            run, events, artifacts
        )

    assert connection.rollbacks == 1


def test_bundle_rejects_cross_run_artifact_before_opening_transaction() -> None:
    run, events, artifacts = build_bundle()
    foreign = type(artifacts[0])(
        **{
            **artifacts[0].__dict__,
            "run_id": UUID("00000000-0000-0000-0000-000000000099"),
        }
    ) if hasattr(artifacts[0], "__dict__") else None
    if foreign is None:
        from dataclasses import replace

        foreign = replace(
            artifacts[0],
            run_id=UUID("00000000-0000-0000-0000-000000000099"),
        )
    connection = FakeConnection([])

    with pytest.raises(NeonExecutionLedgerValidationError, match="artifact run"):
        NeonExecutionLedgerAdapter(connection).persist_bundle(
            run, events, (foreign,)
        )

    assert connection.transaction_entries == 0
    assert connection.calls == []


def test_bundle_rejects_event_sequence_gap_before_sql() -> None:
    from dataclasses import replace

    run, events, artifacts = build_bundle()
    broken = list(events)
    broken[1] = replace(broken[1], sequence=7)
    connection = FakeConnection([])

    with pytest.raises(NeonExecutionLedgerValidationError, match="sequence"):
        NeonExecutionLedgerAdapter(connection).persist_bundle(
            run, broken, artifacts
        )

    assert connection.transaction_entries == 0


def test_verify_run_reports_database_drift() -> None:
    run, events, _ = build_bundle()
    head = events[-1]
    connection = FakeConnection(
        [
            [
                {
                    "head_event_id": head.event_id,
                    "head_sequence": head.sequence,
                    "head_event_hash": head.event_hash,
                    "status": "completed",
                    "drift_count": 2,
                }
            ]
        ]
    )

    verification = NeonExecutionLedgerAdapter(connection).verify_run(
        run.space_id, run.run_id
    )

    assert verification.matches is False
    assert verification.drift_count == 2


def test_verify_run_rejects_missing_database_head() -> None:
    connection = FakeConnection([[]])

    with pytest.raises(NeonExecutionLedgerInvariantError, match="head"):
        NeonExecutionLedgerAdapter(connection).verify_run(
            SPACE_ID, UUID("00000000-0000-0000-0000-000000000088")
        )
