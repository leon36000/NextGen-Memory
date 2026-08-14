"""Scoped, aggregate-only Neon utility snapshot reading."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID

from .utility_reranker import UtilityEvidence

NODE_UTILITY_SELECT_SQL = """
SELECT
    space_id,
    node_id,
    feedback_count,
    avg_reward,
    positive_count,
    negative_count,
    last_feedback_at
FROM ngm.node_utility
WHERE space_id = %(space_id)s
  AND node_id = ANY(%(memory_ids)s::uuid[])
ORDER BY node_id
""".strip()

_REQUIRED_COLUMNS = frozenset(
    {
        "space_id",
        "node_id",
        "feedback_count",
        "avg_reward",
        "positive_count",
        "negative_count",
        "last_feedback_at",
    }
)


class UtilityCursor(Protocol):
    """Minimal DB-API-style cursor needed by the utility reader."""

    def execute(self, sql: str, params: Mapping[str, Any]) -> Any:
        """Execute one parameterized statement."""
        ...

    def fetchall(self) -> Iterable[Mapping[str, Any]]:
        """Return mapping-shaped rows."""
        ...


class NodeUtilityReader:
    """Map scoped `ngm.node_utility` rows to immutable utility evidence."""

    def fetch(
        self,
        cursor: UtilityCursor,
        *,
        space_id: UUID,
        memory_ids: Sequence[UUID],
    ) -> Mapping[UUID, UtilityEvidence]:
        requested_ids = tuple(sorted(set(memory_ids), key=str))
        if not requested_ids:
            return MappingProxyType({})

        cursor.execute(
            NODE_UTILITY_SELECT_SQL,
            {
                "space_id": space_id,
                "memory_ids": list(requested_ids),
            },
        )
        requested = frozenset(requested_ids)
        evidence_by_id: dict[UUID, UtilityEvidence] = {}

        for raw_row in cursor.fetchall():
            if not isinstance(raw_row, Mapping):
                raise ValueError("utility row must be a mapping")
            missing = _REQUIRED_COLUMNS.difference(raw_row)
            if missing:
                missing_columns = ", ".join(sorted(missing))
                raise ValueError(f"missing utility column: {missing_columns}")

            row_space_id = _parse_uuid("space_id", raw_row["space_id"])
            if row_space_id != space_id:
                raise ValueError("utility row contains unexpected space_id")
            memory_id = _parse_uuid("node_id", raw_row["node_id"])
            if memory_id not in requested:
                raise ValueError("utility row contains unexpected memory_id")
            if memory_id in evidence_by_id:
                raise ValueError("duplicate utility row for memory_id")

            avg_reward_value = raw_row["avg_reward"]
            try:
                avg_reward = (
                    None
                    if avg_reward_value is None
                    else float(avg_reward_value)
                )
            except (TypeError, ValueError) as exc:
                raise ValueError("avg_reward must be numeric when supplied") from exc

            evidence_by_id[memory_id] = UtilityEvidence(
                memory_id=memory_id,
                feedback_count=raw_row["feedback_count"],
                avg_reward=avg_reward,
                positive_count=raw_row["positive_count"],
                negative_count=raw_row["negative_count"],
                last_feedback_at=raw_row["last_feedback_at"],
            )

        return MappingProxyType(evidence_by_id)


def _parse_uuid(name: str, value: object) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc
