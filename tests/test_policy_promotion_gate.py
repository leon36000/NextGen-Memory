from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from nextgen_memory.paired_rerank_policy_evaluation import PairedPolicyVerdict
from nextgen_memory.policy_promotion_gate import (
    AdvisoryPolicyPromotionGate,
    PairedPolicyEvidence,
    PolicyIdentity,
    PolicyOperationalReadiness,
    PolicyPromotionDecision,
    PolicyPromotionGateConfig,
    PolicyPromotionReason,
    PolicyPromotionRequest,
    PolicyPromotionValidationError,
)

EVALUATION_ID = UUID("00000000-0000-5000-8000-000000001001")
CURRENT_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
CURRENT_FP = "a" * 64
CANDIDATE_FP = "b" * 64
EVALUATION_HASH = "c" * 64
REGISTRY_HASH = "d" * 64


def identity(
    *,
    version: str = "control-v1",
    fingerprint: str = CURRENT_FP,
    source_sha: str = CURRENT_SHA,
    **overrides: object,
) -> PolicyIdentity:
    values: dict[str, object] = {
        "policy_version": version,
        "policy_fingerprint": fingerprint,
        "source_sha": source_sha,
    }
    values.update(overrides)
    return PolicyIdentity(**values)  # type: ignore[arg-type]


def paired_evidence(**overrides: object) -> PairedPolicyEvidence:
    values: dict[str, object] = {
        "evaluation_id": EVALUATION_ID,
        "evaluation_content_hash": EVALUATION_HASH,
        "control_policy_version": "control-v1",
        "control_policy_fingerprint": CURRENT_FP,
        "treatment_policy_version": "treatment-v1",
        "treatment_policy_fingerprint": CANDIDATE_FP,
        "evaluated_base_sha": CURRENT_SHA,
        "evaluated_candidate_sha": CANDIDATE_SHA,
        "verdict": PairedPolicyVerdict.PROMISING,
        "matched_pair_count": 24,
        "mean_score_effect": 0.08,
        "score_confidence_lower_bound": 0.04,
        "score_confidence_upper_bound": 0.12,
        "score_standard_error": 0.02,
        "mean_token_delta": 4.0,
        "mean_latency_delta_ms": 8.0,
        "harm_rate": 0.01,
        "registry_summary_content_hash": REGISTRY_HASH,
        "registry_pair_count": 24,
        "registry_completed_trial_count": 24,
        "registry_failed_count": 0,
        "registry_cancelled_count": 0,
        "registry_active_count": 0,
    }
    values.update(overrides)
    return PairedPolicyEvidence(**values)  # type: ignore[arg-type]


def readiness(**overrides: object) -> PolicyOperationalReadiness:
    values: dict[str, object] = {
        "tests_passed": True,
        "integration_passed": True,
        "artifact_integrity_passed": True,
        "rollback_ready": True,
        "safety_violation": False,
        "reviewer_count": 2,
        "evidence_age_seconds": 60.0,
    }
    values.update(overrides)
    return PolicyOperationalReadiness(**values)  # type: ignore[arg-type]


def request(**overrides: object) -> PolicyPromotionRequest:
    values: dict[str, object] = {
        "current_policy": identity(),
        "candidate_policy": identity(
            version="treatment-v1",
            fingerprint=CANDIDATE_FP,
            source_sha=CANDIDATE_SHA,
        ),
        "evaluation": paired_evidence(),
        "readiness": readiness(),
    }
    values.update(overrides)
    return PolicyPromotionRequest(**values)  # type: ignore[arg-type]


def config(**overrides: object) -> PolicyPromotionGateConfig:
    values: dict[str, object] = {
        "minimum_matched_pairs": 20,
        "minimum_score_lower_bound": 0.0,
        "maximum_score_standard_error": 0.05,
        "maximum_mean_token_delta": 10.0,
        "maximum_mean_latency_delta_ms": 20.0,
        "maximum_harm_rate": 0.05,
        "maximum_evidence_age_seconds": 3_600.0,
        "minimum_reviewer_count": 2,
        "gate_policy_version": "advisory-policy-promotion-gate-v0",
    }
    values.update(overrides)
    return PolicyPromotionGateConfig(**values)  # type: ignore[arg-type]


def evaluate(
    promotion_request: PolicyPromotionRequest | None = None,
    gate_config: PolicyPromotionGateConfig | None = None,
):
    return AdvisoryPolicyPromotionGate().evaluate(
        promotion_request or request(),
        gate_config or config(),
    )


