"""Deterministic, evidence-shrunk utility-aware memory reranking."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from uuid import UUID

from .retrieval import ResearchRetrievalHit


@dataclass(frozen=True, slots=True)
class UtilityEvidence:
    """Aggregate utility evidence for one canonical memory node."""

    memory_id: UUID
    feedback_count: int = 0
    avg_reward: float | None = None
    positive_count: int = 0
    negative_count: int = 0
    last_feedback_at: datetime | None = None

    def __post_init__(self) -> None:
        for name in ("feedback_count", "positive_count", "negative_count"):
            _validate_nonnegative_integer(name, getattr(self, name))
        if self.positive_count + self.negative_count > self.feedback_count:
            raise ValueError(
                "positive_count plus negative_count must not exceed feedback_count"
            )
        if self.avg_reward is not None:
            if not isfinite(self.avg_reward):
                raise ValueError("avg_reward must be finite when supplied")
            if self.feedback_count == 0:
                raise ValueError("avg_reward requires at least one feedback observation")
        if self.last_feedback_at is not None and (
            self.last_feedback_at.tzinfo is None
            or self.last_feedback_at.utcoffset() is None
        ):
            raise ValueError("last_feedback_at must be timezone-aware")

    @classmethod
    def neutral(cls, memory_id: UUID) -> UtilityEvidence:
        """Return an explicit zero-evidence prior for a memory."""

        return cls(memory_id=memory_id)


@dataclass(frozen=True, slots=True)
class UtilityRerankCandidate:
    """One retrieval hit enriched with utility and bounded cost estimates."""

    hit: ResearchRetrievalHit
    utility: UtilityEvidence
    estimated_tokens: int = 0
    estimated_latency_ms: float = 0.0

    def __post_init__(self) -> None:
        if self.hit.memory_id != self.utility.memory_id:
            raise ValueError("hit and utility must reference the same memory_id")
        _validate_nonnegative_integer("estimated_tokens", self.estimated_tokens)
        if not isfinite(self.estimated_latency_ms) or self.estimated_latency_ms < 0:
            raise ValueError("estimated_latency_ms must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class UtilityRerankerConfig:
    """Transparent weights and priors for deterministic reranking."""

    prior_strength: float = 4.0
    relevance_weight: float = 1.0
    utility_weight: float = 0.35
    harm_weight: float = 0.75
    token_weight: float = 0.08
    latency_weight: float = 0.07
    token_reference: int = 512
    latency_reference_ms: float = 100.0

    def __post_init__(self) -> None:
        if not isfinite(self.prior_strength) or self.prior_strength <= 0:
            raise ValueError("prior_strength must be finite and greater than zero")
        for name in (
            "relevance_weight",
            "utility_weight",
            "harm_weight",
            "token_weight",
            "latency_weight",
        ):
            value = getattr(self, name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        _validate_positive_integer("token_reference", self.token_reference)
        if not isfinite(self.latency_reference_ms) or self.latency_reference_ms <= 0:
            raise ValueError(
                "latency_reference_ms must be finite and greater than zero"
            )


@dataclass(frozen=True, slots=True)
class UtilityScoreBreakdown:
    """Auditable raw signals and signed weighted contributions."""

    relevance: float
    utility: float
    harm_risk: float
    token_cost: float
    latency_cost: float
    weighted_relevance: float
    weighted_utility: float
    weighted_harm_penalty: float
    weighted_token_penalty: float
    weighted_latency_penalty: float

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")

    @property
    def total(self) -> float:
        return (
            self.weighted_relevance
            + self.weighted_utility
            + self.weighted_harm_penalty
            + self.weighted_token_penalty
            + self.weighted_latency_penalty
        )


@dataclass(frozen=True, slots=True)
class RerankedMemory:
    """A retrieval hit with its deterministic utility-aware rank."""

    hit: ResearchRetrievalHit
    original_rank: int
    final_rank: int
    final_score: float
    breakdown: UtilityScoreBreakdown

    def __post_init__(self) -> None:
        if self.original_rank <= 0 or self.final_rank <= 0:
            raise ValueError("original_rank and final_rank must be greater than zero")
        if not isfinite(self.final_score):
            raise ValueError("final_score must be finite")


class UtilityAwareReranker:
    """Rerank retrieval hits without learning from contaminated bundle rewards."""

    def __init__(self, config: UtilityRerankerConfig | None = None) -> None:
        self.config = config or UtilityRerankerConfig()

    def rerank(
        self,
        candidates: Sequence[UtilityRerankCandidate],
        *,
        limit: int | None = None,
    ) -> tuple[RerankedMemory, ...]:
        candidates = tuple(candidates)
        if not candidates:
            return ()
        if limit is not None:
            _validate_positive_integer("limit", limit)

        positive_scores = [
            candidate.hit.score
            for candidate in candidates
            if candidate.hit.score > 0
        ]
        max_positive_score = max(positive_scores, default=0.0)
        scored: list[
            tuple[UtilityRerankCandidate, UtilityScoreBreakdown, float]
        ] = []

        for candidate in candidates:
            relevance = (
                max(candidate.hit.score, 0.0) / max_positive_score
                if max_positive_score > 0
                else 1.0 / candidate.hit.rank
            )
            utility, harm_risk = self._utility_signals(candidate.utility)
            token_cost = min(
                candidate.estimated_tokens / self.config.token_reference,
                1.0,
            )
            latency_cost = min(
                candidate.estimated_latency_ms / self.config.latency_reference_ms,
                1.0,
            )
            breakdown = UtilityScoreBreakdown(
                relevance=relevance,
                utility=utility,
                harm_risk=harm_risk,
                token_cost=token_cost,
                latency_cost=latency_cost,
                weighted_relevance=self.config.relevance_weight * relevance,
                weighted_utility=self.config.utility_weight * utility,
                weighted_harm_penalty=-self.config.harm_weight * harm_risk,
                weighted_token_penalty=-self.config.token_weight * token_cost,
                weighted_latency_penalty=-self.config.latency_weight * latency_cost,
            )
            if not isfinite(breakdown.total):
                raise ValueError("final reranker score must be finite")
            scored.append((candidate, breakdown, breakdown.total))

        scored.sort(
            key=lambda item: (
                -item[2],
                item[0].hit.rank,
                str(item[0].hit.memory_id),
            )
        )
        if limit is not None:
            scored = scored[:limit]
        return tuple(
            RerankedMemory(
                hit=candidate.hit,
                original_rank=candidate.hit.rank,
                final_rank=final_rank,
                final_score=score,
                breakdown=breakdown,
            )
            for final_rank, (candidate, breakdown, score) in enumerate(
                scored,
                start=1,
            )
        )

    def _utility_signals(self, evidence: UtilityEvidence) -> tuple[float, float]:
        prior_strength = self.config.prior_strength
        signals: list[float] = []

        if evidence.avg_reward is not None:
            clipped_reward = max(-1.0, min(evidence.avg_reward, 1.0))
            confidence = evidence.feedback_count / (
                evidence.feedback_count + prior_strength
            )
            signals.append(clipped_reward * confidence)

        verdict_count = evidence.positive_count + evidence.negative_count
        harm_risk = 0.0
        if verdict_count > 0:
            verdict_confidence = verdict_count / (verdict_count + prior_strength)
            signals.append(
                (
                    (evidence.positive_count - evidence.negative_count)
                    / verdict_count
                )
                * verdict_confidence
            )
            harm_risk = (
                evidence.negative_count / verdict_count
            ) * verdict_confidence

        utility = sum(signals) / len(signals) if signals else 0.0
        return utility, harm_risk


def _validate_nonnegative_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _validate_positive_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
