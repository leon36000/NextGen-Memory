from __future__ import annotations

import hashlib
from math import sqrt
from statistics import stdev
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
    build_inherited_rerank_telemetry,
)
from nextgen_memory.paired_rerank_policy_evaluation import (
    PairedPolicyAbstentionReason,
    PairedPolicyEvaluationConfig,
    PairedPolicyVerdict,
    PairedRerankPolicyEvaluator,
    PairedRerankPolicyTrial,
)
from nextgen_memory.retrieval import ResearchRetrievalHit
from nextgen_memory.utility_reranker import (
    RerankedMemory,
    UtilityScoreBreakdown,
)

SPACE = UUID("90000000-0000-0000-0000-000000000001")
DECISION = UUID("90000000-0000-0000-0000-000000000002")
MEMORY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
MEMORY_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CONTINUATION_HASH = hashlib.sha256(b"paired-policy-property-continuation-v0").hexdigest()
FORBIDDEN = (
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
)


def _base_result(
    memory_id: UUID,
    *,
    rank: int,
    score: float,
) -> RerankedMemory:
    hit = ResearchRetrievalHit(
        memory_id=memory_id,
        backend_ref=f"paired-property:{memory_id}",
        rank=rank,
        score=score,
        title=f"Paired property {memory_id}",
        source_uri=f"https://example.invalid/{memory_id}",
        tags=("paired-policy",),
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


def _no_evidence(policy_version: str) -> InheritedScoreBreakdown:
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


def _applied(policy_version: str) -> InheritedScoreBreakdown:
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
        uncapped_component=0.03,
        applied_component=0.03,
        disposition=InheritedEvidenceDisposition.APPLIED,
        policy_version=policy_version,
    )


def _telemetry_batches():
    control_config = BoundedInheritedRerankerConfig(
        inherited_weight=0.0,
        maximum_absolute_adjustment=0.0,
        policy_version="paired-property-control-v0",
    )
    treatment_config = BoundedInheritedRerankerConfig(policy_version="paired-property-treatment-v0")
    base_a = _base_result(MEMORY_A, rank=1, score=0.80)
    base_b = _base_result(MEMORY_B, rank=2, score=0.79)
    control_results = (
        InheritedAwareRerankedMemory(
            base=base_a,
            final_rank=1,
            final_score=0.80,
            inherited_breakdown=_no_evidence(control_config.policy_version),
        ),
        InheritedAwareRerankedMemory(
            base=base_b,
            final_rank=2,
            final_score=0.79,
            inherited_breakdown=_no_evidence(control_config.policy_version),
        ),
    )
    treatment_results = (
        InheritedAwareRerankedMemory(
            base=base_b,
            final_rank=1,
            final_score=0.82,
            inherited_breakdown=_applied(treatment_config.policy_version),
        ),
        InheritedAwareRerankedMemory(
            base=base_a,
            final_rank=2,
            final_score=0.80,
            inherited_breakdown=_no_evidence(treatment_config.policy_version),
        ),
    )
    return (
        build_inherited_rerank_telemetry(
            space_id=SPACE,
            router_decision_id=DECISION,
            config=control_config,
            results=control_results,
        ),
        build_inherited_rerank_telemetry(
            space_id=SPACE,
            router_decision_id=DECISION,
            config=treatment_config,
            results=treatment_results,
        ),
    )


CONTROL_BATCH, TREATMENT_BATCH = _telemetry_batches()


def _trial_id(experiment: int, trial_index: int) -> UUID:
    return UUID(int=((experiment + 1) << 32) + trial_index + 1)


def _context_hash(experiment: int, trial_index: int) -> str:
    return hashlib.sha256(f"paired-property:{experiment}:{trial_index}".encode()).hexdigest()


def _outcome(
    *,
    score: float,
    success: bool,
    tokens: int,
    latency_ms: float,
) -> OutcomeMeasurement:
    return OutcomeMeasurement(
        score=score,
        task_success=success,
        tokens=tokens,
        latency_ms=latency_ms,
    )


