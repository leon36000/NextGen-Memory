from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

import nextgen_memory.retrieval_telemetry as retrieval_telemetry
from nextgen_memory.retrieval import ResearchRetrievalHit
from nextgen_memory.retrieval_telemetry import (
    RETRIEVAL_EVENT_INSERT_SQL,
    RetrievalEvent,
    RetrievalEventWriter,
    build_retrieval_events,
)

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
OTHER_SPACE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DECISION_ID = UUID("29c9cc3c-8c2e-5d7d-92ff-cc9071fd9cb5")
MEMORY_ID = UUID("4b84a18f-056f-5be9-bd27-a33ef835d29c")


def _hit() -> ResearchRetrievalHit:
    return ResearchRetrievalHit(
        memory_id=MEMORY_ID,
        backend_ref="paper:arxiv:2605.21951",
        rank=1,
        score=0.0163,
        title="Dynamic Mixture of Latent Memories",
        source_uri="https://arxiv.org/html/2605.21951v1",
        tags=("moe", "latent-memory"),
    )


def _event() -> RetrievalEvent:
    return build_retrieval_events(
        space_id=SPACE_ID,
        router_decision_id=DECISION_ID,
        expert_key="research",
        hits=(_hit(),),
    )[0]


def _stored_row(event: RetrievalEvent, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = event.to_db_params()
    row.update(overrides)
    return row


def test_build_events_is_deterministic_and_marks_selected_memories() -> None:
    kwargs = {
        "space_id": SPACE_ID,
        "router_decision_id": DECISION_ID,
        "expert_key": "research",
        "hits": (_hit(),),
        "selected_memory_ids": frozenset({MEMORY_ID}),
    }

    first = build_retrieval_events(**kwargs)
    second = build_retrieval_events(**kwargs)

    assert first == second
    assert first[0].id == second[0].id
    assert first[0].node_id == MEMORY_ID
    assert first[0].selected_for_context is True
    assert first[0].used_in_action is False


def test_event_database_params_never_include_raw_query_text() -> None:
    event = _event()

    params = event.to_db_params()

    assert "query" not in params
    assert "query_text" not in params
    assert params["space_id"] == SPACE_ID
    assert params["router_decision_id"] == DECISION_ID
    assert params["node_id"] == MEMORY_ID
    assert params["backend_ref"] == "paper:arxiv:2605.21951"


class FakeCursor:
    def __init__(self, stored_rows: tuple[object, ...] = ()) -> None:
        self.stored_rows = stored_rows
        self.executemany_calls: list[tuple[str, list[dict[str, object]]]] = []
        self.execute_calls: list[tuple[str, dict[str, object]]] = []
        self.operations: list[str] = []

    def executemany(self, sql: str, rows: list[dict[str, object]]) -> None:
        self.operations.append("executemany")
        self.executemany_calls.append((sql, rows))

    def execute(self, sql: str, params: dict[str, object]) -> None:
        self.operations.append("execute")
        self.execute_calls.append((sql, params))

    def fetchall(self) -> tuple[object, ...]:
        self.operations.append("fetchall")
        return self.stored_rows


def _conflict_error_type() -> type[RuntimeError]:
    error_type = getattr(retrieval_telemetry, "RetrievalEventConflictError", None)
    assert isinstance(error_type, type)
    assert issubclass(error_type, RuntimeError)
    return error_type


def test_writer_uses_parameterized_insert_then_scope_bound_exact_readback() -> None:
    event = _event()
    cursor = FakeCursor((_stored_row(event),))

    count = RetrievalEventWriter().write(cursor, (event,))

    assert count == 1
    assert cursor.operations == ["executemany", "execute", "fetchall"]
    assert cursor.executemany_calls == [
        (RETRIEVAL_EVENT_INSERT_SQL, [event.to_db_params()])
    ]

    select_sql = getattr(retrieval_telemetry, "RETRIEVAL_EVENT_SELECT_SQL", None)
    assert isinstance(select_sql, str)
    assert cursor.execute_calls == [
        (
            select_sql,
            {
                "space_id": SPACE_ID,
                "ids": [event.id],
            },
        )
    ]
    assert "WHERE space_id = %(space_id)s" in select_sql
    assert "id = ANY(%(ids)s::uuid[])" in select_sql
    assert "ORDER BY id" in select_sql


def test_writer_accepts_exact_idempotent_retry() -> None:
    event = _event()

    first = RetrievalEventWriter().write(
        FakeCursor((_stored_row(event),)),
        (event,),
    )
    second = RetrievalEventWriter().write(
        FakeCursor((_stored_row(event),)),
        (event,),
    )

    assert first == second == 1


def test_writer_rejects_conflicting_immutable_payload() -> None:
    event = _event()
    cursor = FakeCursor((_stored_row(event, final_score=0.999),))

    with pytest.raises(_conflict_error_type(), match="immutable payload differs"):
        RetrievalEventWriter().write(cursor, (event,))


@pytest.mark.parametrize(
    ("stored_rows", "message"),
    [
        ((), "missing deterministic rows"),
        (({"id": uuid4()},), "missing immutable fields"),
        ((object(),), "row is not a mapping"),
    ],
)
def test_writer_rejects_missing_or_malformed_readback(
    stored_rows: tuple[object, ...],
    message: str,
) -> None:
    event = _event()

    with pytest.raises(_conflict_error_type(), match=message):
        RetrievalEventWriter().write(FakeCursor(stored_rows), (event,))


def test_writer_rejects_duplicate_readback_id() -> None:
    event = _event()
    row = _stored_row(event)

    with pytest.raises(_conflict_error_type(), match="duplicate ID"):
        RetrievalEventWriter().write(FakeCursor((row, row)), (event,))


def test_writer_rejects_unexpected_readback_id() -> None:
    event = _event()
    unexpected = _stored_row(event, id=uuid4())

    with pytest.raises(_conflict_error_type(), match="unexpected ID"):
        RetrievalEventWriter().write(FakeCursor((unexpected,)), (event,))


def test_writer_conflict_error_does_not_echo_stored_payload() -> None:
    event = _event()
    sentinel = "mongodb://user:secret@private-host/research"
    cursor = FakeCursor((_stored_row(event, backend_ref=sentinel),))

    with pytest.raises(_conflict_error_type()) as exc_info:
        RetrievalEventWriter().write(cursor, (event,))

    message = str(exc_info.value)
    assert sentinel not in message
    assert "secret" not in message
    assert "private-host" not in message


@pytest.mark.parametrize(
    ("events", "message"),
    [
        ((object(),), "RetrievalEvent instances"),
        ((_event(), _event()), "duplicate IDs"),
        (
            (
                _event(),
                replace(_event(), id=uuid4(), space_id=OTHER_SPACE_ID),
            ),
            "one space_id",
        ),
    ],
)
def test_writer_rejects_invalid_batch_before_sql(
    events: tuple[object, ...],
    message: str,
) -> None:
    cursor = FakeCursor()

    with pytest.raises(ValueError, match=message):
        RetrievalEventWriter().write(cursor, events)  # type: ignore[arg-type]

    assert cursor.operations == []


def test_writer_skips_empty_batches() -> None:
    cursor = FakeCursor()

    count = RetrievalEventWriter().write(cursor, ())

    assert count == 0
    assert cursor.operations == []
