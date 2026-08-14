from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from nextgen_memory.neon_utility import NODE_UTILITY_SELECT_SQL, NodeUtilityReader

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
MEMORY_A = UUID("00000000-0000-5000-8000-000000000001")
MEMORY_B = UUID("00000000-0000-5000-8000-000000000002")
OTHER_SPACE = UUID("00000000-0000-5000-8000-000000000099")
NOW = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


class FakeCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute(self, sql: str, params: dict[str, object]) -> None:
        self.calls.append((sql, params))

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


def utility_row(
    memory_id: UUID,
    *,
    space_id: UUID = SPACE_ID,
    feedback_count: int = 3,
    avg_reward: float | None = 0.5,
    positive_count: int = 2,
    negative_count: int = 1,
) -> dict[str, object]:
    return {
        "space_id": space_id,
        "node_id": memory_id,
        "feedback_count": feedback_count,
        "avg_reward": avg_reward,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "last_feedback_at": NOW,
    }


def test_sql_is_scoped_parameterized_and_aggregate_only() -> None:
    assert "FROM ngm.node_utility" in NODE_UTILITY_SELECT_SQL
    assert "space_id = %(space_id)s" in NODE_UTILITY_SELECT_SQL
    assert "node_id = ANY(%(memory_ids)s::uuid[])" in NODE_UTILITY_SELECT_SQL
    assert "notes" not in NODE_UTILITY_SELECT_SQL
    assert "metadata" not in NODE_UTILITY_SELECT_SQL


def test_reader_maps_scoped_rows_to_immutable_utility_evidence() -> None:
    cursor = FakeCursor([utility_row(MEMORY_A)])

    result = NodeUtilityReader().fetch(
        cursor,
        space_id=SPACE_ID,
        memory_ids=(MEMORY_B, MEMORY_A),
    )

    assert len(cursor.calls) == 1
    sql, params = cursor.calls[0]
    assert sql == NODE_UTILITY_SELECT_SQL
    assert params == {
        "space_id": SPACE_ID,
        "memory_ids": [MEMORY_A, MEMORY_B],
    }
    evidence = result[MEMORY_A]
    assert evidence.feedback_count == 3
    assert evidence.avg_reward == 0.5
    assert evidence.positive_count == 2
    assert evidence.negative_count == 1
    assert evidence.last_feedback_at == NOW
    with pytest.raises(TypeError):
        result[MEMORY_B] = evidence


def test_empty_memory_ids_skip_database_access() -> None:
    cursor = FakeCursor([])

    result = NodeUtilityReader().fetch(cursor, space_id=SPACE_ID, memory_ids=())

    assert result == {}
    assert cursor.calls == []


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([utility_row(MEMORY_A), utility_row(MEMORY_A)], "duplicate"),
        ([utility_row(MEMORY_B)], "unexpected memory_id"),
        ([utility_row(MEMORY_A, space_id=OTHER_SPACE)], "unexpected space_id"),
    ],
)
def test_reader_rejects_duplicate_unexpected_or_out_of_scope_rows(
    rows: list[dict[str, object]],
    message: str,
) -> None:
    cursor = FakeCursor(rows)

    with pytest.raises(ValueError, match=message):
        NodeUtilityReader().fetch(
            cursor,
            space_id=SPACE_ID,
            memory_ids=(MEMORY_A,),
        )


def test_reader_rejects_missing_required_columns() -> None:
    row = utility_row(MEMORY_A)
    del row["feedback_count"]

    with pytest.raises(ValueError, match="missing utility column"):
        NodeUtilityReader().fetch(
            FakeCursor([row]),
            space_id=SPACE_ID,
            memory_ids=(MEMORY_A,),
        )
