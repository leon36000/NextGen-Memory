from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

import pytest

from nextgen_memory.learning_evidence import (
    LEARNING_EVIDENCE_SELECT_SQL,
    DirectUtilityEvidence,
    InheritedUtilityEvidence,
    LearningEvidenceReadConflictError,
    LearningEvidenceValidationError,
    NeonLearningEvidenceReader,
    NodeLearningEvidence,
)

SPACE = UUID("11111111-1111-1111-1111-111111111111")
OTHER_SPACE = UUID("22222222-2222-2222-2222-222222222222")
MEMORY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
MEMORY_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
NOW = datetime(2026, 8, 14, 23, 30, tzinfo=UTC)


def direct(**overrides: object) -> DirectUtilityEvidence:
    values: dict[str, object] = {
        "feedback_count": 3,
        "average_reward": 0.4,
        "positive_count": 2,
        "negative_count": 1,
        "last_feedback_at": NOW,
    }
    values.update(overrides)
    return DirectUtilityEvidence(**values)


def inherited(**overrides: object) -> InheritedUtilityEvidence:
    values: dict[str, object] = {
        "contribution_count": 2,
        "value_sum": 0.3,
        "absolute_value_sum": 0.5,
        "standard_error_sum": 0.08,
        "minimum_structural_confidence": 0.75,
        "last_credit_at": NOW,
    }
    values.update(overrides)
    return InheritedUtilityEvidence(**values)


def row(memory_id: UUID = MEMORY_A, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "space_id": SPACE,
        "node_id": memory_id,
        "direct_feedback_count": 3,
        "direct_avg_reward": 0.4,
        "direct_positive_count": 2,
        "direct_negative_count": 1,
        "last_direct_feedback_at": NOW,
        "inherited_contribution_count": 2,
        "inherited_value_sum": 0.3,
        "inherited_absolute_value_sum": 0.5,
        "inherited_standard_error_sum": 0.08,
        "minimum_structural_confidence": 0.75,
        "last_inherited_credit_at": NOW,
    }
    values.update(overrides)
    return values


class FakeCursor:
    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        self.calls.append((sql, params))

    def fetchall(self) -> Iterable[Mapping[str, Any]]:
        return list(self.rows)


