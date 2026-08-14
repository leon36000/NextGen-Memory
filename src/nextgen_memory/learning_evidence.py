"""Read direct and inherited learning evidence without conflating them."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID


class LearningEvidenceValidationError(ValueError):
    """A learning-evidence request or value violates its typed contract."""


class LearningEvidenceReadConflictError(RuntimeError):
    """Stored learning evidence is missing, duplicated, unexpected, or malformed."""


LEARNING_EVIDENCE_SELECT_SQL = """
SELECT
  space_id,
  node_id,
  direct_feedback_count,
  direct_avg_reward,
  direct_positive_count,
  direct_negative_count,
  last_direct_feedback_at,
  inherited_contribution_count,
  inherited_value_sum,
  inherited_absolute_value_sum,
  inherited_standard_error_sum,
  minimum_structural_confidence,
  last_inherited_credit_at
FROM ngm.node_learning_evidence
WHERE space_id = %(space_id)s
  AND node_id = ANY(%(memory_ids)s::uuid[])
ORDER BY node_id
""".strip()


@dataclass(frozen=True, slots=True)
class DirectUtilityEvidence:
    """Direct task-outcome feedback for one canonical memory."""

    feedback_count: int
    average_reward: float | None
    positive_count: int
    negative_count: int
    last_feedback_at: datetime | None

    def __post_init__(self) -> None:
        feedback_count = _nonnegative_integer(
            "feedback_count", self.feedback_count
        )
        positive_count = _nonnegative_integer(
            "positive_count", self.positive_count
        )
        negative_count = _nonnegative_integer(
            "negative_count", self.negative_count
        )
        if positive_count + negative_count > feedback_count:
            raise LearningEvidenceValidationError(
                "positive and negative counts cannot exceed feedback_count"
            )
        average_reward = _optional_finite_number(
            "average_reward", self.average_reward
        )
        last_feedback_at = _optional_aware_datetime(
            "last_feedback_at", self.last_feedback_at
        )
        if feedback_count == 0:
            if (
                average_reward is not None
                or positive_count != 0
                or negative_count != 0
                or last_feedback_at is not None
            ):
                raise LearningEvidenceValidationError(
                    "zero direct feedback requires null aggregates and zero verdict counts"
                )
        elif average_reward is None or last_feedback_at is None:
            raise LearningEvidenceValidationError(
                "observed direct feedback requires reward and timestamp"
            )
        object.__setattr__(self, "feedback_count", feedback_count)
        object.__setattr__(self, "average_reward", average_reward)
        object.__setattr__(self, "positive_count", positive_count)
        object.__setattr__(self, "negative_count", negative_count)
        object.__setattr__(self, "last_feedback_at", last_feedback_at)

    @property
    def has_evidence(self) -> bool:
        return self.feedback_count > 0


@dataclass(frozen=True, slots=True)
class InheritedUtilityEvidence:
    """Separate inherited provenance evidence for one canonical memory."""

    contribution_count: int
    value_sum: float | None
    absolute_value_sum: float | None
    standard_error_sum: float | None
    minimum_structural_confidence: float | None
    last_credit_at: datetime | None

    def __post_init__(self) -> None:
        contribution_count = _nonnegative_integer(
            "contribution_count", self.contribution_count
        )
        value_sum = _optional_finite_number("value_sum", self.value_sum)
        absolute_value_sum = _optional_finite_number(
            "absolute_value_sum", self.absolute_value_sum
        )
        standard_error_sum = _optional_finite_number(
            "standard_error_sum", self.standard_error_sum
        )
        minimum_structural_confidence = _optional_probability(
            "minimum_structural_confidence",
            self.minimum_structural_confidence,
        )
        last_credit_at = _optional_aware_datetime(
            "last_credit_at", self.last_credit_at
        )
        optional_values = (
            value_sum,
            absolute_value_sum,
            standard_error_sum,
            minimum_structural_confidence,
            last_credit_at,
        )
        if contribution_count == 0:
            if any(value is not None for value in optional_values):
                raise LearningEvidenceValidationError(
                    "zero inherited contributions require null aggregates"
                )
        else:
            if any(value is None for value in optional_values):
                raise LearningEvidenceValidationError(
                    "observed inherited evidence requires every aggregate and timestamp"
                )
            assert value_sum is not None
            assert absolute_value_sum is not None
            assert standard_error_sum is not None
            if absolute_value_sum < 0:
                raise LearningEvidenceValidationError(
                    "absolute_value_sum must be non-negative"
                )
            if absolute_value_sum + 1e-12 < abs(value_sum):
                raise LearningEvidenceValidationError(
                    "absolute_value_sum cannot be smaller than abs(value_sum)"
                )
            if standard_error_sum < 0:
                raise LearningEvidenceValidationError(
                    "standard_error_sum must be non-negative"
                )
        object.__setattr__(self, "contribution_count", contribution_count)
        object.__setattr__(self, "value_sum", value_sum)
        object.__setattr__(self, "absolute_value_sum", absolute_value_sum)
        object.__setattr__(self, "standard_error_sum", standard_error_sum)
        object.__setattr__(
            self,
            "minimum_structural_confidence",
            minimum_structural_confidence,
        )
        object.__setattr__(self, "last_credit_at", last_credit_at)

    @property
    def has_evidence(self) -> bool:
        return self.contribution_count > 0


@dataclass(frozen=True, slots=True)
class NodeLearningEvidence:
    """One scoped snapshot with direct and inherited evidence kept separate."""

    space_id: UUID
    memory_id: UUID
    direct: DirectUtilityEvidence
    inherited: InheritedUtilityEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.space_id, UUID):
            raise LearningEvidenceValidationError("space_id must be a UUID")
        if not isinstance(self.memory_id, UUID):
            raise LearningEvidenceValidationError("memory_id must be a UUID")
        if not isinstance(self.direct, DirectUtilityEvidence):
            raise LearningEvidenceValidationError(
                "direct must be DirectUtilityEvidence"
            )
        if not isinstance(self.inherited, InheritedUtilityEvidence):
            raise LearningEvidenceValidationError(
                "inherited must be InheritedUtilityEvidence"
            )

    @property
    def has_direct_evidence(self) -> bool:
        return self.direct.has_evidence

    @property
    def has_inherited_evidence(self) -> bool:
        return self.inherited.has_evidence


class LearningEvidenceCursor(Protocol):
    """Minimal structural cursor for the scoped Neon evidence query."""

    def execute(self, sql: str, params: Mapping[str, Any]) -> Any: ...

    def fetchall(self) -> Iterable[Mapping[str, Any]]: ...


class NeonLearningEvidenceReader:
    """Read complete node-learning snapshots from `ngm.node_learning_evidence`."""

    def __init__(self, cursor: LearningEvidenceCursor) -> None:
        self._cursor = cursor

    def fetch(
        self,
        *,
        space_id: UUID,
        memory_ids: Sequence[UUID],
    ) -> Mapping[UUID, NodeLearningEvidence]:
        if not isinstance(space_id, UUID):
            raise LearningEvidenceValidationError("space_id must be a UUID")
        normalized_ids = _normalize_memory_ids(memory_ids)
        if not normalized_ids:
            return MappingProxyType({})

        self._cursor.execute(
            LEARNING_EVIDENCE_SELECT_SQL,
            {
                "space_id": space_id,
                "memory_ids": list(normalized_ids),
            },
        )
        requested = set(normalized_ids)
        snapshots: dict[UUID, NodeLearningEvidence] = {}
        for raw_row in self._cursor.fetchall():
            if not isinstance(raw_row, Mapping):
                raise LearningEvidenceReadConflictError(
                    "learning evidence row must be a mapping"
                )
            missing_columns = _REQUIRED_COLUMNS.difference(raw_row)
            if missing_columns:
                raise LearningEvidenceReadConflictError(
                    "learning evidence row is missing required columns"
                )
            row_space = _parse_uuid("space_id", raw_row["space_id"])
            memory_id = _parse_uuid("node_id", raw_row["node_id"])
            if row_space != space_id:
                raise LearningEvidenceReadConflictError(
                    "learning evidence row belongs to another space"
                )
            if memory_id not in requested:
                raise LearningEvidenceReadConflictError(
                    "learning evidence returned an unexpected memory"
                )
            if memory_id in snapshots:
                raise LearningEvidenceReadConflictError(
                    "learning evidence returned a duplicate memory"
                )
            try:
                snapshot = NodeLearningEvidence(
                    space_id=row_space,
                    memory_id=memory_id,
                    direct=DirectUtilityEvidence(
                        feedback_count=_parse_integer(
                            "direct_feedback_count",
                            raw_row["direct_feedback_count"],
                        ),
                        average_reward=_parse_optional_number(
                            "direct_avg_reward",
                            raw_row["direct_avg_reward"],
                        ),
                        positive_count=_parse_integer(
                            "direct_positive_count",
                            raw_row["direct_positive_count"],
                        ),
                        negative_count=_parse_integer(
                            "direct_negative_count",
                            raw_row["direct_negative_count"],
                        ),
                        last_feedback_at=_parse_optional_datetime(
                            "last_direct_feedback_at",
                            raw_row["last_direct_feedback_at"],
                        ),
                    ),
                    inherited=InheritedUtilityEvidence(
                        contribution_count=_parse_integer(
                            "inherited_contribution_count",
                            raw_row["inherited_contribution_count"],
                        ),
                        value_sum=_parse_optional_number(
                            "inherited_value_sum",
                            raw_row["inherited_value_sum"],
                        ),
                        absolute_value_sum=_parse_optional_number(
                            "inherited_absolute_value_sum",
                            raw_row["inherited_absolute_value_sum"],
                        ),
                        standard_error_sum=_parse_optional_number(
                            "inherited_standard_error_sum",
                            raw_row["inherited_standard_error_sum"],
                        ),
                        minimum_structural_confidence=(
                            _parse_optional_number(
                                "minimum_structural_confidence",
                                raw_row["minimum_structural_confidence"],
                            )
                        ),
                        last_credit_at=_parse_optional_datetime(
                            "last_inherited_credit_at",
                            raw_row["last_inherited_credit_at"],
                        ),
                    ),
                )
            except LearningEvidenceValidationError as error:
                raise LearningEvidenceReadConflictError(
                    "learning evidence row is malformed"
                ) from error
            snapshots[memory_id] = snapshot

        missing_ids = requested.difference(snapshots)
        if missing_ids:
            raise LearningEvidenceReadConflictError(
                "learning evidence is missing requested memories"
            )
        return MappingProxyType(
            {memory_id: snapshots[memory_id] for memory_id in normalized_ids}
        )


_REQUIRED_COLUMNS = frozenset(
    {
        "space_id",
        "node_id",
        "direct_feedback_count",
        "direct_avg_reward",
        "direct_positive_count",
        "direct_negative_count",
        "last_direct_feedback_at",
        "inherited_contribution_count",
        "inherited_value_sum",
        "inherited_absolute_value_sum",
        "inherited_standard_error_sum",
        "minimum_structural_confidence",
        "last_inherited_credit_at",
    }
)


def _normalize_memory_ids(values: object) -> tuple[UUID, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise LearningEvidenceValidationError(
            "memory_ids must be an iterable of UUID values"
        )
    normalized: set[UUID] = set()
    for value in values:
        if not isinstance(value, UUID):
            raise LearningEvidenceValidationError(
                "memory_ids must contain UUID values"
            )
        normalized.add(value)
    return tuple(sorted(normalized, key=str))


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise LearningEvidenceValidationError(
            f"{name} must be a non-negative integer"
        )
    return value


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LearningEvidenceValidationError(
            f"{name} must be a finite number"
        )
    normalized = float(value)
    if not isfinite(normalized):
        raise LearningEvidenceValidationError(
            f"{name} must be a finite number"
        )
    return normalized


def _optional_finite_number(name: str, value: object) -> float | None:
    if value is None:
        return None
    return _finite_number(name, value)


def _optional_probability(name: str, value: object) -> float | None:
    if value is None:
        return None
    normalized = _finite_number(name, value)
    if not 0.0 <= normalized <= 1.0:
        raise LearningEvidenceValidationError(
            f"{name} must be between zero and one"
        )
    return normalized


def _optional_aware_datetime(
    name: str, value: object
) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise LearningEvidenceValidationError(
            f"{name} must be a datetime or null"
        )
    if value.tzinfo is None or value.utcoffset() is None:
        raise LearningEvidenceValidationError(
            f"{name} must be timezone-aware"
        )
    return value


def _parse_uuid(name: str, value: object) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise LearningEvidenceReadConflictError(
            f"learning evidence {name} is not a UUID"
        ) from error


def _parse_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise LearningEvidenceReadConflictError(
            f"learning evidence {name} is not an integer"
        )
    return value


def _parse_optional_number(name: str, value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise LearningEvidenceReadConflictError(
            f"learning evidence {name} is not numeric"
        )
    try:
        normalized = float(value)
    except (TypeError, ValueError) as error:
        raise LearningEvidenceReadConflictError(
            f"learning evidence {name} is not numeric"
        ) from error
    if not isfinite(normalized):
        raise LearningEvidenceReadConflictError(
            f"learning evidence {name} is not finite"
        )
    return normalized


def _parse_optional_datetime(name: str, value: object) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as error:
            raise LearningEvidenceReadConflictError(
                f"learning evidence {name} is not a datetime"
            ) from error
    else:
        raise LearningEvidenceReadConflictError(
            f"learning evidence {name} is not a datetime"
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise LearningEvidenceReadConflictError(
            f"learning evidence {name} is not timezone-aware"
        )
    return parsed
