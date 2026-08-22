from __future__ import annotations

from uuid import UUID

import pytest

from nextgen_memory.credit_targets import CREDIT_TARGETS_SELECT_SQL, CreditTargetReader

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
ROUTER_DECISION_ID = UUID("00000000-0000-5000-8000-000000000021")
OTHER_DECISION_ID = UUID("00000000-0000-5000-8000-000000000022")
OTHER_SPACE_ID = UUID("00000000-0000-5000-8000-000000000099")
MEMORY_A = UUID("00000000-0000-5000-8000-000000000001")
MEMORY_B = UUID("00000000-0000-5000-8000-000000000002")
EVENT_A = UUID("00000000-0000-5000-8000-000000000011")
EVENT_B = UUID("00000000-0000-5000-8000-000000000012")


class FakeCursor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute(self, sql: str, params: dict[str, object]) -> None:
        self.calls.append((sql, params))

    def fetchall(self) -> list[dict[str, object]]:
        return self.rows


def row(
    memory_id: UUID,
    retrieval_event_id: UUID,
    *,
    space_id: UUID = SPACE_ID,
    router_decision_id: UUID = ROUTER_DECISION_ID,
    rank: int = 1,
    selected_for_context: bool = True,
    used_in_action: bool = True,
) -> dict[str, object]:
    return {
        "space_id": space_id,
        "retrieval_event_id": retrieval_event_id,
        "router_decision_id": router_decision_id,
        "node_id": memory_id,
        "rank": rank,
        "selected_for_context": selected_for_context,
        "used_in_action": used_in_action,
    }


def test_sql_is_scoped_to_selected_canonical_retrieval_events() -> None:
    assert "FROM ngm.retrieval_events" in CREDIT_TARGETS_SELECT_SQL
    assert "space_id = %(space_id)s" in CREDIT_TARGETS_SELECT_SQL
    assert "router_decision_id = %(router_decision_id)s" in CREDIT_TARGETS_SELECT_SQL
    assert "node_id IS NOT NULL" in CREDIT_TARGETS_SELECT_SQL
    assert "selected_for_context = true" in CREDIT_TARGETS_SELECT_SQL
    assert "ORDER BY rank, node_id" in CREDIT_TARGETS_SELECT_SQL
    assert "backend_ref" not in CREDIT_TARGETS_SELECT_SQL


def test_reader_returns_deterministic_targets_and_preserves_use_evidence() -> None:
    cursor = FakeCursor(
        [
            row(MEMORY_A, EVENT_A, rank=1, used_in_action=True),
            row(MEMORY_B, EVENT_B, rank=2, used_in_action=False),
        ]
    )

    targets = CreditTargetReader().fetch(
        cursor,
        space_id=SPACE_ID,
        router_decision_id=ROUTER_DECISION_ID,
    )

    assert cursor.calls == [
        (
            CREDIT_TARGETS_SELECT_SQL,
            {
                "space_id": SPACE_ID,
                "router_decision_id": ROUTER_DECISION_ID,
            },
        )
    ]
    assert [target.memory_id for target in targets] == [MEMORY_A, MEMORY_B]
    assert targets[0].retrieval_event_id == EVENT_A
    assert targets[0].selected_for_context is True
    assert targets[0].used_in_action is True
    assert targets[1].used_in_action is False


def test_reader_allows_empty_result() -> None:
    cursor = FakeCursor([])

    assert CreditTargetReader().fetch(
        cursor,
        space_id=SPACE_ID,
        router_decision_id=ROUTER_DECISION_ID,
    ) == ()


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([row(MEMORY_A, EVENT_A), row(MEMORY_A, EVENT_B, rank=2)], "duplicate"),
        (
            [row(MEMORY_A, EVENT_A, space_id=OTHER_SPACE_ID)],
            "unexpected space_id",
        ),
        (
            [row(MEMORY_A, EVENT_A, router_decision_id=OTHER_DECISION_ID)],
            "unexpected router_decision_id",
        ),
        (
            [row(MEMORY_A, EVENT_A, selected_for_context=False)],
            "not selected_for_context",
        ),
    ],
)
def test_reader_rejects_duplicate_or_out_of_scope_rows(
    rows: list[dict[str, object]],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        CreditTargetReader().fetch(
            FakeCursor(rows),
            space_id=SPACE_ID,
            router_decision_id=ROUTER_DECISION_ID,
        )


def test_reader_rejects_missing_columns_and_invalid_uuid() -> None:
    missing = row(MEMORY_A, EVENT_A)
    del missing["used_in_action"]
    with pytest.raises(ValueError, match="missing credit target column"):
        CreditTargetReader().fetch(
            FakeCursor([missing]),
            space_id=SPACE_ID,
            router_decision_id=ROUTER_DECISION_ID,
        )

    invalid = row(MEMORY_A, EVENT_A)
    invalid["node_id"] = "not-a-uuid"
    with pytest.raises(ValueError, match="node_id must be a UUID"):
        CreditTargetReader().fetch(
            FakeCursor([invalid]),
            space_id=SPACE_ID,
            router_decision_id=ROUTER_DECISION_ID,
        )
