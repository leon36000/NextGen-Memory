from __future__ import annotations

import random
from uuid import UUID

from nextgen_memory.bounded_inherited_reranker import (
    BoundedInheritedRerankerConfig,
    InheritedAwareRerankedMemory,
    InheritedEvidenceDisposition,
    InheritedScoreBreakdown,
)
from nextgen_memory.inherited_rerank_telemetry import (
    build_inherited_rerank_telemetry,
)
from nextgen_memory.retrieval import ResearchRetrievalHit
from nextgen_memory.utility_reranker import (
    RerankedMemory,
    UtilityScoreBreakdown,
)

SPACE = UUID("90000000-0000-0000-0000-000000000001")
DECISION = UUID("90000000-0000-0000-0000-000000000002")
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
    "token",
    "api_key",
    "feedback_note",
    "direct_reward",
    "avg_reward",
    "positive_count",
    "negative_count",
    "relation_path",
    "edge_path",
)


def _memory_id(seed: int, index: int) -> UUID:
    return UUID(int=(seed + 1) * 64 + index + 1)


def _base_result(
    memory_id: UUID,
    *,
    rank: int,
    score: float,
) -> RerankedMemory:
    hit = ResearchRetrievalHit(
        memory_id=memory_id,
        backend_ref=f"telemetry:{memory_id}",
        rank=rank,
        score=score,
        title=f"Telemetry {memory_id}",
        source_uri=f"https://example.invalid/{memory_id}",
        tags=("telemetry",),
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


def _no_evidence_breakdown() -> InheritedScoreBreakdown:
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
        policy_version="bounded-inherited-reranker-v0",
    )


def _observed_breakdown(
    rng: random.Random,
    *,
    disposition: InheritedEvidenceDisposition,
    contribution_count: int,
    confidence: float,
    applied_component: float,
) -> InheritedScoreBreakdown:
    mean = round(rng.uniform(-1.0, 1.0), 8)
    value_sum = round(mean * contribution_count, 8)
    absolute_value_sum = round(
        abs(value_sum) + rng.uniform(0.0, 2.0),
        8,
    )
    standard_error_sum = round(rng.uniform(0.0, 1.0), 8)
    count_shrinkage = contribution_count / (contribution_count + 8.0)
    path_coherence = (
        1.0
        if absolute_value_sum == 0.0 and value_sum == 0.0
        else abs(value_sum) / absolute_value_sum
    )
    uncertainty_reliability = 1.0 / (
        1.0 + standard_error_sum / (absolute_value_sum + 0.05)
    )
    return InheritedScoreBreakdown(
        contribution_count=contribution_count,
        value_sum=value_sum,
        absolute_value_sum=absolute_value_sum,
        standard_error_sum=standard_error_sum,
        minimum_structural_confidence=confidence,
        inherited_mean=value_sum / contribution_count,
        signed_signal=max(-1.0, min(1.0, mean)),
        count_shrinkage=count_shrinkage,
        path_coherence=path_coherence,
        uncertainty_reliability=uncertainty_reliability,
        confidence_reliability=confidence,
        uncapped_component=(
            applied_component
            if disposition is InheritedEvidenceDisposition.APPLIED
            else round(rng.uniform(-0.1, 0.1), 8)
        ),
        applied_component=applied_component,
        disposition=disposition,
        policy_version="bounded-inherited-reranker-v0",
    )


def _generated_results(
    seed: int,
) -> tuple[InheritedAwareRerankedMemory, ...]:
    rng = random.Random(seed)
    candidate_count = rng.randint(0, 6)
    memory_ids = tuple(
        _memory_id(seed, index) for index in range(candidate_count)
    )
    base_scores = [
        round(rng.uniform(-1.5, 1.5) + index * 1e-7, 8)
        for index in range(candidate_count)
    ]
    base_order = sorted(
        range(candidate_count),
        key=lambda index: (-base_scores[index], str(memory_ids[index])),
    )
    base_rank_by_index = {
        candidate_index: rank
        for rank, candidate_index in enumerate(base_order, start=1)
    }

    breakdowns: list[InheritedScoreBreakdown] = []
    adjustments: list[float] = []
    for _memory_id_value in memory_ids:
        selector = rng.random()
        if selector < 0.20:
            breakdown = _no_evidence_breakdown()
        elif selector < 0.35:
            breakdown = _observed_breakdown(
                rng,
                disposition=(
                    InheritedEvidenceDisposition.BELOW_MINIMUM_COUNT
                ),
                contribution_count=1,
                confidence=round(rng.uniform(0.5, 1.0), 8),
                applied_component=0.0,
            )
        elif selector < 0.55:
            breakdown = _observed_breakdown(
                rng,
                disposition=(
                    InheritedEvidenceDisposition.BELOW_MINIMUM_CONFIDENCE
                ),
                contribution_count=rng.randint(2, 20),
                confidence=round(rng.uniform(0.0, 0.49999999), 8),
                applied_component=0.0,
            )
        else:
            adjustment = round(rng.uniform(-0.05, 0.05), 10)
            breakdown = _observed_breakdown(
                rng,
                disposition=InheritedEvidenceDisposition.APPLIED,
                contribution_count=rng.randint(2, 30),
                confidence=round(rng.uniform(0.5, 1.0), 8),
                applied_component=adjustment,
            )
        breakdowns.append(breakdown)
        adjustments.append(breakdown.applied_component)

    final_scores = [
        base_score + adjustment
        for base_score, adjustment in zip(
            base_scores,
            adjustments,
            strict=True,
        )
    ]
    final_order = sorted(
        range(candidate_count),
        key=lambda index: (
            -final_scores[index],
            base_rank_by_index[index],
            str(memory_ids[index]),
        ),
    )
    final_rank_by_index = {
        candidate_index: rank
        for rank, candidate_index in enumerate(final_order, start=1)
    }

    results = []
    for index, memory_id in enumerate(memory_ids):
        base = _base_result(
            memory_id,
            rank=base_rank_by_index[index],
            score=base_scores[index],
        )
        results.append(
            InheritedAwareRerankedMemory(
                base=base,
                final_rank=final_rank_by_index[index],
                final_score=final_scores[index],
                inherited_breakdown=breakdowns[index],
            )
        )
    return tuple(results)


