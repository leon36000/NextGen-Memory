"""Pure deterministic advisory gate for bounded policy-promotion evidence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from uuid import NAMESPACE_URL, UUID, uuid5

from .paired_rerank_policy_evaluation import PairedPolicyVerdict

_SCHEMA = "nextgen-memory-advisory-policy-promotion-gate-v0"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class PolicyPromotionValidationError(ValueError):
    """Promotion evidence violates a bounded immutable contract."""


class PolicyPromotionDecision(StrEnum):
    """Advisory outcome; none of these values performs an activation."""

    PROMOTE = "promote"
    HOLD = "hold"
    REJECT = "reject"


class PolicyPromotionReason(StrEnum):
    """Bounded machine-readable reasons in fixed evaluation precedence."""

    SAFETY_VIOLATION = "safety_violation"
    CURRENT_POLICY_IDENTITY_MISMATCH = "current_policy_identity_mismatch"
    CANDIDATE_POLICY_IDENTITY_MISMATCH = "candidate_policy_identity_mismatch"
    REGISTRY_EVALUATION_MISMATCH = "registry_evaluation_mismatch"
    HARMFUL_VERDICT = "harmful_verdict"
    TOO_COSTLY_VERDICT = "too_costly_verdict"
    NEGATIVE_MEAN_EFFECT = "negative_mean_effect"
    TOKEN_COST_EXCEEDED = "token_cost_exceeded"
    LATENCY_COST_EXCEEDED = "latency_cost_exceeded"
    HARM_RATE_EXCEEDED = "harm_rate_exceeded"

    INSUFFICIENT_MATCHED_PAIRS = "insufficient_matched_pairs"
    NON_POSITIVE_CONFIDENCE_LOWER_BOUND = "non_positive_confidence_lower_bound"
    STANDARD_ERROR_EXCEEDED = "standard_error_exceeded"
    EVIDENCE_STALE = "evidence_stale"
    REGISTRY_INCOMPLETE = "registry_incomplete"
    ROLLBACK_NOT_READY = "rollback_not_ready"
    TESTS_INCOMPLETE = "tests_incomplete"
    INTEGRATION_INCOMPLETE = "integration_incomplete"
    ARTIFACT_INTEGRITY_MISSING = "artifact_integrity_missing"
    REVIEWERS_INSUFFICIENT = "reviewers_insufficient"
    INSUFFICIENT_EVIDENCE_VERDICT = "insufficient_evidence_verdict"
    NEUTRAL_VERDICT = "neutral_verdict"
    INCONCLUSIVE_VERDICT = "inconclusive_verdict"

    ALL_GATES_PASSED = "all_gates_passed"


@dataclass(frozen=True, slots=True)
class PolicyIdentity:
    """Versioned policy identity bound to one immutable source commit."""

    policy_version: str
    policy_fingerprint: str
    source_sha: str
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        policy_version = _identifier("policy_version", self.policy_version)
        _sha256("policy_fingerprint", self.policy_fingerprint)
        _git_sha("source_sha", self.source_sha)
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "source_sha": self.source_sha,
        }


@dataclass(frozen=True, slots=True)
class PairedPolicyEvidence:
    """Statistical and registry evidence produced by a matched evaluation."""

    evaluation_id: UUID
    evaluation_content_hash: str
    control_policy_version: str
    control_policy_fingerprint: str
    treatment_policy_version: str
    treatment_policy_fingerprint: str
    evaluated_base_sha: str
    evaluated_candidate_sha: str
    verdict: PairedPolicyVerdict
    matched_pair_count: int
    mean_score_effect: float
    score_confidence_lower_bound: float
    score_confidence_upper_bound: float
    score_standard_error: float
    mean_token_delta: float
    mean_latency_delta_ms: float
    harm_rate: float
    registry_summary_content_hash: str
    registry_pair_count: int
    registry_completed_trial_count: int
    registry_failed_count: int
    registry_cancelled_count: int
    registry_active_count: int
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _uuid("evaluation_id", self.evaluation_id)
        _sha256("evaluation_content_hash", self.evaluation_content_hash)
        control_version = _identifier("control_policy_version", self.control_policy_version)
        treatment_version = _identifier("treatment_policy_version", self.treatment_policy_version)
        _sha256("control_policy_fingerprint", self.control_policy_fingerprint)
        _sha256("treatment_policy_fingerprint", self.treatment_policy_fingerprint)
        if self.control_policy_fingerprint == self.treatment_policy_fingerprint:
            raise PolicyPromotionValidationError(
                "control and treatment fingerprints must be distinct"
            )
        _git_sha("evaluated_base_sha", self.evaluated_base_sha)
        _git_sha("evaluated_candidate_sha", self.evaluated_candidate_sha)
        if not isinstance(self.verdict, PairedPolicyVerdict):
            raise PolicyPromotionValidationError("verdict must be a PairedPolicyVerdict")

        matched_pair_count = _nonnegative_integer("matched_pair_count", self.matched_pair_count)
        mean_score_effect = _finite_number("mean_score_effect", self.mean_score_effect)
        lower = _finite_number(
            "score_confidence_lower_bound",
            self.score_confidence_lower_bound,
        )
        upper = _finite_number(
            "score_confidence_upper_bound",
            self.score_confidence_upper_bound,
        )
        if lower > mean_score_effect or mean_score_effect > upper:
            raise PolicyPromotionValidationError(
                "score confidence interval must contain the mean effect"
            )
        standard_error = _nonnegative_number("score_standard_error", self.score_standard_error)
        mean_token_delta = _finite_number("mean_token_delta", self.mean_token_delta)
        mean_latency_delta_ms = _finite_number("mean_latency_delta_ms", self.mean_latency_delta_ms)
        harm_rate = _bounded_rate("harm_rate", self.harm_rate)
        _sha256(
            "registry_summary_content_hash",
            self.registry_summary_content_hash,
        )
        registry_pair_count = _nonnegative_integer("registry_pair_count", self.registry_pair_count)
        registry_completed_trial_count = _nonnegative_integer(
            "registry_completed_trial_count",
            self.registry_completed_trial_count,
        )
        registry_failed_count = _nonnegative_integer(
            "registry_failed_count", self.registry_failed_count
        )
        registry_cancelled_count = _nonnegative_integer(
            "registry_cancelled_count", self.registry_cancelled_count
        )
        registry_active_count = _nonnegative_integer(
            "registry_active_count", self.registry_active_count
        )
        if (
            registry_completed_trial_count
            + registry_failed_count
            + registry_cancelled_count
            + registry_active_count
            != registry_pair_count
        ):
            raise PolicyPromotionValidationError(
                "registry state counts must partition registry_pair_count"
            )

        object.__setattr__(self, "control_policy_version", control_version)
        object.__setattr__(self, "treatment_policy_version", treatment_version)
        object.__setattr__(self, "matched_pair_count", matched_pair_count)
        object.__setattr__(self, "mean_score_effect", mean_score_effect)
        object.__setattr__(self, "score_confidence_lower_bound", lower)
        object.__setattr__(self, "score_confidence_upper_bound", upper)
        object.__setattr__(self, "score_standard_error", standard_error)
        object.__setattr__(self, "mean_token_delta", mean_token_delta)
        object.__setattr__(self, "mean_latency_delta_ms", mean_latency_delta_ms)
        object.__setattr__(self, "harm_rate", harm_rate)
        object.__setattr__(self, "registry_pair_count", registry_pair_count)
        object.__setattr__(
            self,
            "registry_completed_trial_count",
            registry_completed_trial_count,
        )
        object.__setattr__(self, "registry_failed_count", registry_failed_count)
        object.__setattr__(self, "registry_cancelled_count", registry_cancelled_count)
        object.__setattr__(self, "registry_active_count", registry_active_count)
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "evaluation_id": str(self.evaluation_id),
            "evaluation_content_hash": self.evaluation_content_hash,
            "control_policy_version": self.control_policy_version,
            "control_policy_fingerprint": self.control_policy_fingerprint,
            "treatment_policy_version": self.treatment_policy_version,
            "treatment_policy_fingerprint": (self.treatment_policy_fingerprint),
            "evaluated_base_sha": self.evaluated_base_sha,
            "evaluated_candidate_sha": self.evaluated_candidate_sha,
            "verdict": self.verdict.value,
            "matched_pair_count": self.matched_pair_count,
            "mean_score_effect": self.mean_score_effect,
            "score_confidence_lower_bound": (self.score_confidence_lower_bound),
            "score_confidence_upper_bound": (self.score_confidence_upper_bound),
            "score_standard_error": self.score_standard_error,
            "mean_token_delta": self.mean_token_delta,
            "mean_latency_delta_ms": self.mean_latency_delta_ms,
            "harm_rate": self.harm_rate,
            "registry_summary_content_hash": (self.registry_summary_content_hash),
            "registry_pair_count": self.registry_pair_count,
            "registry_completed_trial_count": (self.registry_completed_trial_count),
            "registry_failed_count": self.registry_failed_count,
            "registry_cancelled_count": self.registry_cancelled_count,
            "registry_active_count": self.registry_active_count,
        }


@dataclass(frozen=True, slots=True)
class PolicyOperationalReadiness:
    """Bounded operational evidence supplied without consulting a runtime."""

    tests_passed: bool
    integration_passed: bool
    artifact_integrity_passed: bool
    rollback_ready: bool
    safety_violation: bool
    reviewer_count: int
    evidence_age_seconds: float
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "tests_passed",
            "integration_passed",
            "artifact_integrity_passed",
            "rollback_ready",
            "safety_violation",
        ):
            if not isinstance(getattr(self, name), bool):
                raise PolicyPromotionValidationError(f"{name} must be a boolean")
        reviewer_count = _nonnegative_integer("reviewer_count", self.reviewer_count)
        evidence_age_seconds = _nonnegative_number(
            "evidence_age_seconds", self.evidence_age_seconds
        )
        object.__setattr__(self, "reviewer_count", reviewer_count)
        object.__setattr__(self, "evidence_age_seconds", evidence_age_seconds)
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "tests_passed": self.tests_passed,
            "integration_passed": self.integration_passed,
            "artifact_integrity_passed": self.artifact_integrity_passed,
            "rollback_ready": self.rollback_ready,
            "safety_violation": self.safety_violation,
            "reviewer_count": self.reviewer_count,
            "evidence_age_seconds": self.evidence_age_seconds,
        }


@dataclass(frozen=True, slots=True)
class PolicyPromotionGateConfig:
    """Versioned thresholds for the advisory gate."""

    minimum_matched_pairs: int
    minimum_score_lower_bound: float
    maximum_score_standard_error: float
    maximum_mean_token_delta: float
    maximum_mean_latency_delta_ms: float
    maximum_harm_rate: float
    maximum_evidence_age_seconds: float
    minimum_reviewer_count: int
    gate_policy_version: str = "advisory-policy-promotion-gate-v0"
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        minimum_matched_pairs = _positive_integer(
            "minimum_matched_pairs", self.minimum_matched_pairs
        )
        minimum_score_lower_bound = _finite_number(
            "minimum_score_lower_bound", self.minimum_score_lower_bound
        )
        maximum_score_standard_error = _positive_number(
            "maximum_score_standard_error",
            self.maximum_score_standard_error,
        )
        maximum_mean_token_delta = _nonnegative_number(
            "maximum_mean_token_delta", self.maximum_mean_token_delta
        )
        maximum_mean_latency_delta_ms = _nonnegative_number(
            "maximum_mean_latency_delta_ms",
            self.maximum_mean_latency_delta_ms,
        )
        maximum_harm_rate = _bounded_rate("maximum_harm_rate", self.maximum_harm_rate)
        maximum_evidence_age_seconds = _positive_number(
            "maximum_evidence_age_seconds",
            self.maximum_evidence_age_seconds,
        )
        minimum_reviewer_count = _nonnegative_integer(
            "minimum_reviewer_count", self.minimum_reviewer_count
        )
        gate_policy_version = _identifier("gate_policy_version", self.gate_policy_version)

        object.__setattr__(self, "minimum_matched_pairs", minimum_matched_pairs)
        object.__setattr__(
            self,
            "minimum_score_lower_bound",
            minimum_score_lower_bound,
        )
        object.__setattr__(
            self,
            "maximum_score_standard_error",
            maximum_score_standard_error,
        )
        object.__setattr__(self, "maximum_mean_token_delta", maximum_mean_token_delta)
        object.__setattr__(
            self,
            "maximum_mean_latency_delta_ms",
            maximum_mean_latency_delta_ms,
        )
        object.__setattr__(self, "maximum_harm_rate", maximum_harm_rate)
        object.__setattr__(
            self,
            "maximum_evidence_age_seconds",
            maximum_evidence_age_seconds,
        )
        object.__setattr__(self, "minimum_reviewer_count", minimum_reviewer_count)
        object.__setattr__(self, "gate_policy_version", gate_policy_version)
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "minimum_matched_pairs": self.minimum_matched_pairs,
            "minimum_score_lower_bound": self.minimum_score_lower_bound,
            "maximum_score_standard_error": (self.maximum_score_standard_error),
            "maximum_mean_token_delta": self.maximum_mean_token_delta,
            "maximum_mean_latency_delta_ms": (self.maximum_mean_latency_delta_ms),
            "maximum_harm_rate": self.maximum_harm_rate,
            "maximum_evidence_age_seconds": (self.maximum_evidence_age_seconds),
            "minimum_reviewer_count": self.minimum_reviewer_count,
            "gate_policy_version": self.gate_policy_version,
        }


@dataclass(frozen=True, slots=True)
class PolicyPromotionRequest:
    """Complete immutable input bundle for one advisory decision."""

    current_policy: PolicyIdentity
    candidate_policy: PolicyIdentity
    evaluation: PairedPolicyEvidence
    readiness: PolicyOperationalReadiness
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.current_policy, PolicyIdentity):
            raise PolicyPromotionValidationError("current_policy must be a PolicyIdentity")
        if not isinstance(self.candidate_policy, PolicyIdentity):
            raise PolicyPromotionValidationError("candidate_policy must be a PolicyIdentity")
        if not isinstance(self.evaluation, PairedPolicyEvidence):
            raise PolicyPromotionValidationError("evaluation must be PairedPolicyEvidence")
        if not isinstance(self.readiness, PolicyOperationalReadiness):
            raise PolicyPromotionValidationError("readiness must be PolicyOperationalReadiness")
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "current_policy": self.current_policy.to_dict(),
            "current_policy_content_hash": self.current_policy.content_hash,
            "candidate_policy": self.candidate_policy.to_dict(),
            "candidate_policy_content_hash": (self.candidate_policy.content_hash),
            "evaluation": self.evaluation.to_dict(),
            "evaluation_evidence_content_hash": self.evaluation.content_hash,
            "readiness": self.readiness.to_dict(),
            "readiness_content_hash": self.readiness.content_hash,
        }


@dataclass(frozen=True, slots=True)
class PolicyPromotionRecord:
    """Canonical advisory record; it has no execution capability."""

    decision: PolicyPromotionDecision
    reasons: tuple[PolicyPromotionReason, ...]
    request_content_hash: str
    config_content_hash: str
    current_policy_content_hash: str
    candidate_policy_content_hash: str
    evaluation_evidence_content_hash: str
    readiness_content_hash: str
    advisory_only: bool = True
    id: UUID = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.decision, PolicyPromotionDecision):
            raise PolicyPromotionValidationError("decision must be a PolicyPromotionDecision")
        reasons = tuple(self.reasons)
        if not reasons or any(not isinstance(reason, PolicyPromotionReason) for reason in reasons):
            raise PolicyPromotionValidationError(
                "reasons must contain bounded PolicyPromotionReason values"
            )
        if len(reasons) != len(set(reasons)):
            raise PolicyPromotionValidationError("reasons must not contain duplicates")
        for name in (
            "request_content_hash",
            "config_content_hash",
            "current_policy_content_hash",
            "candidate_policy_content_hash",
            "evaluation_evidence_content_hash",
            "readiness_content_hash",
        ):
            _sha256(name, getattr(self, name))
        if self.advisory_only is not True:
            raise PolicyPromotionValidationError("promotion records must remain advisory only")
        object.__setattr__(self, "reasons", reasons)
        payload = self._identity_payload()
        content_hash = _hash_payload(payload)
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(
            self,
            "id",
            uuid5(NAMESPACE_URL, f"{_SCHEMA}:record:{content_hash}"),
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "decision": self.decision.value,
            "reasons": [reason.value for reason in self.reasons],
            "request_content_hash": self.request_content_hash,
            "config_content_hash": self.config_content_hash,
            "current_policy_content_hash": (self.current_policy_content_hash),
            "candidate_policy_content_hash": (self.candidate_policy_content_hash),
            "evaluation_evidence_content_hash": (self.evaluation_evidence_content_hash),
            "readiness_content_hash": self.readiness_content_hash,
            "advisory_only": self.advisory_only,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "id": str(self.id),
            "content_hash": self.content_hash,
        }

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


class AdvisoryPolicyPromotionGate:
    """Evaluate immutable evidence without activating or persisting a policy."""

    __slots__ = ()

    def evaluate(
        self,
        request: PolicyPromotionRequest,
        config: PolicyPromotionGateConfig,
    ) -> PolicyPromotionRecord:
        if not isinstance(request, PolicyPromotionRequest):
            raise PolicyPromotionValidationError("request must be a PolicyPromotionRequest")
        if not isinstance(config, PolicyPromotionGateConfig):
            raise PolicyPromotionValidationError("config must be a PolicyPromotionGateConfig")

        evidence = request.evaluation
        readiness = request.readiness
        current = request.current_policy
        candidate = request.candidate_policy

        reject_reasons: list[PolicyPromotionReason] = []
        if readiness.safety_violation:
            reject_reasons.append(PolicyPromotionReason.SAFETY_VIOLATION)
        if not _matches_control_identity(current, evidence):
            reject_reasons.append(PolicyPromotionReason.CURRENT_POLICY_IDENTITY_MISMATCH)
        if candidate.content_hash == current.content_hash or not _matches_treatment_identity(
            candidate, evidence
        ):
            reject_reasons.append(PolicyPromotionReason.CANDIDATE_POLICY_IDENTITY_MISMATCH)
        if evidence.registry_completed_trial_count != evidence.matched_pair_count:
            reject_reasons.append(PolicyPromotionReason.REGISTRY_EVALUATION_MISMATCH)
        if evidence.verdict is PairedPolicyVerdict.HARMFUL:
            reject_reasons.append(PolicyPromotionReason.HARMFUL_VERDICT)
        if evidence.verdict is PairedPolicyVerdict.TOO_COSTLY:
            reject_reasons.append(PolicyPromotionReason.TOO_COSTLY_VERDICT)
        if evidence.mean_score_effect < 0.0:
            reject_reasons.append(PolicyPromotionReason.NEGATIVE_MEAN_EFFECT)
        if evidence.mean_token_delta > config.maximum_mean_token_delta:
            reject_reasons.append(PolicyPromotionReason.TOKEN_COST_EXCEEDED)
        if evidence.mean_latency_delta_ms > config.maximum_mean_latency_delta_ms:
            reject_reasons.append(PolicyPromotionReason.LATENCY_COST_EXCEEDED)
        if evidence.harm_rate > config.maximum_harm_rate:
            reject_reasons.append(PolicyPromotionReason.HARM_RATE_EXCEEDED)

        if reject_reasons:
            return _record(
                PolicyPromotionDecision.REJECT,
                reject_reasons,
                request,
                config,
            )

        hold_reasons: list[PolicyPromotionReason] = []
        if evidence.matched_pair_count < config.minimum_matched_pairs:
            hold_reasons.append(PolicyPromotionReason.INSUFFICIENT_MATCHED_PAIRS)
        if evidence.score_confidence_lower_bound <= config.minimum_score_lower_bound:
            hold_reasons.append(PolicyPromotionReason.NON_POSITIVE_CONFIDENCE_LOWER_BOUND)
        if evidence.score_standard_error > config.maximum_score_standard_error:
            hold_reasons.append(PolicyPromotionReason.STANDARD_ERROR_EXCEEDED)
        if readiness.evidence_age_seconds > config.maximum_evidence_age_seconds:
            hold_reasons.append(PolicyPromotionReason.EVIDENCE_STALE)
        if (
            evidence.registry_active_count > 0
            or evidence.registry_failed_count > 0
            or evidence.registry_cancelled_count > 0
        ):
            hold_reasons.append(PolicyPromotionReason.REGISTRY_INCOMPLETE)
        if not readiness.rollback_ready:
            hold_reasons.append(PolicyPromotionReason.ROLLBACK_NOT_READY)
        if not readiness.tests_passed:
            hold_reasons.append(PolicyPromotionReason.TESTS_INCOMPLETE)
        if not readiness.integration_passed:
            hold_reasons.append(PolicyPromotionReason.INTEGRATION_INCOMPLETE)
        if not readiness.artifact_integrity_passed:
            hold_reasons.append(PolicyPromotionReason.ARTIFACT_INTEGRITY_MISSING)
        if readiness.reviewer_count < config.minimum_reviewer_count:
            hold_reasons.append(PolicyPromotionReason.REVIEWERS_INSUFFICIENT)
        if evidence.verdict is PairedPolicyVerdict.INSUFFICIENT_EVIDENCE:
            hold_reasons.append(PolicyPromotionReason.INSUFFICIENT_EVIDENCE_VERDICT)
        elif evidence.verdict is PairedPolicyVerdict.NEUTRAL:
            hold_reasons.append(PolicyPromotionReason.NEUTRAL_VERDICT)
        elif evidence.verdict is PairedPolicyVerdict.INCONCLUSIVE:
            hold_reasons.append(PolicyPromotionReason.INCONCLUSIVE_VERDICT)

        if hold_reasons:
            return _record(
                PolicyPromotionDecision.HOLD,
                hold_reasons,
                request,
                config,
            )
        if evidence.verdict is not PairedPolicyVerdict.PROMISING:
            raise PolicyPromotionValidationError(
                "unsupported evaluator verdict escaped bounded precedence"
            )
        return _record(
            PolicyPromotionDecision.PROMOTE,
            [PolicyPromotionReason.ALL_GATES_PASSED],
            request,
            config,
        )


def _matches_control_identity(
    identity: PolicyIdentity,
    evidence: PairedPolicyEvidence,
) -> bool:
    return (
        evidence.control_policy_version == identity.policy_version
        and evidence.control_policy_fingerprint == identity.policy_fingerprint
        and evidence.evaluated_base_sha == identity.source_sha
    )


def _matches_treatment_identity(
    identity: PolicyIdentity,
    evidence: PairedPolicyEvidence,
) -> bool:
    return (
        evidence.treatment_policy_version == identity.policy_version
        and evidence.treatment_policy_fingerprint == identity.policy_fingerprint
        and evidence.evaluated_candidate_sha == identity.source_sha
    )


def _record(
    decision: PolicyPromotionDecision,
    reasons: list[PolicyPromotionReason],
    request: PolicyPromotionRequest,
    config: PolicyPromotionGateConfig,
) -> PolicyPromotionRecord:
    return PolicyPromotionRecord(
        decision=decision,
        reasons=tuple(reasons),
        request_content_hash=request.content_hash,
        config_content_hash=config.content_hash,
        current_policy_content_hash=request.current_policy.content_hash,
        candidate_policy_content_hash=request.candidate_policy.content_hash,
        evaluation_evidence_content_hash=request.evaluation.content_hash,
        readiness_content_hash=request.readiness.content_hash,
    )


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


def _identifier(name: str, value: object) -> str:
    if not isinstance(value, str) or _IDENTIFIER_RE.fullmatch(value) is None:
        raise PolicyPromotionValidationError(f"{name} must be a bounded policy identifier")
    return value


def _sha256(name: str, value: object) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise PolicyPromotionValidationError(f"{name} must be a lowercase SHA-256 value")
    return value


def _git_sha(name: str, value: object) -> str:
    if not isinstance(value, str) or _GIT_SHA_RE.fullmatch(value) is None:
        raise PolicyPromotionValidationError(f"{name} must be a lowercase 40-character Git SHA")
    return value


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise PolicyPromotionValidationError(f"{name} must be a UUID")
    return value


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PolicyPromotionValidationError(f"{name} must be a positive integer")
    return value


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PolicyPromotionValidationError(f"{name} must be a non-negative integer")
    return value


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyPromotionValidationError(f"{name} must be a finite number")
    normalized = float(value)
    if not isfinite(normalized):
        raise PolicyPromotionValidationError(f"{name} must be a finite number")
    return normalized


def _positive_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized <= 0.0:
        raise PolicyPromotionValidationError(f"{name} must be a positive finite number")
    return normalized


def _nonnegative_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized < 0.0:
        raise PolicyPromotionValidationError(f"{name} must be a non-negative finite number")
    return normalized


def _bounded_rate(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized < 0.0 or normalized > 1.0:
        raise PolicyPromotionValidationError(f"{name} must be a finite rate in [0, 1]")
    return normalized


__all__ = [
    "AdvisoryPolicyPromotionGate",
    "PairedPolicyEvidence",
    "PolicyIdentity",
    "PolicyOperationalReadiness",
    "PolicyPromotionDecision",
    "PolicyPromotionGateConfig",
    "PolicyPromotionReason",
    "PolicyPromotionRecord",
    "PolicyPromotionRequest",
    "PolicyPromotionValidationError",
]
