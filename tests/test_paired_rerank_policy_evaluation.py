from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from nextgen_memory.bounded_inherited_reranker import (
    BoundedInheritedRerankerConfig,
    InheritedAwareRerankedMemory,
    InheritedEvidenceDisposition,
    InheritedScoreBreakdown,
)
from nextgen_memory.causal_credit import OutcomeMeasurement
from nextgen_memory.inherited_rerank_telemetry import (
    InheritedRerankTelemetryBatch,
    build_inherited_rerank_telemetry,
)
from nextgen_memory.paired_rerank_policy_evaluation import (
    PairedPolicyAbstentionReason,
    PairedPolicyEvaluationConfig,
    PairedPolicyVerdict,
    PairedRerankPolicyEvaluation,
    PairedRerankPolicyEvaluationValidationError,
    PairedRerankPolicyEvaluator,
    PairedRerankPolicyTrial,
    fingerprint_paired_policy_evaluation_config,
)
from nextgen_memory.retrieval import ResearchRetrievalHit
from nextgen_memory.utility_reranker import (
    RerankedMemory,
    UtilityScoreBreakdown,
)

SPACE = UUID("11111111-1111-1111-1111-111111111111")
OTHER_SPACE = UUID("22222222-2222-2222-2222-222222222222")
DECISION = UUID("33333333-3333-3333-3333-333333333333")
OTHER_DECISION = UUID("44444444-4444-4444-4444-444444444444")
MEMORY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
MEMORY_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CONTINUATION_HASH = hashlib.sha256(b"fixed-continuation-v0").hexdigest()


def context_hash(index: int) -> str:
    return hashlib.sha256(f"context-{index}".encode()).hexdigest()


def base_result(
    memory_id: UUID,
    *,
    rank: int,
    score: float,
) -> RerankedMemory:
    hit = ResearchRetrievalHit(
        memory_id=memory_id,
        backend_ref=f"policy-eval:{memory_id}",
        rank=rank,
        score=score,
        title=f"Policy eval {memory_id}",
        source_uri=f"https://example.invalid/{memory_id}",
        tags=("policy-evaluation",),
    )
    return RerankedMemory(
        hit=hit,
        original_rank=rank,
        final_rank=rank,
        final_score=score,
        breakdown=UtilityScoreBreakdown(
            relevance=score,
            utility=0.0,
            harm_risk=0.0,
            token_cost=0.0,
            latency_cost=0.0,
            weighted_relevance=score,
            weighted_utility=0.0,
            weighted_harm_penalty=0.0,
            weighted_token_penalty=0.0,
            weighted_latency_penalty=0.0,
        ),
    )


def no_evidence_breakdown(policy_version: str) -> InheritedScoreBreakdown:
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
        policy_version=policy_version,
    )


def applied_breakdown(
    policy_version: str,
    *,
    component: float,
) -> InheritedScoreBreakdown:
    return InheritedScoreBreakdown(
        contribution_count=8,
        value_sum=1.6,
        absolute_value_sum=1.6,
        standard_error_sum=0.1,
        minimum_structural_confidence=0.9,
        inherited_mean=0.2,
        signed_signal=0.5,
        count_shrinkage=0.5,
        path_coherence=1.0,
        uncertainty_reliability=0.9,
        confidence_reliability=0.9,
        uncapped_component=component,
        applied_component=component,
        disposition=InheritedEvidenceDisposition.APPLIED,
        policy_version=policy_version,
    )


def control_config() -> BoundedInheritedRerankerConfig:
    return BoundedInheritedRerankerConfig(
        inherited_weight=0.0,
        maximum_absolute_adjustment=0.0,
        policy_version="bounded-inherited-control-v0",
    )


def treatment_config() -> BoundedInheritedRerankerConfig:
    return BoundedInheritedRerankerConfig(
        policy_version="bounded-inherited-treatment-v0"
    )


def telemetry_batch(
    *,
    config: BoundedInheritedRerankerConfig,
    space_id: UUID = SPACE,
    decision_id: UUID = DECISION,
    treatment: bool,
    base_b_score: float = 0.79,
    include_b: bool = True,
) -> InheritedRerankTelemetryBatch:
    base_a = base_result(MEMORY_A, rank=1, score=0.80)
    base_b = base_result(MEMORY_B, rank=2, score=base_b_score)
    if not treatment:
        results: tuple[InheritedAwareRerankedMemory, ...] = (
            InheritedAwareRerankedMemory(
                base=base_a,
                final_rank=1,
                final_score=base_a.final_score,
                inherited_breakdown=no_evidence_breakdown(
                    config.policy_version
                ),
            ),
        )
        if include_b:
            results = (
                *results,
                InheritedAwareRerankedMemory(
                    base=base_b,
                    final_rank=2,
                    final_score=base_b.final_score,
                    inherited_breakdown=no_evidence_breakdown(
                        config.policy_version
                    ),
                ),
            )
    else:
        results = (
            InheritedAwareRerankedMemory(
                base=base_b,
                final_rank=1,
                final_score=base_b.final_score + 0.03,
                inherited_breakdown=applied_breakdown(
                    config.policy_version,
                    component=0.03,
                ),
            ),
            InheritedAwareRerankedMemory(
                base=base_a,
                final_rank=2,
                final_score=base_a.final_score,
                inherited_breakdown=no_evidence_breakdown(
                    config.policy_version
                ),
            ),
        )
        if not include_b:
            results = (results[1],)
            results = (
                replace(results[0], final_rank=1),
            )
    return build_inherited_rerank_telemetry(
        space_id=space_id,
        router_decision_id=decision_id,
        config=config,
        results=results,
    )


def outcome(
    *,
    score: float,
    success: bool = True,
    tokens: int = 100,
    latency_ms: float = 1000.0,
) -> OutcomeMeasurement:
    return OutcomeMeasurement(
        score=score,
        task_success=success,
        tokens=tokens,
        latency_ms=latency_ms,
    )


def trial(
    index: int,
    *,
    score_delta: float,
    control_score: float = 0.0,
    control_success: bool = True,
    treatment_success: bool = True,
    control_tokens: int = 100,
    treatment_tokens: int = 100,
    control_latency_ms: float = 1000.0,
    treatment_latency_ms: float = 1000.0,
    control_batch: InheritedRerankTelemetryBatch | None = None,
    treatment_batch: InheritedRerankTelemetryBatch | None = None,
    continuation_hash: str = CONTINUATION_HASH,
    trial_id: UUID | None = None,
) -> PairedRerankPolicyTrial:
    return PairedRerankPolicyTrial(
        trial_id=trial_id or UUID(int=index + 1),
        space_id=SPACE,
        context_set_hash=context_hash(index),
        continuation_set_hash=continuation_hash,
        control_batch=(
            control_batch
            or telemetry_batch(
                config=control_config(),
                treatment=False,
            )
        ),
        treatment_batch=(
            treatment_batch
            or telemetry_batch(
                config=treatment_config(),
                treatment=True,
            )
        ),
        control_outcome=outcome(
            score=control_score,
            success=control_success,
            tokens=control_tokens,
            latency_ms=control_latency_ms,
        ),
        treatment_outcome=outcome(
            score=control_score + score_delta,
            success=treatment_success,
            tokens=treatment_tokens,
            latency_ms=treatment_latency_ms,
        ),
    )


def trials_from_deltas(
    deltas: tuple[float, ...],
    **kwargs: object,
) -> tuple[PairedRerankPolicyTrial, ...]:
    return tuple(
        trial(index, score_delta=delta, **kwargs)
        for index, delta in enumerate(deltas)
    )


