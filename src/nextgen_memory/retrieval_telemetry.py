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


class RetrievalEventWriter:
    """Write retrieval events without owning the surrounding transaction."""

    def write(
        self,
        cursor: ExecutemanyCursor,
        events: Iterable[RetrievalEvent],
    ) -> int:
        rows = [event.to_db_params() for event in events]
        if not rows:
            return 0
        cursor.executemany(RETRIEVAL_EVENT_INSERT_SQL, rows)
        return len(rows)
