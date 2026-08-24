"""Pure advisory promotion decisions for evaluated rerank policies.

The gate deliberately has no activation, persistence, clock, network, or
feedback-writing behavior.  It turns already-bounded immutable evidence into a
deterministic ``promote``, ``hold``, or ``reject`` recommendation.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from uuid import NAMESPACE_URL, UUID, uuid5

from .paired_rerank_policy_evaluation import PairedPolicyVerdict

_SCHEMA = "nextgen-memory-policy-promotion-gate-v0"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class PolicyPromotionValidationError(ValueError):
    """A gate configuration or evidence value violates the bounded contract."""


class PolicyPromotionDisposition(StrEnum):
    """Advisory outcome from the promotion gate."""

    PROMOTE = "promote"
    HOLD = "hold"
    REJECT = "reject"


class PolicyPromotionReason(StrEnum):
    """Bounded machine-readable reasons in canonical precedence order."""

    SECURITY_VIOLATION = "security_violation"
    CONTROL_POLICY_IDENTITY_DRIFT = "control_policy_identity_drift"
    TREATMENT_POLICY_IDENTITY_DRIFT = "treatment_policy_identity_drift"
    HARMFUL_EVALUATION = "harmful_evaluation"
    TOO_COSTLY_EVALUATION = "too_costly_evaluation"
    NEGATIVE_SCORE_EFFECT = "negative_score_effect"
    EXCESS_HARM_RATE = "excess_harm_rate"
    EXCESS_TOKEN_COST = "excess_token_cost"
    EXCESS_LATENCY_COST = "excess_latency_cost"
    INSUFFICIENT_PAIRS = "insufficient_pairs"
    NON_POSITIVE_SCORE_LOWER_BOUND = "non_positive_score_lower_bound"
    EXCESS_SCORE_UNCERTAINTY = "excess_score_uncertainty"
    STALE_EVIDENCE = "stale_evidence"
    ROLLBACK_NOT_READY = "rollback_not_ready"
    FOCUSED_TESTS_NOT_GREEN = "focused_tests_not_green"
    FULL_TESTS_NOT_GREEN = "full_tests_not_green"
    INTEGRATION_NOT_GREEN = "integration_not_green"
    ARTIFACT_INTEGRITY_NOT_VERIFIED = "artifact_integrity_not_verified"
    INSUFFICIENT_INDEPENDENT_REVIEWS = "insufficient_independent_reviews"
    EVALUATION_NOT_PROMISING = "evaluation_not_promising"


_REJECT_REASONS = frozenset(
    {
        PolicyPromotionReason.SECURITY_VIOLATION,
        PolicyPromotionReason.CONTROL_POLICY_IDENTITY_DRIFT,
        PolicyPromotionReason.TREATMENT_POLICY_IDENTITY_DRIFT,
        PolicyPromotionReason.HARMFUL_EVALUATION,
        PolicyPromotionReason.TOO_COSTLY_EVALUATION,
        PolicyPromotionReason.NEGATIVE_SCORE_EFFECT,
        PolicyPromotionReason.EXCESS_HARM_RATE,
        PolicyPromotionReason.EXCESS_TOKEN_COST,
        PolicyPromotionReason.EXCESS_LATENCY_COST,
    }
)
_REASON_ORDER = tuple(PolicyPromotionReason)


@dataclass(frozen=True, slots=True)
class PolicyPromotionGateConfig:
    """Immutable quantitative and operational promotion thresholds."""

    minimum_pairs: int
    minimum_score_lower_bound: float
    maximum_score_interval_width: float
    maximum_harm_rate: float
    maximum_token_delta: float
    maximum_latency_delta_ms: float
    maximum_evidence_age_seconds: int
    minimum_independent_reviewers: int
    gate_policy_version: str = "policy-promotion-gate-v0"
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        minimum_pairs = _positive_integer("minimum_pairs", self.minimum_pairs)
        minimum_lower_bound = _nonnegative_number(
            "minimum_score_lower_bound",
            self.minimum_score_lower_bound,
        )
        maximum_width = _positive_number(
            "maximum_score_interval_width",
            self.maximum_score_interval_width,
        )
        maximum_harm_rate = _rate("maximum_harm_rate", self.maximum_harm_rate)
        maximum_token_delta = _nonnegative_number(
            "maximum_token_delta",
            self.maximum_token_delta,
        )
        maximum_latency_delta_ms = _nonnegative_number(
            "maximum_latency_delta_ms",
            self.maximum_latency_delta_ms,
        )
        maximum_age = _positive_integer(
            "maximum_evidence_age_seconds",
            self.maximum_evidence_age_seconds,
        )
        minimum_reviewers = _positive_integer(
            "minimum_independent_reviewers",
            self.minimum_independent_reviewers,
        )
        version = _required_text("gate_policy_version", self.gate_policy_version)

        object.__setattr__(self, "minimum_pairs", minimum_pairs)
        object.__setattr__(
            self,
            "minimum_score_lower_bound",
            minimum_lower_bound,
        )
        object.__setattr__(self, "maximum_score_interval_width", maximum_width)
        object.__setattr__(self, "maximum_harm_rate", maximum_harm_rate)
        object.__setattr__(self, "maximum_token_delta", maximum_token_delta)
        object.__setattr__(
            self,
            "maximum_latency_delta_ms",
            maximum_latency_delta_ms,
        )
        object.__setattr__(self, "maximum_evidence_age_seconds", maximum_age)
        object.__setattr__(
            self,
            "minimum_independent_reviewers",
            minimum_reviewers,
        )
        object.__setattr__(self, "gate_policy_version", version)
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        """Return the canonical JSON-safe configuration payload."""

        return {
            "minimum_pairs": self.minimum_pairs,
            "minimum_score_lower_bound": self.minimum_score_lower_bound,
            "maximum_score_interval_width": self.maximum_score_interval_width,
            "maximum_harm_rate": self.maximum_harm_rate,
            "maximum_token_delta": self.maximum_token_delta,
            "maximum_latency_delta_ms": self.maximum_latency_delta_ms,
            "maximum_evidence_age_seconds": self.maximum_evidence_age_seconds,
            "minimum_independent_reviewers": self.minimum_independent_reviewers,
            "gate_policy_version": self.gate_policy_version,
        }


@dataclass(frozen=True, slots=True)
class PolicyPromotionEvidence:
    """Immutable statistical, identity, and readiness evidence for one policy."""

    evaluation_id: UUID
    evaluation_content_hash: str
    control_policy_version: str
    control_policy_fingerprint: str
    treatment_policy_version: str
    treatment_policy_fingerprint: str
    current_control_policy_fingerprint: str
    current_treatment_policy_fingerprint: str
    verdict: PairedPolicyVerdict
    pair_count: int
    mean_score_effect: float
    score_confidence_low: float
    score_confidence_high: float
    harm_rate: float
    mean_token_delta: float
    mean_latency_delta_ms: float
    evidence_age_seconds: int
    security_violation: bool
    rollback_ready: bool
    focused_tests_green: bool
    full_tests_green: bool
    integration_green: bool
    artifact_integrity_verified: bool
    independent_review_ids: tuple[UUID, ...]
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid("evaluation_id", self.evaluation_id)
        _require_hash("evaluation_content_hash", self.evaluation_content_hash)
        control_version = _required_text(
            "control_policy_version",
            self.control_policy_version,
        )
        treatment_version = _required_text(
            "treatment_policy_version",
            self.treatment_policy_version,
        )
        _require_hash(
            "control_policy_fingerprint",
            self.control_policy_fingerprint,
        )
        _require_hash(
            "treatment_policy_fingerprint",
            self.treatment_policy_fingerprint,
        )
        _require_hash(
            "current_control_policy_fingerprint",
            self.current_control_policy_fingerprint,
        )
        _require_hash(
            "current_treatment_policy_fingerprint",
            self.current_treatment_policy_fingerprint,
        )
        if self.control_policy_fingerprint == self.treatment_policy_fingerprint:
            raise PolicyPromotionValidationError(
                "control and treatment policy fingerprints must be distinct"
            )
        if not isinstance(self.verdict, PairedPolicyVerdict):
            raise PolicyPromotionValidationError(
                "verdict must be a PairedPolicyVerdict"
            )
        pair_count = _nonnegative_integer("pair_count", self.pair_count)
        mean_score_effect = _finite_number(
            "mean_score_effect",
            self.mean_score_effect,
        )
        confidence_low = _finite_number(
            "score_confidence_low",
            self.score_confidence_low,
        )
        confidence_high = _finite_number(
            "score_confidence_high",
            self.score_confidence_high,
        )
        if confidence_low > confidence_high:
            raise PolicyPromotionValidationError(
                "score confidence interval must be ordered"
            )
        if not confidence_low <= mean_score_effect <= confidence_high:
            raise PolicyPromotionValidationError(
                "mean_score_effect must lie inside its confidence interval"
            )
        harm_rate = _rate("harm_rate", self.harm_rate)
        token_delta = _finite_number("mean_token_delta", self.mean_token_delta)
        latency_delta = _finite_number(
            "mean_latency_delta_ms",
            self.mean_latency_delta_ms,
        )
        evidence_age = _nonnegative_integer(
            "evidence_age_seconds",
            self.evidence_age_seconds,
        )
        security_violation = _strict_bool(
            "security_violation",
            self.security_violation,
        )
        rollback_ready = _strict_bool("rollback_ready", self.rollback_ready)
        focused_tests_green = _strict_bool(
            "focused_tests_green",
            self.focused_tests_green,
        )
        full_tests_green = _strict_bool(
            "full_tests_green",
            self.full_tests_green,
        )
        integration_green = _strict_bool(
            "integration_green",
            self.integration_green,
        )
        artifact_integrity_verified = _strict_bool(
            "artifact_integrity_verified",
            self.artifact_integrity_verified,
        )
        review_ids = _normalize_review_ids(self.independent_review_ids)

        object.__setattr__(self, "control_policy_version", control_version)
        object.__setattr__(self, "treatment_policy_version", treatment_version)
        object.__setattr__(self, "pair_count", pair_count)
        object.__setattr__(self, "mean_score_effect", mean_score_effect)
        object.__setattr__(self, "score_confidence_low", confidence_low)
        object.__setattr__(self, "score_confidence_high", confidence_high)
        object.__setattr__(self, "harm_rate", harm_rate)
        object.__setattr__(self, "mean_token_delta", token_delta)
        object.__setattr__(self, "mean_latency_delta_ms", latency_delta)
        object.__setattr__(self, "evidence_age_seconds", evidence_age)
        object.__setattr__(self, "security_violation", security_violation)
        object.__setattr__(self, "rollback_ready", rollback_ready)
        object.__setattr__(self, "focused_tests_green", focused_tests_green)
        object.__setattr__(self, "full_tests_green", full_tests_green)
        object.__setattr__(self, "integration_green", integration_green)
        object.__setattr__(
            self,
            "artifact_integrity_verified",
            artifact_integrity_verified,
        )
        object.__setattr__(self, "independent_review_ids", review_ids)
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    @property
    def score_interval_width(self) -> float:
        """Return the finite confidence-interval width."""

        return self.score_confidence_high - self.score_confidence_low

    def to_dict(self) -> dict[str, object]:
        """Return the canonical JSON-safe evidence payload."""

        return {
            "evaluation_id": str(self.evaluation_id),
            "evaluation_content_hash": self.evaluation_content_hash,
            "control_policy_version": self.control_policy_version,
            "control_policy_fingerprint": self.control_policy_fingerprint,
            "treatment_policy_version": self.treatment_policy_version,
            "treatment_policy_fingerprint": self.treatment_policy_fingerprint,
            "current_control_policy_fingerprint": (
                self.current_control_policy_fingerprint
            ),
            "current_treatment_policy_fingerprint": (
                self.current_treatment_policy_fingerprint
            ),
            "verdict": self.verdict.value,
            "pair_count": self.pair_count,
            "mean_score_effect": self.mean_score_effect,
            "score_confidence_low": self.score_confidence_low,
            "score_confidence_high": self.score_confidence_high,
            "harm_rate": self.harm_rate,
            "mean_token_delta": self.mean_token_delta,
            "mean_latency_delta_ms": self.mean_latency_delta_ms,
            "evidence_age_seconds": self.evidence_age_seconds,
            "security_violation": self.security_violation,
            "rollback_ready": self.rollback_ready,
            "focused_tests_green": self.focused_tests_green,
            "full_tests_green": self.full_tests_green,
            "integration_green": self.integration_green,
            "artifact_integrity_verified": self.artifact_integrity_verified,
            "independent_review_ids": [
                str(value) for value in self.independent_review_ids
            ],
        }


@dataclass(frozen=True, slots=True)
class PolicyPromotionDecision:
    """Deterministic advisory result with no activation behavior."""

    disposition: PolicyPromotionDisposition
    reasons: tuple[PolicyPromotionReason, ...]
    evidence_content_hash: str
    config_content_hash: str
    gate_policy_version: str
    id: UUID = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.disposition, PolicyPromotionDisposition):
            raise PolicyPromotionValidationError(
                "disposition must be a PolicyPromotionDisposition"
            )
        reasons = tuple(self.reasons)
        if any(not isinstance(value, PolicyPromotionReason) for value in reasons):
            raise PolicyPromotionValidationError(
                "reasons must contain PolicyPromotionReason values"
            )
        if len(reasons) != len(set(reasons)):
            raise PolicyPromotionValidationError("reasons must be unique")
        canonical = tuple(value for value in _REASON_ORDER if value in reasons)
        if reasons != canonical:
            raise PolicyPromotionValidationError(
                "reasons must use canonical precedence order"
            )
        _require_hash("evidence_content_hash", self.evidence_content_hash)
        _require_hash("config_content_hash", self.config_content_hash)
        version = _required_text("gate_policy_version", self.gate_policy_version)
        payload = {
            "schema": _SCHEMA,
            "disposition": self.disposition.value,
            "reasons": [value.value for value in reasons],
            "evidence_content_hash": self.evidence_content_hash,
            "config_content_hash": self.config_content_hash,
            "gate_policy_version": version,
        }
        content_hash = _hash_payload(payload)
        object.__setattr__(self, "reasons", reasons)
        object.__setattr__(self, "gate_policy_version", version)
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "id", _stable_uuid("decision", content_hash))

    @property
    def promotion_allowed(self) -> bool:
        """Return whether this advisory result recommends promotion."""

        return self.disposition is PolicyPromotionDisposition.PROMOTE

    def to_dict(self) -> dict[str, object]:
        """Return the canonical privacy-safe decision payload."""

        return {
            "schema": _SCHEMA,
            "id": str(self.id),
            "content_hash": self.content_hash,
            "disposition": self.disposition.value,
            "reasons": [value.value for value in self.reasons],
            "evidence_content_hash": self.evidence_content_hash,
            "config_content_hash": self.config_content_hash,
            "gate_policy_version": self.gate_policy_version,
            "promotion_allowed": self.promotion_allowed,
        }

    def render_json(self) -> str:
        """Render canonical deterministic JSON."""

        return _canonical_json(self.to_dict())


class PolicyPromotionGate:
    """Evaluate immutable evidence without executing a promotion."""

    __slots__ = ("_config",)

    def __init__(self, config: PolicyPromotionGateConfig) -> None:
        if not isinstance(config, PolicyPromotionGateConfig):
            raise PolicyPromotionValidationError(
                "config must be a PolicyPromotionGateConfig"
            )
        self._config = config

    @property
    def config(self) -> PolicyPromotionGateConfig:
        """Expose the immutable gate configuration."""

        return self._config

    def decide(self, evidence: PolicyPromotionEvidence) -> PolicyPromotionDecision:
        """Return a deterministic advisory recommendation."""

        if not isinstance(evidence, PolicyPromotionEvidence):
            raise PolicyPromotionValidationError(
                "evidence must be PolicyPromotionEvidence"
            )
        reasons: set[PolicyPromotionReason] = set()

        if evidence.security_violation:
            reasons.add(PolicyPromotionReason.SECURITY_VIOLATION)
        if (
            evidence.control_policy_fingerprint
            != evidence.current_control_policy_fingerprint
        ):
            reasons.add(PolicyPromotionReason.CONTROL_POLICY_IDENTITY_DRIFT)
        if (
            evidence.treatment_policy_fingerprint
            != evidence.current_treatment_policy_fingerprint
        ):
            reasons.add(PolicyPromotionReason.TREATMENT_POLICY_IDENTITY_DRIFT)
        if evidence.verdict is PairedPolicyVerdict.HARMFUL:
            reasons.add(PolicyPromotionReason.HARMFUL_EVALUATION)
        if evidence.verdict is PairedPolicyVerdict.TOO_COSTLY:
            reasons.add(PolicyPromotionReason.TOO_COSTLY_EVALUATION)
        if evidence.mean_score_effect < 0.0:
            reasons.add(PolicyPromotionReason.NEGATIVE_SCORE_EFFECT)
        if evidence.harm_rate > self._config.maximum_harm_rate:
            reasons.add(PolicyPromotionReason.EXCESS_HARM_RATE)
        if evidence.mean_token_delta > self._config.maximum_token_delta:
            reasons.add(PolicyPromotionReason.EXCESS_TOKEN_COST)
        if (
            evidence.mean_latency_delta_ms
            > self._config.maximum_latency_delta_ms
        ):
            reasons.add(PolicyPromotionReason.EXCESS_LATENCY_COST)

        if evidence.pair_count < self._config.minimum_pairs:
            reasons.add(PolicyPromotionReason.INSUFFICIENT_PAIRS)
        if (
            evidence.score_confidence_low
            <= self._config.minimum_score_lower_bound
        ):
            reasons.add(PolicyPromotionReason.NON_POSITIVE_SCORE_LOWER_BOUND)
        if (
            evidence.score_interval_width
            > self._config.maximum_score_interval_width
        ):
            reasons.add(PolicyPromotionReason.EXCESS_SCORE_UNCERTAINTY)
        if (
            evidence.evidence_age_seconds
            > self._config.maximum_evidence_age_seconds
        ):
            reasons.add(PolicyPromotionReason.STALE_EVIDENCE)
        if not evidence.rollback_ready:
            reasons.add(PolicyPromotionReason.ROLLBACK_NOT_READY)
        if not evidence.focused_tests_green:
            reasons.add(PolicyPromotionReason.FOCUSED_TESTS_NOT_GREEN)
        if not evidence.full_tests_green:
            reasons.add(PolicyPromotionReason.FULL_TESTS_NOT_GREEN)
        if not evidence.integration_green:
            reasons.add(PolicyPromotionReason.INTEGRATION_NOT_GREEN)
        if not evidence.artifact_integrity_verified:
            reasons.add(
                PolicyPromotionReason.ARTIFACT_INTEGRITY_NOT_VERIFIED
            )
        if (
            len(evidence.independent_review_ids)
            < self._config.minimum_independent_reviewers
        ):
            reasons.add(
                PolicyPromotionReason.INSUFFICIENT_INDEPENDENT_REVIEWS
            )
        if evidence.verdict in {
            PairedPolicyVerdict.NEUTRAL,
            PairedPolicyVerdict.INCONCLUSIVE,
            PairedPolicyVerdict.INSUFFICIENT_EVIDENCE,
        }:
            reasons.add(PolicyPromotionReason.EVALUATION_NOT_PROMISING)

        canonical_reasons = tuple(
            value for value in _REASON_ORDER if value in reasons
        )
        if reasons & _REJECT_REASONS:
            disposition = PolicyPromotionDisposition.REJECT
        elif canonical_reasons:
            disposition = PolicyPromotionDisposition.HOLD
        else:
            disposition = PolicyPromotionDisposition.PROMOTE
        return PolicyPromotionDecision(
            disposition=disposition,
            reasons=canonical_reasons,
            evidence_content_hash=evidence.content_hash,
            config_content_hash=self._config.content_hash,
            gate_policy_version=self._config.gate_policy_version,
        )


def _normalize_review_ids(values: Iterable[UUID]) -> tuple[UUID, ...]:
    if isinstance(values, (str, bytes, Mapping)):
        raise PolicyPromotionValidationError(
            "independent_review_ids must be a UUID collection"
        )
    try:
        normalized = tuple(values)
    except TypeError as exc:
        raise PolicyPromotionValidationError(
            "independent_review_ids must be iterable"
        ) from exc
    if any(not isinstance(value, UUID) for value in normalized):
        raise PolicyPromotionValidationError(
            "independent_review_ids must contain UUID values"
        )
    if len(normalized) != len(set(normalized)):
        raise PolicyPromotionValidationError(
            "independent_review_ids must be unique"
        )
    return tuple(sorted(normalized, key=str))


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


def _stable_uuid(kind: str, *parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, ":".join((_SCHEMA, kind, *parts)))


def _require_uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise PolicyPromotionValidationError(f"{name} must be a UUID")
    return value


def _require_hash(name: str, value: object) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise PolicyPromotionValidationError(
            f"{name} must be a lowercase SHA-256 value"
        )
    return value


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise PolicyPromotionValidationError(f"{name} must be text")
    normalized = value.strip()
    if not normalized:
        raise PolicyPromotionValidationError(f"{name} must not be empty")
    if len(normalized) > 128:
        raise PolicyPromotionValidationError(
            f"{name} exceeds the bounded length"
        )
    return normalized


def _strict_bool(name: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise PolicyPromotionValidationError(f"{name} must be boolean")
    return value


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PolicyPromotionValidationError(
            f"{name} must be a positive integer"
        )
    return value


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PolicyPromotionValidationError(
            f"{name} must be a non-negative integer"
        )
    return value


def _finite_number(name: str, value: object) -> float:
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


def _positive_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized <= 0.0:
        raise PolicyPromotionValidationError(
            f"{name} must be a positive finite number"
        )
    return normalized


def _nonnegative_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized < 0.0:
        raise PolicyPromotionValidationError(
            f"{name} must be a non-negative finite number"
        )
    return normalized


def _rate(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if not 0.0 <= normalized <= 1.0:
        raise PolicyPromotionValidationError(f"{name} must be in [0, 1]")
    return normalized


__all__ = [
    "PolicyPromotionDecision",
    "PolicyPromotionDisposition",
    "PolicyPromotionEvidence",
    "PolicyPromotionGate",
    "PolicyPromotionGateConfig",
    "PolicyPromotionReason",
    "PolicyPromotionValidationError",
]
