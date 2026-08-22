"""Build and verify deterministic post-action causal feedback rows."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID, uuid5

from .causal_credit import CreditAssignmentResult, CreditVerdict

EVIDENCE_KEY = "paired_leave_one_out_v0"

CAUSAL_FEEDBACK_INSERT_SQL = """
INSERT INTO ngm.memory_feedback (
    id,
    space_id,
    node_id,
    router_decision_id,
    verdict,
    reward,
    task_success,
    token_delta,
    latency_delta_ms,
    notes,
    metadata,
    credit_evaluation_id,
    evidence_key,
    content_hash
) VALUES (
    %(id)s,
    %(space_id)s,
    %(node_id)s,
    %(router_decision_id)s,
    %(verdict)s,
    %(reward)s,
    %(task_success)s,
    %(token_delta)s,
    %(latency_delta_ms)s,
    %(notes)s,
    %(metadata)s,
    %(credit_evaluation_id)s,
    %(evidence_key)s,
    %(content_hash)s
)
ON CONFLICT (space_id, credit_evaluation_id, node_id)
WHERE credit_evaluation_id IS NOT NULL
DO NOTHING
""".strip()

CAUSAL_FEEDBACK_SELECT_SQL = """
SELECT
    id,
    space_id,
    node_id,
    router_decision_id,
    verdict,
    reward,
    task_success,
    token_delta,
    latency_delta_ms,
    notes,
    metadata,
    credit_evaluation_id,
    evidence_key,
    content_hash
FROM ngm.memory_feedback
WHERE space_id = %(space_id)s
  AND id = ANY(%(ids)s::uuid[])
