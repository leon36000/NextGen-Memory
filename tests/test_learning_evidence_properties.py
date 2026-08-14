from __future__ import annotations

import json
import random
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from nextgen_memory.learning_evidence import NeonLearningEvidenceReader

SPACE = UUID("90000000-0000-0000-0000-000000000001")
BASE_TIME = datetime(2026, 8, 14, 23, 45, tzinfo=UTC)
FORBIDDEN = (
    "query_text",
    "prompt",
    "answer",
    "memory_body",
    "body_text",
    "command_text",
    "stdout",
    "stderr",
    "secret",
    "api_key",
    "raw_payload",
    "patch_text",
    "environment",
    "feedback_note",
    "combined_utility",
)


class FakeCursor:
    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        self.calls.append((sql, params))

    def fetchall(self) -> Iterable[Mapping[str, Any]]:
        return list(self.rows)


def _memory_id(seed: int, index: int) -> UUID:
    return UUID(int=(seed + 1) * 32 + index + 1)


def _generated_rows(
    seed: int,
) -> tuple[tuple[UUID, ...], tuple[dict[str, object], ...]]:
    rng = random.Random(seed)
    count = rng.randint(1, 7)
    memory_ids = tuple(_memory_id(seed, index) for index in range(count))
    rows: list[dict[str, object]] = []
    for index, memory_id in enumerate(memory_ids):
        direct_count = rng.randint(0, 8)
        if direct_count:
            positive_count = rng.randint(0, direct_count)
            negative_count = rng.randint(
                0,
                direct_count - positive_count,
            )
            direct_average: object = round(rng.uniform(-1.0, 1.0), 8)
            last_direct: object = BASE_TIME + timedelta(
                seconds=seed + index
            )
        else:
            positive_count = 0
            negative_count = 0
            direct_average = None
            last_direct = None

        inherited_count = rng.randint(0, 8)
        if inherited_count:
            inherited_value = round(rng.uniform(-1.0, 1.0), 8)
            inherited_absolute = round(
                abs(inherited_value) + rng.uniform(0.0, 1.0),
                8,
            )
            inherited_error: object = round(rng.uniform(0.0, 0.5), 8)
            inherited_confidence: object = round(
                rng.uniform(0.0, 1.0),
                8,
            )
            last_inherited: object = BASE_TIME + timedelta(
                seconds=seed + index + 1
            )
        else:
            inherited_value = None
            inherited_absolute = None
            inherited_error = None
            inherited_confidence = None
            last_inherited = None

        rows.append(
            {
                "space_id": str(SPACE) if index % 2 else SPACE,
                "node_id": str(memory_id) if index % 2 else memory_id,
                "direct_feedback_count": direct_count,
                "direct_avg_reward": direct_average,
                "direct_positive_count": positive_count,
                "direct_negative_count": negative_count,
                "last_direct_feedback_at": last_direct,
                "inherited_contribution_count": inherited_count,
                "inherited_value_sum": inherited_value,
                "inherited_absolute_value_sum": inherited_absolute,
                "inherited_standard_error_sum": inherited_error,
                "minimum_structural_confidence": inherited_confidence,
                "last_inherited_credit_at": last_inherited,
            }
        )
    return memory_ids, tuple(rows)


def _serialize(result: Mapping[UUID, Any]) -> str:
    payload = {
        str(memory_id): {
            "space_id": str(snapshot.space_id),
            "memory_id": str(snapshot.memory_id),
            "direct": {
                "feedback_count": snapshot.direct.feedback_count,
                "average_reward": snapshot.direct.average_reward,
                "positive_count": snapshot.direct.positive_count,
                "negative_count": snapshot.direct.negative_count,
                "last_feedback_at": (
                    snapshot.direct.last_feedback_at.isoformat()
                    if snapshot.direct.last_feedback_at is not None
                    else None
                ),
            },
            "inherited": {
                "contribution_count": snapshot.inherited.contribution_count,
                "value_sum": snapshot.inherited.value_sum,
                "absolute_value_sum": snapshot.inherited.absolute_value_sum,
                "standard_error_sum": snapshot.inherited.standard_error_sum,
                "minimum_structural_confidence": (
                    snapshot.inherited.minimum_structural_confidence
                ),
                "last_credit_at": (
                    snapshot.inherited.last_credit_at.isoformat()
                    if snapshot.inherited.last_credit_at is not None
                    else None
                ),
            },
        }
        for memory_id, snapshot in result.items()
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def test_5000_generated_reads_are_order_invariant_and_privacy_safe() -> None:
    direct_neutral = 0
    direct_observed = 0
    inherited_neutral = 0
    inherited_observed = 0

    for seed in range(5000):
        memory_ids, rows = _generated_rows(seed)
        request_order = (*reversed(memory_ids), memory_ids[0])

        first_cursor = FakeCursor(tuple(reversed(rows)))
        first = NeonLearningEvidenceReader(first_cursor).fetch(
            space_id=SPACE,
            memory_ids=request_order,
        )
        second_cursor = FakeCursor(rows)
        second = NeonLearningEvidenceReader(second_cursor).fetch(
            space_id=SPACE,
            memory_ids=memory_ids,
        )

        assert first == second
        assert tuple(first) == tuple(sorted(set(memory_ids), key=str))
        assert _serialize(first) == _serialize(second)
        assert first_cursor.calls[0][1]["memory_ids"] == list(
            sorted(set(memory_ids), key=str)
        )

        for snapshot in first.values():
            assert snapshot.space_id == SPACE
            assert snapshot.memory_id in memory_ids
            assert not hasattr(snapshot, "score")
            assert not hasattr(snapshot, "utility")
            assert not hasattr(snapshot, "combined_utility")
            if snapshot.direct.has_evidence:
                direct_observed += 1
                assert snapshot.direct.average_reward is not None
                assert snapshot.direct.last_feedback_at is not None
            else:
                direct_neutral += 1
                assert snapshot.direct.average_reward is None
                assert snapshot.direct.last_feedback_at is None
            if snapshot.inherited.has_evidence:
                inherited_observed += 1
                assert snapshot.inherited.value_sum is not None
                assert snapshot.inherited.absolute_value_sum is not None
                assert snapshot.inherited.absolute_value_sum >= abs(
                    snapshot.inherited.value_sum
                )
            else:
                inherited_neutral += 1
                assert snapshot.inherited.value_sum is None
                assert snapshot.inherited.last_credit_at is None

        serialized = _serialize(first).lower()
        assert all(term not in serialized for term in FORBIDDEN)

    assert direct_neutral > 1000
    assert direct_observed > 1000
    assert inherited_neutral > 1000
    assert inherited_observed > 1000
