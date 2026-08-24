from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from nextgen_memory.paired_rerank_policy_evaluation import PairedPolicyVerdict
from nextgen_memory.policy_promotion import (
    DeterministicPolicyPromotionGate,
    PolicyPromotionDisposition,
    PolicyPromotionEvidence,
    PolicyPromotionGateConfig,
    PolicyPromotionReason,
    PolicyPromotionValidationError,
    PolicyVerificationSignal,
    fingerprint_policy_promotion_config,
)

NOW = datetime(2026, 8, 24, 3, 30, tzinfo=UTC)
SPACE_ID = UUID("00000000-0000-5000-8000-000000000d01")
POLICY_ID = UUID("00000000-0000-5000-8000-000000000d02")
EVALUATION_ID = UUID("00000000-0000-5000-8000-000000000d03")
ROLLBACK_ID = UUID("00000000-0000-5000-8000-000000000d04")
SIGNALS = tuple(PolicyVerificationSignal)


def valid_evidence(**overrides: object) -> PolicyPromotionEvidence:
    values: dict[str, object] = {
        "space_id": SPACE_ID,
        "candidate_policy_id": POLICY_ID,
        "evaluated_policy_version": "treatment-v1",
        "current_policy_version": "treatment-v1",
        "evaluated_policy_fingerprint": "a" * 64,
        "current_policy_fingerprint": "a" * 64,
        "evaluation_id": EVALUATION_ID,
        "evaluation_content_hash": "b" * 64,
        "context_collection_hash": "c" * 64,
        "continuation_set_hash": "d" * 64,
        "paired_trial_count": 32,
        "mean_effect": 0.05,
        "confidence_lower": 0.02,
        "confidence_upper": 0.08,
        "standard_error": 0.01,
        "mean_cost_delta": 0.01,
        "harm_rate": 0.0,
        "evaluator_verdict": PairedPolicyVerdict.PROMISING,
        "evidence_at": NOW - timedelta(hours=1),
        "decision_at": NOW,
        "maximum_evidence_age_seconds": 86_400,
        "rollback_plan_id": ROLLBACK_ID,
        "rollback_plan_hash": "e" * 64,
        "rollback_ready": True,
        "required_signals": SIGNALS,
        "passed_signals": tuple(reversed(SIGNALS)),
        "reviewer_count": 2,
        "required_reviewer_count": 2,
        "evaluated_base_sha": "1" * 40,
        "current_base_sha": "1" * 40,
        "evaluated_candidate_sha": "2" * 40,
        "current_candidate_sha": "2" * 40,
        "hard_safety_violation": False,
    }
    values.update(overrides)
    return PolicyPromotionEvidence(**values)  # type: ignore[arg-type]


def evaluate(
    evidence: PolicyPromotionEvidence,
    config: PolicyPromotionGateConfig | None = None,
):
    return DeterministicPolicyPromotionGate(config).evaluate(evidence)


def test_fully_satisfied_promising_evidence_promotes() -> None:
    decision = evaluate(valid_evidence())

    assert decision.disposition is PolicyPromotionDisposition.PROMOTE
    assert decision.reasons == (
        PolicyPromotionReason.ALL_REQUIREMENTS_SATISFIED,
    )
    assert decision.invalid_fields == ()
    assert decision.missing_signals == ()
    assert decision.candidate_policy_id == POLICY_ID
    assert decision.candidate_policy_version == "treatment-v1"
    assert decision.evaluation_id == EVALUATION_ID
    assert decision.metrics.evidence_age_seconds == 3_600.0
    assert decision.metrics.required_signal_count == len(SIGNALS)
    assert decision.metrics.passed_required_signal_count == len(SIGNALS)
    assert decision.metrics.missing_signal_count == 0
    assert len(decision.evidence_fingerprint) == 64
    assert len(decision.config_fingerprint) == 64
    assert len(decision.content_hash) == 64
    assert decision.id.version == 5


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {"evaluator_verdict": PairedPolicyVerdict.HARMFUL},
            PolicyPromotionReason.EVALUATOR_HARMFUL,
        ),
        (
            {"evaluator_verdict": PairedPolicyVerdict.TOO_COSTLY},
            PolicyPromotionReason.EVALUATOR_TOO_COSTLY,
        ),
        (
            {
                "confidence_lower": -0.02,
                "mean_effect": -0.01,
                "confidence_upper": -0.001,
            },
            PolicyPromotionReason.ESTABLISHED_NEGATIVE_EFFECT,
        ),
        (
            {"mean_cost_delta": 0.0500001},
            PolicyPromotionReason.COST_LIMIT_EXCEEDED,
        ),
        (
            {"harm_rate": 0.0100001},
            PolicyPromotionReason.HARM_RATE_EXCEEDED,
        ),
    ],
)
def test_hard_rejection_conditions(
    overrides: dict[str, object],
    reason: PolicyPromotionReason,
) -> None:
    decision = evaluate(valid_evidence(**overrides))

    assert decision.disposition is PolicyPromotionDisposition.REJECT
    assert reason in decision.reasons


@pytest.mark.parametrize(
    "field",
    [
        "current_policy_version",
        "current_policy_fingerprint",
        "current_base_sha",
        "current_candidate_sha",
    ],
)
def test_identity_drift_rejects(field: str) -> None:
    values: dict[str, object] = {
        "current_policy_version": "treatment-v2",
        "current_policy_fingerprint": "f" * 64,
        "current_base_sha": "3" * 40,
        "current_candidate_sha": "4" * 40,
    }

    decision = evaluate(valid_evidence(**{field: values[field]}))

    assert decision.disposition is PolicyPromotionDisposition.REJECT
    assert PolicyPromotionReason.IDENTITY_MISMATCH in decision.reasons


def test_all_reject_reasons_are_ordered_and_exclude_holds() -> None:
    decision = evaluate(
        valid_evidence(
            current_policy_version="treatment-v2",
            evaluator_verdict=PairedPolicyVerdict.HARMFUL,
            confidence_lower=-0.2,
            mean_effect=-0.1,
            confidence_upper=-0.05,
            mean_cost_delta=0.2,
            harm_rate=0.5,
            hard_safety_violation=True,
            paired_trial_count=1,
            rollback_ready=False,
            passed_signals=(),
            reviewer_count=0,
        )
    )

    assert decision.disposition is PolicyPromotionDisposition.REJECT
    assert decision.reasons == (
        PolicyPromotionReason.HARD_SAFETY_VIOLATION,
        PolicyPromotionReason.IDENTITY_MISMATCH,
        PolicyPromotionReason.EVALUATOR_HARMFUL,
        PolicyPromotionReason.ESTABLISHED_NEGATIVE_EFFECT,
        PolicyPromotionReason.COST_LIMIT_EXCEEDED,
        PolicyPromotionReason.HARM_RATE_EXCEEDED,
    )
    assert PolicyPromotionReason.INSUFFICIENT_TRIALS not in decision.reasons
    assert PolicyPromotionReason.ROLLBACK_NOT_READY not in decision.reasons


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        (
            {"evaluator_verdict": PairedPolicyVerdict.INSUFFICIENT_EVIDENCE},
            PolicyPromotionReason.EVALUATOR_INSUFFICIENT_EVIDENCE,
        ),
        (
            {"evaluator_verdict": PairedPolicyVerdict.NEUTRAL},
            PolicyPromotionReason.EVALUATOR_NEUTRAL,
        ),
        (
            {"evaluator_verdict": PairedPolicyVerdict.INCONCLUSIVE},
            PolicyPromotionReason.EVALUATOR_INCONCLUSIVE,
        ),
        (
            {"paired_trial_count": 15},
            PolicyPromotionReason.INSUFFICIENT_TRIALS,
        ),
        (
            {"confidence_lower": 0.0},
            PolicyPromotionReason.NONPOSITIVE_LOWER_BOUND,
        ),
        (
            {"standard_error": 0.0500001},
            PolicyPromotionReason.UNCERTAINTY_TOO_HIGH,
        ),
        (
            {
                "evidence_at": NOW - timedelta(days=1, microseconds=1),
                "maximum_evidence_age_seconds": 86_400,
            },
            PolicyPromotionReason.STALE_EVIDENCE,
        ),
        (
            {"rollback_ready": False},
            PolicyPromotionReason.ROLLBACK_NOT_READY,
        ),
        (
            {"passed_signals": SIGNALS[:-1]},
            PolicyPromotionReason.VERIFICATION_INCOMPLETE,
        ),
        (
            {"reviewer_count": 1},
            PolicyPromotionReason.INSUFFICIENT_REVIEWERS,
        ),
    ],
)
def test_hold_conditions(
    overrides: dict[str, object],
    reason: PolicyPromotionReason,
) -> None:
    decision = evaluate(valid_evidence(**overrides))

    assert decision.disposition is PolicyPromotionDisposition.HOLD
    assert reason in decision.reasons