ORDER BY id
""".strip()

_REQUIRED_COLUMNS = frozenset(
    {
        "id",
        "space_id",
        "node_id",
        "router_decision_id",
        "verdict",
        "reward",
        "task_success",
        "token_delta",
        "latency_delta_ms",
        "notes",
        "metadata",
        "credit_evaluation_id",
        "evidence_key",
        "content_hash",
    }
)
_ALLOWED_VERDICTS = frozenset(verdict.value for verdict in CreditVerdict)
_CAUSAL_METADATA_KEYS = frozenset(
    {
        "credit_version",
        "trial_count",
        "mean_full_score",
        "mean_no_memory_score",
        "mean_without_memory_score",
        "mean_bundle_uplift",
        "mean_effect",
        "standard_error",
        "context_set_hash",
        "continuation_set_hash",
    }
)
_CAUSAL_NUMERIC_KEYS = (
    "mean_full_score",
    "mean_no_memory_score",
    "mean_without_memory_score",
    "mean_bundle_uplift",
    "mean_effect",
    "standard_error",
)
_CAUSAL_HASH_KEYS = ("context_set_hash", "continuation_set_hash")


class CausalFeedbackConflictError(RuntimeError):
    """Stored causal feedback differs from its deterministic immutable payload."""


@dataclass(frozen=True, slots=True)
class MemoryFeedbackRecord:
    """One deterministic causal-feedback row for ``ngm.memory_feedback``."""

    id: UUID
    space_id: UUID
    node_id: UUID
    router_decision_id: UUID
    verdict: str
    reward: float
    task_success: bool
    token_delta: int
    latency_delta_ms: float
    notes: None
    metadata: Mapping[str, Any]
    credit_evaluation_id: UUID
    evidence_key: str
    content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "id",
            "space_id",
            "node_id",
            "router_decision_id",
            "credit_evaluation_id",
        ):
            if not isinstance(getattr(self, name), UUID):
                raise ValueError(f"{name} must be a UUID")
        if self.verdict not in _ALLOWED_VERDICTS:
            raise ValueError("verdict is not supported for causal feedback")
        if not isfinite(self.reward):
            raise ValueError("reward must be finite")
        if not isinstance(self.task_success, bool):
            raise ValueError("task_success must be a boolean")
        if isinstance(self.token_delta, bool) or not isinstance(self.token_delta, int):
            raise ValueError("token_delta must be an integer")
        if not isfinite(self.latency_delta_ms):
            raise ValueError("latency_delta_ms must be finite")
        if self.notes is not None:
            raise ValueError("causal feedback notes must be None")
        if self.evidence_key != EVIDENCE_KEY:
            raise ValueError(f"evidence_key must be {EVIDENCE_KEY}")
        if len(self.content_hash) != 64 or any(
            character not in "0123456789abcdef" for character in self.content_hash
        ):
            raise ValueError("content_hash must be lowercase SHA-256 hex")
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    def to_db_params(self) -> dict[str, Any]:
        """Return parameter values for the causal feedback SQL contract."""

        return {
            "id": self.id,
            "space_id": self.space_id,
            "node_id": self.node_id,
            "router_decision_id": self.router_decision_id,
            "verdict": self.verdict,
            "reward": self.reward,
            "task_success": self.task_success,
            "token_delta": self.token_delta,
            "latency_delta_ms": self.latency_delta_ms,
            "notes": self.notes,
            "metadata": _thaw_json(self.metadata),
            "credit_evaluation_id": self.credit_evaluation_id,
            "evidence_key": self.evidence_key,
            "content_hash": self.content_hash,
        }


def build_memory_feedback_records(
    *,
    space_id: UUID,
    credit_evaluation_id: UUID,
    assignment: CreditAssignmentResult,
) -> tuple[MemoryFeedbackRecord, ...]:
    """Convert stable node-level credits to deterministic feedback records."""

    if not isinstance(space_id, UUID):
        raise ValueError("space_id must be a UUID")
    if not isinstance(credit_evaluation_id, UUID):
        raise ValueError("credit_evaluation_id must be a UUID")
    if not isinstance(assignment, CreditAssignmentResult):
        raise ValueError("assignment must be a CreditAssignmentResult")

    records: list[MemoryFeedbackRecord] = []
    seen: set[UUID] = set()
    for attributed in sorted(assignment.credits, key=lambda item: str(item.memory_id)):
        if attributed.memory_id in seen:
            raise ValueError("assignment contains duplicate memory credit")
        seen.add(attributed.memory_id)
        if assignment.router_decision_id != attributed.router_decision_id:
            raise ValueError("assignment router decision does not match credit")
        if assignment.context_set_hash != attributed.context_set_hash:
            raise ValueError("assignment context hash does not match credit")
        if assignment.continuation_set_hash != attributed.continuation_set_hash:
            raise ValueError("assignment continuation hash does not match credit")

        feedback_id = uuid5(
            credit_evaluation_id,
            f"{EVIDENCE_KEY}:{attributed.memory_id}",
        )
        metadata = _freeze_metadata(
            {
                "credit_version": EVIDENCE_KEY,
                "trial_count": attributed.trial_count,
                "mean_full_score": attributed.mean_full_score,
                "mean_no_memory_score": attributed.mean_no_memory_score,
                "mean_without_memory_score": attributed.mean_without_memory_score,
                "mean_bundle_uplift": attributed.mean_bundle_uplift,
                "mean_effect": attributed.mean_effect,
                "standard_error": attributed.standard_error,
                "context_set_hash": attributed.context_set_hash,
                "continuation_set_hash": attributed.continuation_set_hash,
            }
        )
        payload = {
            "id": str(feedback_id),
            "space_id": str(space_id),
            "node_id": str(attributed.memory_id),
            "router_decision_id": str(attributed.router_decision_id),
            "verdict": attributed.verdict.value,
            "reward": attributed.reward,
            "task_success": attributed.task_success,
            "token_delta": attributed.token_delta,
            "latency_delta_ms": attributed.latency_delta_ms,
            "notes": None,
            "metadata": metadata,
            "credit_evaluation_id": str(credit_evaluation_id),
            "evidence_key": EVIDENCE_KEY,
        }
        records.append(
            MemoryFeedbackRecord(
                id=feedback_id,
                space_id=space_id,
                node_id=attributed.memory_id,
                router_decision_id=attributed.router_decision_id,
                verdict=attributed.verdict.value,
                reward=attributed.reward,
                task_success=attributed.task_success,
                token_delta=attributed.token_delta,
                latency_delta_ms=attributed.latency_delta_ms,
                notes=None,
                metadata=metadata,
                credit_evaluation_id=credit_evaluation_id,
                evidence_key=EVIDENCE_KEY,
                content_hash=_hash_payload(payload),
            )
        )
    return tuple(records)


class CausalFeedbackCursor(Protocol):
    """Minimal mapping cursor used by the insert-then-verify writer."""

    def executemany(
        self,
        sql: str,
        rows: list[Mapping[str, Any]],
    ) -> Any:
        """Execute an insert for every row."""
        ...

    def execute(self, sql: str, params: Mapping[str, Any]) -> Any:
        """Execute one parameterized verification query."""
        ...

    def fetchall(self) -> Iterable[Mapping[str, Any]]:
        """Return mapping-shaped stored rows."""
        ...


class CausalFeedbackWriter:
    """Insert deterministic feedback and verify the exact immutable payload."""

    def write(
        self,
        cursor: CausalFeedbackCursor,
        records: Iterable[MemoryFeedbackRecord],
    ) -> int:
        records = tuple(records)
        if not records:
            return 0
        if any(not isinstance(record, MemoryFeedbackRecord) for record in records):
            raise ValueError("records must contain MemoryFeedbackRecord instances")

        spaces = {record.space_id for record in records}
        if len(spaces) != 1:
            raise ValueError("causal feedback batch must use one space_id")
        expected = {record.id: record.to_db_params() for record in records}
        if len(expected) != len(records):
            raise ValueError("causal feedback batch contains duplicate IDs")

        cursor.executemany(
            CAUSAL_FEEDBACK_INSERT_SQL,
            [record.to_db_params() for record in records],
        )
        space_id = next(iter(spaces))
        ids = sorted(expected, key=str)
        cursor.execute(
            CAUSAL_FEEDBACK_SELECT_SQL,
            {
                "space_id": space_id,
                "ids": ids,
            },
        )

        stored_by_id: dict[UUID, dict[str, Any]] = {}
        for raw_row in cursor.fetchall():
            if not isinstance(raw_row, Mapping):
                raise CausalFeedbackConflictError(
                    "stored causal feedback row is not a mapping"
                )
            missing = _REQUIRED_COLUMNS.difference(raw_row)
            if missing:
                raise CausalFeedbackConflictError(
                    "stored causal feedback row is missing immutable fields"
                )
            stored = _normalize_stored_row(raw_row)
            stored_id = stored["id"]
            if stored_id not in expected:
                raise CausalFeedbackConflictError(
                    "stored causal feedback returned an unexpected ID"
                )
            if stored_id in stored_by_id:
                raise CausalFeedbackConflictError(
                    "stored causal feedback returned a duplicate ID"
                )
            stored_by_id[stored_id] = stored

        missing_ids = set(expected).difference(stored_by_id)
        if missing_ids:
            raise CausalFeedbackConflictError(
                "stored causal feedback is missing deterministic rows"
            )
        for feedback_id, expected_payload in expected.items():
            if stored_by_id[feedback_id] != expected_payload:
                raise CausalFeedbackConflictError(
                    "stored causal feedback immutable payload differs"
                )
        return len(records)


def _normalize_stored_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _parse_uuid("id", row["id"]),
        "space_id": _parse_uuid("space_id", row["space_id"]),
        "node_id": _parse_uuid("node_id", row["node_id"]),
        "router_decision_id": _parse_uuid(
            "router_decision_id",
            row["router_decision_id"],
        ),
        "verdict": str(row["verdict"]),
        "reward": float(row["reward"]),
        "task_success": row["task_success"],
        "token_delta": row["token_delta"],
        "latency_delta_ms": float(row["latency_delta_ms"]),
        "notes": row["notes"],
        "metadata": _normalize_stored_metadata(row["metadata"]),
        "credit_evaluation_id": _parse_uuid(
            "credit_evaluation_id",
            row["credit_evaluation_id"],
        ),
        "evidence_key": str(row["evidence_key"]),
        "content_hash": str(row["content_hash"]),
    }


def _freeze_metadata(metadata: object) -> Mapping[str, Any]:
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be a mapping")
    if any(not isinstance(key, str) for key in metadata):
        raise ValueError("metadata keys must be strings")
    if set(metadata) != _CAUSAL_METADATA_KEYS:
        raise ValueError("metadata must use the exact causal aggregate schema")

    normalized = dict(metadata)
    if normalized["credit_version"] != EVIDENCE_KEY:
        raise ValueError(f"credit_version must be {EVIDENCE_KEY}")

    trial_count = normalized["trial_count"]
    if (
        isinstance(trial_count, bool)
        or not isinstance(trial_count, int)
        or trial_count <= 0
    ):
        raise ValueError("trial_count must be a positive integer")

    for name in _CAUSAL_NUMERIC_KEYS:
        value = normalized[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a finite number")
        try:
            finite = isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError(f"{name} must be a finite number")
    if normalized["standard_error"] < 0:
        raise ValueError("standard_error must be non-negative")

    for name in _CAUSAL_HASH_KEYS:
        value = normalized[name]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise ValueError(f"{name} must be lowercase SHA-256 hex")
    return MappingProxyType(normalized)


def _normalize_stored_metadata(metadata: object) -> dict[str, Any]:
    try:
        return _thaw_json(_freeze_metadata(metadata))
    except (OverflowError, TypeError, ValueError) as exc:
        raise CausalFeedbackConflictError(
            "stored causal feedback metadata violates the causal aggregate schema"
        ) from exc


def _thaw_json(value: Mapping[str, Any]) -> dict[str, Any]:
    return dict(value)


def _hash_payload(payload: Mapping[str, Any]) -> str:
    normalized = {
        key: _thaw_json(value) if isinstance(value, Mapping) else value
        for key, value in payload.items()
    }
    encoded = json.dumps(
        normalized,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_uuid(name: str, value: object) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise CausalFeedbackConflictError(f"stored {name} must be a UUID") from exc
