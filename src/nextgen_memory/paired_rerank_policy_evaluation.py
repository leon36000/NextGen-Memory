"""Strict matched-replay evaluation for inherited reranking policies."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite, sqrt
from statistics import stdev
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from .causal_credit import OutcomeMeasurement
from .inherited_rerank_telemetry import InheritedRerankTelemetryBatch

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = "nextgen-memory-paired-rerank-policy-evaluation-v0"
_SCORE_TOLERANCE = 1e-12


class PairedRerankPolicyEvaluationValidationError(ValueError):
    """A trial, configuration, or evaluation violates the matched contract."""


class PairedPolicyVerdict(StrEnum):
    """Conservative policy-level decision from matched replay evidence."""

    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    HARMFUL = "harmful"
    TOO_COSTLY = "too_costly"
    PROMISING = "promising"
    NEUTRAL = "neutral"
    INCONCLUSIVE = "inconclusive"


class PairedPolicyAbstentionReason(StrEnum):
    """Why the evaluator refused to issue a directional policy verdict."""

    INSUFFICIENT_PAIRS = "insufficient_pairs"
    STANDARD_ERROR_TOO_HIGH = "standard_error_too_high"


@dataclass(frozen=True, slots=True)
class PairedRerankPolicyTrial:
    """One control/treatment replay pair over the same routed candidates."""

    trial_id: UUID
    space_id: UUID
    context_set_hash: str
    continuation_set_hash: str
    control_batch: InheritedRerankTelemetryBatch
    treatment_batch: InheritedRerankTelemetryBatch
    control_outcome: OutcomeMeasurement
    treatment_outcome: OutcomeMeasurement
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid("trial_id", self.trial_id)
        _require_uuid("space_id", self.space_id)
        _require_hash("context_set_hash", self.context_set_hash)
        _require_hash("continuation_set_hash", self.continuation_set_hash)
        if not isinstance(self.control_batch, InheritedRerankTelemetryBatch):
            raise PairedRerankPolicyEvaluationValidationError(
                "control_batch must be an InheritedRerankTelemetryBatch"
            )
        if not isinstance(self.treatment_batch, InheritedRerankTelemetryBatch):
            raise PairedRerankPolicyEvaluationValidationError(
                "treatment_batch must be an InheritedRerankTelemetryBatch"
            )
        if not isinstance(self.control_outcome, OutcomeMeasurement):
            raise PairedRerankPolicyEvaluationValidationError(
                "control_outcome must be an OutcomeMeasurement"
            )
        if not isinstance(self.treatment_outcome, OutcomeMeasurement):
            raise PairedRerankPolicyEvaluationValidationError(
                "treatment_outcome must be an OutcomeMeasurement"
            )
        if (
            self.control_batch.space_id != self.space_id
            or self.treatment_batch.space_id != self.space_id
        ):
            raise PairedRerankPolicyEvaluationValidationError(
                "control and treatment telemetry must match trial space"
            )
        if self.control_batch.router_decision_id != self.treatment_batch.router_decision_id:
            raise PairedRerankPolicyEvaluationValidationError(
                "control and treatment must share one router decision"
            )
        if self.control_batch.policy_fingerprint == self.treatment_batch.policy_fingerprint:
            raise PairedRerankPolicyEvaluationValidationError(
                "control and treatment must use distinct policies"
            )

        control_by_memory = {item.memory_id: item for item in self.control_batch.observations}
        treatment_by_memory = {item.memory_id: item for item in self.treatment_batch.observations}
        if set(control_by_memory) != set(treatment_by_memory):
            raise PairedRerankPolicyEvaluationValidationError(
                "control and treatment candidate sets must match exactly"
            )
        for memory_id in sorted(control_by_memory, key=str):
            control = control_by_memory[memory_id]
            treatment = treatment_by_memory[memory_id]
            if control.base_rank != treatment.base_rank:
                raise PairedRerankPolicyEvaluationValidationError(
                    "control and treatment base rank must match per candidate"
                )
            if not _close(control.base_score, treatment.base_score):
                raise PairedRerankPolicyEvaluationValidationError(
                    "control and treatment base score must match per candidate"
                )

        object.__setattr__(self, "content_hash", _hash_payload(self._hash_payload()))

    @property
    def score_delta(self) -> float:
        return self.treatment_outcome.score - self.control_outcome.score

    @property
    def success_delta(self) -> float:
        return float(
            int(self.treatment_outcome.task_success) - int(self.control_outcome.task_success)
        )

    @property
    def token_delta(self) -> int:
        return self.treatment_outcome.tokens - self.control_outcome.tokens

    @property
    def latency_delta_ms(self) -> float:
        return self.treatment_outcome.latency_ms - self.control_outcome.latency_ms

    @property
    def treatment_top_changed(self) -> bool:
        return (
            self.control_batch.summary.final_top_memory_id
            != self.treatment_batch.summary.final_top_memory_id
        )

    @property
    def treatment_applied_observation_count(self) -> int:
        return self.treatment_batch.summary.applied_count

    @property
    def treatment_candidate_count(self) -> int:
        return self.treatment_batch.summary.candidate_count

    @property
    def treatment_absolute_adjustment(self) -> float:
        return self.treatment_batch.summary.absolute_adjustment_sum

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "trial_id": str(self.trial_id),
            "space_id": str(self.space_id),
            "context_set_hash": self.context_set_hash,
            "continuation_set_hash": self.continuation_set_hash,
            "control_batch_id": str(self.control_batch.id),
            "control_batch_content_hash": self.control_batch.content_hash,
            "control_policy_version": self.control_batch.policy_version,
            "control_policy_fingerprint": (self.control_batch.policy_fingerprint),
            "treatment_batch_id": str(self.treatment_batch.id),
            "treatment_batch_content_hash": (self.treatment_batch.content_hash),
            "treatment_policy_version": self.treatment_batch.policy_version,
            "treatment_policy_fingerprint": (self.treatment_batch.policy_fingerprint),
            "control_outcome": _outcome_payload(self.control_outcome),
            "treatment_outcome": _outcome_payload(self.treatment_outcome),
        }


@dataclass(frozen=True, slots=True)
class PairedPolicyEvaluationConfig:
    """Conservative thresholds for policy-level matched replay evaluation."""

    minimum_pairs: int = 8
    confidence_z: float = 1.96
    minimum_promising_effect: float = 0.02
    harmful_effect_threshold: float = -0.02
    neutral_effect_band: float = 0.01
    maximum_standard_error: float = 0.10
    maximum_token_increase_ratio: float = 0.05
    maximum_latency_increase_ratio: float = 0.10
    minimum_success_delta: float = 0.0
    policy_version: str = "paired-rerank-policy-evaluation-v0"

    def __post_init__(self) -> None:
        minimum_pairs = _positive_integer("minimum_pairs", self.minimum_pairs)
        confidence_z = _positive_number("confidence_z", self.confidence_z)
        minimum_promising_effect = _nonnegative_number(
            "minimum_promising_effect", self.minimum_promising_effect
        )
        harmful_effect_threshold = _finite_number(
            "harmful_effect_threshold", self.harmful_effect_threshold
        )
        if harmful_effect_threshold >= 0.0:
            raise PairedRerankPolicyEvaluationValidationError(
                "harmful_effect_threshold must be negative"
            )
        neutral_effect_band = _nonnegative_number("neutral_effect_band", self.neutral_effect_band)
        if minimum_promising_effect < neutral_effect_band:
            raise PairedRerankPolicyEvaluationValidationError(
                "minimum_promising_effect must be at least neutral_effect_band"
            )
        maximum_standard_error = _nonnegative_number(
            "maximum_standard_error", self.maximum_standard_error
        )
        maximum_token_increase_ratio = _nonnegative_number(
            "maximum_token_increase_ratio",
            self.maximum_token_increase_ratio,
        )
        maximum_latency_increase_ratio = _nonnegative_number(
            "maximum_latency_increase_ratio",
            self.maximum_latency_increase_ratio,
        )
        minimum_success_delta = _bounded_delta("minimum_success_delta", self.minimum_success_delta)
        policy_version = _required_text("policy_version", self.policy_version)

        object.__setattr__(self, "minimum_pairs", minimum_pairs)
        object.__setattr__(self, "confidence_z", confidence_z)
        object.__setattr__(
            self,
            "minimum_promising_effect",
            minimum_promising_effect,
        )
        object.__setattr__(
            self,
            "harmful_effect_threshold",
            harmful_effect_threshold,
        )
        object.__setattr__(
            self,
            "neutral_effect_band",
            neutral_effect_band,
        )
        object.__setattr__(
            self,
            "maximum_standard_error",
            maximum_standard_error,
        )
        object.__setattr__(
            self,
            "maximum_token_increase_ratio",
            maximum_token_increase_ratio,
        )
        object.__setattr__(
            self,
            "maximum_latency_increase_ratio",
            maximum_latency_increase_ratio,
        )
        object.__setattr__(
            self,
            "minimum_success_delta",
            minimum_success_delta,
        )
        object.__setattr__(self, "policy_version", policy_version)


@dataclass(frozen=True, slots=True)
class PairedRerankPolicyEvaluation:
    """One deterministic policy-level evaluation without memory-level credit."""

    id: UUID
    space_id: UUID
    control_policy_version: str
    control_policy_fingerprint: str
    treatment_policy_version: str
    treatment_policy_fingerprint: str
    continuation_set_hash: str
    context_collection_hash: str
    trial_count: int
    mean_score_delta: float
    score_standard_deviation: float
    score_standard_error: float
    score_confidence_lower: float
    score_confidence_upper: float
    mean_success_delta: float
    mean_token_delta: float
    mean_latency_delta_ms: float
    token_increase_ratio: float
    latency_increase_ratio: float
    treatment_top_change_rate: float
    treatment_applied_observation_rate: float
    treatment_mean_absolute_adjustment: float
    verdict: PairedPolicyVerdict
    abstention_reason: PairedPolicyAbstentionReason | None
    config_version: str
    config_fingerprint: str
    trial_ids: tuple[UUID, ...]
    content_hash: str

    def __post_init__(self) -> None:
        _require_uuid("id", self.id)
        _require_uuid("space_id", self.space_id)
        for name in (
            "control_policy_version",
            "treatment_policy_version",
            "config_version",
        ):
            object.__setattr__(
                self,
                name,
                _required_text(name, getattr(self, name)),
            )
        for name in (
            "control_policy_fingerprint",
            "treatment_policy_fingerprint",
            "continuation_set_hash",
            "context_collection_hash",
            "config_fingerprint",
            "content_hash",
        ):
            _require_hash(name, getattr(self, name))
        trial_count = _positive_integer("trial_count", self.trial_count)
        numeric_fields = (
            "mean_score_delta",
            "score_standard_deviation",
            "score_standard_error",
            "score_confidence_lower",
            "score_confidence_upper",
            "mean_success_delta",
            "mean_token_delta",
            "mean_latency_delta_ms",
            "token_increase_ratio",
            "latency_increase_ratio",
            "treatment_top_change_rate",
            "treatment_applied_observation_rate",
            "treatment_mean_absolute_adjustment",
        )
        normalized: dict[str, float] = {
            name: _finite_number(name, getattr(self, name)) for name in numeric_fields
        }
        if normalized["score_standard_deviation"] < 0.0:
            raise PairedRerankPolicyEvaluationValidationError(
                "score_standard_deviation must be non-negative"
            )
        if normalized["score_standard_error"] < 0.0:
            raise PairedRerankPolicyEvaluationValidationError(
                "score_standard_error must be non-negative"
            )
        if normalized["score_confidence_lower"] > normalized["score_confidence_upper"]:
            raise PairedRerankPolicyEvaluationValidationError(
                "score confidence interval is reversed"
            )
        for name in (
            "treatment_top_change_rate",
            "treatment_applied_observation_rate",
        ):
            if not 0.0 <= normalized[name] <= 1.0:
                raise PairedRerankPolicyEvaluationValidationError(
                    f"{name} must be between zero and one"
                )
        if normalized["treatment_mean_absolute_adjustment"] < 0.0:
            raise PairedRerankPolicyEvaluationValidationError(
                "treatment_mean_absolute_adjustment must be non-negative"
            )
        if not isinstance(self.verdict, PairedPolicyVerdict):
            raise PairedRerankPolicyEvaluationValidationError(
                "verdict must be a PairedPolicyVerdict"
            )
        if self.abstention_reason is not None and not isinstance(
            self.abstention_reason,
            PairedPolicyAbstentionReason,
        ):
            raise PairedRerankPolicyEvaluationValidationError(
                "abstention_reason must be a PairedPolicyAbstentionReason or null"
            )
        if (
            self.verdict is PairedPolicyVerdict.INSUFFICIENT_EVIDENCE
            and self.abstention_reason is None
        ):
            raise PairedRerankPolicyEvaluationValidationError(
                "insufficient evidence verdict requires an abstention reason"
            )
        if (
            self.verdict is not PairedPolicyVerdict.INSUFFICIENT_EVIDENCE
            and self.abstention_reason is not None
        ):
            raise PairedRerankPolicyEvaluationValidationError(
                "directional verdict cannot carry an abstention reason"
            )
        trial_ids = tuple(self.trial_ids)
        if len(trial_ids) != trial_count:
            raise PairedRerankPolicyEvaluationValidationError(
                "trial_ids length must equal trial_count"
            )
        if any(not isinstance(trial_id, UUID) for trial_id in trial_ids):
            raise PairedRerankPolicyEvaluationValidationError("trial_ids must contain UUID values")
        if len(trial_ids) != len(set(trial_ids)):
            raise PairedRerankPolicyEvaluationValidationError("trial_ids must be unique")
        if trial_ids != tuple(sorted(trial_ids, key=str)):
            raise PairedRerankPolicyEvaluationValidationError(
                "trial_ids must use deterministic lexical order"
            )

        object.__setattr__(self, "trial_count", trial_count)
        object.__setattr__(self, "trial_ids", trial_ids)
        for name, value in normalized.items():
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "id": str(self.id),
            "space_id": str(self.space_id),
            "control_policy_version": self.control_policy_version,
            "control_policy_fingerprint": self.control_policy_fingerprint,
            "treatment_policy_version": self.treatment_policy_version,
            "treatment_policy_fingerprint": (self.treatment_policy_fingerprint),
            "continuation_set_hash": self.continuation_set_hash,
            "context_collection_hash": self.context_collection_hash,
            "trial_count": self.trial_count,
            "mean_score_delta": self.mean_score_delta,
            "score_standard_deviation": self.score_standard_deviation,
            "score_standard_error": self.score_standard_error,
            "score_confidence_lower": self.score_confidence_lower,
            "score_confidence_upper": self.score_confidence_upper,
            "mean_success_delta": self.mean_success_delta,
            "mean_token_delta": self.mean_token_delta,
            "mean_latency_delta_ms": self.mean_latency_delta_ms,
            "token_increase_ratio": self.token_increase_ratio,
            "latency_increase_ratio": self.latency_increase_ratio,
            "treatment_top_change_rate": self.treatment_top_change_rate,
            "treatment_applied_observation_rate": (self.treatment_applied_observation_rate),
            "treatment_mean_absolute_adjustment": (self.treatment_mean_absolute_adjustment),
            "verdict": self.verdict.value,
            "abstention_reason": (
                self.abstention_reason.value if self.abstention_reason is not None else None
            ),
            "config_version": self.config_version,
            "config_fingerprint": self.config_fingerprint,
            "trial_ids": [str(trial_id) for trial_id in self.trial_ids],
            "content_hash": self.content_hash,
        }

    def render_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


class PairedRerankPolicyEvaluator:
    """Evaluate one matched control/treatment policy pair conservatively."""

    def __init__(
        self,
        config: PairedPolicyEvaluationConfig | None = None,
    ) -> None:
        if config is not None and not isinstance(
            config,
            PairedPolicyEvaluationConfig,
        ):
            raise PairedRerankPolicyEvaluationValidationError(
                "config must be a PairedPolicyEvaluationConfig"
            )
        self.config = config or PairedPolicyEvaluationConfig()

    def evaluate(
        self,
        trials: Sequence[PairedRerankPolicyTrial],
    ) -> PairedRerankPolicyEvaluation:
        normalized = tuple(trials)
        if not normalized:
            raise PairedRerankPolicyEvaluationValidationError(
                "evaluation requires at least one paired trial"
            )
        if any(not isinstance(item, PairedRerankPolicyTrial) for item in normalized):
            raise PairedRerankPolicyEvaluationValidationError(
                "trials must contain PairedRerankPolicyTrial values"
            )

        by_id: dict[UUID, PairedRerankPolicyTrial] = {}
        for item in normalized:
            existing = by_id.get(item.trial_id)
            if existing is None:
                by_id[item.trial_id] = item
            elif existing != item:
                raise PairedRerankPolicyEvaluationValidationError(
                    "conflicting trial_id immutable content"
                )
        ordered = tuple(by_id[key] for key in sorted(by_id, key=str))
        first = ordered[0]
        for item in ordered[1:]:
            if item.space_id != first.space_id:
                raise PairedRerankPolicyEvaluationValidationError("all trials must share one space")
            if item.control_batch.policy_fingerprint != first.control_batch.policy_fingerprint:
                raise PairedRerankPolicyEvaluationValidationError(
                    "all trials must share one control policy"
                )
            if item.treatment_batch.policy_fingerprint != first.treatment_batch.policy_fingerprint:
                raise PairedRerankPolicyEvaluationValidationError(
                    "all trials must share one treatment policy"
                )
            if item.control_batch.policy_version != first.control_batch.policy_version:
                raise PairedRerankPolicyEvaluationValidationError(
                    "all trials must share one control policy version"
                )
            if item.treatment_batch.policy_version != first.treatment_batch.policy_version:
                raise PairedRerankPolicyEvaluationValidationError(
                    "all trials must share one treatment policy version"
                )
            if item.continuation_set_hash != first.continuation_set_hash:
                raise PairedRerankPolicyEvaluationValidationError(
                    "all trials must share one continuation contract"
                )

        score_deltas = [item.score_delta for item in ordered]
        success_deltas = [item.success_delta for item in ordered]
        token_deltas = [item.token_delta for item in ordered]
        latency_deltas = [item.latency_delta_ms for item in ordered]
        trial_count = len(ordered)
        mean_score_delta = _mean(score_deltas)
        score_standard_deviation = stdev(score_deltas) if trial_count > 1 else 0.0
        score_standard_error = score_standard_deviation / sqrt(trial_count)
        score_confidence_lower = mean_score_delta - self.config.confidence_z * score_standard_error
        score_confidence_upper = mean_score_delta + self.config.confidence_z * score_standard_error
        mean_success_delta = _mean(success_deltas)
        mean_token_delta = _mean(token_deltas)
        mean_latency_delta_ms = _mean(latency_deltas)
        total_control_tokens = sum(item.control_outcome.tokens for item in ordered)
        total_control_latency = sum(item.control_outcome.latency_ms for item in ordered)
        token_increase_ratio = sum(token_deltas) / max(
            total_control_tokens,
            1,
        )
        latency_increase_ratio = sum(latency_deltas) / max(
            total_control_latency,
            1.0,
        )
        treatment_top_change_rate = _mean([float(item.treatment_top_changed) for item in ordered])
        total_treatment_candidates = sum(item.treatment_candidate_count for item in ordered)
        treatment_applied_observation_rate = sum(
            item.treatment_applied_observation_count for item in ordered
        ) / max(total_treatment_candidates, 1)
        treatment_mean_absolute_adjustment = _mean(
            [item.treatment_absolute_adjustment for item in ordered]
        )

        verdict, abstention_reason = self._verdict(
            trial_count=trial_count,
            standard_error=score_standard_error,
            confidence_lower=score_confidence_lower,
            confidence_upper=score_confidence_upper,
            mean_success_delta=mean_success_delta,
            token_increase_ratio=token_increase_ratio,
            latency_increase_ratio=latency_increase_ratio,
        )
        config_fingerprint = fingerprint_paired_policy_evaluation_config(self.config)
        context_collection_hash = _hash_payload(
            {"context_hashes": sorted(item.context_set_hash for item in ordered)}
        )
        aggregate_payload = {
            "space_id": str(first.space_id),
            "control_policy_version": first.control_batch.policy_version,
            "control_policy_fingerprint": (first.control_batch.policy_fingerprint),
            "treatment_policy_version": (first.treatment_batch.policy_version),
            "treatment_policy_fingerprint": (first.treatment_batch.policy_fingerprint),
            "continuation_set_hash": first.continuation_set_hash,
            "context_collection_hash": context_collection_hash,
            "trial_count": trial_count,
            "mean_score_delta": mean_score_delta,
            "score_standard_deviation": score_standard_deviation,
            "score_standard_error": score_standard_error,
            "score_confidence_lower": score_confidence_lower,
            "score_confidence_upper": score_confidence_upper,
            "mean_success_delta": mean_success_delta,
            "mean_token_delta": mean_token_delta,
            "mean_latency_delta_ms": mean_latency_delta_ms,
            "token_increase_ratio": token_increase_ratio,
            "latency_increase_ratio": latency_increase_ratio,
            "treatment_top_change_rate": treatment_top_change_rate,
            "treatment_applied_observation_rate": (treatment_applied_observation_rate),
            "treatment_mean_absolute_adjustment": (treatment_mean_absolute_adjustment),
            "verdict": verdict.value,
            "abstention_reason": (
                abstention_reason.value if abstention_reason is not None else None
            ),
            "config_version": self.config.policy_version,
            "config_fingerprint": config_fingerprint,
            "trial_ids": [str(item.trial_id) for item in ordered],
            "trial_content_hashes": [item.content_hash for item in ordered],
        }
        content_hash = _hash_payload(aggregate_payload)
        evaluation_id = uuid5(
            NAMESPACE_URL,
            f"{_SCHEMA}:{content_hash}",
        )
        return PairedRerankPolicyEvaluation(
            id=evaluation_id,
            space_id=first.space_id,
            control_policy_version=first.control_batch.policy_version,
            control_policy_fingerprint=(first.control_batch.policy_fingerprint),
            treatment_policy_version=(first.treatment_batch.policy_version),
            treatment_policy_fingerprint=(first.treatment_batch.policy_fingerprint),
            continuation_set_hash=first.continuation_set_hash,
            context_collection_hash=context_collection_hash,
            trial_count=trial_count,
            mean_score_delta=mean_score_delta,
            score_standard_deviation=score_standard_deviation,
            score_standard_error=score_standard_error,
            score_confidence_lower=score_confidence_lower,
            score_confidence_upper=score_confidence_upper,
            mean_success_delta=mean_success_delta,
            mean_token_delta=mean_token_delta,
            mean_latency_delta_ms=mean_latency_delta_ms,
            token_increase_ratio=token_increase_ratio,
            latency_increase_ratio=latency_increase_ratio,
            treatment_top_change_rate=treatment_top_change_rate,
            treatment_applied_observation_rate=(treatment_applied_observation_rate),
            treatment_mean_absolute_adjustment=(treatment_mean_absolute_adjustment),
            verdict=verdict,
            abstention_reason=abstention_reason,
            config_version=self.config.policy_version,
            config_fingerprint=config_fingerprint,
            trial_ids=tuple(item.trial_id for item in ordered),
            content_hash=content_hash,
        )

    def _verdict(
        self,
        *,
        trial_count: int,
        standard_error: float,
        confidence_lower: float,
        confidence_upper: float,
        mean_success_delta: float,
        token_increase_ratio: float,
        latency_increase_ratio: float,
    ) -> tuple[PairedPolicyVerdict, PairedPolicyAbstentionReason | None]:
        if trial_count < self.config.minimum_pairs:
            return (
                PairedPolicyVerdict.INSUFFICIENT_EVIDENCE,
                PairedPolicyAbstentionReason.INSUFFICIENT_PAIRS,
            )
        if standard_error > self.config.maximum_standard_error:
            return (
                PairedPolicyVerdict.INSUFFICIENT_EVIDENCE,
                PairedPolicyAbstentionReason.STANDARD_ERROR_TOO_HIGH,
            )
        if confidence_upper <= self.config.harmful_effect_threshold:
            return PairedPolicyVerdict.HARMFUL, None

        resource_limits_pass = (
            token_increase_ratio <= self.config.maximum_token_increase_ratio
            and latency_increase_ratio <= self.config.maximum_latency_increase_ratio
        )
        if not resource_limits_pass and confidence_lower < self.config.minimum_promising_effect:
            return PairedPolicyVerdict.TOO_COSTLY, None
        if (
            confidence_lower >= self.config.minimum_promising_effect
            and mean_success_delta >= self.config.minimum_success_delta
            and resource_limits_pass
        ):
            return PairedPolicyVerdict.PROMISING, None
        if (
            confidence_lower >= -self.config.neutral_effect_band
            and confidence_upper <= self.config.neutral_effect_band
            and resource_limits_pass
        ):
            return PairedPolicyVerdict.NEUTRAL, None
        return PairedPolicyVerdict.INCONCLUSIVE, None


def fingerprint_paired_policy_evaluation_config(
    config: PairedPolicyEvaluationConfig,
) -> str:
    """Hash every policy-evaluation threshold that changes behavior."""

    if not isinstance(config, PairedPolicyEvaluationConfig):
        raise PairedRerankPolicyEvaluationValidationError(
            "config must be a PairedPolicyEvaluationConfig"
        )
    return _hash_payload(
        {
            "minimum_pairs": config.minimum_pairs,
            "confidence_z": config.confidence_z,
            "minimum_promising_effect": config.minimum_promising_effect,
            "harmful_effect_threshold": config.harmful_effect_threshold,
            "neutral_effect_band": config.neutral_effect_band,
            "maximum_standard_error": config.maximum_standard_error,
            "maximum_token_increase_ratio": (config.maximum_token_increase_ratio),
            "maximum_latency_increase_ratio": (config.maximum_latency_increase_ratio),
            "minimum_success_delta": config.minimum_success_delta,
            "policy_version": config.policy_version,
        }
    )


def _outcome_payload(outcome: OutcomeMeasurement) -> dict[str, Any]:
    return {
        "score": outcome.score,
        "task_success": outcome.task_success,
        "tokens": outcome.tokens,
        "latency_ms": outcome.latency_ms,
    }


def _mean(values: Sequence[float | int]) -> float:
    if not values:
        raise PairedRerankPolicyEvaluationValidationError("mean requires at least one value")
    return sum(float(value) for value in values) / len(values)


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= _SCORE_TOLERANCE


def _require_uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise PairedRerankPolicyEvaluationValidationError(f"{name} must be a UUID")


def _require_hash(name: str, value: object) -> None:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise PairedRerankPolicyEvaluationValidationError(
            f"{name} must be a lowercase SHA-256 hex digest"
        )


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise PairedRerankPolicyEvaluationValidationError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise PairedRerankPolicyEvaluationValidationError(f"{name} must not be empty")
    return normalized


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PairedRerankPolicyEvaluationValidationError(f"{name} must be a finite number")
    normalized = float(value)
    if not isfinite(normalized):
        raise PairedRerankPolicyEvaluationValidationError(f"{name} must be a finite number")
    return normalized


def _positive_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized <= 0.0:
        raise PairedRerankPolicyEvaluationValidationError(f"{name} must be positive")
    return normalized


def _nonnegative_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized < 0.0:
        raise PairedRerankPolicyEvaluationValidationError(f"{name} must be non-negative")
    return normalized


def _bounded_delta(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if not -1.0 <= normalized <= 1.0:
        raise PairedRerankPolicyEvaluationValidationError(
            f"{name} must be between minus one and one"
        )
    return normalized


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PairedRerankPolicyEvaluationValidationError(f"{name} must be a positive integer")
    return value
