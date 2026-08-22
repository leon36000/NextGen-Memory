"""Read canonical post-action credit targets from retrieval telemetry."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol
from uuid import UUID

from .causal_credit import CreditTarget

CREDIT_TARGETS_SELECT_SQL = """
SELECT
    space_id,
    id AS retrieval_event_id,
    router_decision_id,
    node_id,
    rank,
    selected_for_context,
    used_in_action
FROM ngm.retrieval_events
WHERE space_id = %(space_id)s
  AND router_decision_id = %(router_decision_id)s
  AND node_id IS NOT NULL
  AND selected_for_context = true
ORDER BY rank, node_id
""".strip()

_REQUIRED_COLUMNS = frozenset(
    {
        "space_id",
        "retrieval_event_id",
        "router_decision_id",
        "node_id",
        "rank",
        "selected_for_context",
        "used_in_action",
    }
)


class CreditTargetCursor(Protocol):
    """Minimal mapping-cursor contract for credit target lookup."""

    def execute(self, sql: str, params: Mapping[str, Any]) -> Any:
        """Execute one parameterized statement."""
        ...

    def fetchall(self) -> Iterable[Mapping[str, Any]]:
        """Return mapping-shaped rows."""
        ...


class CreditTargetReader:
    """Load selected canonical memories for one scoped router decision."""

    def fetch(
        self,
        cursor: CreditTargetCursor,
        *,
        space_id: UUID,
        router_decision_id: UUID,
    ) -> tuple[CreditTarget, ...]:
        if not isinstance(space_id, UUID):
            raise ValueError("space_id must be a UUID")
        if not isinstance(router_decision_id, UUID):
            raise ValueError("router_decision_id must be a UUID")

        cursor.execute(
            CREDIT_TARGETS_SELECT_SQL,
            {
                "space_id": space_id,
                "router_decision_id": router_decision_id,
            },
        )

        seen_nodes: set[UUID] = set()
        seen_events: set[UUID] = set()
        ranked_targets: list[tuple[int, CreditTarget]] = []
        for raw_row in cursor.fetchall():
            if not isinstance(raw_row, Mapping):
                raise ValueError("credit target row must be a mapping")
            missing = _REQUIRED_COLUMNS.difference(raw_row)
            if missing:
                columns = ", ".join(sorted(missing))
                raise ValueError(f"missing credit target column: {columns}")

            row_space_id = _parse_uuid("space_id", raw_row["space_id"])
            if row_space_id != space_id:
                raise ValueError("credit target row contains unexpected space_id")
            row_decision_id = _parse_uuid(
                "router_decision_id",
                raw_row["router_decision_id"],
            )
            if row_decision_id != router_decision_id:
                raise ValueError(
                    "credit target row contains unexpected router_decision_id"
                )

            memory_id = _parse_uuid("node_id", raw_row["node_id"])
            retrieval_event_id = _parse_uuid(
                "retrieval_event_id",
                raw_row["retrieval_event_id"],
            )
            if memory_id in seen_nodes:
                raise ValueError("duplicate credit target memory_id")
            if retrieval_event_id in seen_events:
                raise ValueError("duplicate retrieval_event_id")
            seen_nodes.add(memory_id)
            seen_events.add(retrieval_event_id)

            rank = raw_row["rank"]
            if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0:
                raise ValueError("rank must be a positive integer")
            selected = raw_row["selected_for_context"]
            used = raw_row["used_in_action"]
            if not isinstance(selected, bool):
                raise ValueError("selected_for_context must be a boolean")
            if not selected:
                raise ValueError("credit target row is not selected_for_context")
            if not isinstance(used, bool):
                raise ValueError("used_in_action must be a boolean")

            ranked_targets.append(
                (
                    rank,
                    CreditTarget(
                        memory_id=memory_id,
                        retrieval_event_id=retrieval_event_id,
                        router_decision_id=row_decision_id,
                        selected_for_context=selected,
                        used_in_action=used,
                    ),
                )
            )

        ranked_targets.sort(key=lambda item: (item[0], str(item[1].memory_id)))
        return tuple(target for _, target in ranked_targets)


def _parse_uuid(name: str, value: object) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc
