"""Deterministic comparison of naive and bounded inherited-evidence scoring."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nextgen_memory.bounded_inherited_reranker import (
    BoundedInheritedReranker,
    BoundedInheritedRerankerConfig,
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

SPACE = UUID("70000000-0000-0000-0000-000000000001")
MEMORY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
MEMORY_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
NOW = datetime(2026, 8, 14, 23, 58, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    base_a: float
    base_b: float
    expected_top: UUID
    inherited_b: InheritedUtilityEvidence


def _base(memory_id: UUID, *, rank: int, score: float) -> RerankedMemory:
    hit = ResearchRetrievalHit(
        memory_id=memory_id,
        backend_ref=f"simulation:{memory_id}",
        title=f"Simulation {memory_id}",
        source_uri=f"https://example.invalid/{memory_id}",
        source_type="simulation",
        year=2026,
        tags=("inherited-credit",),
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


def _neutral_inherited() -> InheritedUtilityEvidence:
    return InheritedUtilityEvidence(0, None, None, None, None, None)


def _learning(
    memory_id: UUID,
    inherited: InheritedUtilityEvidence,
) -> NodeLearningEvidence:
    return NodeLearningEvidence(
        space_id=SPACE,
        memory_id=memory_id,
        direct=DirectUtilityEvidence(0, None, 0, 0, None),
        inherited=inherited,
    )


def _scenarios() -> tuple[Scenario, ...]:
    return (
        Scenario(
            name="rare_large_value",
            base_a=0.80,
            base_b=0.75,
            expected_top=MEMORY_A,
            inherited_b=InheritedUtilityEvidence(
                1,
                10.0,
                10.0,
                0.0,
                1.0,
                NOW,
            ),
        ),
        Scenario(
            name="low_structural_confidence",
            base_a=0.80,
            base_b=0.75,
            expected_top=MEMORY_A,
            inherited_b=InheritedUtilityEvidence(
                10,
                1.0,
                1.0,
                0.0,
                0.20,
                NOW,
            ),
        ),
        Scenario(
            name="conflicting_paths",
            base_a=0.80,
            base_b=0.79,
            expected_top=MEMORY_A,
            inherited_b=InheritedUtilityEvidence(
                10,
                0.2,
                10.0,
                0.1,
                0.90,
                NOW,
            ),
        ),
        Scenario(
            name="high_uncertainty",
            base_a=0.80,
            base_b=0.75,
            expected_top=MEMORY_A,
            inherited_b=InheritedUtilityEvidence(
                10,
                1.0,
                1.0,
                10.0,
                0.90,
                NOW,
            ),
        ),
        Scenario(
            name="many_consistent_high_confidence_paths",
            base_a=0.80,
            base_b=0.79,
            expected_top=MEMORY_B,
            inherited_b=InheritedUtilityEvidence(
                50,
                10.0,
                10.0,
                0.1,
                1.0,
                NOW,
            ),
        ),
    )


def _naive_score(base_score: float, evidence: InheritedUtilityEvidence) -> float:
    if evidence.contribution_count == 0:
        return base_score
    assert evidence.value_sum is not None
    return base_score + evidence.value_sum / evidence.contribution_count


def simulate_bounded_inherited_reranker_v0() -> dict[str, Any]:
    config = BoundedInheritedRerankerConfig()
    reranker = BoundedInheritedReranker(config)
    scenario_rows: list[dict[str, Any]] = []
    naive_false_promotions = 0
    bounded_false_promotions = 0
    strong_promotions = 0

    for scenario in _scenarios():
        base_results = (
            _base(MEMORY_A, rank=1, score=scenario.base_a),
            _base(MEMORY_B, rank=2, score=scenario.base_b),
        )
        evidence = {
            MEMORY_A: _learning(MEMORY_A, _neutral_inherited()),
            MEMORY_B: _learning(MEMORY_B, scenario.inherited_b),
        }
        naive_scores = {
            MEMORY_A: _naive_score(
                scenario.base_a,
                evidence[MEMORY_A].inherited,
            ),
            MEMORY_B: _naive_score(
                scenario.base_b,
                evidence[MEMORY_B].inherited,
            ),
        }
        naive_top = sorted(
            naive_scores,
            key=lambda memory_id: (
                -naive_scores[memory_id],
                str(memory_id),
            ),
        )[0]
        bounded = reranker.rerank(
            space_id=SPACE,
            base_results=base_results,
            learning_evidence=evidence,
        )
        bounded_top = bounded[0].base.hit.memory_id
        bounded_b = next(
            item for item in bounded if item.base.hit.memory_id == MEMORY_B
        )
        expected_is_strong_promotion = scenario.expected_top == MEMORY_B
        if naive_top != scenario.expected_top:
            naive_false_promotions += 1
        if bounded_top != scenario.expected_top:
            bounded_false_promotions += 1
        if expected_is_strong_promotion and bounded_top == MEMORY_B:
            strong_promotions += 1

        scenario_rows.append(
            {
                "name": scenario.name,
                "expected_top": str(scenario.expected_top),
                "naive_top": str(naive_top),
                "bounded_top": str(bounded_top),
                "base_b": scenario.base_b,
                "naive_score_b": naive_scores[MEMORY_B],
                "bounded_score_b": bounded_b.final_score,
                "bounded_adjustment_b": (
                    bounded_b.inherited_breakdown.applied_component
                ),
                "bounded_disposition_b": (
                    bounded_b.inherited_breakdown.disposition.value
                ),
                "count_shrinkage_b": (
                    bounded_b.inherited_breakdown.count_shrinkage
                ),
                "path_coherence_b": (
                    bounded_b.inherited_breakdown.path_coherence
                ),
                "uncertainty_reliability_b": (
                    bounded_b.inherited_breakdown.uncertainty_reliability
                ),
                "confidence_reliability_b": (
                    bounded_b.inherited_breakdown.confidence_reliability
                ),
            }
        )

    return {
        "policy_version": config.policy_version,
        "maximum_absolute_adjustment": config.maximum_absolute_adjustment,
        "scenario_count": len(scenario_rows),
        "naive_false_promotions": naive_false_promotions,
        "bounded_false_promotions": bounded_false_promotions,
        "bounded_strong_promotions": strong_promotions,
        "scenarios": scenario_rows,
    }


def main() -> None:
    print(
        json.dumps(
            simulate_bounded_inherited_reranker_v0(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
