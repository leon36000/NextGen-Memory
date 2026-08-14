from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from math import isfinite
from types import MappingProxyType
from uuid import UUID

from nextgen_memory.bounded_inherited_reranker import (
    BoundedInheritedReranker,
    BoundedInheritedRerankerConfig,
    InheritedEvidenceDisposition,
)
from nextgen_memory.learning_evidence import (
    DirectUtilityEvidence,
    InheritedUtilityEvidence,
    NodeLearningEvidence,
)
from nextgen_memory.retrieval import ResearchRetrievalHit
from nextgen_memory.utility_reranker import (
    RerankedMemory,
    UtilityEvidence,
    UtilityScoreBreakdown,
)

SPACE = UUID("90000000-0000-0000-0000-000000000001")
NOW = datetime(2026, 8, 14, 23, 55, tzinfo=UTC)


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
        backend_ref=f"paper:{memory_id}",
        title=f"Paper {memory_id}",
        source_uri=f"https://example.invalid/{memory_id}",
        source_type="paper",
        year=2026,
        tags=("memory",),
        score=score,
        rank=rank,
    )
    return RerankedMemory(
        hit=hit,
        final_rank=rank,
        final_score=score,
        score_breakdown=UtilityScoreBreakdown(
            relevance_component=score,
            reward_component=0.0,
            verdict_component=0.0,
            harm_penalty=0.0,
            token_penalty=0.0,
            latency_penalty=0.0,
            final_score=score,
        ),
        utility_evidence=UtilityEvidence(
            memory_id=memory_id,
            feedback_count=0,
            avg_reward=None,
            positive_count=0,
            negative_count=0,
            last_feedback_at=None,
        ),
    )


def _direct_evidence(
    rng: random.Random,
    *,
    timestamp: datetime,
) -> DirectUtilityEvidence:
    feedback_count = rng.randint(0, 8)
    if feedback_count == 0:
        return DirectUtilityEvidence(0, None, 0, 0, None)
    positive_count = rng.randint(0, feedback_count)
    negative_count = rng.randint(0, feedback_count - positive_count)
    return DirectUtilityEvidence(
        feedback_count=feedback_count,
        average_reward=round(rng.uniform(-1.0, 1.0), 8),
        positive_count=positive_count,
        negative_count=negative_count,
        last_feedback_at=timestamp,
    )


def _inherited_evidence(
    rng: random.Random,
    *,
    timestamp: datetime,
) -> InheritedUtilityEvidence:
    if rng.random() < 0.22:
        return InheritedUtilityEvidence(0, None, None, None, None, None)
    count = rng.randint(1, 30)
    inherited_mean = rng.uniform(-2.0, 2.0)
    value_sum = inherited_mean * count
    contradiction_mass = rng.uniform(0.0, abs(value_sum) + 3.0)
    absolute_value_sum = abs(value_sum) + contradiction_mass
    standard_error_sum = rng.uniform(0.0, 5.0)
    confidence = rng.uniform(0.0, 1.0)
    return InheritedUtilityEvidence(
        contribution_count=count,
        value_sum=round(value_sum, 8),
        absolute_value_sum=round(absolute_value_sum, 8),
        standard_error_sum=round(standard_error_sum, 8),
        minimum_structural_confidence=round(confidence, 8),
        last_credit_at=timestamp,
    )


def _generated_case(seed: int):
    rng = random.Random(seed)
    candidate_count = rng.randint(1, 6)
    memory_ids = tuple(
        _memory_id(seed, index) for index in range(candidate_count)
    )
    scores = [round(rng.uniform(-1.5, 1.5), 8) for _ in memory_ids]
    ranked_indices = sorted(
        range(candidate_count),
        key=lambda index: (-scores[index], str(memory_ids[index])),
    )
    rank_by_index = {
        candidate_index: rank
        for rank, candidate_index in enumerate(ranked_indices, start=1)
    }
    base_results = tuple(
        _base_result(
            memory_id,
            rank=rank_by_index[index],
            score=scores[index],
        )
        for index, memory_id in enumerate(memory_ids)
    )
    evidence = {
        memory_id: NodeLearningEvidence(
            space_id=SPACE,
            memory_id=memory_id,
            direct=_direct_evidence(
                rng,
                timestamp=NOW + timedelta(seconds=seed + index),
            ),
            inherited=_inherited_evidence(
                rng,
                timestamp=NOW + timedelta(seconds=seed + index + 1),
            ),
        )
        for index, memory_id in enumerate(memory_ids)
    }
    return base_results, evidence


def test_10000_generated_rankings_preserve_hard_invariants() -> None:
    config = BoundedInheritedRerankerConfig()
    reranker = BoundedInheritedReranker(config)
    applied = 0
    no_evidence = 0
    count_gated = 0
    confidence_gated = 0
    changed_top = 0

    for seed in range(10000):
        base_results, evidence = _generated_case(seed)
        reversed_evidence = MappingProxyType(
            dict(reversed(tuple(evidence.items())))
        )
        first = reranker.rerank(
            space_id=SPACE,
            base_results=tuple(reversed(base_results)),
            learning_evidence=reversed_evidence,
        )
        second = reranker.rerank(
            space_id=SPACE,
            base_results=base_results,
            learning_evidence=evidence,
        )

        assert first == second
        assert len(first) == len(base_results)
        assert [item.final_rank for item in first] == list(
            range(1, len(first) + 1)
        )
        assert {item.base.hit.memory_id for item in first} == set(evidence)
        assert len({item.base.hit.memory_id for item in first}) == len(first)
        assert all(isfinite(item.final_score) for item in first)
        assert all(
            abs(item.inherited_breakdown.applied_component)
            <= config.maximum_absolute_adjustment + 1e-15
            for item in first
        )
        assert all(
            item.final_score
            == item.base.final_score
            + item.inherited_breakdown.applied_component
            for item in first
        )
        assert all(
            item.base is next(
                candidate
                for candidate in base_results
                if candidate.hit.memory_id == item.base.hit.memory_id
            )
            for item in first
        )

        if first[0].base.final_rank != 1:
            changed_top += 1
        for item in first:
            breakdown = item.inherited_breakdown
            inherited = evidence[item.base.hit.memory_id].inherited
            assert breakdown.contribution_count == inherited.contribution_count
            if breakdown.disposition is InheritedEvidenceDisposition.APPLIED:
                applied += 1
                assert inherited.contribution_count >= config.minimum_contribution_count
                assert (
                    inherited.minimum_structural_confidence
                    is not None
                    and inherited.minimum_structural_confidence
                    >= config.minimum_structural_confidence
                )
            elif breakdown.disposition is InheritedEvidenceDisposition.NO_EVIDENCE:
                no_evidence += 1
                assert inherited.contribution_count == 0
                assert breakdown.applied_component == 0.0
            elif (
                breakdown.disposition
                is InheritedEvidenceDisposition.BELOW_MINIMUM_COUNT
            ):
                count_gated += 1
                assert 0 < inherited.contribution_count < config.minimum_contribution_count
                assert breakdown.applied_component == 0.0
            else:
                confidence_gated += 1
                assert (
                    inherited.minimum_structural_confidence
                    is not None
                    and inherited.minimum_structural_confidence
                    < config.minimum_structural_confidence
                )
                assert breakdown.applied_component == 0.0

    assert applied > 10000
    assert no_evidence > 5000
    assert count_gated > 1000
    assert confidence_gated > 10000
    assert changed_top > 0


def test_direct_evidence_permutations_never_change_inherited_component() -> None:
    reranker = BoundedInheritedReranker()

    for seed in range(2000):
        base_results, evidence = _generated_case(seed)
        original = reranker.rerank(
            space_id=SPACE,
            base_results=base_results,
            learning_evidence=evidence,
        )
        changed = {
            memory_id: NodeLearningEvidence(
                space_id=snapshot.space_id,
                memory_id=snapshot.memory_id,
                direct=DirectUtilityEvidence(
                    feedback_count=1,
                    average_reward=(-1.0 if seed % 2 else 1.0),
                    positive_count=(0 if seed % 2 else 1),
                    negative_count=(1 if seed % 2 else 0),
                    last_feedback_at=NOW,
                ),
                inherited=snapshot.inherited,
            )
            for memory_id, snapshot in evidence.items()
        }
        reranked = reranker.rerank(
            space_id=SPACE,
            base_results=base_results,
            learning_evidence=changed,
        )

        assert [item.inherited_breakdown for item in original] == [
            item.inherited_breakdown for item in reranked
        ]
        assert [item.final_score for item in original] == [
            item.final_score for item in reranked
        ]
