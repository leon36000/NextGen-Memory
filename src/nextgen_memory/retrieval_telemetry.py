"""Privacy-preserving retrieval events compatible with the Neon ledger."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass
from math import isfinite
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from .retrieval import ResearchRetrievalHit

RETRIEVAL_EVENT_INSERT_SQL = """
INSERT INTO ngm.retrieval_events (
    id,
    space_id,
    router_decision_id,
    expert_key,
    node_id,
    backend_ref,
    rank,
    raw_score,
    final_score,
    estimated_tokens,
    selected_for_context,
    used_in_action
) VALUES (
    %(id)s,
    %(space_id)s,
    %(router_decision_id)s,
    %(expert_key)s,
    %(node_id)s,
    %(backend_ref)s,
    %(rank)s,
    %(raw_score)s,
    %(final_score)s,
    %(estimated_tokens)s,
    %(selected_for_context)s,
    %(used_in_action)s
)
ON CONFLICT (id) DO NOTHING
""".strip()

RETRIEVAL_EVENT_SELECT_SQL = """
SELECT
    id,
    space_id,
    router_decision_id,
    expert_key,
    node_id,
    backend_ref,
    rank,
    raw_score,
    final_score,
    estimated_tokens,
    selected_for_context,
    used_in_action
FROM ngm.retrieval_events
WHERE space_id = %(space_id)s
  AND id = ANY(%(ids)s::uuid[])