def test_hold_reasons_use_deterministic_precedence() -> None:
    decision = evaluate(
        valid_evidence(
            evaluator_verdict=PairedPolicyVerdict.INCONCLUSIVE,
            paired_trial_count=1,
            confidence_lower=0.0,
            standard_error=0.2,
            evidence_at=NOW - timedelta(days=2),
            rollback_ready=False,
            passed_signals=(),
            reviewer_count=0,
        )
    )

    assert decision.disposition is PolicyPromotionDisposition.HOLD
    assert decision.reasons == (
        PolicyPromotionReason.EVALUATOR_INCONCLUSIVE,
        PolicyPromotionReason.INSUFFICIENT_TRIALS,
        PolicyPromotionReason.NONPOSITIVE_LOWER_BOUND,
        PolicyPromotionReason.UNCERTAINTY_TOO_HIGH,
        PolicyPromotionReason.STALE_EVIDENCE,
        PolicyPromotionReason.ROLLBACK_NOT_READY,
        PolicyPromotionReason.VERIFICATION_INCOMPLETE,
        PolicyPromotionReason.INSUFFICIENT_REVIEWERS,
    )
    assert decision.missing_signals == tuple(sorted(SIGNALS, key=lambda item: item.value))


def test_threshold_equalities_are_not_rejected() -> None:
    config = PolicyPromotionGateConfig(
        minimum_paired_trials=16,
        minimum_confidence_lower_bound=0.0,
        maximum_standard_error=0.05,
        maximum_mean_cost_delta=0.05,
        maximum_harm_rate=0.01,
        established_negative_effect_tolerance=0.01,
    )
    evidence = valid_evidence(
        paired_trial_count=16,
        confidence_lower=0.01,
        mean_effect=0.02,
        confidence_upper=0.03,
        standard_error=0.05,
        mean_cost_delta=0.05,
        harm_rate=0.01,
    )

    decision = evaluate(evidence, config)

    assert decision.disposition is PolicyPromotionDisposition.PROMOTE


@pytest.mark.parametrize(
    ("field", "value", "invalid_field"),
    [
        ("space_id", "not-a-uuid", "space_id"),
        ("candidate_policy_id", "not-a-uuid", "candidate_policy_id"),
        ("paired_trial_count", True, "paired_trial_count"),
        ("paired_trial_count", -1, "paired_trial_count"),
        ("mean_effect", math.nan, "mean_effect"),
        ("confidence_lower", -math.inf, "confidence_lower"),
        ("confidence_upper", math.inf, "confidence_upper"),
        ("standard_error", -0.1, "standard_error"),
        ("harm_rate", -0.1, "harm_rate"),
        ("harm_rate", 1.1, "harm_rate"),
        ("evaluation_content_hash", "A" * 64, "evaluation_content_hash"),
        ("context_collection_hash", "c" * 63, "context_collection_hash"),
        ("current_base_sha", "A" * 40, "current_base_sha"),
        ("current_candidate_sha", "2" * 41, "current_candidate_sha"),
        ("evidence_at", NOW.replace(tzinfo=None), "evidence_at"),
        ("maximum_evidence_age_seconds", 0, "maximum_evidence_age_seconds"),
        ("reviewer_count", -1, "reviewer_count"),
        ("required_reviewer_count", 0, "required_reviewer_count"),
        ("rollback_ready", 1, "rollback_ready"),
        ("hard_safety_violation", 0, "hard_safety_violation"),
        ("required_signals", ("unknown",), "required_signals"),
    ],
)
def test_malformed_fields_reject_privately(
    field: str,
    value: object,
    invalid_field: str,
) -> None:
    decision = evaluate(valid_evidence(**{field: value}))

    assert decision.disposition is PolicyPromotionDisposition.REJECT
    assert decision.reasons == (PolicyPromotionReason.MALFORMED_EVIDENCE,)
    assert invalid_field in decision.invalid_fields


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "confidence_lower": 0.09,
            "mean_effect": 0.05,
            "confidence_upper": 0.10,
        },
        {
            "confidence_lower": 0.08,
            "mean_effect": 0.09,
            "confidence_upper": 0.07,
        },
        {"decision_at": NOW - timedelta(hours=2)},
    ],
)
def test_impossible_relationships_are_malformed(
    overrides: dict[str, object],
) -> None:
    decision = evaluate(valid_evidence(**overrides))

    assert decision.disposition is PolicyPromotionDisposition.REJECT
    assert decision.reasons == (PolicyPromotionReason.MALFORMED_EVIDENCE,)