def test_5000_generated_batches_preserve_identity_partition_and_privacy() -> None:
    config = BoundedInheritedRerankerConfig()
    empty_batches = 0
    top_changes = 0
    applied_observations = 0
    gated_observations = 0

    for seed in range(5000):
        results = _generated_results(seed)
        first = build_inherited_rerank_telemetry(
            space_id=SPACE,
            router_decision_id=DECISION,
            config=config,
            results=tuple(reversed(results)),
        )
        second = build_inherited_rerank_telemetry(
            space_id=SPACE,
            router_decision_id=DECISION,
            config=config,
            results=results,
        )

        assert first == second
        assert first.render_json() == second.render_json()
        assert len(first.observations) == first.summary.candidate_count
        assert [item.final_rank for item in first.observations] == list(
            range(1, len(first.observations) + 1)
        )
        assert len({item.id for item in first.observations}) == len(
            first.observations
        )
        assert len({item.memory_id for item in first.observations}) == len(
            first.observations
        )
        assert all(item.batch_id == first.id for item in first.observations)
        assert all(
            item.policy_fingerprint == first.policy_fingerprint
            for item in first.observations
        )
        assert all(
            abs(item.applied_component)
            <= config.maximum_absolute_adjustment + 1e-12
            for item in first.observations
        )
        assert all(
            abs(
                item.final_score
                - item.base_score
                - item.applied_component
            )
            <= 1e-12
            for item in first.observations
        )
        assert (
            first.summary.applied_count
            + first.summary.no_evidence_count
            + first.summary.below_minimum_count
            + first.summary.below_minimum_confidence
            == first.summary.candidate_count
        )
        assert (
            first.summary.promoted_count
            + first.summary.demoted_count
            + first.summary.unchanged_count
            == first.summary.candidate_count
        )
        assert first.summary.absolute_adjustment_sum + 1e-12 >= abs(
            first.summary.signed_adjustment_sum
        )
        assert (
            first.summary.maximum_absolute_adjustment_observed
            <= config.maximum_absolute_adjustment + 1e-12
        )
        if not results:
            empty_batches += 1
            assert first.observations == ()
            assert first.summary.top_changed is False
            assert first.summary.base_top_memory_id is None
            assert first.summary.final_top_memory_id is None
        else:
            expected_base_top = next(
                item.base.hit.memory_id
                for item in results
                if item.base.final_rank == 1
            )
            expected_final_top = next(
                item.base.hit.memory_id
                for item in results
                if item.final_rank == 1
            )
            assert first.summary.base_top_memory_id == expected_base_top
            assert first.summary.final_top_memory_id == expected_final_top
            assert first.summary.top_changed == (
                expected_base_top != expected_final_top
            )
            top_changes += first.summary.top_changed

        applied_observations += first.summary.applied_count
        gated_observations += (
            first.summary.below_minimum_count
            + first.summary.below_minimum_confidence
        )
        rendered = first.render_json().lower()
        assert all(term not in rendered for term in FORBIDDEN)

    assert empty_batches > 500
    assert top_changes > 0
    assert applied_observations > 3000
    assert gated_observations > 3000


def test_policy_or_context_changes_deterministic_batch_identity() -> None:
    results = _generated_results(42)
    baseline = build_inherited_rerank_telemetry(
        space_id=SPACE,
        router_decision_id=DECISION,
        config=BoundedInheritedRerankerConfig(),
        results=results,
    )
    changed_policy = build_inherited_rerank_telemetry(
        space_id=SPACE,
        router_decision_id=DECISION,
        config=BoundedInheritedRerankerConfig(
            inherited_weight=0.2,
            maximum_absolute_adjustment=0.05,
        ),
        results=results,
    )
    changed_decision = build_inherited_rerank_telemetry(
        space_id=SPACE,
        router_decision_id=UUID(
            "90000000-0000-0000-0000-000000000003"
        ),
        config=BoundedInheritedRerankerConfig(),
        results=results,
    )

    assert baseline.id != changed_policy.id
    assert baseline.policy_fingerprint != changed_policy.policy_fingerprint
    assert baseline.id != changed_decision.id
    assert baseline.content_hash != changed_decision.content_hash
