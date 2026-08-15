"""Conservative second-stage reranking from inherited provenance evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite, tanh
from uuid import UUID

from .learning_evidence import NodeLearningEvidence
from .utility_reranker import RerankedMemory


class BoundedInheritedRerankerValidationError(ValueError):
    """The inherited-evidence scoring contract was violated."""


class InheritedEvidenceDisposition(StrEnum):
    """Why inherited evidence did or did not affect a candidate score."""

    NO_EVIDENCE = "no_evidence"
    BELOW_MINIMUM_COUNT = "below_minimum_count"
    BELOW_MINIMUM_CONFIDENCE = "below_minimum_confidence"
    APPLIED = "applied"


@dataclass(frozen=True, slots=True)
class BoundedInheritedRerankerConfig:
    """Explicit conservative policy for inherited-evidence adjustment."""

    inherited_weight: float = 0.10
    maximum_absolute_adjustment: float = 0.05
    prior_contribution_count: float = 8.0
    minimum_contribution_count: int = 2
    minimum_structural_confidence: float = 0.50
    value_scale: float = 0.25
    uncertainty_floor: float = 0.05
    policy_version: str = "bounded-inherited-reranker-v0"

    def __post_init__(self) -> None:
        inherited_weight = _nonnegative_number("inherited_weight", self.inherited_weight)
        maximum_absolute_adjustment = _nonnegative_number(
            "maximum_absolute_adjustment",
            self.maximum_absolute_adjustment,
        )
        if maximum_absolute_adjustment > inherited_weight:
            raise BoundedInheritedRerankerValidationError(
                "maximum_absolute_adjustment cannot exceed inherited_weight"
            )
        prior_contribution_count = _nonnegative_number(
            "prior_contribution_count",
            self.prior_contribution_count,
        )
        minimum_contribution_count = _positive_integer(
            "minimum_contribution_count",
            self.minimum_contribution_count,
        )
        minimum_structural_confidence = _probability(
            "minimum_structural_confidence",
            self.minimum_structural_confidence,
        )
        value_scale = _positive_number("value_scale", self.value_scale)
        uncertainty_floor = _positive_number("uncertainty_floor", self.uncertainty_floor)
        policy_version = _required_text("policy_version", self.policy_version)

        object.__setattr__(self, "inherited_weight", inherited_weight)
        object.__setattr__(
            self,
            "maximum_absolute_adjustment",
            maximum_absolute_adjustment,
        )
        object.__setattr__(
            self,
            "prior_contribution_count",
            prior_contribution_count,
        )
        object.__setattr__(
            self,
            "minimum_contribution_count",
            minimum_contribution_count,
        )
        object.__setattr__(
            self,
            "minimum_structural_confidence",
            minimum_structural_confidence,
        )
        object.__setattr__(self, "value_scale", value_scale)
        object.__setattr__(self, "uncertainty_floor", uncertainty_floor)
        object.__setattr__(self, "policy_version", policy_version)


@dataclass(frozen=True, slots=True)
class InheritedScoreBreakdown:
    """Complete inherited-only score calculation for one memory."""

    contribution_count: int
    value_sum: float | None
    absolute_value_sum: float | None
    standard_error_sum: float | None
    minimum_structural_confidence: float | None
    inherited_mean: float | None
    signed_signal: float
    count_shrinkage: float
    path_coherence: float
    uncertainty_reliability: float
    confidence_reliability: float
    uncapped_component: float
    applied_component: float
    disposition: InheritedEvidenceDisposition
    policy_version: str

    def __post_init__(self) -> None:
        contribution_count = _nonnegative_integer("contribution_count", self.contribution_count)
        value_sum = _optional_finite_number("value_sum", self.value_sum)
        absolute_value_sum = _optional_finite_number("absolute_value_sum", self.absolute_value_sum)
        standard_error_sum = _optional_finite_number("standard_error_sum", self.standard_error_sum)
        minimum_structural_confidence = _optional_probability(
            "minimum_structural_confidence",
            self.minimum_structural_confidence,
        )
        inherited_mean = _optional_finite_number("inherited_mean", self.inherited_mean)
        signed_signal = _bounded_unit_number("signed_signal", self.signed_signal)
        count_shrinkage = _probability("count_shrinkage", self.count_shrinkage)
        path_coherence = _probability("path_coherence", self.path_coherence)
        uncertainty_reliability = _probability(
            "uncertainty_reliability",
            self.uncertainty_reliability,
        )
        confidence_reliability = _probability(
            "confidence_reliability",
            self.confidence_reliability,
        )
        uncapped_component = _finite_number("uncapped_component", self.uncapped_component)
        applied_component = _finite_number("applied_component", self.applied_component)
        if not isinstance(self.disposition, InheritedEvidenceDisposition):
            raise BoundedInheritedRerankerValidationError(
                "disposition must be an InheritedEvidenceDisposition"
            )
        policy_version = _required_text("policy_version", self.policy_version)

        if contribution_count == 0:
            if any(
                value is not None
                for value in (
                    value_sum,
                    absolute_value_sum,
                    standard_error_sum,
                    minimum_structural_confidence,
                    inherited_mean,
                )
            ):
                raise BoundedInheritedRerankerValidationError(
                    "zero inherited evidence requires null observed fields"
                )
            if self.disposition is not InheritedEvidenceDisposition.NO_EVIDENCE:
                raise BoundedInheritedRerankerValidationError(
                    "zero inherited evidence requires no_evidence disposition"
                )
        else:
            if any(
                value is None
                for value in (
                    value_sum,
                    absolute_value_sum,
                    standard_error_sum,
                    minimum_structural_confidence,
                    inherited_mean,
                )
            ):
                raise BoundedInheritedRerankerValidationError(
                    "observed inherited evidence requires every observed field"
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
        object.__setattr__(self, "inherited_mean", inherited_mean)
        object.__setattr__(self, "signed_signal", signed_signal)
        object.__setattr__(self, "count_shrinkage", count_shrinkage)
        object.__setattr__(self, "path_coherence", path_coherence)
        object.__setattr__(
            self,
            "uncertainty_reliability",
            uncertainty_reliability,
        )
        object.__setattr__(
            self,
            "confidence_reliability",
            confidence_reliability,
        )
        object.__setattr__(self, "uncapped_component", uncapped_component)
        object.__setattr__(self, "applied_component", applied_component)
        object.__setattr__(self, "policy_version", policy_version)


@dataclass(frozen=True, slots=True)
class InheritedAwareRerankedMemory:
    """One base result plus a separately inspectable inherited adjustment."""

    base: RerankedMemory
    final_rank: int
    final_score: float
    inherited_breakdown: InheritedScoreBreakdown

    def __post_init__(self) -> None:
        if not isinstance(self.base, RerankedMemory):
            raise BoundedInheritedRerankerValidationError("base must be a RerankedMemory")
        final_rank = _positive_integer("final_rank", self.final_rank)
        final_score = _finite_number("final_score", self.final_score)
        if not isinstance(self.inherited_breakdown, InheritedScoreBreakdown):
            raise BoundedInheritedRerankerValidationError(
                "inherited_breakdown must be an InheritedScoreBreakdown"
            )
        object.__setattr__(self, "final_rank", final_rank)
        object.__setattr__(self, "final_score", final_score)


class BoundedInheritedReranker:
    """Apply a capped inherited-only adjustment to existing ranked results."""

    def __init__(
        self,
        config: BoundedInheritedRerankerConfig | None = None,
    ) -> None:
        if config is not None and not isinstance(config, BoundedInheritedRerankerConfig):
            raise BoundedInheritedRerankerValidationError(
                "config must be a BoundedInheritedRerankerConfig"
            )
        self._config = config or BoundedInheritedRerankerConfig()

    @property
    def config(self) -> BoundedInheritedRerankerConfig:
        return self._config

    def rerank(
        self,
        *,
        space_id: UUID,
        base_results: Sequence[RerankedMemory],
        learning_evidence: Mapping[UUID, NodeLearningEvidence],
    ) -> tuple[InheritedAwareRerankedMemory, ...]:
        if not isinstance(space_id, UUID):
            raise BoundedInheritedRerankerValidationError("space_id must be a UUID")
        if not isinstance(learning_evidence, Mapping):
            raise BoundedInheritedRerankerValidationError("learning_evidence must be a mapping")
        normalized_results = tuple(base_results)
        if any(not isinstance(result, RerankedMemory) for result in normalized_results):
            raise BoundedInheritedRerankerValidationError(
                "base_results must contain RerankedMemory values"
            )

        candidate_ids = [result.hit.memory_id for result in normalized_results]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise BoundedInheritedRerankerValidationError(
                "base_results contain a duplicate memory UUID"
            )

        ranks = [result.final_rank for result in normalized_results]
        if any(isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0 for rank in ranks):
            raise BoundedInheritedRerankerValidationError(
                "base final rank must be a positive integer"
            )
        if len(ranks) != len(set(ranks)):
            raise BoundedInheritedRerankerValidationError("base final rank values must be unique")
        if sorted(ranks) != list(range(1, len(ranks) + 1)):
            raise BoundedInheritedRerankerValidationError("base final ranks must be contiguous")
        if any(not isfinite(result.final_score) for result in normalized_results):
            raise BoundedInheritedRerankerValidationError("base final scores must be finite")

        evidence_keys = set(learning_evidence)
        if any(not isinstance(key, UUID) for key in evidence_keys):
            raise BoundedInheritedRerankerValidationError(
                "learning evidence mapping keys must be UUID values"
            )
        candidate_set = set(candidate_ids)
        missing = candidate_set.difference(evidence_keys)
        if missing:
            raise BoundedInheritedRerankerValidationError(
                "learning evidence is missing candidate memories"
            )
        unexpected = evidence_keys.difference(candidate_set)
        if unexpected:
            raise BoundedInheritedRerankerValidationError(
                "learning evidence contains unexpected memories"
            )

        for key, evidence in learning_evidence.items():
            if not isinstance(evidence, NodeLearningEvidence):
                raise BoundedInheritedRerankerValidationError(
                    "learning evidence values must be NodeLearningEvidence"
                )
            if key != evidence.memory_id:
                raise BoundedInheritedRerankerValidationError(
                    "learning evidence mapping key does not match memory_id"
                )
            if evidence.space_id != space_id:
                raise BoundedInheritedRerankerValidationError(
                    "learning evidence belongs to another space"
                )

        scored: list[tuple[float, int, str, RerankedMemory, InheritedScoreBreakdown]] = []
        for base in normalized_results:
            evidence = learning_evidence[base.hit.memory_id]
            breakdown = self._score_inherited(evidence)
            final_score = base.final_score + breakdown.applied_component
            if not isfinite(final_score):
                raise BoundedInheritedRerankerValidationError(
                    "inherited-aware final score must be finite"
                )
            scored.append(
                (
                    final_score,
                    base.final_rank,
                    str(base.hit.memory_id),
                    base,
                    breakdown,
                )
            )

        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        return tuple(
            InheritedAwareRerankedMemory(
                base=base,
                final_rank=final_rank,
                final_score=final_score,
                inherited_breakdown=breakdown,
            )
            for final_rank, (
                final_score,
                _base_rank,
                _memory_id,
                base,
                breakdown,
            ) in enumerate(scored, start=1)
        )

    def _score_inherited(
        self,
        evidence: NodeLearningEvidence,
    ) -> InheritedScoreBreakdown:
        inherited = evidence.inherited
        config = self._config
        if inherited.contribution_count == 0:
            return InheritedScoreBreakdown(
                contribution_count=0,
                value_sum=None,
                absolute_value_sum=None,
                standard_error_sum=None,
                minimum_structural_confidence=None,
                inherited_mean=None,
                signed_signal=0.0,
                count_shrinkage=0.0,
                path_coherence=0.0,
                uncertainty_reliability=0.0,
                confidence_reliability=0.0,
                uncapped_component=0.0,
                applied_component=0.0,
                disposition=InheritedEvidenceDisposition.NO_EVIDENCE,
                policy_version=config.policy_version,
            )

        count = inherited.contribution_count
        value_sum = _required_observed("value_sum", inherited.value_sum)
        absolute_value_sum = _required_observed("absolute_value_sum", inherited.absolute_value_sum)
        standard_error_sum = _required_observed("standard_error_sum", inherited.standard_error_sum)
        confidence = _required_observed(
            "minimum_structural_confidence",
            inherited.minimum_structural_confidence,
        )

        inherited_mean = value_sum / count
        signed_signal = tanh(inherited_mean / config.value_scale)
        count_shrinkage = count / (count + config.prior_contribution_count)
        if absolute_value_sum == 0.0:
            path_coherence = 1.0 if value_sum == 0.0 else 0.0
        else:
            path_coherence = min(
                1.0,
                abs(value_sum) / absolute_value_sum,
            )
        uncertainty_reliability = 1.0 / (
            1.0 + standard_error_sum / (absolute_value_sum + config.uncertainty_floor)
        )
        confidence_reliability = confidence
        uncapped_component = (
            config.inherited_weight
            * signed_signal
            * count_shrinkage
            * path_coherence
            * uncertainty_reliability
            * confidence_reliability
        )

        if count < config.minimum_contribution_count:
            disposition = InheritedEvidenceDisposition.BELOW_MINIMUM_COUNT
            applied_component = 0.0
        elif confidence < config.minimum_structural_confidence:
            disposition = InheritedEvidenceDisposition.BELOW_MINIMUM_CONFIDENCE
            applied_component = 0.0
        else:
            disposition = InheritedEvidenceDisposition.APPLIED
            cap = config.maximum_absolute_adjustment
            applied_component = max(
                -cap,
                min(cap, uncapped_component),
            )

        return InheritedScoreBreakdown(
            contribution_count=count,
            value_sum=value_sum,
            absolute_value_sum=absolute_value_sum,
            standard_error_sum=standard_error_sum,
            minimum_structural_confidence=confidence,
            inherited_mean=inherited_mean,
            signed_signal=signed_signal,
            count_shrinkage=count_shrinkage,
            path_coherence=path_coherence,
            uncertainty_reliability=uncertainty_reliability,
            confidence_reliability=confidence_reliability,
            uncapped_component=uncapped_component,
            applied_component=applied_component,
            disposition=disposition,
            policy_version=config.policy_version,
        )


def _required_observed(name: str, value: float | None) -> float:
    if value is None or not isfinite(value):
        raise BoundedInheritedRerankerValidationError(f"observed inherited {name} must be finite")
    return float(value)


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise BoundedInheritedRerankerValidationError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise BoundedInheritedRerankerValidationError(f"{name} must not be empty")
    return normalized


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BoundedInheritedRerankerValidationError(f"{name} must be a finite number")
    normalized = float(value)
    if not isfinite(normalized):
        raise BoundedInheritedRerankerValidationError(f"{name} must be a finite number")
    return normalized


def _nonnegative_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized < 0.0:
        raise BoundedInheritedRerankerValidationError(f"{name} must be non-negative")
    return normalized


def _positive_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized <= 0.0:
        raise BoundedInheritedRerankerValidationError(f"{name} must be positive")
    return normalized


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BoundedInheritedRerankerValidationError(f"{name} must be a positive integer")
    return value


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BoundedInheritedRerankerValidationError(f"{name} must be a non-negative integer")
    return value


def _probability(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if not 0.0 <= normalized <= 1.0:
        raise BoundedInheritedRerankerValidationError(f"{name} must be between zero and one")
    return normalized


def _optional_probability(name: str, value: object) -> float | None:
    if value is None:
        return None
    return _probability(name, value)


def _optional_finite_number(name: str, value: object) -> float | None:
    if value is None:
        return None
    return _finite_number(name, value)


def _bounded_unit_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if not -1.0 <= normalized <= 1.0:
        raise BoundedInheritedRerankerValidationError(f"{name} must be between minus one and one")
    return normalized
