"""Deterministic matched-replay simulation for reranking policy evaluation."""

from __future__ import annotations

import json
import random
from math import sqrt
from statistics import stdev
from uuid import UUID

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
    PairedPolicyEvaluationConfig,
    PairedRerankPolicyEvaluator,
    PairedRerankPolicyTrial,
)
from nextgen_memory.retrieval import ResearchRetrievalHit
from nextgen_memory.utility_reranker import (
    RerankedMemory,
    UtilityScoreBreakdown,
)

SPACE = UUID("70000000-0000-0000-0000-000000000001")
DECISION = UUID("70000000-0000-0000-0000-000000000002")
MEMORY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
MEMORY_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
CONTINUATION_HASH = (
    "f5ff3b39e4b835e699ca83eaef938ff20228809ec5f45b3c"
    "e6e2452c03446b6d"
)


def _base_result(
    memory_id: UUID,
    *,
    rank: int,
    score: float,
) -> RerankedMemory:
    hit = ResearchRetrievalHit(
        memory_id=memory_id,
        backend_ref=f"paired-simulation:{memory_id}",
        rank=rank,
        score=score,
        title=f"Paired simulation {memory_id}",
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
        contribution_count=12,
        value_sum=2.4,
        absolute_value_sum=2.4,
        standard_error_sum=0.1,
        minimum_structural_confidence=0.95,
        inherited_mean=0.2,
        signed_signal=0.5,
        count_shrinkage=0.6,
        path_coherence=1.0,
        uncertainty_reliability=0.95,
        confidence_reliability=0.95,
        uncapped_component=0.03,
        applied_component=0.03,
        disposition=InheritedEvidenceDisposition.APPLIED,
        policy_version=policy_version,
    )


def _telemetry_batches():
    control_config = BoundedInheritedRerankerConfig(
        inherited_weight=0.0,
        maximum_absolute_adjustment=0.0,
        policy_version="paired-simulation-control-v0",
    )
    treatment_config = BoundedInheritedRerankerConfig(
        policy_version="paired-simulation-treatment-v0"
    )
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


def _context_hash(prefix: str, index: int) -> str:
    import hashlib

    return hashlib.sha256(f"{prefix}:{index}".encode()).hexdigest()


def _outcome(
    *,
    score: float,
    tokens: int = 100,
    latency_ms: float = 1000.0,
    success: bool = True,
) -> OutcomeMeasurement:
    return OutcomeMeasurement(
        score=score,
        task_success=success,
        tokens=tokens,
        latency_ms=latency_ms,
    )


def _trial(
    *,
    trial_id: UUID,
    context_prefix: str,
    index: int,
    control_score: float,
    treatment_score: float,
    control_tokens: int = 100,
    treatment_tokens: int = 100,
    control_latency_ms: float = 1000.0,
    treatment_latency_ms: float = 1000.0,
) -> PairedRerankPolicyTrial:
    return PairedRerankPolicyTrial(
        trial_id=trial_id,
        space_id=SPACE,
        context_set_hash=_context_hash(context_prefix, index),
        continuation_set_hash=CONTINUATION_HASH,
        control_batch=CONTROL_BATCH,
        treatment_batch=TREATMENT_BATCH,
        control_outcome=_outcome(
            score=control_score,
            tokens=control_tokens,
            latency_ms=control_latency_ms,
        ),
        treatment_outcome=_outcome(
            score=treatment_score,
            tokens=treatment_tokens,
            latency_ms=treatment_latency_ms,
        ),
    )


def _trials_from_deltas(
    name: str,
    deltas: tuple[float, ...],
    *,
    treatment_tokens: int = 100,
    treatment_latency_ms: float = 1000.0,
) -> tuple[PairedRerankPolicyTrial, ...]:
    return tuple(
        _trial(
            trial_id=UUID(int=(hash(name) & ((1 << 64) - 1)) << 32 | index + 1),
            context_prefix=name,
            index=index,
            control_score=0.0,
            treatment_score=delta,
            treatment_tokens=treatment_tokens,
            treatment_latency_ms=treatment_latency_ms,
        )
        for index, delta in enumerate(deltas)
    )


def _variance_experiment() -> dict[str, float | int | str]:
    rng = random.Random(20_260_815)
    control_scores: list[float] = []
    treatment_scores: list[float] = []
    trials: list[PairedRerankPolicyTrial] = []

    for index in range(64):
        shared_context_noise = rng.gauss(0.0, 0.15)
        control_noise = rng.gauss(0.0, 0.02)
        treatment_noise = rng.gauss(0.0, 0.02)
        control_score = shared_context_noise + control_noise
        treatment_score = shared_context_noise + 0.05 + treatment_noise
        if not -1.0 <= control_score <= 1.0:
            raise RuntimeError("deterministic control score left the bounded domain")
        if not -1.0 <= treatment_score <= 1.0:
            raise RuntimeError("deterministic treatment score left the bounded domain")
        control_scores.append(control_score)
        treatment_scores.append(treatment_score)
        trials.append(
            _trial(
                trial_id=UUID(int=(1 << 96) + index + 1),
                context_prefix="variance",
                index=index,
                control_score=control_score,
                treatment_score=treatment_score,
            )
        )

    evaluation = PairedRerankPolicyEvaluator().evaluate(tuple(trials))
    unpaired_standard_error = sqrt(
        stdev(control_scores) ** 2 / len(control_scores)
        + stdev(treatment_scores) ** 2 / len(treatment_scores)
    )
    return {
        "trial_count": len(trials),
        "mean_score_delta": evaluation.mean_score_delta,
        "paired_standard_error": evaluation.score_standard_error,
        "unpaired_standard_error": unpaired_standard_error,
        "standard_error_ratio": (
            evaluation.score_standard_error / unpaired_standard_error
        ),
        "verdict": evaluation.verdict.value,
    }


def _verdict_scenarios() -> dict[str, str]:
    scenarios = {
        "insufficient_evidence": (
            PairedRerankPolicyEvaluator(),
            _trials_from_deltas("insufficient", (0.1, 0.1)),
        ),
        "harmful": (
            PairedRerankPolicyEvaluator(),
            _trials_from_deltas("harmful", (-0.1,) * 8),
        ),
        "too_costly": (
            PairedRerankPolicyEvaluator(),
            _trials_from_deltas(
                "costly",
                (0.005,) * 8,
                treatment_tokens=120,
            ),
        ),
        "promising": (
            PairedRerankPolicyEvaluator(),
            _trials_from_deltas("promising", (0.1,) * 8),
        ),
        "neutral": (
            PairedRerankPolicyEvaluator(),
            _trials_from_deltas("neutral", (0.0,) * 8),
        ),
        "inconclusive": (
            PairedRerankPolicyEvaluator(),
            _trials_from_deltas("inconclusive", (0.0, 0.04) * 4),
        ),
    }
    return {
        name: evaluator.evaluate(trials).verdict.value
        for name, (evaluator, trials) in scenarios.items()
    }


def simulate_paired_rerank_policy_evaluation_v0() -> dict[str, object]:
    verdict_scenarios = _verdict_scenarios()
    return {
        "schema": "nextgen-memory-paired-rerank-policy-evaluation-simulation-v0",
        "variance_experiment": _variance_experiment(),
        "scenario_count": len(verdict_scenarios),
        "verdict_scenarios": verdict_scenarios,
        "memory_level_credit_emitted": False,
    }


def main() -> None:
    print(
        json.dumps(
            simulate_paired_rerank_policy_evaluation_v0(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