def test_trial_is_matched_immutable_and_exposes_exact_deltas() -> None:
    item = trial(
        0,
        score_delta=0.1,
        control_success=False,
        treatment_success=True,
        control_tokens=100,
        treatment_tokens=90,
        control_latency_ms=1000.0,
        treatment_latency_ms=900.0,
    )

    assert item.score_delta == pytest.approx(0.1)
    assert item.success_delta == 1.0
    assert item.token_delta == -10
    assert item.latency_delta_ms == -100.0
    assert item.treatment_top_changed is True
    assert item.treatment_applied_observation_count == 1
    assert item.treatment_absolute_adjustment == pytest.approx(0.03)
    assert len(item.content_hash) == 64
    with pytest.raises(FrozenInstanceError):
        item.space_id = OTHER_SPACE  # type: ignore[misc]


def test_trial_rejects_same_policy_or_unmatched_telemetry() -> None:
    control = telemetry_batch(
        config=control_config(),
        treatment=False,
    )
    treatment = telemetry_batch(
        config=treatment_config(),
        treatment=True,
    )

    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="distinct policies",
    ):
        trial(
            0,
            score_delta=0.1,
            control_batch=control,
            treatment_batch=control,
        )

    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="router decision",
    ):
        trial(
            0,
            score_delta=0.1,
            control_batch=control,
            treatment_batch=telemetry_batch(
                config=treatment_config(),
                treatment=True,
                decision_id=OTHER_DECISION,
            ),
        )

    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="candidate set",
    ):
        trial(
            0,
            score_delta=0.1,
            control_batch=control,
            treatment_batch=telemetry_batch(
                config=treatment_config(),
                treatment=True,
                include_b=False,
            ),
        )

    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="base score",
    ):
        trial(
            0,
            score_delta=0.1,
            control_batch=control,
            treatment_batch=telemetry_batch(
                config=treatment_config(),
                treatment=True,
                base_b_score=0.78,
            ),
        )

    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="space",
    ):
        PairedRerankPolicyTrial(
            trial_id=UUID(int=1),
            space_id=OTHER_SPACE,
            context_set_hash=context_hash(0),
            continuation_set_hash=CONTINUATION_HASH,
            control_batch=control,
            treatment_batch=treatment,
            control_outcome=outcome(score=0.0),
            treatment_outcome=outcome(score=0.1),
        )


def test_trial_rejects_invalid_hashes_and_outcome_types() -> None:
    values = {
        "trial_id": UUID(int=1),
        "space_id": SPACE,
        "context_set_hash": context_hash(0),
        "continuation_set_hash": CONTINUATION_HASH,
        "control_batch": telemetry_batch(
            config=control_config(),
            treatment=False,
        ),
        "treatment_batch": telemetry_batch(
            config=treatment_config(),
            treatment=True,
        ),
        "control_outcome": outcome(score=0.0),
        "treatment_outcome": outcome(score=0.1),
    }
    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="context_set_hash",
    ):
        PairedRerankPolicyTrial(**{**values, "context_set_hash": "bad"})
    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="control_outcome",
    ):
        PairedRerankPolicyTrial(**{**values, "control_outcome": None})


def test_config_defaults_fingerprint_and_validation() -> None:
    config = PairedPolicyEvaluationConfig()

    assert config.minimum_pairs == 8
    assert config.confidence_z == 1.96
    assert config.minimum_promising_effect == 0.02
    assert config.harmful_effect_threshold == -0.02
    assert config.neutral_effect_band == 0.01
    assert config.maximum_standard_error == 0.10
    assert config.maximum_token_increase_ratio == 0.05
    assert config.maximum_latency_increase_ratio == 0.10
    assert config.minimum_success_delta == 0.0
    assert len(fingerprint_paired_policy_evaluation_config(config)) == 64
    assert fingerprint_paired_policy_evaluation_config(config) == (
        fingerprint_paired_policy_evaluation_config(config)
    )
    with pytest.raises(FrozenInstanceError):
        config.minimum_pairs = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"minimum_pairs": 0},
        {"minimum_pairs": True},
        {"confidence_z": 0.0},
        {"minimum_promising_effect": -0.1},
        {"harmful_effect_threshold": 0.0},
        {"neutral_effect_band": -0.1},
        {"minimum_promising_effect": 0.01, "neutral_effect_band": 0.02},
        {"maximum_standard_error": -0.1},
        {"maximum_token_increase_ratio": -0.1},
        {"maximum_latency_increase_ratio": -0.1},
        {"minimum_success_delta": 1.1},
        {"policy_version": " "},
    ],
)
def test_config_rejects_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(PairedRerankPolicyEvaluationValidationError):
        PairedPolicyEvaluationConfig(**overrides)