def test_all_gates_pass_produces_advisory_promote() -> None:
    record = evaluate()

    assert record.decision is PolicyPromotionDecision.PROMOTE
    assert record.reasons == (PolicyPromotionReason.ALL_GATES_PASSED,)
    assert record.advisory_only is True
    assert record.current_policy_content_hash == request().current_policy.content_hash
    assert record.candidate_policy_content_hash == request().candidate_policy.content_hash
    assert record.request_content_hash == request().content_hash
    assert len(record.content_hash) == 64
    assert record.id.version == 5
    assert not hasattr(record, "__dict__")
    with pytest.raises((FrozenInstanceError, AttributeError)):
        record.advisory_only = False  # type: ignore[misc]


@pytest.mark.parametrize(
    ("promotion_request", "gate_config", "reason"),
    [
        (
            request(readiness=readiness(safety_violation=True)),
            config(),
            PolicyPromotionReason.SAFETY_VIOLATION,
        ),
        (
            request(evaluation=paired_evidence(control_policy_fingerprint="e" * 64)),
            config(),
            PolicyPromotionReason.CURRENT_POLICY_IDENTITY_MISMATCH,
        ),
        (
            request(evaluation=paired_evidence(treatment_policy_fingerprint="e" * 64)),
            config(),
            PolicyPromotionReason.CANDIDATE_POLICY_IDENTITY_MISMATCH,
        ),
        (
            request(
                candidate_policy=identity(),
            ),
            config(),
            PolicyPromotionReason.CANDIDATE_POLICY_IDENTITY_MISMATCH,
        ),
        (
            request(
                evaluation=paired_evidence(
                    registry_completed_trial_count=23,
                    registry_active_count=1,
                )
            ),
            config(),
            PolicyPromotionReason.REGISTRY_EVALUATION_MISMATCH,
        ),
        (
            request(evaluation=paired_evidence(verdict=PairedPolicyVerdict.HARMFUL)),
            config(),
            PolicyPromotionReason.HARMFUL_VERDICT,
        ),
        (
            request(evaluation=paired_evidence(verdict=PairedPolicyVerdict.TOO_COSTLY)),
            config(),
            PolicyPromotionReason.TOO_COSTLY_VERDICT,
        ),
        (
            request(
                evaluation=paired_evidence(
                    mean_score_effect=-0.001,
                    score_confidence_lower_bound=-0.01,
                    score_confidence_upper_bound=0.01,
                )
            ),
            config(),
            PolicyPromotionReason.NEGATIVE_MEAN_EFFECT,
        ),
        (
            request(evaluation=paired_evidence(mean_token_delta=10.01)),
            config(),
            PolicyPromotionReason.TOKEN_COST_EXCEEDED,
        ),
        (
            request(evaluation=paired_evidence(mean_latency_delta_ms=20.01)),
            config(),
            PolicyPromotionReason.LATENCY_COST_EXCEEDED,
        ),
        (
            request(evaluation=paired_evidence(harm_rate=0.051)),
            config(),
            PolicyPromotionReason.HARM_RATE_EXCEEDED,
        ),
    ],
)
def test_each_hard_rejection_condition_is_bounded(
    promotion_request: PolicyPromotionRequest,
    gate_config: PolicyPromotionGateConfig,
    reason: PolicyPromotionReason,
) -> None:
    record = evaluate(promotion_request, gate_config)

    assert record.decision is PolicyPromotionDecision.REJECT
    assert reason in record.reasons
    assert PolicyPromotionReason.ALL_GATES_PASSED not in record.reasons


