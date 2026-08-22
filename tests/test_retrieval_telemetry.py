from __future__ import annotations

from uuid import UUID

from nextgen_memory.retrieval import ResearchRetrievalHit
from nextgen_memory.retrieval_telemetry import (
    RETRIEVAL_EVENT_INSERT_SQL,
    RetrievalEventWriter,
    build_retrieval_events,
)

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
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
    event = build_retrieval_events(
        space_id=SPACE_ID,
        router_decision_id=DECISION_ID,
        expert_key="research",
        hits=(_hit(),),
    )[0]

    params = event.to_db_params()

    assert "query" not in params
    assert "query_text" not in params
    assert params["space_id"] == SPACE_ID
    assert params["router_decision_id"] == DECISION_ID
    assert params["node_id"] == MEMORY_ID
    assert params["backend_ref"] == "paper:arxiv:2605.21951"


class FakeCursor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[dict[str, object]]]] = []

    def executemany(self, sql: str, rows: list[dict[str, object]]) -> None:
        self.calls.append((sql, rows))


def test_writer_uses_parameterized_idempotent_batch_insert() -> None:
    events = build_retrieval_events(
        space_id=SPACE_ID,
        router_decision_id=DECISION_ID,
        expert_key="research",
        hits=(_hit(),),
    )
    cursor = FakeCursor()

    count = RetrievalEventWriter().write(cursor, events)

    assert count == 1
    assert len(cursor.calls) == 1
    sql, rows = cursor.calls[0]
    assert sql == RETRIEVAL_EVENT_INSERT_SQL
    assert "ON CONFLICT (id) DO NOTHING" in sql
    assert "%(space_id)s" in sql
    assert rows == [events[0].to_db_params()]


def test_writer_skips_empty_batches() -> None:
    cursor = FakeCursor()

    count = RetrievalEventWriter().write(cursor, ())

    assert count == 0
    assert cursor.calls == []