def test_promising_evaluation_uses_paired_statistics_and_diagnostics() -> None:
    evaluation = PairedRerankPolicyEvaluator().evaluate(
        trials_from_deltas((0.1,) * 8)
    )

    assert isinstance(evaluation, PairedRerankPolicyEvaluation)
    assert evaluation.verdict is PairedPolicyVerdict.PROMISING
    assert evaluation.abstention_reason is None
    assert evaluation.trial_count == 8
    assert evaluation.mean_score_delta == pytest.approx(0.1)
    assert evaluation.score_standard_deviation == 0.0
    assert evaluation.score_standard_error == 0.0
    assert evaluation.score_confidence_lower == pytest.approx(0.1)
    assert evaluation.score_confidence_upper == pytest.approx(0.1)
    assert evaluation.mean_success_delta == 0.0
    assert evaluation.mean_token_delta == 0.0
    assert evaluation.mean_latency_delta_ms == 0.0
    assert evaluation.token_increase_ratio == 0.0
    assert evaluation.latency_increase_ratio == 0.0
    assert evaluation.treatment_top_change_rate == 1.0
    assert evaluation.treatment_applied_observation_rate == 0.5
    assert evaluation.treatment_mean_absolute_adjustment == pytest.approx(0.03)
    assert len(evaluation.id.hex) == 32
    assert len(evaluation.content_hash) == 64
    assert json.loads(evaluation.render_json())["verdict"] == "promising"


def test_insufficient_pair_and_high_standard_error_abstentions() -> None:
    insufficient = PairedRerankPolicyEvaluator().evaluate(
        trials_from_deltas((0.1, 0.1))
    )
    noisy = PairedRerankPolicyEvaluator(
        PairedPolicyEvaluationConfig(maximum_standard_error=0.05)
    ).evaluate(trials_from_deltas((0.5, -0.5) * 4))

    assert insufficient.verdict is PairedPolicyVerdict.INSUFFICIENT_EVIDENCE
    assert (
        insufficient.abstention_reason
        is PairedPolicyAbstentionReason.INSUFFICIENT_PAIRS
    )
    assert noisy.verdict is PairedPolicyVerdict.INSUFFICIENT_EVIDENCE
    assert (
        noisy.abstention_reason
        is PairedPolicyAbstentionReason.STANDARD_ERROR_TOO_HIGH
    )
    assert noisy.score_standard_error > 0.05


def test_harmful_costly_neutral_and_inconclusive_verdicts() -> None:
    evaluator = PairedRerankPolicyEvaluator()
    harmful = evaluator.evaluate(trials_from_deltas((-0.1,) * 8))
    costly = evaluator.evaluate(
        trials_from_deltas(
            (0.005,) * 8,
            control_tokens=100,
            treatment_tokens=120,
        )
    )
    neutral = evaluator.evaluate(trials_from_deltas((0.0,) * 8))
    inconclusive = evaluator.evaluate(
        trials_from_deltas((0.0, 0.04) * 4)
    )

    assert harmful.verdict is PairedPolicyVerdict.HARMFUL
    assert harmful.score_confidence_upper <= -0.02
    assert costly.verdict is PairedPolicyVerdict.TOO_COSTLY
    assert costly.token_increase_ratio == pytest.approx(0.20)
    assert neutral.verdict is PairedPolicyVerdict.NEUTRAL
    assert neutral.score_confidence_lower == 0.0
    assert neutral.score_confidence_upper == 0.0
    assert inconclusive.verdict is PairedPolicyVerdict.INCONCLUSIVE
    assert inconclusive.score_confidence_lower < 0.02
    assert inconclusive.score_confidence_upper > 0.01


