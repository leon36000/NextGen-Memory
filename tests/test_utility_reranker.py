from __future__ import annotations

from uuid import UUID

import pytest

from nextgen_memory.retrieval import ResearchRetrievalHit
from nextgen_memory.utility_reranker import (
    UtilityAwareReranker,
    UtilityEvidence,
    UtilityRerankCandidate,
    UtilityRerankerConfig,
)

MEMORY_A = UUID("00000000-0000-5000-8000-000000000001")
MEMORY_B = UUID("00000000-0000-5000-8000-000000000002")


def hit(memory_id: UUID, *, rank: int, score: float) -> ResearchRetrievalHit:
    return ResearchRetrievalHit(
        memory_id=memory_id,
        backend_ref=f"paper:{memory_id}",
        rank=rank,
        score=score,
        title=f"Memory {memory_id}",
        source_uri="https://example.invalid/research",
    )


def candidate(
    memory_id: UUID,
    *,
    rank: int,
    score: float,
    utility: UtilityEvidence | None = None,
    estimated_tokens: int = 0,
    estimated_latency_ms: float = 0.0,
) -> UtilityRerankCandidate:
    return UtilityRerankCandidate(
        hit=hit(memory_id, rank=rank, score=score),
        utility=utility or UtilityEvidence.neutral(memory_id),
        estimated_tokens=estimated_tokens,
        estimated_latency_ms=estimated_latency_ms,
    )


def test_no_feedback_preserves_relevance_order() -> None:
    results = UtilityAwareReranker().rerank(
        (
            candidate(MEMORY_B, rank=2, score=0.01),
            candidate(MEMORY_A, rank=1, score=0.02),
        )
    )

    assert [result.hit.memory_id for result in results] == [MEMORY_A, MEMORY_B]
    assert results[0].final_rank == 1
    assert results[0].breakdown.utility == 0.0
    assert results[0].breakdown.harm_risk == 0.0
    assert results[0].final_score == pytest.approx(results[0].breakdown.total)


def test_one_positive_event_does_not_overpower_clear_relevance_gap() -> None:
    one_positive = UtilityEvidence(
        memory_id=MEMORY_B,
        feedback_count=1,
        positive_count=1,
    )

    results = UtilityAwareReranker().rerank(
        (
            candidate(MEMORY_A, rank=1, score=0.02),
            candidate(MEMORY_B, rank=2, score=0.01, utility=one_positive),
        )
    )

    assert [result.hit.memory_id for result in results] == [MEMORY_A, MEMORY_B]
    assert results[1].breakdown.utility == pytest.approx(0.2)


def test_repeated_helpful_evidence_can_promote_near_tied_candidate() -> None:
    repeated_helpful = UtilityEvidence(
        memory_id=MEMORY_B,
        feedback_count=20,
        avg_reward=1.0,
        positive_count=20,
    )

    results = UtilityAwareReranker().rerank(
        (
            candidate(MEMORY_A, rank=1, score=0.02),
            candidate(MEMORY_B, rank=2, score=0.019, utility=repeated_helpful),
        )
    )

    assert results[0].hit.memory_id == MEMORY_B
    assert results[0].breakdown.utility == pytest.approx(20 / 24)
    assert results[0].final_score > results[1].final_score


def test_harmful_evidence_demotes_high_relevance_candidate() -> None:
    repeated_harm = UtilityEvidence(
        memory_id=MEMORY_A,
        feedback_count=10,
        avg_reward=-1.0,
        negative_count=10,
    )

    results = UtilityAwareReranker().rerank(
        (
            candidate(MEMORY_A, rank=1, score=0.02, utility=repeated_harm),
            candidate(MEMORY_B, rank=2, score=0.019),
        )
    )

    assert results[0].hit.memory_id == MEMORY_B
    assert results[1].breakdown.utility < 0
    assert results[1].breakdown.harm_risk == pytest.approx(10 / 14)


def test_cost_penalties_are_bounded_and_exposed() -> None:
    result = UtilityAwareReranker().rerank(
        (
            candidate(
                MEMORY_A,
                rank=1,
                score=1.0,
                estimated_tokens=50_000,
                estimated_latency_ms=10_000,
            ),
        )
    )[0]

    assert result.breakdown.token_cost == 1.0
    assert result.breakdown.latency_cost == 1.0
    assert result.breakdown.weighted_token_penalty == pytest.approx(-0.08)
    assert result.breakdown.weighted_latency_penalty == pytest.approx(-0.07)
    assert result.final_score == pytest.approx(0.85)


def test_ties_are_deterministic_by_original_rank_then_uuid() -> None:
    results = UtilityAwareReranker().rerank(
        (
            candidate(MEMORY_B, rank=1, score=1.0),
            candidate(MEMORY_A, rank=1, score=1.0),
        )
    )

    assert [result.hit.memory_id for result in results] == [MEMORY_A, MEMORY_B]


def test_invalid_counts_costs_and_weights_fail_closed() -> None:
    with pytest.raises(ValueError, match="feedback_count"):
        UtilityEvidence(memory_id=MEMORY_A, feedback_count=-1)
    with pytest.raises(ValueError, match="positive_count plus negative_count"):
        UtilityEvidence(
            memory_id=MEMORY_A,
            feedback_count=1,
            positive_count=1,
            negative_count=1,
        )
    with pytest.raises(ValueError, match="same memory_id"):
        UtilityRerankCandidate(
            hit=hit(MEMORY_A, rank=1, score=1.0),
            utility=UtilityEvidence.neutral(MEMORY_B),
        )
    with pytest.raises(ValueError, match="estimated_tokens"):
        candidate(MEMORY_A, rank=1, score=1.0, estimated_tokens=-1)
    with pytest.raises(ValueError, match="prior_strength"):
        UtilityRerankerConfig(prior_strength=0.0)
    with pytest.raises(ValueError, match="harm_weight"):
        UtilityRerankerConfig(harm_weight=-0.1)