def _scenario(experiment: int):
    category = experiment % 7
    if category == 0:
        return {
            "deltas": (0.1, 0.1),
            "config": PairedPolicyEvaluationConfig(),
            "verdict": PairedPolicyVerdict.INSUFFICIENT_EVIDENCE,
            "abstention": PairedPolicyAbstentionReason.INSUFFICIENT_PAIRS,
            "treatment_tokens": 100,
            "treatment_latency": 1000.0,
        }
    if category == 1:
        return {
            "deltas": (0.5, -0.5) * 4,
            "config": PairedPolicyEvaluationConfig(maximum_standard_error=0.05),
            "verdict": PairedPolicyVerdict.INSUFFICIENT_EVIDENCE,
            "abstention": (PairedPolicyAbstentionReason.STANDARD_ERROR_TOO_HIGH),
            "treatment_tokens": 100,
            "treatment_latency": 1000.0,
        }
    if category == 2:
        return {
            "deltas": (-0.1,) * 8,
            "config": PairedPolicyEvaluationConfig(),
            "verdict": PairedPolicyVerdict.HARMFUL,
            "abstention": None,
            "treatment_tokens": 100,
            "treatment_latency": 1000.0,
        }
    if category == 3:
        return {
            "deltas": (0.005,) * 8,
            "config": PairedPolicyEvaluationConfig(),
            "verdict": PairedPolicyVerdict.TOO_COSTLY,
            "abstention": None,
            "treatment_tokens": 120,
            "treatment_latency": 1000.0,
        }
    if category == 4:
        return {
            "deltas": (0.1,) * 8,
            "config": PairedPolicyEvaluationConfig(),
            "verdict": PairedPolicyVerdict.PROMISING,
            "abstention": None,
            "treatment_tokens": 100,
            "treatment_latency": 1000.0,
        }
    if category == 5:
        return {
            "deltas": (0.0,) * 8,
            "config": PairedPolicyEvaluationConfig(),
            "verdict": PairedPolicyVerdict.NEUTRAL,
            "abstention": None,
            "treatment_tokens": 100,
            "treatment_latency": 1000.0,
        }
    return {
        "deltas": (0.0, 0.04) * 4,
        "config": PairedPolicyEvaluationConfig(),
        "verdict": PairedPolicyVerdict.INCONCLUSIVE,
        "abstention": None,
        "treatment_tokens": 100,
        "treatment_latency": 1000.0,
    }


def _trials(experiment: int, scenario: dict[str, object]):
    deltas = tuple(float(value) for value in scenario["deltas"])
    treatment_tokens = int(scenario["treatment_tokens"])
    treatment_latency = float(scenario["treatment_latency"])
    return tuple(
        PairedRerankPolicyTrial(
            trial_id=_trial_id(experiment, trial_index),
            space_id=SPACE,
            context_set_hash=_context_hash(experiment, trial_index),
            continuation_set_hash=CONTINUATION_HASH,
            control_batch=CONTROL_BATCH,
            treatment_batch=TREATMENT_BATCH,
            control_outcome=_outcome(
                score=0.0,
                success=True,
                tokens=100,
                latency_ms=1000.0,
            ),
            treatment_outcome=_outcome(
                score=delta,
                success=True,
                tokens=treatment_tokens,
                latency_ms=treatment_latency,
            ),
        )
        for trial_index, delta in enumerate(deltas)
    )


def test_5000_generated_experiments_preserve_statistics_verdicts_and_privacy() -> None:
    verdict_counts = {verdict: 0 for verdict in PairedPolicyVerdict}
    abstention_counts = {reason: 0 for reason in PairedPolicyAbstentionReason}

    for experiment in range(5000):
        scenario = _scenario(experiment)
        trials = _trials(experiment, scenario)
        config = scenario["config"]
        assert isinstance(config, PairedPolicyEvaluationConfig)
        evaluator = PairedRerankPolicyEvaluator(config)

        first = evaluator.evaluate(trials)
        second = evaluator.evaluate((*reversed(trials), trials[0]))

        assert first == second
        assert first.render_json() == second.render_json()
        assert first.trial_count == len(trials)
        assert first.trial_ids == tuple(sorted((item.trial_id for item in trials), key=str))
        assert first.verdict is scenario["verdict"]
        assert first.abstention_reason is scenario["abstention"]

        deltas = [item.score_delta for item in trials]
        expected_mean = sum(deltas) / len(deltas)
        expected_stdev = stdev(deltas) if len(deltas) > 1 else 0.0
        expected_se = expected_stdev / sqrt(len(deltas))
        assert first.mean_score_delta == pytest.approx(expected_mean)
        assert first.score_standard_deviation == pytest.approx(expected_stdev)
        assert first.score_standard_error == pytest.approx(expected_se)
        assert first.score_confidence_lower == pytest.approx(
            expected_mean - config.confidence_z * expected_se
        )
        assert first.score_confidence_upper == pytest.approx(
            expected_mean + config.confidence_z * expected_se
        )
        assert first.mean_success_delta == 0.0
        assert first.mean_token_delta == pytest.approx(int(scenario["treatment_tokens"]) - 100)
        assert first.mean_latency_delta_ms == pytest.approx(
            float(scenario["treatment_latency"]) - 1000.0
        )
        assert first.token_increase_ratio == pytest.approx(
            (int(scenario["treatment_tokens"]) - 100) / 100
        )
        assert first.latency_increase_ratio == pytest.approx(
            (float(scenario["treatment_latency"]) - 1000.0) / 1000.0
        )
        assert first.treatment_top_change_rate == 1.0
        assert first.treatment_applied_observation_rate == 0.5
        assert first.treatment_mean_absolute_adjustment == pytest.approx(0.03)
        assert len(first.id.hex) == 32
        assert len(first.content_hash) == 64
        assert len(first.context_collection_hash) == 64
        assert len(first.config_fingerprint) == 64

        rendered = first.render_json().lower()
        assert all(term not in rendered for term in FORBIDDEN)
        verdict_counts[first.verdict] += 1
        if first.abstention_reason is not None:
            abstention_counts[first.abstention_reason] += 1

    assert all(count > 600 for count in verdict_counts.values())
    assert all(count > 600 for count in abstention_counts.values())
