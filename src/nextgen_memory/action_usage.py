"""Append-only evidence that one action used selected memory evidence."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from .retrieval_telemetry import RetrievalEvent

ACTION_MEMORY_USAGE_VERSION = "action-memory-usage-v0"

ACTION_MEMORY_USAGE_INSERT_SQL = """
INSERT INTO ngm.action_memory_usage_events (
    id,
    space_id,
    action_id,
    router_decision_id,
    retrieval_event_id,
    node_id,
    content_hash
) VALUES (
    %(id)s,
    %(space_id)s,
    %(action_id)s,
    %(router_decision_id)s,
    %(retrieval_event_id)s,
    %(node_id)s,
    %(content_hash)s
)
ON CONFLICT (id) DO NOTHING
""".strip()

ACTION_MEMORY_USAGE_SELECT_SQL = """
SELECT
    id,
    space_id,
    action_id,
    router_decision_id,
    retrieval_event_id,
    node_id,
    content_hash
FROM ngm.action_memory_usage_events
WHERE space_id = %(space_id)s
  AND action_id = %(action_id)s
  AND id = ANY(%(ids)s::uuid[])
ORDER BY id
""".strip()

_REQUIRED_COLUMNS = frozenset(
    {
        "id",
        "space_id",
        "action_id",
        "router_decision_id",
        "retrieval_event_id",
        "node_id",
        "content_hash",
    }
)


class ActionMemoryUsageConflictError(RuntimeError):
    """Stored action-memory usage differs from its immutable payload."""


@dataclass(frozen=True, slots=True)
class ActionMemoryUsageEvent:
    """One privacy-safe positive statement that an action used one memory."""

    id: UUID
    space_id: UUID
    action_id: UUID
    router_decision_id: UUID
    retrieval_event_id: UUID
    memory_id: UUID
    content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "id",
            "space_id",
            "action_id",
            "router_decision_id",
            "retrieval_event_id",
            "memory_id",
        ):
            if not isinstance(getattr(self, name), UUID):
                raise ValueError(f"{name} must be a UUID")
        if not _is_sha256(self.content_hash):
            raise ValueError("content_hash must be lowercase SHA-256 hex")

    def to_db_params(self) -> dict[str, Any]:
        """Return only the allowlisted immutable persistence payload."""

        return {
            "id": self.id,
            "space_id": self.space_id,
            "action_id": self.action_id,
            "router_decision_id": self.router_decision_id,
            "retrieval_event_id": self.retrieval_event_id,
            "node_id": self.memory_id,
            "content_hash": self.content_hash,
        }


def build_action_memory_usage_events(
    *,
    action_id: UUID,
    retrieval_events: Sequence[RetrievalEvent],
    used_memory_ids: Set[UUID],
) -> tuple[ActionMemoryUsageEvent, ...]:
    """Build deterministic positive usage events from selected retrieval evidence."""

    if not isinstance(action_id, UUID):
        raise ValueError("action_id must be a UUID")
    events = tuple(retrieval_events)
    if any(not isinstance(event, RetrievalEvent) for event in events):
        raise ValueError("retrieval_events must contain RetrievalEvent instances")
    if not isinstance(used_memory_ids, Set):
        raise ValueError("used_memory_ids must be a set of UUIDs")
    used = frozenset(used_memory_ids)
    if any(not isinstance(memory_id, UUID) for memory_id in used):
        raise ValueError("used_memory_ids must contain UUIDs")

    if not events:
        if used:
            raise ValueError("used memory is unknown to retrieval events")
        return ()

    spaces = {event.space_id for event in events}
    if len(spaces) != 1:
        raise ValueError("retrieval events must use one space_id")
    decisions = {event.router_decision_id for event in events}
    if len(decisions) != 1:
        raise ValueError("retrieval events must use one router_decision_id")

    seen_retrieval_ids: set[UUID] = set()
    by_memory: dict[UUID, RetrievalEvent] = {}
    for event in events:
        if event.id in seen_retrieval_ids:
            raise ValueError("duplicate retrieval event")
        seen_retrieval_ids.add(event.id)
        if event.node_id is None:
            continue
        if event.node_id in by_memory:
            raise ValueError("duplicate memory in retrieval events")
        by_memory[event.node_id] = event

    unknown = used.difference(by_memory)
    if unknown:
        raise ValueError("used memory is unknown to retrieval events")

    built: list[ActionMemoryUsageEvent] = []
    for memory_id in sorted(used, key=str):
        retrieval = by_memory[memory_id]
        if not retrieval.selected_for_context:
            raise ValueError("used memory must be selected_for_context")
        payload = {
            "version": ACTION_MEMORY_USAGE_VERSION,
            "space_id": str(retrieval.space_id),
            "action_id": str(action_id),
            "router_decision_id": str(retrieval.router_decision_id),
            "retrieval_event_id": str(retrieval.id),
            "memory_id": str(memory_id),
        }
        content_hash = _canonical_sha256(payload)
        event_id = uuid5(
            NAMESPACE_URL,
            f"nextgen-memory:{ACTION_MEMORY_USAGE_VERSION}:{content_hash}",
        )
        built.append(
            ActionMemoryUsageEvent(
                id=event_id,
                space_id=retrieval.space_id,
                action_id=action_id,
                router_decision_id=retrieval.router_decision_id,
                retrieval_event_id=retrieval.id,
                memory_id=memory_id,
                content_hash=content_hash,
            )
        )
    return tuple(built)


class ActionMemoryUsageCursor(Protocol):
    """Minimal mapping-cursor contract for insert and immutable readback."""

    def executemany(
        self,
        sql: str,
        rows: list[Mapping[str, Any]],
    ) -> Any:
        """Execute one parameterized insert for each row."""
        ...

    def execute(self, sql: str, params: Mapping[str, Any]) -> Any:
        """Execute one parameterized readback."""
        ...

    def fetchall(self) -> Iterable[Mapping[str, Any]]:
        """Return mapping-shaped rows."""
        ...


class ActionMemoryUsageWriter:
    """Insert usage events and verify the exact immutable stored payload."""

    def write(
        self,
        cursor: ActionMemoryUsageCursor,
        events: Iterable[ActionMemoryUsageEvent],
    ) -> int:
        rows = tuple(events)
        if not rows:
            return 0
        if any(not isinstance(event, ActionMemoryUsageEvent) for event in rows):
            raise ValueError(
                "events must contain ActionMemoryUsageEvent instances"
            )

        spaces = {event.space_id for event in rows}
        if len(spaces) != 1:
            raise ValueError("action memory usage batch must use one space_id")
        actions = {event.action_id for event in rows}
        if len(actions) != 1:
            raise ValueError("action memory usage batch must use one action_id")
        decisions = {event.router_decision_id for event in rows}
        if len(decisions) != 1:
            raise ValueError(
                "action memory usage batch must use one router_decision_id"
            )

        expected = {event.id: event.to_db_params() for event in rows}
        if len(expected) != len(rows):
            raise ValueError("action memory usage batch contains duplicate IDs")
        if len({event.retrieval_event_id for event in rows}) != len(rows):
            raise ValueError(
                "action memory usage batch contains duplicate retrieval events"
            )
        if len({event.memory_id for event in rows}) != len(rows):
            raise ValueError("action memory usage batch contains duplicate memories")

        cursor.executemany(
            ACTION_MEMORY_USAGE_INSERT_SQL,
            [event.to_db_params() for event in rows],
        )
        space_id = next(iter(spaces))
        action_id = next(iter(actions))
        ids = sorted(expected, key=str)
        cursor.execute(
            ACTION_MEMORY_USAGE_SELECT_SQL,
            {
                "space_id": space_id,
                "action_id": action_id,
                "ids": ids,
            },
        )

        stored_by_id: dict[UUID, dict[str, Any]] = {}
        for raw_row in cursor.fetchall():
            if not isinstance(raw_row, Mapping):
                raise ActionMemoryUsageConflictError(
                    "stored action memory usage row must be a mapping"
                )
            missing = _REQUIRED_COLUMNS.difference(raw_row)
            if missing:
                raise ActionMemoryUsageConflictError(
                    "stored action memory usage row is missing immutable fields"
                )
            stored = _normalize_stored_row(raw_row)
            stored_id = stored["id"]
            if stored_id not in expected:
                raise ActionMemoryUsageConflictError(
                    "stored action memory usage returned an unexpected ID"
                )
            if stored_id in stored_by_id:
                raise ActionMemoryUsageConflictError(
                    "stored action memory usage returned a duplicate ID"
                )
            stored_by_id[stored_id] = stored

        if set(expected) != set(stored_by_id):
            raise ActionMemoryUsageConflictError(
                "stored action memory usage is missing deterministic rows"
            )
        for event_id, expected_payload in expected.items():
            if stored_by_id[event_id] != expected_payload:
                raise ActionMemoryUsageConflictError(
                    "stored action memory usage immutable payload differs"
                )
        return len(rows)


def _normalize_stored_row(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        content_hash = row["content_hash"]
        if not isinstance(content_hash, str) or not _is_sha256(content_hash):
            raise ValueError
        return {
            "id": _parse_uuid(row["id"]),
            "space_id": _parse_uuid(row["space_id"]),
            "action_id": _parse_uuid(row["action_id"]),
            "router_decision_id": _parse_uuid(row["router_decision_id"]),
            "retrieval_event_id": _parse_uuid(row["retrieval_event_id"]),
            "node_id": _parse_uuid(row["node_id"]),
            "content_hash": content_hash,
        }
    except (AttributeError, TypeError, ValueError) as exc:
        raise ActionMemoryUsageConflictError(
            "stored action memory usage contains malformed immutable fields"
        ) from exc


def _parse_uuid(value: object) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


def _canonical_sha256(payload: Mapping[str, str]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