def test_direct_evidence_accepts_observed_and_neutral_states() -> None:
    observed = direct()
    neutral = DirectUtilityEvidence(
        feedback_count=0,
        average_reward=None,
        positive_count=0,
        negative_count=0,
        last_feedback_at=None,
    )

    assert observed.feedback_count == 3
    assert observed.average_reward == 0.4
    assert observed.has_evidence is True
    assert neutral.has_evidence is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"feedback_count": -1},
        {"feedback_count": True},
        {"average_reward": float("nan")},
        {"positive_count": -1},
        {"negative_count": -1},
        {"positive_count": 3, "negative_count": 2},
        {"last_feedback_at": datetime(2026, 8, 14, 23, 30)},
        {
            "feedback_count": 0,
            "average_reward": 0.0,
            "positive_count": 0,
            "negative_count": 0,
            "last_feedback_at": None,
        },
        {
            "feedback_count": 0,
            "average_reward": None,
            "positive_count": 1,
            "negative_count": 0,
            "last_feedback_at": None,
        },
        {
            "feedback_count": 1,
            "average_reward": None,
            "positive_count": 1,
            "negative_count": 0,
            "last_feedback_at": NOW,
        },
        {
            "feedback_count": 1,
            "average_reward": 0.4,
            "positive_count": 1,
            "negative_count": 0,
            "last_feedback_at": None,
        },
    ],
)
def test_direct_evidence_rejects_inconsistent_values(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(LearningEvidenceValidationError):
        direct(**overrides)


def test_inherited_evidence_accepts_observed_and_neutral_states() -> None:
    observed = inherited()
    neutral = InheritedUtilityEvidence(
        contribution_count=0,
        value_sum=None,
        absolute_value_sum=None,
        standard_error_sum=None,
        minimum_structural_confidence=None,
        last_credit_at=None,
    )

    assert observed.contribution_count == 2
    assert observed.has_evidence is True
    assert neutral.has_evidence is False


@pytest.mark.parametrize(
    "overrides",
    [
        {"contribution_count": -1},
        {"contribution_count": True},
        {"value_sum": float("inf")},
        {"absolute_value_sum": -0.1},
        {"value_sum": 0.6, "absolute_value_sum": 0.5},
        {"standard_error_sum": -0.1},
        {"minimum_structural_confidence": -0.1},
        {"minimum_structural_confidence": 1.1},
        {"last_credit_at": datetime(2026, 8, 14, 23, 30)},
        {
            "contribution_count": 0,
            "value_sum": 0.0,
            "absolute_value_sum": None,
            "standard_error_sum": None,
            "minimum_structural_confidence": None,
            "last_credit_at": None,
        },
        {
            "contribution_count": 1,
            "value_sum": None,
            "absolute_value_sum": 0.1,
            "standard_error_sum": 0.01,
            "minimum_structural_confidence": 0.8,
            "last_credit_at": NOW,
        },
        {
            "contribution_count": 1,
            "value_sum": 0.1,
            "absolute_value_sum": 0.1,
            "standard_error_sum": 0.01,
            "minimum_structural_confidence": 0.8,
            "last_credit_at": None,
        },
    ],
)
def test_inherited_evidence_rejects_inconsistent_values(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(LearningEvidenceValidationError):
        inherited(**overrides)


def test_node_snapshot_keeps_direct_and_inherited_contracts_separate() -> None:
    snapshot = NodeLearningEvidence(
        space_id=SPACE,
        memory_id=MEMORY_A,
        direct=direct(),
        inherited=inherited(),
    )

    assert snapshot.has_direct_evidence is True
    assert snapshot.has_inherited_evidence is True
    assert not hasattr(snapshot, "score")
    assert not hasattr(snapshot, "utility")
    assert not hasattr(snapshot, "combined_utility")
    with pytest.raises(FrozenInstanceError):
        snapshot.memory_id = MEMORY_B  # type: ignore[misc]


def test_node_snapshot_rejects_invalid_ids_and_nested_types() -> None:
    with pytest.raises(LearningEvidenceValidationError, match="space_id"):
        NodeLearningEvidence(
            space_id="bad",  # type: ignore[arg-type]
            memory_id=MEMORY_A,
            direct=direct(),
            inherited=inherited(),
        )
    with pytest.raises(LearningEvidenceValidationError, match="memory_id"):
        NodeLearningEvidence(
            space_id=SPACE,
            memory_id="bad",  # type: ignore[arg-type]
            direct=direct(),
            inherited=inherited(),
        )
    with pytest.raises(LearningEvidenceValidationError, match="direct"):
        NodeLearningEvidence(
            space_id=SPACE,
            memory_id=MEMORY_A,
            direct=None,  # type: ignore[arg-type]
            inherited=inherited(),
        )


def test_reader_returns_immutable_sorted_mapping_and_deduplicates_request() -> None:
    cursor = FakeCursor([row(MEMORY_B), row(MEMORY_A)])
    reader = NeonLearningEvidenceReader(cursor)

    result = reader.fetch(
        space_id=SPACE,
        memory_ids=(MEMORY_B, MEMORY_A, MEMORY_A),
    )

    assert isinstance(result, MappingProxyType)
    assert tuple(result) == (MEMORY_A, MEMORY_B)
    assert result[MEMORY_A].direct == direct()
    assert result[MEMORY_A].inherited == inherited()
    assert len(cursor.calls) == 1
    sql, params = cursor.calls[0]
    assert sql == LEARNING_EVIDENCE_SELECT_SQL
    assert params == {
        "space_id": SPACE,
        "memory_ids": [MEMORY_A, MEMORY_B],
    }
    with pytest.raises(TypeError):
        result[MEMORY_A] = result[MEMORY_B]  # type: ignore[index]


def test_reader_normalizes_explicit_neutral_view_row() -> None:
    cursor = FakeCursor(
        [
            row(
                direct_feedback_count=0,
                direct_avg_reward=None,
                direct_positive_count=0,
                direct_negative_count=0,
                last_direct_feedback_at=None,
                inherited_contribution_count=0,
                inherited_value_sum=None,
                inherited_absolute_value_sum=None,
                inherited_standard_error_sum=None,
                minimum_structural_confidence=None,
                last_inherited_credit_at=None,
            )
        ]
    )

    snapshot = NeonLearningEvidenceReader(cursor).fetch(
        space_id=SPACE,
        memory_ids=(MEMORY_A,),
    )[MEMORY_A]

    assert snapshot.has_direct_evidence is False
    assert snapshot.has_inherited_evidence is False
    assert snapshot.direct.average_reward is None
    assert snapshot.inherited.value_sum is None


def test_reader_performs_no_sql_for_empty_request() -> None:
    cursor = FakeCursor([])

    result = NeonLearningEvidenceReader(cursor).fetch(
        space_id=SPACE,
        memory_ids=(),
    )

    assert result == {}
    assert cursor.calls == []


def test_reader_accepts_string_uuids_and_numeric_values() -> None:
    cursor = FakeCursor(
        [
            row(
                space_id=str(SPACE),
                node_id=str(MEMORY_A),
                direct_feedback_count=3,
                direct_avg_reward="0.4",
                inherited_value_sum="0.3",
                inherited_absolute_value_sum="0.5",
                inherited_standard_error_sum="0.08",
                minimum_structural_confidence="0.75",
            )
        ]
    )

    snapshot = NeonLearningEvidenceReader(cursor).fetch(
        space_id=SPACE,
        memory_ids=(MEMORY_A,),
    )[MEMORY_A]

    assert snapshot.space_id == SPACE
    assert snapshot.memory_id == MEMORY_A
    assert snapshot.direct.average_reward == 0.4
    assert snapshot.inherited.minimum_structural_confidence == 0.75


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([], "missing"),
        ([row(MEMORY_B)], "unexpected"),
        ([row(), row()], "duplicate"),
        ([row(space_id=OTHER_SPACE)], "space"),
        ([{"space_id": SPACE, "node_id": MEMORY_A}], "missing"),
        (["not-a-mapping"], "mapping"),
    ],
)
def test_reader_rejects_missing_unexpected_duplicate_or_malformed_rows(
    rows: list[object],
    message: str,
) -> None:
    cursor = FakeCursor(rows)  # type: ignore[arg-type]

    with pytest.raises(LearningEvidenceReadConflictError, match=message):
        NeonLearningEvidenceReader(cursor).fetch(
            space_id=SPACE,
            memory_ids=(MEMORY_A,),
        )


def test_reader_rejects_invalid_request_types_before_sql() -> None:
    cursor = FakeCursor([])
    reader = NeonLearningEvidenceReader(cursor)

    with pytest.raises(LearningEvidenceValidationError, match="space_id"):
        reader.fetch(
            space_id="bad",  # type: ignore[arg-type]
            memory_ids=(MEMORY_A,),
        )
    with pytest.raises(LearningEvidenceValidationError, match="memory_ids"):
        reader.fetch(
            space_id=SPACE,
            memory_ids=(MEMORY_A, "bad"),  # type: ignore[arg-type]
        )

    assert cursor.calls == []