def test_success_and_latency_gates_are_respected() -> None:
    success_blocked = PairedRerankPolicyEvaluator(
        PairedPolicyEvaluationConfig(minimum_success_delta=0.1)
    ).evaluate(
        trials_from_deltas(
            (0.1,) * 8,
            control_success=True,
            treatment_success=True,
        )
    )
    latency_costly = PairedRerankPolicyEvaluator().evaluate(
        trials_from_deltas(
            (0.005,) * 8,
            control_latency_ms=1000.0,
            treatment_latency_ms=1200.0,
        )
    )

    assert success_blocked.verdict is PairedPolicyVerdict.INCONCLUSIVE
    assert success_blocked.mean_success_delta == 0.0
    assert latency_costly.verdict is PairedPolicyVerdict.TOO_COSTLY
    assert latency_costly.latency_increase_ratio == pytest.approx(0.20)


def test_exact_retries_deduplicate_and_trial_order_is_irrelevant() -> None:
    trials = trials_from_deltas((0.1,) * 8)
    evaluator = PairedRerankPolicyEvaluator()

    first = evaluator.evaluate(trials)
    second = evaluator.evaluate(tuple(reversed(trials)))
    with_retry = evaluator.evaluate((*trials, trials[0]))

    assert first == second == with_retry
    assert first.render_json() == second.render_json()
    assert first.trial_ids == tuple(sorted((item.trial_id for item in trials), key=str))


def test_conflicting_trial_id_and_mixed_policy_pairs_fail_closed() -> None:
    base_trials = list(trials_from_deltas((0.1,) * 8))
    conflicting = replace(
        base_trials[0],
        treatment_outcome=outcome(score=0.2),
    )
    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="conflicting trial_id",
    ):
        PairedRerankPolicyEvaluator().evaluate(
            (*base_trials, conflicting)
        )

    alternate_treatment = telemetry_batch(
        config=BoundedInheritedRerankerConfig(
            inherited_weight=0.2,
            maximum_absolute_adjustment=0.05,
            policy_version="alternate-treatment-v0",
        ),
        treatment=True,
    )
    base_trials[1] = trial(
        1,
        score_delta=0.1,
        treatment_batch=alternate_treatment,
    )
    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="treatment policy",
    ):
        PairedRerankPolicyEvaluator().evaluate(tuple(base_trials))


def test_mixed_continuation_contract_fails_closed() -> None:
    trials = list(trials_from_deltas((0.1,) * 8))
    trials[1] = trial(
        1,
        score_delta=0.1,
        continuation_hash=hashlib.sha256(b"other-continuation").hexdigest(),
    )
    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="continuation",
    ):
        PairedRerankPolicyEvaluator().evaluate(tuple(trials))


def test_evaluation_requires_at_least_one_trial_and_valid_types() -> None:
    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="at least one",
    ):
        PairedRerankPolicyEvaluator().evaluate(())
    with pytest.raises(
        PairedRerankPolicyEvaluationValidationError,
        match="trials",
    ):
        PairedRerankPolicyEvaluator().evaluate(("bad",))  # type: ignore[arg-type]


def test_evaluation_json_contains_no_memory_credit_or_raw_content() -> None:
    rendered = PairedRerankPolicyEvaluator().evaluate(
        trials_from_deltas((0.1,) * 8)
    ).render_json().lower()

    for forbidden in (
        "query",
        "prompt",
        "answer",
        "memory_body",
        "body_text",
        "command",
        "stdout",
        "stderr",
        "patch",
        "environment",
        "secret",
        "api_key",
        "feedback_note",
        "memory_credit",
        "memory_id",
        "relation_path",
        "edge_path",
    ):
        assert forbidden not in rendered
