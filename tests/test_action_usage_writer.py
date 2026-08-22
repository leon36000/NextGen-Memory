from __future__ import annotations

import importlib
from types import ModuleType
from uuid import UUID, uuid4

import pytest

from nextgen_memory.retrieval_telemetry import RetrievalEvent

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
DECISION_ID = UUID("00000000-0000-5000-8000-000000000021")
ACTION_ID = UUID("00000000-0000-5000-8000-000000000031")
OTHER_ACTION_ID = UUID("00000000-0000-5000-8000-000000000032")
MEMORY_ID = UUID("00000000-0000-5000-8000-000000000001")
RETRIEVAL_ID = UUID("00000000-0000-5000-8000-000000000011")


def action_usage() -> ModuleType:
    return importlib.import_module("nextgen_memory.action_usage")


def built_event():
    module = action_usage()
    retrieval = RetrievalEvent(
        id=RETRIEVAL_ID,
        space_id=SPACE_ID,
        router_decision_id=DECISION_ID,
        expert_key="research",
        node_id=MEMORY_ID,
        backend_ref="paper:test",
        rank=1,
        raw_score=0.5,
        final_score=0.5,
        selected_for_context=True,
    )
    return module.build_action_memory_usage_events(
        action_id=ACTION_ID,
        retrieval_events=(retrieval,),
        used_memory_ids=frozenset({MEMORY_ID}),
    )[0]


class FakeCursor:
    def __init__(self, rows: tuple[object, ...] = ()) -> None:
        self.rows = rows
        self.operations: list[str] = []
        self.executemany_calls: list[tuple[str, list[dict[str, object]]]] = []
        self.execute_calls: list[tuple[str, dict[str, object]]] = []

    def executemany(self, sql: str, params: list[dict[str, object]]) -> None:
        self.operations.append("executemany")
        self.executemany_calls.append((sql, params))

    def execute(self, sql: str, params: dict[str, object]) -> None:
        self.operations.append("execute")
        self.execute_calls.append((sql, params))

    def fetchall(self) -> tuple[object, ...]:
        self.operations.append("fetchall")
        return self.rows


def stored_row(event, **overrides: object) -> dict[str, object]:
    row = event.to_db_params()
    row.update(overrides)
    return row


def conflict_type():
    error = action_usage().ActionMemoryUsageConflictError
    assert issubclass(error, RuntimeError)
    return error


def test_writer_inserts_then_reads_back_exact_action_scope() -> None:
    module = action_usage()
    event = built_event()
    cursor = FakeCursor((stored_row(event),))

    assert module.ActionMemoryUsageWriter().write(cursor, (event,)) == 1
    assert cursor.operations == ["executemany", "execute", "fetchall"]
    assert cursor.executemany_calls == [
        (module.ACTION_MEMORY_USAGE_INSERT_SQL, [event.to_db_params()])
    ]
    assert cursor.execute_calls == [
        (
            module.ACTION_MEMORY_USAGE_SELECT_SQL,
            {
                "space_id": SPACE_ID,
                "action_id": ACTION_ID,
                "ids": [event.id],
            },
        )
    ]
    assert "space_id = %(space_id)s" in module.ACTION_MEMORY_USAGE_SELECT_SQL
    assert "action_id = %(action_id)s" in module.ACTION_MEMORY_USAGE_SELECT_SQL
    assert "id = ANY(%(ids)s::uuid[])" in module.ACTION_MEMORY_USAGE_SELECT_SQL


def test_writer_accepts_exact_retry() -> None:
    module = action_usage()
    event = built_event()

    assert module.ActionMemoryUsageWriter().write(
        FakeCursor((stored_row(event),)),
        (event,),
    ) == 1


def test_writer_rejects_conflicting_stored_payload_without_echo() -> None:
    module = action_usage()
    event = built_event()
    sentinel = "private-secret-payload"
    row = stored_row(event, content_hash="f" * 64, sentinel=sentinel)

    with pytest.raises(conflict_type(), match="immutable payload") as exc_info:
        module.ActionMemoryUsageWriter().write(FakeCursor((row,)), (event,))

    assert sentinel not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ((), "missing"),
        ((object(),), "mapping"),
        (({"id": uuid4()},), "missing immutable fields"),
    ],
)
def test_writer_rejects_missing_or_malformed_readback(
    rows: tuple[object, ...],
    message: str,
) -> None:
    module = action_usage()
    event = built_event()

    with pytest.raises(conflict_type(), match=message):
        module.ActionMemoryUsageWriter().write(FakeCursor(rows), (event,))


def test_writer_rejects_duplicate_or_unexpected_readback() -> None:
    module = action_usage()
    event = built_event()
    row = stored_row(event)

    with pytest.raises(conflict_type(), match="duplicate"):
        module.ActionMemoryUsageWriter().write(FakeCursor((row, row)), (event,))

    with pytest.raises(conflict_type(), match="unexpected"):
        module.ActionMemoryUsageWriter().write(
            FakeCursor((stored_row(event, id=uuid4()),)),
            (event,),
        )


def test_writer_validates_one_action_before_sql() -> None:
    module = action_usage()
    event = built_event()
    conflicting = module.ActionMemoryUsageEvent(
        id=uuid4(),
        space_id=event.space_id,
        action_id=OTHER_ACTION_ID,
        router_decision_id=event.router_decision_id,
        retrieval_event_id=uuid4(),
        memory_id=uuid4(),
        content_hash="a" * 64,
    )
    cursor = FakeCursor()

    with pytest.raises(ValueError, match="one action_id"):
        module.ActionMemoryUsageWriter().write(cursor, (event, conflicting))
    assert cursor.operations == []


def test_writer_empty_batch_is_noop() -> None:
    module = action_usage()
    cursor = FakeCursor()

    assert module.ActionMemoryUsageWriter().write(cursor, ()) == 0
    assert cursor.operations == []