@pytest.mark.parametrize(
    ("promotion_request", "gate_config", "reason"),
    [
        (
            request(
                evaluation=paired_evidence(
                    matched_pair_count=19,
                    registry_pair_count=19,
                    registry_completed_trial_count=19,
                )
            ),
            config(),
            PolicyPromotionReason.INSUFFICIENT_MATCHED_PAIRS,
        ),
        (
            request(
                evaluation=paired_evidence(
                    mean_score_effect=0.01,
                    score_confidence_lower_bound=0.0,
                    score_confidence_upper_bound=0.02,
                )
            ),
            config(),
            PolicyPromotionReason.NON_POSITIVE_CONFIDENCE_LOWER_BOUND,
        ),
        (
            request(evaluation=paired_evidence(score_standard_error=0.051)),
            config(),
            PolicyPromotionReason.STANDARD_ERROR_EXCEEDED,
        ),
        (
            request(readiness=readiness(evidence_age_seconds=3_600.1)),
            config(),
            PolicyPromotionReason.EVIDENCE_STALE,
        ),
        (
            request(evaluation=paired_evidence(registry_active_count=1, registry_pair_count=25)),
            config(),
            PolicyPromotionReason.REGISTRY_INCOMPLETE,
        ),
        (
            request(readiness=readiness(rollback_ready=False)),
            config(),
            PolicyPromotionReason.ROLLBACK_NOT_READY,
        ),
        (
            request(readiness=readiness(tests_passed=False)),
            config(),
            PolicyPromotionReason.TESTS_INCOMPLETE,
        ),
        (
            request(readiness=readiness(integration_passed=False)),
            config(),
            PolicyPromotionReason.INTEGRATION_INCOMPLETE,
        ),
        (
            request(readiness=readiness(artifact_integrity_passed=False)),
            config(),
            PolicyPromotionReason.ARTIFACT_INTEGRITY_MISSING,
        ),
        (
            request(readiness=readiness(reviewer_count=1)),
            config(),
            PolicyPromotionReason.REVIEWERS_INSUFFICIENT,
        ),
        (
            request(evaluation=paired_evidence(verdict=PairedPolicyVerdict.INSUFFICIENT_EVIDENCE)),
            config(),
            PolicyPromotionReason.INSUFFICIENT_EVIDENCE_VERDICT,
        ),
        (
            request(evaluation=paired_evidence(verdict=PairedPolicyVerdict.NEUTRAL)),
            config(),
            PolicyPromotionReason.NEUTRAL_VERDICT,
        ),
        (
            request(evaluation=paired_evidence(verdict=PairedPolicyVerdict.INCONCLUSIVE)),
            config(),
            PolicyPromotionReason.INCONCLUSIVE_VERDICT,
        ),
    ],
)
def test_each_incomplete_condition_holds_without_activation(
    promotion_request: PolicyPromotionRequest,
    gate_config: PolicyPromotionGateConfig,
    reason: PolicyPromotionReason,
) -> None:
    record = evaluate(promotion_request, gate_config)

    assert record.decision is PolicyPromotionDecision.HOLD
    assert reason in record.reasons
    assert record.advisory_only is True


def test_reject_precedence_over_every_simultaneous_hold_condition() -> None:
    evidence = paired_evidence(
        verdict=PairedPolicyVerdict.HARMFUL,
        matched_pair_count=1,
        mean_score_effect=-0.1,
        score_confidence_lower_bound=-0.2,
        score_confidence_upper_bound=0.0,
        score_standard_error=0.2,
        mean_token_delta=100.0,
        mean_latency_delta_ms=200.0,
        harm_rate=0.5,
        registry_pair_count=2,
        registry_completed_trial_count=1,
        registry_active_count=1,
    )
    operational = readiness(
        tests_passed=False,
        integration_passed=False,
        artifact_integrity_passed=False,
        rollback_ready=False,
        safety_violation=True,
        reviewer_count=0,
        evidence_age_seconds=99_999.0,
    )

    record = evaluate(request(evaluation=evidence, readiness=operational))

    assert record.decision is PolicyPromotionDecision.REJECT
    assert record.reasons[0] is PolicyPromotionReason.SAFETY_VIOLATION
    assert PolicyPromotionReason.HARMFUL_VERDICT in record.reasons
    assert PolicyPromotionReason.NEGATIVE_MEAN_EFFECT in record.reasons
    assert PolicyPromotionReason.INSUFFICIENT_MATCHED_PAIRS not in record.reasons
    assert PolicyPromotionReason.ROLLBACK_NOT_READY not in record.reasons


def test_threshold_equalities_are_explicit() -> None:
    evidence = paired_evidence(
        score_standard_error=0.05,
        mean_token_delta=10.0,
        mean_latency_delta_ms=20.0,
        harm_rate=0.05,
    )
    operational = readiness(evidence_age_seconds=3_600.0, reviewer_count=2)

    record = evaluate(request(evaluation=evidence, readiness=operational))

    assert record.decision is PolicyPromotionDecision.PROMOTE

    lower_bound_equal = paired_evidence(
        mean_score_effect=0.02,
        score_confidence_lower_bound=0.0,
        score_confidence_upper_bound=0.04,
    )
    assert evaluate(request(evaluation=lower_bound_equal)).decision is PolicyPromotionDecision.HOLD


