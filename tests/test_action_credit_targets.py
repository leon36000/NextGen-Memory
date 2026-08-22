from __future__ import annotations

from uuid import UUID

from nextgen_memory.credit_targets import CreditTargetReader

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
DECISION_ID = UUID("00000000-0000-5000-8000-000000000021")
ACTION_ID = UUID("00000000-0000-5000-8000-000000000031")
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


def test_fetch_for_action_uses_exact_action_specific_join() -> None:
    rows = [
        {
            "memory_id": MEMORY_A,
            "retrieval_event_id": EVENT_A,
            "router_decision_id": DECISION_ID,
            "selected_for_context": True,
            "used_in_action": True,
        },
        {
            "memory_id": MEMORY_B,
            "retrieval_event_id": EVENT_B,
            "router_decision_id": DECISION_ID,
            "selected_for_context": True,
            "used_in_action": False,
        },
    ]
    cursor = FakeCursor(rows)

    targets = CreditTargetReader().fetch_for_action(
        cursor,
        space_id=SPACE_ID,
        router_decision_id=DECISION_ID,
        action_id=ACTION_ID,
    )

    assert [target.memory_id for target in targets] == [MEMORY_A, MEMORY_B]
    assert [target.used_in_action for target in targets] == [True, False]
    sql, params = cursor.calls[0]
    assert params == {
        "space_id": SPACE_ID,
        "router_decision_id": DECISION_ID,
        "action_id": ACTION_ID,
    }
    assert "action_memory_usage_events" in sql
    assert "usage.action_id = %(action_id)s" in sql
    assert "usage.retrieval_event_id = retrieval.id" in sql
    assert "usage.node_id = retrieval.node_id" in sql
    assert "usage.router_decision_id = retrieval.router_decision_id" in sql
    assert "usage.space_id = retrieval.space_id" in sql


def test_legacy_fetch_contract_remains_available() -> None:
    cursor = FakeCursor(
        [
            {
                "space_id": SPACE_ID,
                "node_id": MEMORY_A,
                "retrieval_event_id": EVENT_A,
                "router_decision_id": DECISION_ID,
                "rank": 1,
                "selected_for_context": True,
                "used_in_action": False,
            }
        ]
    )

    targets = CreditTargetReader().fetch(
        cursor,
        space_id=SPACE_ID,
        router_decision_id=DECISION_ID,
    )

    assert targets[0].used_in_action is False


def test_action_for_another_id_cannot_contaminate_reader_contract() -> None:
    cursor = FakeCursor(
        [
            {
                "memory_id": MEMORY_A,
                "retrieval_event_id": EVENT_A,
                "router_decision_id": DECISION_ID,
                "selected_for_context": True,
                "used_in_action": False,
            }
        ]
    )

    target = CreditTargetReader().fetch_for_action(
        cursor,
        space_id=SPACE_ID,
        router_decision_id=DECISION_ID,
        action_id=ACTION_ID,
    )[0]

    assert target.used_in_action is False