ORDER BY id
""".strip()

_REQUIRED_COLUMNS = frozenset(
    {
        "id",
        "space_id",
        "router_decision_id",
        "expert_key",
        "node_id",
        "backend_ref",
        "rank",
        "raw_score",
        "final_score",
        "estimated_tokens",
        "selected_for_context",
        "used_in_action",
    }
)


class RetrievalEventConflictError(RuntimeError):
    """Stored retrieval telemetry differs from its deterministic immutable payload."""


@dataclass(frozen=True, slots=True)
class RetrievalEvent:
    """One immutable retrieval observation; it intentionally contains no query text."""

    id: UUID
    space_id: UUID
    router_decision_id: UUID
    expert_key: str
    node_id: UUID | None
    backend_ref: str | None
    rank: int
    raw_score: float | None
    final_score: float | None
    estimated_tokens: int | None = None
    selected_for_context: bool = False
    used_in_action: bool = False

    def __post_init__(self) -> None:
        expert_key = self.expert_key.strip()
        if not expert_key:
            raise ValueError("expert_key must not be empty")
        backend_ref = self.backend_ref.strip() if self.backend_ref is not None else None
        if self.node_id is None and not backend_ref:
            raise ValueError("node_id or backend_ref must be supplied")
        if self.rank <= 0:
            raise ValueError("rank must be greater than zero")
        for name in ("raw_score", "final_score"):
            value = getattr(self, name)
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} must be finite when supplied")
        if self.estimated_tokens is not None and self.estimated_tokens < 0:
            raise ValueError("estimated_tokens must be non-negative when supplied")
        object.__setattr__(self, "expert_key", expert_key)
        object.__setattr__(self, "backend_ref", backend_ref)

    def to_db_params(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "space_id": self.space_id,
            "router_decision_id": self.router_decision_id,
            "expert_key": self.expert_key,
            "node_id": self.node_id,
            "backend_ref": self.backend_ref,
            "rank": self.rank,
            "raw_score": self.raw_score,
            "final_score": self.final_score,
            "estimated_tokens": self.estimated_tokens,
            "selected_for_context": self.selected_for_context,
            "used_in_action": self.used_in_action,
        }


def build_retrieval_events(
    *,
    space_id: UUID,
    router_decision_id: UUID,
    expert_key: str,
    hits: Sequence[ResearchRetrievalHit],
    selected_memory_ids: Set[UUID] = frozenset(),
) -> tuple[RetrievalEvent, ...]:
    """Convert ranked hits to deterministic, retry-safe Neon retrieval rows."""

    normalized_expert = expert_key.strip()
    if not normalized_expert:
        raise ValueError("expert_key must not be empty")

    events: list[RetrievalEvent] = []
    for hit in hits:
        event_key = ":".join(
            (
                "nextgen-memory",
                "retrieval-v1",
                str(space_id),
                str(router_decision_id),
                normalized_expert,
                str(hit.memory_id),
                hit.backend_ref,
                str(hit.rank),
            )
        )
        events.append(
            RetrievalEvent(
                id=uuid5(NAMESPACE_URL, event_key),
                space_id=space_id,
                router_decision_id=router_decision_id,
                expert_key=normalized_expert,
                node_id=hit.memory_id,
                backend_ref=hit.backend_ref,
                rank=hit.rank,
                raw_score=hit.score,
                final_score=hit.score,
                selected_for_context=hit.memory_id in selected_memory_ids,
            )
        )
    return tuple(events)


class ExecutemanyCursor(Protocol):
    def executemany(
        self,
        sql: str,
        rows: list[Mapping[str, Any]],
    ) -> Any:
        """Execute one parameterized statement for each mapping."""
        ...

    def execute(self, sql: str, params: Mapping[str, Any]) -> Any:
        """Execute one parameterized verification query."""
        ...

    def fetchall(self) -> Iterable[Mapping[str, Any]]:
        """Return mapping-shaped stored retrieval rows."""
        ...


class RetrievalEventWriter:
    """Insert retrieval events and verify their exact immutable payload."""

    def write(
        self,
        cursor: ExecutemanyCursor,
        events: Iterable[RetrievalEvent],
    ) -> int:
        events = tuple(events)
        if not events:
            return 0
        if any(not isinstance(event, RetrievalEvent) for event in events):
            raise ValueError("events must contain RetrievalEvent instances")

        spaces = {event.space_id for event in events}
        if len(spaces) != 1:
            raise ValueError("retrieval event batch must use one space_id")
        expected = {event.id: event.to_db_params() for event in events}
        if len(expected) != len(events):
            raise ValueError("retrieval event batch contains duplicate IDs")

        cursor.executemany(
            RETRIEVAL_EVENT_INSERT_SQL,
            [event.to_db_params() for event in events],
        )
        space_id = next(iter(spaces))
        ids = sorted(expected, key=str)
        cursor.execute(
            RETRIEVAL_EVENT_SELECT_SQL,
            {
                "space_id": space_id,
                "ids": ids,
            },
        )

        stored_by_id: dict[UUID, dict[str, Any]] = {}
        for raw_row in cursor.fetchall():
            if not isinstance(raw_row, Mapping):
                raise RetrievalEventConflictError(
                    "stored retrieval event row is not a mapping"
                )
            missing = _REQUIRED_COLUMNS.difference(raw_row)
            if missing:
                raise RetrievalEventConflictError(
                    "stored retrieval event row is missing immutable fields"
                )
            stored = _normalize_stored_row(raw_row)
            stored_id = stored["id"]
            if stored_id not in expected:
                raise RetrievalEventConflictError(
                    "stored retrieval event returned an unexpected ID"
                )
            if stored_id in stored_by_id:
                raise RetrievalEventConflictError(
                    "stored retrieval event returned a duplicate ID"
                )
            stored_by_id[stored_id] = stored

        missing_ids = set(expected).difference(stored_by_id)
        if missing_ids:
            raise RetrievalEventConflictError(
                "stored retrieval event is missing deterministic rows"
            )
        for event_id, expected_payload in expected.items():
            if stored_by_id[event_id] != expected_payload:
                raise RetrievalEventConflictError(
                    "stored retrieval event immutable payload differs"
                )
        return len(events)


def _normalize_stored_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _parse_uuid("id", row["id"]),
        "space_id": _parse_uuid("space_id", row["space_id"]),
        "router_decision_id": _parse_uuid(
            "router_decision_id",
            row["router_decision_id"],
        ),
        "expert_key": _parse_text("expert_key", row["expert_key"]),
        "node_id": _parse_optional_uuid("node_id", row["node_id"]),
        "backend_ref": _parse_optional_text("backend_ref", row["backend_ref"]),
        "rank": _parse_int("rank", row["rank"]),
        "raw_score": _parse_optional_float("raw_score", row["raw_score"]),
        "final_score": _parse_optional_float("final_score", row["final_score"]),
        "estimated_tokens": _parse_optional_int(
            "estimated_tokens",
            row["estimated_tokens"],
        ),
        "selected_for_context": _parse_bool(
            "selected_for_context",
            row["selected_for_context"],
        ),
        "used_in_action": _parse_bool("used_in_action", row["used_in_action"]),
    }


def _parse_uuid(name: str, value: object) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise RetrievalEventConflictError(
            f"stored retrieval event {name} must be a UUID"
        ) from exc


def _parse_optional_uuid(name: str, value: object) -> UUID | None:
    return None if value is None else _parse_uuid(name, value)


def _parse_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise RetrievalEventConflictError(
            f"stored retrieval event {name} must be text"
        )
    return value


def _parse_optional_text(name: str, value: object) -> str | None:
    return None if value is None else _parse_text(name, value)


def _parse_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RetrievalEventConflictError(
            f"stored retrieval event {name} must be an integer"
        )
    return value


def _parse_optional_int(name: str, value: object) -> int | None:
    return None if value is None else _parse_int(name, value)


def _parse_optional_float(name: str, value: object) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RetrievalEventConflictError(
            f"stored retrieval event {name} must be numeric"
        ) from exc
    if not isfinite(parsed):
        raise RetrievalEventConflictError(
            f"stored retrieval event {name} must be finite"
        )
    return parsed


def _parse_bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise RetrievalEventConflictError(
            f"stored retrieval event {name} must be a boolean"
        )
    return value
