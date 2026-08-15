"""Immutable contracts for dependency-aware, set-level context compilation."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Any
from uuid import UUID

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class ContextCompilerValidationError(ValueError):
    """A compiler contract or canonical identity is malformed."""


class ContextDependencyError(ValueError):
    """A prerequisite graph is missing, cyclic, or impossible."""


class ContextBudgetError(ValueError):
    """The packet envelope or mandatory closure cannot fit its hard budget."""


class ContextOptimizationError(RuntimeError):
    """An internal optimization or deterministic-result invariant failed."""


class ContextFidelity(StrEnum):
    """Fidelity class of materialized memory evidence."""

    EXACT = "exact"
    DERIVED = "derived"


class ContextInteractionKind(StrEnum):
    """Stable pairwise effects admitted into set-level compilation."""

    SYNERGY = "synergy"
    REDUNDANCY = "redundancy"


class ContextSolverMode(StrEnum):
    """Optimization mode used for one canonical candidate pool."""

    EXACT = "exact"
    HEURISTIC = "heuristic"


class ContextSelectionPhase(StrEnum):
    """Phase that caused one evidence item to enter the packet."""

    MANDATORY = "mandatory"
    COVERAGE = "coverage"
    EXACT = "exact"
    GREEDY = "greedy"
    LOCAL_IMPROVEMENT = "local_improvement"


class ContextOmissionReason(StrEnum):
    """Machine-readable reason a canonical candidate was not selected."""

    BELOW_AUTHORITY = "below_authority"
    BELOW_CONFIDENCE = "below_confidence"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    DUPLICATE_CONTENT = "duplicate_content"
    DEPENDENCY_UNAVAILABLE = "dependency_unavailable"
    EXPERT_CAP = "expert_cap"
    TOKEN_BUDGET = "token_budget"
    ITEM_LIMIT = "item_limit"
    REQUIRED_COVERAGE_DOMINATED = "required_coverage_dominated"
    NON_POSITIVE_MARGINAL_VALUE = "non_positive_marginal_value"
    REDUNDANCY_DOMINATED = "redundancy_dominated"
    NOT_SELECTED_BY_EXACT_SOLVER = "not_selected_by_exact_solver"
    NOT_SELECTED_BY_HEURISTIC = "not_selected_by_heuristic"


@dataclass(frozen=True, slots=True)
class ContextCoverageDemand:
    """One weighted information demand for the context packet."""

    coverage_key: str
    weight: float = 1.0
    required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "coverage_key",
            _normalize_label("coverage_key", self.coverage_key),
        )
        _validate_positive_finite("weight", self.weight)
        _validate_bool("required", self.required)


@dataclass(frozen=True, slots=True)
class ContextObjectivePolicy:
    """Versioned, explicit weights for the set-level compiler objective."""

    policy_version: str = "integrated-context-compiler-v0"
    relevance_weight: float = 1.00
    utility_weight: float = 0.35
    direct_credit_weight: float = 0.45
    inherited_credit_weight: float = 0.10
    harm_weight: float = 0.75
    new_expert_bonus: float = 0.05
    new_subject_bonus: float = 0.03
    new_source_cluster_bonus: float = 0.04
    pair_interaction_weight: float = 0.25
    inherited_contribution_cap: float = 0.10
    pair_value_cap: float = 0.25
    comparison_tolerance: float = 1e-12

    def __post_init__(self) -> None:
        if not isinstance(self.policy_version, str) or not self.policy_version.strip():
            raise ContextCompilerValidationError(
                "policy_version must be a non-empty string"
            )
        object.__setattr__(self, "policy_version", self.policy_version.strip())
        for name in (
            "relevance_weight",
            "utility_weight",
            "direct_credit_weight",
            "inherited_credit_weight",
            "harm_weight",
            "new_expert_bonus",
            "new_subject_bonus",
            "new_source_cluster_bonus",
            "pair_interaction_weight",
            "inherited_contribution_cap",
            "pair_value_cap",
        ):
            _validate_nonnegative_finite(name, getattr(self, name))
        _validate_positive_finite(
            "comparison_tolerance",
            self.comparison_tolerance,
        )


@dataclass(frozen=True, slots=True)
class IntegratedContextEvidence:
    """One exact, already-scoped memory item eligible for set selection."""

    memory_id: UUID
    space_id: UUID
    expert: str
    subject_key: str
    source_cluster_key: str
    content: str
    content_hash: str
    backend_ref: str
    estimated_tokens: int
    original_rank: int
    source_uri: str | None = None
    fidelity: ContextFidelity = ContextFidelity.EXACT
    coverage_keys: frozenset[str] = field(default_factory=frozenset)
    prerequisite_memory_ids: frozenset[UUID] = field(default_factory=frozenset)
    mandatory: bool = False
    relevance: float = 0.0
    utility: float = 0.0
    direct_credit: float = 0.0
    inherited_credit: float = 0.0
    harm_risk: float = 0.0
    authority: float = 1.0
    confidence: float = 1.0

    def __post_init__(self) -> None:
        _validate_uuid("memory_id", self.memory_id)
        _validate_uuid("space_id", self.space_id)
        object.__setattr__(self, "expert", _normalize_label("expert", self.expert))
        object.__setattr__(
            self,
            "subject_key",
            _normalize_label("subject_key", self.subject_key),
        )
        object.__setattr__(
            self,
            "source_cluster_key",
            _normalize_label("source_cluster_key", self.source_cluster_key),
        )
        if not isinstance(self.content, str) or self.content == "":
            raise ContextCompilerValidationError("content must be a non-empty string")
        _validate_hash("content_hash", self.content_hash)
        expected_hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if self.content_hash != expected_hash:
            raise ContextCompilerValidationError(
                "content_hash does not match exact content"
            )
        _validate_nonempty_string("backend_ref", self.backend_ref)
        if self.source_uri is not None:
            _validate_nonempty_string("source_uri", self.source_uri)
        object.__setattr__(
            self,
            "fidelity",
            _coerce_enum("fidelity", self.fidelity, ContextFidelity),
        )
        _validate_positive_integer("estimated_tokens", self.estimated_tokens)
        _validate_positive_integer("original_rank", self.original_rank)
        object.__setattr__(
            self,
            "coverage_keys",
            _freeze_normalized_labels("coverage", self.coverage_keys),
        )
        prerequisites = _freeze_uuid_set(
            "prerequisite_memory_ids",
            self.prerequisite_memory_ids,
        )
        if self.memory_id in prerequisites:
            raise ContextCompilerValidationError(
                "memory cannot declare itself as a self prerequisite"
            )
        object.__setattr__(self, "prerequisite_memory_ids", prerequisites)
        _validate_bool("mandatory", self.mandatory)
        _validate_unit_interval("relevance", self.relevance)
        _validate_signed_unit_interval("utility", self.utility)
        _validate_signed_unit_interval("direct_credit", self.direct_credit)
        _validate_signed_unit_interval("inherited_credit", self.inherited_credit)
        _validate_unit_interval("harm_risk", self.harm_risk)
        _validate_unit_interval("authority", self.authority)
        _validate_unit_interval("confidence", self.confidence)


@dataclass(frozen=True, slots=True)
class ContextPairInteraction:
    """One stable symmetric synergy or redundancy signal."""

    left_memory_id: UUID
    right_memory_id: UUID
    kind: ContextInteractionKind
    value: float
    standard_error: float
    trial_count: int
    evidence_group_id: UUID

    def __post_init__(self) -> None:
        _validate_uuid("left_memory_id", self.left_memory_id)
        _validate_uuid("right_memory_id", self.right_memory_id)
        _validate_uuid("evidence_group_id", self.evidence_group_id)
        if self.left_memory_id == self.right_memory_id:
            raise ContextCompilerValidationError(
                "pair interaction memory IDs must be distinct"
            )
        if str(self.left_memory_id) >= str(self.right_memory_id):
            raise ContextCompilerValidationError(
                "pair interaction IDs must be in lexicographic order"
            )
        object.__setattr__(
            self,
            "kind",
            _coerce_enum("kind", self.kind, ContextInteractionKind),
        )
        _validate_signed_unit_interval("value", self.value)
        _validate_nonnegative_finite("standard_error", self.standard_error)
        _validate_positive_integer("trial_count", self.trial_count)


@dataclass(frozen=True, slots=True)
class IntegratedContextCompileRequest:
    """Hard controls and explicit demands for one context compilation call."""

    space_id: UUID
    token_budget: int
    envelope_tokens: int
    max_items: int
    coverage_demands: tuple[ContextCoverageDemand, ...] = ()
    max_items_per_expert: Mapping[str, int] | Iterable[tuple[str, int]] = field(
        default_factory=dict
    )
    min_authority: float = 0.0
    min_confidence: float = 0.0
    exact_candidate_limit: int = 18
    local_search_pass_limit: int = 4
    objective_policy: ContextObjectivePolicy = field(
        default_factory=ContextObjectivePolicy
    )

    def __post_init__(self) -> None:
        _validate_uuid("space_id", self.space_id)
        _validate_positive_integer("token_budget", self.token_budget)
        _validate_nonnegative_integer("envelope_tokens", self.envelope_tokens)
        if self.envelope_tokens >= self.token_budget:
            raise ContextBudgetError(
                "envelope_tokens must be strictly smaller than token_budget"
            )
        _validate_positive_integer("max_items", self.max_items)
        object.__setattr__(
            self,
            "coverage_demands",
            _freeze_demands(self.coverage_demands),
        )
        object.__setattr__(
            self,
            "max_items_per_expert",
            _freeze_expert_caps(self.max_items_per_expert),
        )
        _validate_unit_interval("min_authority", self.min_authority)
        _validate_unit_interval("min_confidence", self.min_confidence)
        _validate_positive_integer(
            "exact_candidate_limit",
            self.exact_candidate_limit,
        )
        _validate_positive_integer(
            "local_search_pass_limit",
            self.local_search_pass_limit,
        )
        if not isinstance(self.objective_policy, ContextObjectivePolicy):
            raise ContextCompilerValidationError(
                "objective_policy must be a ContextObjectivePolicy"
            )

    @property
    def evidence_token_budget(self) -> int:
        """Return tokens available for evidence after the packet envelope."""

        return self.token_budget - self.envelope_tokens


def _freeze_demands(
    demands: Iterable[ContextCoverageDemand],
) -> tuple[ContextCoverageDemand, ...]:
    if isinstance(demands, (str, bytes)):
        raise ContextCompilerValidationError(
            "coverage_demands must be an iterable of ContextCoverageDemand"
        )
    normalized: list[ContextCoverageDemand] = []
    seen: set[str] = set()
    try:
        iterator = iter(demands)
    except TypeError as exc:
        raise ContextCompilerValidationError(
            "coverage_demands must be iterable"
        ) from exc
    for demand in iterator:
        if not isinstance(demand, ContextCoverageDemand):
            raise ContextCompilerValidationError(
                "coverage_demands must contain ContextCoverageDemand values"
            )
        if demand.coverage_key in seen:
            raise ContextCompilerValidationError(
                "duplicate coverage demand key"
            )
        seen.add(demand.coverage_key)
        normalized.append(demand)
    return tuple(sorted(normalized, key=lambda item: item.coverage_key))


def _freeze_expert_caps(
    caps: Mapping[str, int] | Iterable[tuple[str, int]],
) -> Mapping[str, int]:
    if isinstance(caps, Mapping):
        items = caps.items()
    else:
        if isinstance(caps, (str, bytes)):
            raise ContextCompilerValidationError(
                "max_items_per_expert must be a mapping or pair iterable"
            )
        try:
            items = iter(caps)
        except TypeError as exc:
            raise ContextCompilerValidationError(
                "max_items_per_expert must be iterable"
            ) from exc
    normalized: dict[str, int] = {}
    for raw_item in items:
        try:
            raw_key, raw_value = raw_item
        except (TypeError, ValueError) as exc:
            raise ContextCompilerValidationError(
                "expert caps must contain key/value pairs"
            ) from exc
        key = _normalize_label("expert cap key", raw_key)
        if key in normalized:
            raise ContextCompilerValidationError(
                "duplicate expert cap after normalization"
            )
        _validate_positive_integer("expert cap", raw_value)
        normalized[key] = raw_value
    return MappingProxyType(dict(sorted(normalized.items())))


def _freeze_normalized_labels(
    name: str,
    values: Iterable[str],
) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ContextCompilerValidationError(
            f"{name} values must be an iterable of strings"
        )
    normalized: set[str] = set()
    raw_count = 0
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise ContextCompilerValidationError(
            f"{name} values must be iterable"
        ) from exc
    for value in iterator:
        raw_count += 1
        label = _normalize_label(f"{name} key", value)
        if label in normalized:
            raise ContextCompilerValidationError(
                f"duplicate {name} key after normalization"
            )
        normalized.add(label)
    if len(normalized) != raw_count:
        raise ContextCompilerValidationError(
            f"duplicate {name} key after normalization"
        )
    return frozenset(normalized)


def _freeze_uuid_set(name: str, values: Iterable[UUID]) -> frozenset[UUID]:
    if isinstance(values, (str, bytes)):
        raise ContextCompilerValidationError(
            f"{name} must be an iterable of UUID values"
        )
    normalized: set[UUID] = set()
    try:
        iterator = iter(values)
    except TypeError as exc:
        raise ContextCompilerValidationError(f"{name} must be iterable") from exc
    for value in iterator:
        _validate_uuid(f"{name} item", value)
        normalized.add(value)
    return frozenset(normalized)


def _coerce_enum(name: str, value: Any, enum_type: type[StrEnum]) -> StrEnum:
    if isinstance(value, enum_type):
        return value
    if isinstance(value, str):
        try:
            return enum_type(value.strip().lower())
        except ValueError as exc:
            raise ContextCompilerValidationError(
                f"{name} is not an allowed value"
            ) from exc
    raise ContextCompilerValidationError(f"{name} must be {enum_type.__name__}")


def _normalize_label(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContextCompilerValidationError(f"{name} must be a non-empty string")
    return value.strip().lower()


def _validate_nonempty_string(name: str, value: Any) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContextCompilerValidationError(f"{name} must be a non-empty string")


def _validate_uuid(name: str, value: Any) -> None:
    if not isinstance(value, UUID):
        raise ContextCompilerValidationError(f"{name} must be a UUID")


def _validate_hash(name: str, value: Any) -> None:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ContextCompilerValidationError(
            f"{name} must be a lowercase SHA-256 hex digest"
        )


def _validate_bool(name: str, value: Any) -> None:
    if not isinstance(value, bool):
        raise ContextCompilerValidationError(f"{name} must be a boolean")


def _validate_finite(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContextCompilerValidationError(f"{name} must be numeric")
    numeric = float(value)
    if not isfinite(numeric):
        raise ContextCompilerValidationError(f"{name} must be finite")
    return numeric


def _validate_positive_finite(name: str, value: Any) -> None:
    numeric = _validate_finite(name, value)
    if numeric <= 0:
        raise ContextCompilerValidationError(f"{name} must be greater than zero")


def _validate_nonnegative_finite(name: str, value: Any) -> None:
    numeric = _validate_finite(name, value)
    if numeric < 0:
        raise ContextCompilerValidationError(f"{name} must be non-negative")


def _validate_unit_interval(name: str, value: Any) -> None:
    numeric = _validate_finite(name, value)
    if not 0 <= numeric <= 1:
        raise ContextCompilerValidationError(f"{name} must be between zero and one")


def _validate_signed_unit_interval(name: str, value: Any) -> None:
    numeric = _validate_finite(name, value)
    if not -1 <= numeric <= 1:
        raise ContextCompilerValidationError(f"{name} must be between -1 and one")


def _validate_positive_integer(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContextCompilerValidationError(f"{name} must be a positive integer")


def _validate_nonnegative_integer(name: str, value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContextCompilerValidationError(
            f"{name} must be a non-negative integer"
        )