def test_one_ulp_around_cost_and_confidence_thresholds() -> None:
    above_token = math.nextafter(10.0, math.inf)
    below_lower_bound = math.nextafter(0.0, -math.inf)
    above_lower_bound = math.nextafter(0.0, math.inf)

    assert (
        evaluate(request(evaluation=paired_evidence(mean_token_delta=above_token))).decision
        is PolicyPromotionDecision.REJECT
    )
    assert (
        evaluate(
            request(
                evaluation=paired_evidence(
                    mean_score_effect=0.01,
                    score_confidence_lower_bound=below_lower_bound,
                    score_confidence_upper_bound=0.02,
                )
            )
        ).decision
        is PolicyPromotionDecision.HOLD
    )
    assert (
        evaluate(
            request(
                evaluation=paired_evidence(
                    mean_score_effect=0.01,
                    score_confidence_lower_bound=above_lower_bound,
                    score_confidence_upper_bound=0.02,
                )
            )
        ).decision
        is PolicyPromotionDecision.PROMOTE
    )


def test_record_identity_and_json_are_deterministic_and_canonical() -> None:
    first = evaluate()
    second = evaluate()

    assert first == second
    assert first.id == second.id
    assert first.content_hash == second.content_hash
    rendered = first.render_json()
    decoded = json.loads(rendered)
    assert (
        rendered
        == json.dumps(
            decoded,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    assert decoded["advisory_only"] is True
    assert decoded["decision"] == "promote"


def test_safe_serialization_excludes_free_form_and_runtime_material() -> None:
    rendered = evaluate().render_json().lower()

    for marker in (
        "query",
        "prompt",
        "answer",
        "memory_body",
        "stdout",
        "stderr",
        "password",
        "credential",
        "connection",
        "postgresql://",
        "mongodb://",
        "/home/",
        "activate_policy",
        "deploy",
    ):
        assert marker not in rendered


@pytest.mark.parametrize(
    ("factory", "overrides"),
    [
        (identity, {"policy_version": " "}),
        (identity, {"policy_fingerprint": "A" * 64}),
        (identity, {"source_sha": "z" * 40}),
        (paired_evidence, {"evaluation_id": "not-a-uuid"}),
        (paired_evidence, {"evaluation_content_hash": "0" * 63}),
        (paired_evidence, {"verdict": "promising"}),
        (paired_evidence, {"matched_pair_count": True}),
        (paired_evidence, {"matched_pair_count": -1}),
        (paired_evidence, {"mean_score_effect": math.nan}),
        (paired_evidence, {"score_standard_error": math.inf}),
        (paired_evidence, {"harm_rate": 1.01}),
        (
            paired_evidence,
            {
                "mean_score_effect": 0.1,
                "score_confidence_lower_bound": 0.2,
                "score_confidence_upper_bound": 0.3,
            },
        ),
        (paired_evidence, {"registry_pair_count": True}),
        (
            paired_evidence,
            {
                "registry_pair_count": 1,
                "registry_completed_trial_count": 1,
                "registry_failed_count": 1,
            },
        ),
        (readiness, {"tests_passed": 1}),
        (readiness, {"reviewer_count": True}),
        (readiness, {"evidence_age_seconds": math.inf}),
        (config, {"minimum_matched_pairs": True}),
        (config, {"maximum_score_standard_error": 0.0}),
        (config, {"maximum_harm_rate": math.nan}),
        (config, {"minimum_reviewer_count": -1}),
    ],
)
def test_malformed_values_fail_closed_without_decision(
    factory,
    overrides: dict[str, object],
) -> None:
    with pytest.raises(PolicyPromotionValidationError):
        factory(**overrides)


@pytest.mark.parametrize(
    "field_name",
    ("maximum_mean_token_delta", "maximum_mean_latency_delta_ms"),
)
def test_cost_thresholds_must_be_nonnegative(field_name: str) -> None:
    with pytest.raises(PolicyPromotionValidationError, match=field_name):
        config(**{field_name: -0.001})


@pytest.mark.parametrize(
    "terminal_counts",
    (
        {"registry_failed_count": 1},
        {"registry_cancelled_count": 1},
    ),
)
def test_terminal_non_complete_registry_state_holds(
    terminal_counts: dict[str, int],
) -> None:
    values: dict[str, object] = {
        "registry_pair_count": 25,
        "registry_completed_trial_count": 24,
        "registry_failed_count": 0,
        "registry_cancelled_count": 0,
        "registry_active_count": 0,
    }
    values.update(terminal_counts)

    record = evaluate(request(evaluation=paired_evidence(**values)))

    assert record.decision is PolicyPromotionDecision.HOLD
    assert PolicyPromotionReason.REGISTRY_INCOMPLETE in record.reasons