class ExplosiveText:
    def __str__(self) -> str:
        raise AssertionError("str must not be called")

    def __repr__(self) -> str:
        raise AssertionError("repr must not be called")


def test_malformed_payload_is_rejected_without_echo_or_conversion() -> None:
    sentinel = "private-prompt-sentinel"
    evidence = valid_evidence(
        evaluation_content_hash=sentinel,
        required_signals=(ExplosiveText(),),
    )

    decision = evaluate(evidence)
    rendered = decision.render_json()

    assert decision.disposition is PolicyPromotionDisposition.REJECT
    assert decision.reasons == (PolicyPromotionReason.MALFORMED_EVIDENCE,)
    assert sentinel not in rendered
    assert "private-prompt" not in rendered
    assert len(decision.evidence_fingerprint) == 64
    assert "evaluation_content_hash" in decision.invalid_fields
    assert "required_signals" in decision.invalid_fields


def test_exact_retry_is_byte_identical() -> None:
    first = evaluate(valid_evidence())
    second = evaluate(valid_evidence())

    assert first == second
    assert first.id == second.id
    assert first.content_hash == second.content_hash
    assert first.render_json() == second.render_json()


def test_signal_order_and_duplicates_do_not_change_identity() -> None:
    first = evaluate(
        valid_evidence(
            required_signals=SIGNALS,
            passed_signals=tuple(reversed(SIGNALS)),
        )
    )
    second = evaluate(
        valid_evidence(
            required_signals=tuple(reversed(SIGNALS)) + SIGNALS,
            passed_signals=SIGNALS + tuple(reversed(SIGNALS)),
        )
    )

    assert first == second
    assert first.render_json() == second.render_json()


def test_material_evidence_change_changes_identity() -> None:
    first = evaluate(valid_evidence())
    second = evaluate(valid_evidence(reviewer_count=3))

    assert first.id != second.id
    assert first.content_hash != second.content_hash
    assert first.evidence_fingerprint != second.evidence_fingerprint


def test_material_configuration_change_changes_identity() -> None:
    evidence = valid_evidence()
    first = evaluate(evidence, PolicyPromotionGateConfig())
    second = evaluate(
        evidence,
        PolicyPromotionGateConfig(maximum_standard_error=0.06),
    )

    assert first.disposition is second.disposition
    assert first.id != second.id
    assert first.config_fingerprint != second.config_fingerprint


def test_decision_is_frozen_and_json_is_canonical() -> None:
    decision = evaluate(valid_evidence())
    raw = decision.render_json()

    with pytest.raises((AttributeError, FrozenInstanceError)):
        decision.content_hash = "0" * 64  # type: ignore[misc]
    assert raw.endswith("\n")
    assert raw == (
        json.dumps(
            json.loads(raw),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    assert "evidence_at" not in raw
    assert "decision_at" not in raw


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"minimum_paired_trials": True}, "minimum_paired_trials"),
        ({"minimum_paired_trials": 0}, "minimum_paired_trials"),
        ({"minimum_confidence_lower_bound": math.nan}, "minimum_confidence"),
        ({"maximum_standard_error": -0.1}, "maximum_standard_error"),
        ({"maximum_mean_cost_delta": math.inf}, "maximum_mean_cost_delta"),
        ({"maximum_harm_rate": 1.1}, "maximum_harm_rate"),
        (
            {"established_negative_effect_tolerance": -0.1},
            "established_negative_effect_tolerance",
        ),
        ({"policy_version": " "}, "policy_version"),
    ],
)
def test_invalid_config_raises(
    overrides: dict[str, object],
    match: str,
) -> None:
    with pytest.raises(PolicyPromotionValidationError, match=match):
        PolicyPromotionGateConfig(**overrides)  # type: ignore[arg-type]


def test_config_fingerprint_is_deterministic_and_type_checked() -> None:
    first = fingerprint_policy_promotion_config(PolicyPromotionGateConfig())
    second = fingerprint_policy_promotion_config(PolicyPromotionGateConfig())

    assert first == second
    assert len(first) == 64
    with pytest.raises(PolicyPromotionValidationError, match="config"):
        fingerprint_policy_promotion_config(object())  # type: ignore[arg-type]
