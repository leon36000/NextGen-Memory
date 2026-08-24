"""Deterministic advisory decisions for bounded policy promotion evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from .paired_rerank_policy_evaluation import PairedPolicyVerdict

_SCHEMA = "nextgen-memory-policy-promotion-gate-v0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MAX_TEXT_LENGTH = 128
_MAX_SIGNAL_VALUES = 64
_MAX_COUNT = 2**63 - 1


class PolicyPromotionValidationError(ValueError):
    """The gate configuration or an internal decision is invalid."""


class PolicyPromotionDisposition(StrEnum):
    """One advisory result from normalized promotion evidence."""

    PROMOTE = "promote"
    HOLD = "hold"
    REJECT = "reject"


class PolicyPromotionReason(StrEnum):
    """Bounded reasons ordered by one explicit precedence table."""

    MALFORMED_EVIDENCE = "malformed_evidence"
    HARD_SAFETY_VIOLATION = "hard_safety_violation"
    IDENTITY_MISMATCH = "identity_mismatch"
    EVALUATOR_HARMFUL = "evaluator_harmful"
    EVALUATOR_TOO_COSTLY = "evaluator_too_costly"
    ESTABLISHED_NEGATIVE_EFFECT = "established_negative_effect"
    COST_LIMIT_EXCEEDED = "cost_limit_exceeded"
    HARM_RATE_EXCEEDED = "harm_rate_exceeded"
    EVALUATOR_INSUFFICIENT_EVIDENCE = "evaluator_insufficient_evidence"
    EVALUATOR_NEUTRAL = "evaluator_neutral"
    EVALUATOR_INCONCLUSIVE = "evaluator_inconclusive"
    INSUFFICIENT_TRIALS = "insufficient_trials"
    NONPOSITIVE_LOWER_BOUND = "nonpositive_lower_bound"
    UNCERTAINTY_TOO_HIGH = "uncertainty_too_high"
    STALE_EVIDENCE = "stale_evidence"
    ROLLBACK_NOT_READY = "rollback_not_ready"
    VERIFICATION_INCOMPLETE = "verification_incomplete"
    INSUFFICIENT_REVIEWERS = "insufficient_reviewers"
    ALL_REQUIREMENTS_SATISFIED = "all_requirements_satisfied"


class PolicyVerificationSignal(StrEnum):
    """Bounded operational evidence that can be required by the gate."""

    FOCUSED_TESTS = "focused_tests"
    FULL_TEST_SUITE = "full_test_suite"
    INTEGRATION_REHEARSAL = "integration_rehearsal"
    ARTIFACT_INTEGRITY = "artifact_integrity"
    ROLLBACK_REHEARSAL = "rollback_rehearsal"
    SECURITY_REVIEW = "security_review"


_REASON_PRECEDENCE = (
    PolicyPromotionReason.MALFORMED_EVIDENCE,
    PolicyPromotionReason.HARD_SAFETY_VIOLATION,
    PolicyPromotionReason.IDENTITY_MISMATCH,
    PolicyPromotionReason.EVALUATOR_HARMFUL,
    PolicyPromotionReason.EVALUATOR_TOO_COSTLY,
    PolicyPromotionReason.ESTABLISHED_NEGATIVE_EFFECT,
    PolicyPromotionReason.COST_LIMIT_EXCEEDED,
    PolicyPromotionReason.HARM_RATE_EXCEEDED,
    PolicyPromotionReason.EVALUATOR_INSUFFICIENT_EVIDENCE,
    PolicyPromotionReason.EVALUATOR_NEUTRAL,
    PolicyPromotionReason.EVALUATOR_INCONCLUSIVE,
    PolicyPromotionReason.INSUFFICIENT_TRIALS,
    PolicyPromotionReason.NONPOSITIVE_LOWER_BOUND,
    PolicyPromotionReason.UNCERTAINTY_TOO_HIGH,
    PolicyPromotionReason.STALE_EVIDENCE,
    PolicyPromotionReason.ROLLBACK_NOT_READY,
    PolicyPromotionReason.VERIFICATION_INCOMPLETE,
    PolicyPromotionReason.INSUFFICIENT_REVIEWERS,
    PolicyPromotionReason.ALL_REQUIREMENTS_SATISFIED,
)
_REASON_PRIORITY = {
    reason: position for position, reason in enumerate(_REASON_PRECEDENCE)
}
_REJECT_REASONS = frozenset(_REASON_PRECEDENCE[:8])
_HOLD_REASONS = frozenset(_REASON_PRECEDENCE[8:18])


@dataclass(frozen=True, slots=True)
class PolicyPromotionGateConfig:
    """Versioned thresholds for the pure advisory gate."""

    minimum_paired_trials: int = 16
    minimum_confidence_lower_bound: float = 0.0
    maximum_standard_error: float = 0.05
    maximum_mean_cost_delta: float = 0.05
    maximum_harm_rate: float = 0.01
    established_negative_effect_tolerance: float = 0.0
    policy_version: str = "policy-promotion-gate-v0"

    def __post_init__(self) -> None:
        minimum_paired_trials = _strict_positive_integer(
            "minimum_paired_trials",
            self.minimum_paired_trials,
        )
        minimum_confidence_lower_bound = _strict_nonnegative_number(
            "minimum_confidence_lower_bound",
            self.minimum_confidence_lower_bound,
        )
        maximum_standard_error = _strict_nonnegative_number(
            "maximum_standard_error",
            self.maximum_standard_error,
        )
        maximum_mean_cost_delta = _strict_nonnegative_number(
            "maximum_mean_cost_delta",
            self.maximum_mean_cost_delta,
        )
        maximum_harm_rate = _strict_nonnegative_number(
            "maximum_harm_rate",
            self.maximum_harm_rate,
        )
        if maximum_harm_rate > 1.0:
            raise PolicyPromotionValidationError(
                "maximum_harm_rate must be at most one"
            )
        negative_tolerance = _strict_nonnegative_number(
            "established_negative_effect_tolerance",
            self.established_negative_effect_tolerance,
        )
        policy_version = _strict_text("policy_version", self.policy_version)

        object.__setattr__(
            self,
            "minimum_paired_trials",
            minimum_paired_trials,
        )
        object.__setattr__(
            self,
            "minimum_confidence_lower_bound",
            minimum_confidence_lower_bound,
        )
        object.__setattr__(
            self,
            "maximum_standard_error",
            maximum_standard_error,
        )
        object.__setattr__(
            self,
            "maximum_mean_cost_delta",
            maximum_mean_cost_delta,
        )
        object.__setattr__(self, "maximum_harm_rate", maximum_harm_rate)
        object.__setattr__(
            self,
            "established_negative_effect_tolerance",
            negative_tolerance,
        )
        object.__setattr__(self, "policy_version", policy_version)

    def to_dict(self) -> dict[str, object]:
        return {
            "minimum_paired_trials": self.minimum_paired_trials,
            "minimum_confidence_lower_bound": (
                self.minimum_confidence_lower_bound
            ),
            "maximum_standard_error": self.maximum_standard_error,
            "maximum_mean_cost_delta": self.maximum_mean_cost_delta,
            "maximum_harm_rate": self.maximum_harm_rate,
            "established_negative_effect_tolerance": (
                self.established_negative_effect_tolerance
            ),
            "policy_version": self.policy_version,
        }


def fingerprint_policy_promotion_config(
    config: PolicyPromotionGateConfig,
) -> str:
    """Return the canonical SHA-256 identity for one gate configuration."""

    if not isinstance(config, PolicyPromotionGateConfig):
        raise PolicyPromotionValidationError(
            "config must be a PolicyPromotionGateConfig"
        )
    return _hash_payload(config.to_dict())


@dataclass(frozen=True, slots=True)
class PolicyPromotionEvidence:
    """Untrusted normalized evidence supplied to the advisory gate."""

    space_id: UUID
    candidate_policy_id: UUID
    evaluated_policy_version: str
    current_policy_version: str
    evaluated_policy_fingerprint: str
    current_policy_fingerprint: str
    evaluation_id: UUID
    evaluation_content_hash: str
    context_collection_hash: str
    continuation_set_hash: str
    paired_trial_count: int
    mean_effect: float
    confidence_lower: float
    confidence_upper: float
    standard_error: float
    mean_cost_delta: float
    harm_rate: float
    evaluator_verdict: PairedPolicyVerdict
    evidence_at: datetime
    decision_at: datetime
    maximum_evidence_age_seconds: int
    rollback_plan_id: UUID
    rollback_plan_hash: str
    rollback_ready: bool
    required_signals: object
    passed_signals: object
    reviewer_count: int
    required_reviewer_count: int
    evaluated_base_sha: str
    current_base_sha: str
    evaluated_candidate_sha: str
    current_candidate_sha: str
    hard_safety_violation: bool


@dataclass(frozen=True, slots=True)
class PolicyPromotionSafeMetrics:
    """Only finite, bounded metrics safe to include in a decision."""

    paired_trial_count: int | None = None
    mean_effect: float | None = None
    confidence_lower: float | None = None
    confidence_upper: float | None = None
    standard_error: float | None = None
    mean_cost_delta: float | None = None
    harm_rate: float | None = None
    evidence_age_seconds: float | None = None
    maximum_evidence_age_seconds: int | None = None
    reviewer_count: int | None = None
    required_reviewer_count: int | None = None
    required_signal_count: int | None = None
    passed_required_signal_count: int | None = None
    missing_signal_count: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "paired_trial_count",
            "maximum_evidence_age_seconds",
            "reviewer_count",
            "required_reviewer_count",
            "required_signal_count",
            "passed_required_signal_count",
            "missing_signal_count",
        ):
            value = getattr(self, name)
            if value is not None:
                _decision_nonnegative_integer(name, value)
        for name in (
            "mean_effect",
            "confidence_lower",
            "confidence_upper",
            "standard_error",
            "mean_cost_delta",
            "harm_rate",
            "evidence_age_seconds",
        ):
            value = getattr(self, name)
            if value is not None:
                _decision_finite_number(name, value)
        if self.standard_error is not None and self.standard_error < 0.0:
            raise PolicyPromotionValidationError(
                "standard_error must be non-negative"
            )
        if self.harm_rate is not None and not 0.0 <= self.harm_rate <= 1.0:
            raise PolicyPromotionValidationError(
                "harm_rate must be between zero and one"
            )
        if (
            self.evidence_age_seconds is not None
            and self.evidence_age_seconds < 0.0
        ):
            raise PolicyPromotionValidationError(
                "evidence_age_seconds must be non-negative"
            )
        if (
            self.required_signal_count is not None
            and self.passed_required_signal_count is not None
            and self.passed_required_signal_count > self.required_signal_count
        ):
            raise PolicyPromotionValidationError(
                "passed_required_signal_count exceeds required_signal_count"
            )
        if (
            self.required_signal_count is not None
            and self.missing_signal_count is not None
            and self.passed_required_signal_count is not None
            and self.passed_required_signal_count + self.missing_signal_count
            != self.required_signal_count
        ):
            raise PolicyPromotionValidationError(
                "signal counts do not partition required signals"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "paired_trial_count": self.paired_trial_count,
            "mean_effect": self.mean_effect,
            "confidence_lower": self.confidence_lower,
            "confidence_upper": self.confidence_upper,
            "standard_error": self.standard_error,
            "mean_cost_delta": self.mean_cost_delta,
            "harm_rate": self.harm_rate,
            "evidence_age_seconds": self.evidence_age_seconds,
            "maximum_evidence_age_seconds": (
                self.maximum_evidence_age_seconds
            ),
            "reviewer_count": self.reviewer_count,
            "required_reviewer_count": self.required_reviewer_count,
            "required_signal_count": self.required_signal_count,
            "passed_required_signal_count": (
                self.passed_required_signal_count
            ),
            "missing_signal_count": self.missing_signal_count,
        }


@dataclass(frozen=True, slots=True)
class PolicyPromotionDecision:
    """One deterministic, immutable, privacy-safe advisory decision."""

    id: UUID
    disposition: PolicyPromotionDisposition
    reasons: tuple[PolicyPromotionReason, ...]
    invalid_fields: tuple[str, ...]
    missing_signals: tuple[PolicyVerificationSignal, ...]
    candidate_policy_id: UUID | None
    candidate_policy_version: str | None
    evaluation_id: UUID | None
    evaluation_content_hash: str | None
    current_base_sha: str | None
    current_candidate_sha: str | None
    evidence_fingerprint: str
    config_fingerprint: str
    metrics: PolicyPromotionSafeMetrics
    content_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, UUID):
            raise PolicyPromotionValidationError("id must be a UUID")
        if not isinstance(self.disposition, PolicyPromotionDisposition):
            raise PolicyPromotionValidationError(
                "disposition must be a PolicyPromotionDisposition"
            )
        reasons = tuple(self.reasons)
        if not reasons or any(
            not isinstance(reason, PolicyPromotionReason) for reason in reasons
        ):
            raise PolicyPromotionValidationError(
                "reasons must contain PolicyPromotionReason values"
            )
        if len(reasons) != len(set(reasons)):
            raise PolicyPromotionValidationError("reasons must be unique")
        if reasons != _ordered_reasons(set(reasons)):
            raise PolicyPromotionValidationError(
                "reasons must use deterministic precedence"
            )
        invalid_fields = tuple(self.invalid_fields)
        if invalid_fields != tuple(sorted(set(invalid_fields))):
            raise PolicyPromotionValidationError(
                "invalid_fields must be unique and sorted"
            )
        if any(
            not isinstance(name, str)
            or not name
            or len(name) > _MAX_TEXT_LENGTH
            for name in invalid_fields
        ):
            raise PolicyPromotionValidationError(
                "invalid_fields contains an invalid field name"
            )
        missing_signals = tuple(self.missing_signals)
        if any(
            not isinstance(signal, PolicyVerificationSignal)
            for signal in missing_signals
        ):
            raise PolicyPromotionValidationError(
                "missing_signals must contain PolicyVerificationSignal values"
            )
        expected_missing = tuple(
            sorted(set(missing_signals), key=lambda item: item.value)
        )
        if missing_signals != expected_missing:
            raise PolicyPromotionValidationError(
                "missing_signals must be unique and sorted"
            )
        if self.candidate_policy_id is not None and not isinstance(
            self.candidate_policy_id,
            UUID,
        ):
            raise PolicyPromotionValidationError(
                "candidate_policy_id must be a UUID or null"
            )
        if self.candidate_policy_version is not None:
            _strict_text(
                "candidate_policy_version",
                self.candidate_policy_version,
            )
        if self.evaluation_id is not None and not isinstance(
            self.evaluation_id,
            UUID,
        ):
            raise PolicyPromotionValidationError(
                "evaluation_id must be a UUID or null"
            )
        if self.evaluation_content_hash is not None:
            _decision_hash(
                "evaluation_content_hash",
                self.evaluation_content_hash,
                _SHA256_RE,
            )
        if self.current_base_sha is not None:
            _decision_hash("current_base_sha", self.current_base_sha, _GIT_SHA_RE)
        if self.current_candidate_sha is not None:
            _decision_hash(
                "current_candidate_sha",
                self.current_candidate_sha,
                _GIT_SHA_RE,
            )
        _decision_hash(
            "evidence_fingerprint",
            self.evidence_fingerprint,
            _SHA256_RE,
        )
        _decision_hash(
            "config_fingerprint",
            self.config_fingerprint,
            _SHA256_RE,
        )
        if not isinstance(self.metrics, PolicyPromotionSafeMetrics):
            raise PolicyPromotionValidationError(
                "metrics must be PolicyPromotionSafeMetrics"
            )
        _decision_hash("content_hash", self.content_hash, _SHA256_RE)
        self._validate_disposition_contract(
            reasons,
            invalid_fields,
            missing_signals,
        )
        expected_hash = _hash_payload(self._identity_payload())
        if self.content_hash != expected_hash:
            raise PolicyPromotionValidationError(
                "content_hash does not match immutable decision content"
            )
        expected_id = uuid5(
            NAMESPACE_URL,
            f"{_SCHEMA}:{self.content_hash}",
        )
        if self.id != expected_id:
            raise PolicyPromotionValidationError(
                "id does not match immutable decision content"
            )
        object.__setattr__(self, "reasons", reasons)
        object.__setattr__(self, "invalid_fields", invalid_fields)
        object.__setattr__(self, "missing_signals", missing_signals)

    def _validate_disposition_contract(
        self,
        reasons: tuple[PolicyPromotionReason, ...],
        invalid_fields: tuple[str, ...],
        missing_signals: tuple[PolicyVerificationSignal, ...],
    ) -> None:
        if self.disposition is PolicyPromotionDisposition.PROMOTE:
            if reasons != (
                PolicyPromotionReason.ALL_REQUIREMENTS_SATISFIED,
            ):
                raise PolicyPromotionValidationError(
                    "promote requires all_requirements_satisfied"
                )
            if invalid_fields or missing_signals:
                raise PolicyPromotionValidationError(
                    "promote cannot carry invalid fields or missing signals"
                )
            return
        if self.disposition is PolicyPromotionDisposition.HOLD:
            if any(reason not in _HOLD_REASONS for reason in reasons):
                raise PolicyPromotionValidationError(
                    "hold contains a non-hold reason"
                )
            if invalid_fields:
                raise PolicyPromotionValidationError(
                    "hold cannot carry invalid fields"
                )
            return
        if any(reason not in _REJECT_REASONS for reason in reasons):
            raise PolicyPromotionValidationError(
                "reject contains a non-reject reason"
            )
        malformed = reasons == (PolicyPromotionReason.MALFORMED_EVIDENCE,)
        if malformed != bool(invalid_fields):
            raise PolicyPromotionValidationError(
                "malformed reject and invalid_fields disagree"
            )
        if missing_signals:
            raise PolicyPromotionValidationError(
                "reject cannot carry hold-only missing signals"
            )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "disposition": self.disposition.value,
            "reasons": [reason.value for reason in self.reasons],
            "invalid_fields": list(self.invalid_fields),
            "missing_signals": [
                signal.value for signal in self.missing_signals
            ],
            "candidate_policy_id": (
                str(self.candidate_policy_id)
                if self.candidate_policy_id is not None
                else None
            ),
            "candidate_policy_version": self.candidate_policy_version,
            "evaluation_id": (
                str(self.evaluation_id)
                if self.evaluation_id is not None
                else None
            ),
            "evaluation_content_hash": self.evaluation_content_hash,
            "current_base_sha": self.current_base_sha,
            "current_candidate_sha": self.current_candidate_sha,
            "evidence_fingerprint": self.evidence_fingerprint,
            "config_fingerprint": self.config_fingerprint,
            "metrics": self.metrics.to_dict(),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "id": str(self.id),
            "content_hash": self.content_hash,
        }

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class _NormalizedEvidence:
    space_id: UUID
    candidate_policy_id: UUID
    evaluated_policy_version: str
    current_policy_version: str
    evaluated_policy_fingerprint: str
    current_policy_fingerprint: str
    evaluation_id: UUID
    evaluation_content_hash: str
    context_collection_hash: str
    continuation_set_hash: str
    paired_trial_count: int
    mean_effect: float
    confidence_lower: float
    confidence_upper: float
    standard_error: float
    mean_cost_delta: float
    harm_rate: float
    evaluator_verdict: PairedPolicyVerdict
    evidence_at: datetime
    decision_at: datetime
    evidence_age_seconds: float
    maximum_evidence_age_seconds: int
    rollback_plan_id: UUID
    rollback_plan_hash: str
    rollback_ready: bool
    required_signals: tuple[PolicyVerificationSignal, ...]
    passed_signals: tuple[PolicyVerificationSignal, ...]
    reviewer_count: int
    required_reviewer_count: int
    evaluated_base_sha: str
    current_base_sha: str
    evaluated_candidate_sha: str
    current_candidate_sha: str
    hard_safety_violation: bool

    @property
    def missing_signals(self) -> tuple[PolicyVerificationSignal, ...]:
        return tuple(
            signal
            for signal in self.required_signals
            if signal not in self.passed_signals
        )

    @property
    def identity_drift(self) -> bool:
        return any(
            (
                self.evaluated_policy_version != self.current_policy_version,
                self.evaluated_policy_fingerprint
                != self.current_policy_fingerprint,
                self.evaluated_base_sha != self.current_base_sha,
                self.evaluated_candidate_sha != self.current_candidate_sha,
            )
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "space_id": str(self.space_id),
            "candidate_policy_id": str(self.candidate_policy_id),
            "evaluated_policy_version": self.evaluated_policy_version,
            "current_policy_version": self.current_policy_version,
            "evaluated_policy_fingerprint": (
                self.evaluated_policy_fingerprint
            ),
            "current_policy_fingerprint": self.current_policy_fingerprint,
            "evaluation_id": str(self.evaluation_id),
            "evaluation_content_hash": self.evaluation_content_hash,
            "context_collection_hash": self.context_collection_hash,
            "continuation_set_hash": self.continuation_set_hash,
            "paired_trial_count": self.paired_trial_count,
            "mean_effect": self.mean_effect,
            "confidence_lower": self.confidence_lower,
            "confidence_upper": self.confidence_upper,
            "standard_error": self.standard_error,
            "mean_cost_delta": self.mean_cost_delta,
            "harm_rate": self.harm_rate,
            "evaluator_verdict": self.evaluator_verdict.value,
            "evidence_at": _canonical_datetime(self.evidence_at),
            "decision_at": _canonical_datetime(self.decision_at),
            "maximum_evidence_age_seconds": (
                self.maximum_evidence_age_seconds
            ),
            "rollback_plan_id": str(self.rollback_plan_id),
            "rollback_plan_hash": self.rollback_plan_hash,
            "rollback_ready": self.rollback_ready,
            "required_signals": [
                signal.value for signal in self.required_signals
            ],
            "passed_signals": [
                signal.value for signal in self.passed_signals
            ],
            "reviewer_count": self.reviewer_count,
            "required_reviewer_count": self.required_reviewer_count,
            "evaluated_base_sha": self.evaluated_base_sha,
            "current_base_sha": self.current_base_sha,
            "evaluated_candidate_sha": self.evaluated_candidate_sha,
            "current_candidate_sha": self.current_candidate_sha,
            "hard_safety_violation": self.hard_safety_violation,
        }


@dataclass(frozen=True, slots=True)
class _NormalizationOutcome:
    normalized: _NormalizedEvidence | None
    invalid_fields: tuple[str, ...]
    evidence_fingerprint: str
    metrics: PolicyPromotionSafeMetrics
    candidate_policy_id: UUID | None
    candidate_policy_version: str | None
    evaluation_id: UUID | None
    evaluation_content_hash: str | None
    current_base_sha: str | None
    current_candidate_sha: str | None


class DeterministicPolicyPromotionGate:
    """Evaluate supplied evidence without persistence or activation."""

    __slots__ = ("config", "config_fingerprint")

    def __init__(
        self,
        config: PolicyPromotionGateConfig | None = None,
    ) -> None:
        if config is not None and not isinstance(
            config,
            PolicyPromotionGateConfig,
        ):
            raise PolicyPromotionValidationError(
                "config must be a PolicyPromotionGateConfig or null"
            )
        self.config = config or PolicyPromotionGateConfig()
        self.config_fingerprint = fingerprint_policy_promotion_config(
            self.config
        )

    def evaluate(self, evidence: PolicyPromotionEvidence) -> PolicyPromotionDecision:
        outcome = _normalize_evidence(evidence)
        if outcome.normalized is None:
            return _build_decision(
                disposition=PolicyPromotionDisposition.REJECT,
                reasons=(PolicyPromotionReason.MALFORMED_EVIDENCE,),
                invalid_fields=outcome.invalid_fields,
                missing_signals=(),
                outcome=outcome,
                config_fingerprint=self.config_fingerprint,
            )

        normalized = outcome.normalized
        reject_reasons: set[PolicyPromotionReason] = set()
        if normalized.hard_safety_violation:
            reject_reasons.add(
                PolicyPromotionReason.HARD_SAFETY_VIOLATION
            )
        if normalized.identity_drift:
            reject_reasons.add(PolicyPromotionReason.IDENTITY_MISMATCH)
        if normalized.evaluator_verdict is PairedPolicyVerdict.HARMFUL:
            reject_reasons.add(PolicyPromotionReason.EVALUATOR_HARMFUL)
        if normalized.evaluator_verdict is PairedPolicyVerdict.TOO_COSTLY:
            reject_reasons.add(PolicyPromotionReason.EVALUATOR_TOO_COSTLY)
        if normalized.confidence_upper < -(
            self.config.established_negative_effect_tolerance
        ):
            reject_reasons.add(
                PolicyPromotionReason.ESTABLISHED_NEGATIVE_EFFECT
            )
        if normalized.mean_cost_delta > self.config.maximum_mean_cost_delta:
            reject_reasons.add(
                PolicyPromotionReason.COST_LIMIT_EXCEEDED
            )
        if normalized.harm_rate > self.config.maximum_harm_rate:
            reject_reasons.add(PolicyPromotionReason.HARM_RATE_EXCEEDED)

        if reject_reasons:
            return _build_decision(
                disposition=PolicyPromotionDisposition.REJECT,
                reasons=_ordered_reasons(reject_reasons),
                invalid_fields=(),
                missing_signals=(),
                outcome=outcome,
                config_fingerprint=self.config_fingerprint,
            )

        hold_reasons: set[PolicyPromotionReason] = set()
        verdict_reason = _hold_reason_for_verdict(
            normalized.evaluator_verdict
        )
        if verdict_reason is not None:
            hold_reasons.add(verdict_reason)
        if normalized.paired_trial_count < self.config.minimum_paired_trials:
            hold_reasons.add(PolicyPromotionReason.INSUFFICIENT_TRIALS)
        if normalized.confidence_lower <= (
            self.config.minimum_confidence_lower_bound
        ):
            hold_reasons.add(
                PolicyPromotionReason.NONPOSITIVE_LOWER_BOUND
            )
        if normalized.standard_error > self.config.maximum_standard_error:
            hold_reasons.add(
                PolicyPromotionReason.UNCERTAINTY_TOO_HIGH
            )
        if normalized.evidence_age_seconds > (
            normalized.maximum_evidence_age_seconds
        ):
            hold_reasons.add(PolicyPromotionReason.STALE_EVIDENCE)
        if not normalized.rollback_ready:
            hold_reasons.add(PolicyPromotionReason.ROLLBACK_NOT_READY)
        if normalized.missing_signals:
            hold_reasons.add(
                PolicyPromotionReason.VERIFICATION_INCOMPLETE
            )
        if normalized.reviewer_count < normalized.required_reviewer_count:
            hold_reasons.add(
                PolicyPromotionReason.INSUFFICIENT_REVIEWERS
            )

        if hold_reasons:
            return _build_decision(
                disposition=PolicyPromotionDisposition.HOLD,
                reasons=_ordered_reasons(hold_reasons),
                invalid_fields=(),
                missing_signals=normalized.missing_signals,
                outcome=outcome,
                config_fingerprint=self.config_fingerprint,
            )

        if normalized.evaluator_verdict is not PairedPolicyVerdict.PROMISING:
            raise PolicyPromotionValidationError(
                "normalized evaluator verdict has no decision mapping"
            )
        return _build_decision(
            disposition=PolicyPromotionDisposition.PROMOTE,
            reasons=(PolicyPromotionReason.ALL_REQUIREMENTS_SATISFIED,),
            invalid_fields=(),
            missing_signals=(),
            outcome=outcome,
            config_fingerprint=self.config_fingerprint,
        )


def _normalize_evidence(evidence: object) -> _NormalizationOutcome:
    if not isinstance(evidence, PolicyPromotionEvidence):
        return _NormalizationOutcome(
            normalized=None,
            invalid_fields=("evidence",),
            evidence_fingerprint=_hash_payload(
                {"evidence": _sanitize_untrusted(evidence)}
            ),
            metrics=PolicyPromotionSafeMetrics(),
            candidate_policy_id=None,
            candidate_policy_version=None,
            evaluation_id=None,
            evaluation_content_hash=None,
            current_base_sha=None,
            current_candidate_sha=None,
        )

    invalid: set[str] = set()
    space_id = _normalize_uuid("space_id", evidence.space_id, invalid)
    candidate_policy_id = _normalize_uuid(
        "candidate_policy_id",
        evidence.candidate_policy_id,
        invalid,
    )
    evaluated_policy_version = _normalize_text(
        "evaluated_policy_version",
        evidence.evaluated_policy_version,
        invalid,
    )
    current_policy_version = _normalize_text(
        "current_policy_version",
        evidence.current_policy_version,
        invalid,
    )
    evaluated_policy_fingerprint = _normalize_hash(
        "evaluated_policy_fingerprint",
        evidence.evaluated_policy_fingerprint,
        _SHA256_RE,
        invalid,
    )
    current_policy_fingerprint = _normalize_hash(
        "current_policy_fingerprint",
        evidence.current_policy_fingerprint,
        _SHA256_RE,
        invalid,
    )
    evaluation_id = _normalize_uuid(
        "evaluation_id",
        evidence.evaluation_id,
        invalid,
    )
    evaluation_content_hash = _normalize_hash(
        "evaluation_content_hash",
        evidence.evaluation_content_hash,
        _SHA256_RE,
        invalid,
    )
    context_collection_hash = _normalize_hash(
        "context_collection_hash",
        evidence.context_collection_hash,
        _SHA256_RE,
        invalid,
    )
    continuation_set_hash = _normalize_hash(
        "continuation_set_hash",
        evidence.continuation_set_hash,
        _SHA256_RE,
        invalid,
    )
    paired_trial_count = _normalize_integer(
        "paired_trial_count",
        evidence.paired_trial_count,
        minimum=0,
        invalid=invalid,
    )
    mean_effect = _normalize_number(
        "mean_effect",
        evidence.mean_effect,
        invalid=invalid,
    )
    confidence_lower = _normalize_number(
        "confidence_lower",
        evidence.confidence_lower,
        invalid=invalid,
    )
    confidence_upper = _normalize_number(
        "confidence_upper",
        evidence.confidence_upper,
        invalid=invalid,
    )
    standard_error = _normalize_number(
        "standard_error",
        evidence.standard_error,
        minimum=0.0,
        invalid=invalid,
    )
    mean_cost_delta = _normalize_number(
        "mean_cost_delta",
        evidence.mean_cost_delta,
        invalid=invalid,
    )
    harm_rate = _normalize_number(
        "harm_rate",
        evidence.harm_rate,
        minimum=0.0,
        maximum=1.0,
        invalid=invalid,
    )
    evaluator_verdict = _normalize_verdict(
        "evaluator_verdict",
        evidence.evaluator_verdict,
        invalid,
    )
    evidence_at = _normalize_datetime(
        "evidence_at",
        evidence.evidence_at,
        invalid,
    )
    decision_at = _normalize_datetime(
        "decision_at",
        evidence.decision_at,
        invalid,
    )
    maximum_age = _normalize_integer(
        "maximum_evidence_age_seconds",
        evidence.maximum_evidence_age_seconds,
        minimum=1,
        invalid=invalid,
    )
    rollback_plan_id = _normalize_uuid(
        "rollback_plan_id",
        evidence.rollback_plan_id,
        invalid,
    )
    rollback_plan_hash = _normalize_hash(
        "rollback_plan_hash",
        evidence.rollback_plan_hash,
        _SHA256_RE,
        invalid,
    )
    rollback_ready = _normalize_boolean(
        "rollback_ready",
        evidence.rollback_ready,
        invalid,
    )
    required_signals = _normalize_signals(
        "required_signals",
        evidence.required_signals,
        invalid,
    )
    passed_signals = _normalize_signals(
        "passed_signals",
        evidence.passed_signals,
        invalid,
    )
    reviewer_count = _normalize_integer(
        "reviewer_count",
        evidence.reviewer_count,
        minimum=0,
        invalid=invalid,
    )
    required_reviewer_count = _normalize_integer(
        "required_reviewer_count",
        evidence.required_reviewer_count,
        minimum=1,
        invalid=invalid,
    )
    evaluated_base_sha = _normalize_hash(
        "evaluated_base_sha",
        evidence.evaluated_base_sha,
        _GIT_SHA_RE,
        invalid,
    )
    current_base_sha = _normalize_hash(
        "current_base_sha",
        evidence.current_base_sha,
        _GIT_SHA_RE,
        invalid,
    )
    evaluated_candidate_sha = _normalize_hash(
        "evaluated_candidate_sha",
        evidence.evaluated_candidate_sha,
        _GIT_SHA_RE,
        invalid,
    )
    current_candidate_sha = _normalize_hash(
        "current_candidate_sha",
        evidence.current_candidate_sha,
        _GIT_SHA_RE,
        invalid,
    )
    hard_safety_violation = _normalize_boolean(
        "hard_safety_violation",
        evidence.hard_safety_violation,
        invalid,
    )

    if (
        confidence_lower is not None
        and mean_effect is not None
        and confidence_upper is not None
        and not confidence_lower <= mean_effect <= confidence_upper
    ):
        invalid.add("confidence_interval")
    evidence_age_seconds: float | None = None
    if evidence_at is not None and decision_at is not None:
        if decision_at < evidence_at:
            invalid.add("evidence_time_order")
        else:
            evidence_age_seconds = (
                decision_at - evidence_at
            ).total_seconds()

    required_count = (
        len(required_signals) if required_signals is not None else None
    )
    passed_required_count: int | None = None
    missing_count: int | None = None
    if required_signals is not None and passed_signals is not None:
        passed_required_count = sum(
            signal in passed_signals for signal in required_signals
        )
        missing_count = required_count - passed_required_count
    metrics = PolicyPromotionSafeMetrics(
        paired_trial_count=paired_trial_count,
        mean_effect=mean_effect,
        confidence_lower=confidence_lower,
        confidence_upper=confidence_upper,
        standard_error=standard_error,
        mean_cost_delta=mean_cost_delta,
        harm_rate=harm_rate,
        evidence_age_seconds=evidence_age_seconds,
        maximum_evidence_age_seconds=maximum_age,
        reviewer_count=reviewer_count,
        required_reviewer_count=required_reviewer_count,
        required_signal_count=required_count,
        passed_required_signal_count=passed_required_count,
        missing_signal_count=missing_count,
    )

    if invalid:
        fingerprint = _hash_payload(
            {
                "schema": _SCHEMA,
                "malformed_evidence": _sanitize_evidence(evidence),
            }
        )
        return _NormalizationOutcome(
            normalized=None,
            invalid_fields=tuple(sorted(invalid)),
            evidence_fingerprint=fingerprint,
            metrics=metrics,
            candidate_policy_id=candidate_policy_id,
            candidate_policy_version=current_policy_version,
            evaluation_id=evaluation_id,
            evaluation_content_hash=evaluation_content_hash,
            current_base_sha=current_base_sha,
            current_candidate_sha=current_candidate_sha,
        )

    normalized = _NormalizedEvidence(
        space_id=_required_normalized("space_id", space_id),
        candidate_policy_id=_required_normalized(
            "candidate_policy_id",
            candidate_policy_id,
        ),
        evaluated_policy_version=_required_normalized(
            "evaluated_policy_version",
            evaluated_policy_version,
        ),
        current_policy_version=_required_normalized(
            "current_policy_version",
            current_policy_version,
        ),
        evaluated_policy_fingerprint=_required_normalized(
            "evaluated_policy_fingerprint",
            evaluated_policy_fingerprint,
        ),
        current_policy_fingerprint=_required_normalized(
            "current_policy_fingerprint",
            current_policy_fingerprint,
        ),
        evaluation_id=_required_normalized("evaluation_id", evaluation_id),
        evaluation_content_hash=_required_normalized(
            "evaluation_content_hash",
            evaluation_content_hash,
        ),
        context_collection_hash=_required_normalized(
            "context_collection_hash",
            context_collection_hash,
        ),
        continuation_set_hash=_required_normalized(
            "continuation_set_hash",
            continuation_set_hash,
        ),
        paired_trial_count=_required_normalized(
            "paired_trial_count",
            paired_trial_count,
        ),
        mean_effect=_required_normalized("mean_effect", mean_effect),
        confidence_lower=_required_normalized(
            "confidence_lower",
            confidence_lower,
        ),
        confidence_upper=_required_normalized(
            "confidence_upper",
            confidence_upper,
        ),
        standard_error=_required_normalized(
            "standard_error",
            standard_error,
        ),
        mean_cost_delta=_required_normalized(
            "mean_cost_delta",
            mean_cost_delta,
        ),
        harm_rate=_required_normalized("harm_rate", harm_rate),
        evaluator_verdict=_required_normalized(
            "evaluator_verdict",
            evaluator_verdict,
        ),
        evidence_at=_required_normalized("evidence_at", evidence_at),
        decision_at=_required_normalized("decision_at", decision_at),
        evidence_age_seconds=_required_normalized(
            "evidence_age_seconds",
            evidence_age_seconds,
        ),
        maximum_evidence_age_seconds=_required_normalized(
            "maximum_evidence_age_seconds",
            maximum_age,
        ),
        rollback_plan_id=_required_normalized(
            "rollback_plan_id",
            rollback_plan_id,
        ),
        rollback_plan_hash=_required_normalized(
            "rollback_plan_hash",
            rollback_plan_hash,
        ),
        rollback_ready=_required_normalized(
            "rollback_ready",
            rollback_ready,
        ),
        required_signals=_required_normalized(
            "required_signals",
            required_signals,
        ),
        passed_signals=_required_normalized(
            "passed_signals",
            passed_signals,
        ),
        reviewer_count=_required_normalized(
            "reviewer_count",
            reviewer_count,
        ),
        required_reviewer_count=_required_normalized(
            "required_reviewer_count",
            required_reviewer_count,
        ),
        evaluated_base_sha=_required_normalized(
            "evaluated_base_sha",
            evaluated_base_sha,
        ),
        current_base_sha=_required_normalized(
            "current_base_sha",
            current_base_sha,
        ),
        evaluated_candidate_sha=_required_normalized(
            "evaluated_candidate_sha",
            evaluated_candidate_sha,
        ),
        current_candidate_sha=_required_normalized(
            "current_candidate_sha",
            current_candidate_sha,
        ),
        hard_safety_violation=_required_normalized(
            "hard_safety_violation",
            hard_safety_violation,
        ),
    )
    return _NormalizationOutcome(
        normalized=normalized,
        invalid_fields=(),
        evidence_fingerprint=_hash_payload(normalized.to_dict()),
        metrics=metrics,
        candidate_policy_id=normalized.candidate_policy_id,
        candidate_policy_version=normalized.current_policy_version,
        evaluation_id=normalized.evaluation_id,
        evaluation_content_hash=normalized.evaluation_content_hash,
        current_base_sha=normalized.current_base_sha,
        current_candidate_sha=normalized.current_candidate_sha,
    )


def _build_decision(
    *,
    disposition: PolicyPromotionDisposition,
    reasons: tuple[PolicyPromotionReason, ...],
    invalid_fields: tuple[str, ...],
    missing_signals: tuple[PolicyVerificationSignal, ...],
    outcome: _NormalizationOutcome,
    config_fingerprint: str,
) -> PolicyPromotionDecision:
    payload = {
        "schema": _SCHEMA,
        "disposition": disposition.value,
        "reasons": [reason.value for reason in reasons],
        "invalid_fields": list(invalid_fields),
        "missing_signals": [signal.value for signal in missing_signals],
        "candidate_policy_id": (
            str(outcome.candidate_policy_id)
            if outcome.candidate_policy_id is not None
            else None
        ),
        "candidate_policy_version": outcome.candidate_policy_version,
        "evaluation_id": (
            str(outcome.evaluation_id)
            if outcome.evaluation_id is not None
            else None
        ),
        "evaluation_content_hash": outcome.evaluation_content_hash,
        "current_base_sha": outcome.current_base_sha,
        "current_candidate_sha": outcome.current_candidate_sha,
        "evidence_fingerprint": outcome.evidence_fingerprint,
        "config_fingerprint": config_fingerprint,
        "metrics": outcome.metrics.to_dict(),
    }
    content_hash = _hash_payload(payload)
    decision_id = uuid5(NAMESPACE_URL, f"{_SCHEMA}:{content_hash}")
    return PolicyPromotionDecision(
        id=decision_id,
        disposition=disposition,
        reasons=reasons,
        invalid_fields=invalid_fields,
        missing_signals=missing_signals,
        candidate_policy_id=outcome.candidate_policy_id,
        candidate_policy_version=outcome.candidate_policy_version,
        evaluation_id=outcome.evaluation_id,
        evaluation_content_hash=outcome.evaluation_content_hash,
        current_base_sha=outcome.current_base_sha,
        current_candidate_sha=outcome.current_candidate_sha,
        evidence_fingerprint=outcome.evidence_fingerprint,
        config_fingerprint=config_fingerprint,
        metrics=outcome.metrics,
        content_hash=content_hash,
    )


def _hold_reason_for_verdict(
    verdict: PairedPolicyVerdict,
) -> PolicyPromotionReason | None:
    mapping = {
        PairedPolicyVerdict.INSUFFICIENT_EVIDENCE: (
            PolicyPromotionReason.EVALUATOR_INSUFFICIENT_EVIDENCE
        ),
        PairedPolicyVerdict.NEUTRAL: PolicyPromotionReason.EVALUATOR_NEUTRAL,
        PairedPolicyVerdict.INCONCLUSIVE: (
            PolicyPromotionReason.EVALUATOR_INCONCLUSIVE
        ),
    }
    return mapping.get(verdict)


def _ordered_reasons(
    reasons: set[PolicyPromotionReason],
) -> tuple[PolicyPromotionReason, ...]:
    return tuple(sorted(reasons, key=_REASON_PRIORITY.__getitem__))


def _normalize_uuid(
    name: str,
    value: object,
    invalid: set[str],
) -> UUID | None:
    if isinstance(value, UUID):
        return value
    invalid.add(name)
    return None


def _normalize_text(
    name: str,
    value: object,
    invalid: set[str],
) -> str | None:
    if not isinstance(value, str):
        invalid.add(name)
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_TEXT_LENGTH:
        invalid.add(name)
        return None
    return normalized


def _normalize_hash(
    name: str,
    value: object,
    pattern: re.Pattern[str],
    invalid: set[str],
) -> str | None:
    if isinstance(value, str) and pattern.fullmatch(value) is not None:
        return value
    invalid.add(name)
    return None


def _normalize_integer(
    name: str,
    value: object,
    *,
    minimum: int,
    invalid: set[str],
) -> int | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > _MAX_COUNT
    ):
        invalid.add(name)
        return None
    return value


def _normalize_number(
    name: str,
    value: object,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    invalid: set[str],
) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid.add(name)
        return None
    normalized = float(value)
    if not isfinite(normalized):
        invalid.add(name)
        return None
    if minimum is not None and normalized < minimum:
        invalid.add(name)
        return None
    if maximum is not None and normalized > maximum:
        invalid.add(name)
        return None
    return normalized


def _normalize_verdict(
    name: str,
    value: object,
    invalid: set[str],
) -> PairedPolicyVerdict | None:
    if isinstance(value, PairedPolicyVerdict):
        return value
    invalid.add(name)
    return None


def _normalize_datetime(
    name: str,
    value: object,
    invalid: set[str],
) -> datetime | None:
    if not isinstance(value, datetime):
        invalid.add(name)
        return None
    if value.tzinfo is None:
        invalid.add(name)
        return None
    try:
        offset = value.utcoffset()
    except Exception:
        invalid.add(name)
        return None
    if offset is None:
        invalid.add(name)
        return None
    return value.astimezone(UTC)


def _normalize_boolean(
    name: str,
    value: object,
    invalid: set[str],
) -> bool | None:
    if isinstance(value, bool):
        return value
    invalid.add(name)
    return None


def _normalize_signals(
    name: str,
    value: object,
    invalid: set[str],
) -> tuple[PolicyVerificationSignal, ...] | None:
    if isinstance(value, (str, bytes, bytearray, Mapping)) or not isinstance(
        value,
        (Sequence, Set),
    ):
        invalid.add(name)
        return None
    try:
        items = tuple(value)
    except Exception:
        invalid.add(name)
        return None
    if len(items) > _MAX_SIGNAL_VALUES or any(
        not isinstance(item, PolicyVerificationSignal) for item in items
    ):
        invalid.add(name)
        return None
    return tuple(sorted(set(items), key=lambda item: item.value))


def _sanitize_evidence(evidence: PolicyPromotionEvidence) -> dict[str, object]:
    return {
        name: _sanitize_untrusted(getattr(evidence, name))
        for name in (
            "space_id",
            "candidate_policy_id",
            "evaluated_policy_version",
            "current_policy_version",
            "evaluated_policy_fingerprint",
            "current_policy_fingerprint",
            "evaluation_id",
            "evaluation_content_hash",
            "context_collection_hash",
            "continuation_set_hash",
            "paired_trial_count",
            "mean_effect",
            "confidence_lower",
            "confidence_upper",
            "standard_error",
            "mean_cost_delta",
            "harm_rate",
            "evaluator_verdict",
            "evidence_at",
            "decision_at",
            "maximum_evidence_age_seconds",
            "rollback_plan_id",
            "rollback_plan_hash",
            "rollback_ready",
            "required_signals",
            "passed_signals",
            "reviewer_count",
            "required_reviewer_count",
            "evaluated_base_sha",
            "current_base_sha",
            "evaluated_candidate_sha",
            "current_candidate_sha",
            "hard_safety_violation",
        )
    }


def _sanitize_untrusted(value: object, *, depth: int = 0) -> object:
    if depth >= 8:
        return {"kind": "depth_limit"}
    if value is None:
        return {"kind": "null"}
    if isinstance(value, bool):
        return {"kind": "bool", "value": value}
    if isinstance(value, int):
        return {"kind": "int", "value": value}
    if isinstance(value, float):
        if isfinite(value):
            return {"kind": "float", "value": value}
        if value != value:
            tag = "nan"
        elif value > 0.0:
            tag = "positive_infinity"
        else:
            tag = "negative_infinity"
        return {"kind": "float", "value": tag}
    if isinstance(value, str):
        encoded = value.encode("utf-8")
        return {
            "kind": "text",
            "length": len(value),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        }
    if isinstance(value, bytes):
        return {
            "kind": "bytes",
            "length": len(value),
            "sha256": hashlib.sha256(value).hexdigest(),
        }
    if isinstance(value, UUID):
        return {"kind": "uuid", "value": value.hex}
    if isinstance(value, datetime):
        try:
            canonical = _canonical_datetime(value)
        except (ValueError, OverflowError):
            canonical = "invalid_datetime"
        return {"kind": "datetime", "value": canonical}
    if isinstance(value, StrEnum):
        return {
            "kind": "enum",
            "type": _safe_type_name(value),
            "value": _sanitize_untrusted(value.value, depth=depth + 1),
        }
    if isinstance(value, Mapping):
        entries = [
            {
                "key": _sanitize_untrusted(key, depth=depth + 1),
                "value": _sanitize_untrusted(item, depth=depth + 1),
            }
            for key, item in value.items()
        ]
        entries.sort(key=_canonical_json)
        return {"kind": "mapping", "items": entries}
    if isinstance(value, (list, tuple, set, frozenset)):
        items = [
            _sanitize_untrusted(item, depth=depth + 1)
            for item in tuple(value)[:_MAX_SIGNAL_VALUES]
        ]
        items.sort(key=_canonical_json)
        return {
            "kind": "collection",
            "type": _safe_type_name(value),
            "items": items,
            "truncated": len(value) > _MAX_SIGNAL_VALUES,
        }
    return {"kind": "unsupported", "type": _safe_type_name(value)}


def _safe_type_name(value: object) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _canonical_datetime(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _required_normalized(name: str, value: Any | None) -> Any:
    if value is None:
        raise PolicyPromotionValidationError(
            f"normalized field unexpectedly absent: {name}"
        )
    return value


def _strict_positive_integer(name: str, value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > _MAX_COUNT
    ):
        raise PolicyPromotionValidationError(
            f"{name} must be a positive integer"
        )
    return value


def _strict_nonnegative_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyPromotionValidationError(
            f"{name} must be a non-negative finite number"
        )
    normalized = float(value)
    if not isfinite(normalized) or normalized < 0.0:
        raise PolicyPromotionValidationError(
            f"{name} must be a non-negative finite number"
        )
    return normalized


def _strict_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise PolicyPromotionValidationError(f"{name} must be text")
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_TEXT_LENGTH:
        raise PolicyPromotionValidationError(
            f"{name} must be non-empty bounded text"
        )
    return normalized


def _decision_nonnegative_integer(name: str, value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > _MAX_COUNT
    ):
        raise PolicyPromotionValidationError(
            f"{name} must be a non-negative integer"
        )
    return value


def _decision_finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyPromotionValidationError(
            f"{name} must be a finite number"
        )
    normalized = float(value)
    if not isfinite(normalized):
        raise PolicyPromotionValidationError(
            f"{name} must be a finite number"
        )
    return normalized


def _decision_hash(
    name: str,
    value: object,
    pattern: re.Pattern[str],
) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PolicyPromotionValidationError(f"{name} has an invalid hash")
    return value


def _canonical_json(value: object) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _hash_payload(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


__all__ = [
    "DeterministicPolicyPromotionGate",
    "PolicyPromotionDecision",
    "PolicyPromotionDisposition",
    "PolicyPromotionEvidence",
    "PolicyPromotionGateConfig",
    "PolicyPromotionReason",
    "PolicyPromotionSafeMetrics",
    "PolicyPromotionValidationError",
    "PolicyVerificationSignal",
    "fingerprint_policy_promotion_config",
]
