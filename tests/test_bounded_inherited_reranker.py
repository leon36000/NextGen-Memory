from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from math import isclose, tanh
from types import MappingProxyType
from uuid import UUID

import pytest

from nextgen_memory.bounded_inherited_reranker import (
    BoundedInheritedReranker,
    BoundedInheritedRerankerConfig,
    BoundedInheritedRerankerValidationError,
    InheritedAwareRerankedMemory,
    InheritedEvidenceDisposition,
    InheritedScoreBreakdown,
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

SPACE = UUID("11111111-1111-1111-1111-111111111111")
OTHER_SPACE = UUID("22222222-2222-2222-2222-222222222222")
MEMORY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
MEMORY_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
MEMORY_C = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
NOW = datetime(2026, 8, 14, 23, 50, tzinfo=UTC)


def hit(
    memory_id: UUID = MEMORY_A,
    *,
    rank: int = 1,
    score: float = 0.9,
) -> ResearchRetrievalHit:
    return ResearchRetrievalHit(
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


def base_result(
    memory_id: UUID = MEMORY_A,
    *,
    final_rank: int = 1,
    final_score: float = 0.8,
    direct_reward: float = 0.4,
) -> RerankedMemory:
    retrieval_hit = hit(memory_id, rank=final_rank, score=final_score)
    return RerankedMemory(
        hit=retrieval_hit,
        final_rank=final_rank,
        final_score=final_score,
        score_breakdown=UtilityScoreBreakdown(
            relevance_component=final_score,
            reward_component=0.0,
            verdict_component=0.0,
            harm_penalty=0.0,
            token_penalty=0.0,
            latency_penalty=0.0,
            final_score=final_score,
        ),
        utility_evidence=UtilityEvidence(
            memory_id=memory_id,
            feedback_count=3,
            avg_reward=direct_reward,
            positive_count=2,
            negative_count=1,
            last_feedback_at=NOW,
        ),
    )


def learning_evidence(
    memory_id: UUID = MEMORY_A,
    *,
    space_id: UUID = SPACE,
    contribution_count: int = 4,
    value_sum: float | None = 0.8,
    absolute_value_sum: float | None = 0.8,
    standard_error_sum: float | None = 0.1,
    minimum_structural_confidence: float | None = 0.9,
    direct_reward: float = 0.4,
) -> NodeLearningEvidence:
    inherited = (
        InheritedUtilityEvidence(
            contribution_count=0,
            value_sum=None,
            absolute_value_sum=None,
            standard_error_sum=None,
            minimum_structural_confidence=None,
            last_credit_at=None,
        )
        if contribution_count == 0
        else InheritedUtilityEvidence(
            contribution_count=contribution_count,
            value_sum=value_sum,
            absolute_value_sum=absolute_value_sum,
            standard_error_sum=standard_error_sum,
            minimum_structural_confidence=minimum_structural_confidence,
            last_credit_at=NOW,
        )
    )
    return NodeLearningEvidence(
        space_id=space_id,
        memory_id=memory_id,
        direct=DirectUtilityEvidence(
            feedback_count=3,
            average_reward=direct_reward,
            positive_count=2,
            negative_count=1,
            last_feedback_at=NOW,
        ),
        inherited=inherited,
    )


def test_config_defaults_are_conservative_and_immutable() -> None:
    config = BoundedInheritedRerankerConfig()

    assert config.inherited_weight == 0.10
    assert config.maximum_absolute_adjustment == 0.05
    assert config.prior_contribution_count == 8.0
    assert config.minimum_contribution_count == 2
    assert config.minimum_structural_confidence == 0.50
    assert config.value_scale == 0.25
    assert config.uncertainty_floor == 0.05
    assert config.policy_version == "bounded-inherited-reranker-v0"
    with pytest.raises(FrozenInstanceError):
        config.inherited_weight = 1.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"inherited_weight": -0.1},
        {"inherited_weight": float("nan")},
        {"maximum_absolute_adjustment": -0.1},
        {"inherited_weight": 0.1, "maximum_absolute_adjustment": 0.2},
        {"prior_contribution_count": -1.0},
        {"minimum_contribution_count": 0},
        {"minimum_contribution_count": True},
        {"minimum_structural_confidence": -0.1},
        {"minimum_structural_confidence": 1.1},
        {"value_scale": 0.0},
        {"uncertainty_floor": 0.0},
        {"policy_version": " "},
    ],
)
def test_config_rejects_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(BoundedInheritedRerankerValidationError):
        BoundedInheritedRerankerConfig(**overrides)


def test_no_inherited_evidence_is_exactly_neutral() -> None:
    base = base_result()
    evidence = learning_evidence(contribution_count=0)

    result = BoundedInheritedReranker().rerank(
        space_id=SPACE,
        base_results=(base,),
        learning_evidence={MEMORY_A: evidence},
    )[0]

    assert result.base is base
    assert result.final_score == base.final_score
    assert result.inherited_breakdown.disposition is InheritedEvidenceDisposition.NO_EVIDENCE
    assert result.inherited_breakdown.applied_component == 0.0
    assert result.inherited_breakdown.contribution_count == 0


def test_minimum_count_gate_is_neutral_but_observable() -> None:
    base = base_result()
    evidence = learning_evidence(
        contribution_count=1,
        value_sum=10.0,
        absolute_value_sum=10.0,
        standard_error_sum=0.0,
        minimum_structural_confidence=1.0,
    )

    result = BoundedInheritedReranker().rerank(
        space_id=SPACE,
        base_results=(base,),
        learning_evidence={MEMORY_A: evidence},
    )[0]

    breakdown = result.inherited_breakdown
    assert breakdown.disposition is InheritedEvidenceDisposition.BELOW_MINIMUM_COUNT
    assert breakdown.applied_component == 0.0
    assert breakdown.contribution_count == 1
    assert breakdown.value_sum == 10.0


def test_minimum_confidence_gate_is_neutral_but_observable() -> None:
    evidence = learning_evidence(minimum_structural_confidence=0.49)

    result = BoundedInheritedReranker().rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={MEMORY_A: evidence},
    )[0]

    assert (
        result.inherited_breakdown.disposition
        is InheritedEvidenceDisposition.BELOW_MINIMUM_CONFIDENCE
    )
    assert result.inherited_breakdown.applied_component == 0.0


def test_applied_component_matches_the_declared_equation() -> None:
    config = BoundedInheritedRerankerConfig()
    evidence = learning_evidence()

    result = BoundedInheritedReranker(config).rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={MEMORY_A: evidence},
    )[0]
    breakdown = result.inherited_breakdown

    expected_mean = 0.8 / 4
    expected_signal = tanh(expected_mean / 0.25)
    expected_count = 4 / (4 + 8)
    expected_coherence = 1.0
    expected_uncertainty = 1 / (1 + 0.1 / (0.8 + 0.05))
    expected_confidence = 0.9
    expected_component = (
        0.10
        * expected_signal
        * expected_count
        * expected_coherence
        * expected_uncertainty
        * expected_confidence
    )

    assert breakdown.disposition is InheritedEvidenceDisposition.APPLIED
    assert isclose(breakdown.inherited_mean, expected_mean)
    assert isclose(breakdown.signed_signal, expected_signal)
    assert isclose(breakdown.count_shrinkage, expected_count)
    assert isclose(breakdown.path_coherence, expected_coherence)
    assert isclose(breakdown.uncertainty_reliability, expected_uncertainty)
    assert isclose(breakdown.confidence_reliability, expected_confidence)
    assert isclose(breakdown.uncapped_component, expected_component)
    assert isclose(breakdown.applied_component, expected_component)
    assert isclose(result.final_score, 0.8 + expected_component)


def test_negative_inherited_value_produces_bounded_negative_adjustment() -> None:
    evidence = learning_evidence(
        value_sum=-0.8,
        absolute_value_sum=0.8,
    )

    result = BoundedInheritedReranker().rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={MEMORY_A: evidence},
    )[0]

    assert result.inherited_breakdown.applied_component < 0
    assert result.final_score < result.base.final_score
    assert abs(result.inherited_breakdown.applied_component) <= 0.05


def test_hard_cap_applies_after_saturation() -> None:
    config = BoundedInheritedRerankerConfig(
        inherited_weight=1.0,
        maximum_absolute_adjustment=0.05,
        prior_contribution_count=0.0,
        minimum_contribution_count=1,
        minimum_structural_confidence=0.0,
        value_scale=0.001,
        uncertainty_floor=0.001,
    )
    evidence = learning_evidence(
        contribution_count=100,
        value_sum=1000.0,
        absolute_value_sum=1000.0,
        standard_error_sum=0.0,
        minimum_structural_confidence=1.0,
    )

    breakdown = BoundedInheritedReranker(config).rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={MEMORY_A: evidence},
    )[0].inherited_breakdown

    assert breakdown.uncapped_component > 0.05
    assert breakdown.applied_component == 0.05


def test_more_consistent_evidence_increases_count_reliability() -> None:
    reranker = BoundedInheritedReranker()
    low = reranker.rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={
            MEMORY_A: learning_evidence(
                contribution_count=2,
                value_sum=0.4,
                absolute_value_sum=0.4,
            )
        },
    )[0].inherited_breakdown
    high = reranker.rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={
            MEMORY_A: learning_evidence(
                contribution_count=8,
                value_sum=1.6,
                absolute_value_sum=1.6,
            )
        },
    )[0].inherited_breakdown

    assert high.inherited_mean == low.inherited_mean
    assert high.count_shrinkage > low.count_shrinkage
    assert high.applied_component > low.applied_component


def test_more_uncertainty_reduces_adjustment() -> None:
    reranker = BoundedInheritedReranker()
    certain = reranker.rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={MEMORY_A: learning_evidence(standard_error_sum=0.01)},
    )[0].inherited_breakdown
    uncertain = reranker.rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={MEMORY_A: learning_evidence(standard_error_sum=2.0)},
    )[0].inherited_breakdown

    assert certain.uncertainty_reliability > uncertain.uncertainty_reliability
    assert certain.applied_component > uncertain.applied_component


def test_lower_structural_confidence_reduces_adjustment_above_gate() -> None:
    reranker = BoundedInheritedReranker()
    lower = reranker.rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={
            MEMORY_A: learning_evidence(minimum_structural_confidence=0.6)
        },
    )[0].inherited_breakdown
    higher = reranker.rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={
            MEMORY_A: learning_evidence(minimum_structural_confidence=0.95)
        },
    )[0].inherited_breakdown

    assert lower.confidence_reliability < higher.confidence_reliability
    assert lower.applied_component < higher.applied_component


def test_conflicting_paths_reduce_coherence_and_adjustment() -> None:
    reranker = BoundedInheritedReranker()
    coherent = reranker.rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={MEMORY_A: learning_evidence()},
    )[0].inherited_breakdown
    conflicting = reranker.rerank(
        space_id=SPACE,
        base_results=(base_result(),),
        learning_evidence={
            MEMORY_A: learning_evidence(
                value_sum=0.2,
                absolute_value_sum=1.0,
            )
        },
    )[0].inherited_breakdown

    assert coherent.path_coherence == 1.0
    assert isclose(conflicting.path_coherence, 0.2)
    assert conflicting.applied_component < coherent.applied_component


def test_direct_evidence_never_changes_inherited_component() -> None:
    reranker = BoundedInheritedReranker()
    first = reranker.rerank(
        space_id=SPACE,
        base_results=(base_result(direct_reward=-1.0),),
        learning_evidence={
            MEMORY_A: learning_evidence(direct_reward=-1.0)
        },
    )[0]
    second = reranker.rerank(
        space_id=SPACE,
        base_results=(base_result(direct_reward=1.0),),
        learning_evidence={
            MEMORY_A: learning_evidence(direct_reward=1.0)
        },
    )[0]

    assert first.inherited_breakdown == second.inherited_breakdown
    assert first.final_score == second.final_score


def test_reranking_is_deterministic_and_can_change_order_only_by_bounded_component() -> None:
    base_a = base_result(MEMORY_A, final_rank=1, final_score=0.80)
    base_b = base_result(MEMORY_B, final_rank=2, final_score=0.79)
    evidence_a = learning_evidence(MEMORY_A, contribution_count=0)
    evidence_b = learning_evidence(
        MEMORY_B,
        contribution_count=30,
        value_sum=15.0,
        absolute_value_sum=15.0,
        standard_error_sum=0.0,
        minimum_structural_confidence=1.0,
    )
    evidence_map = MappingProxyType({MEMORY_B: evidence_b, MEMORY_A: evidence_a})

    first = BoundedInheritedReranker().rerank(
        space_id=SPACE,
        base_results=(base_a, base_b),
        learning_evidence=evidence_map,
    )
    second = BoundedInheritedReranker().rerank(
        space_id=SPACE,
        base_results=(base_b, base_a),
        learning_evidence={MEMORY_A: evidence_a, MEMORY_B: evidence_b},
    )

    assert first == second
    assert [item.base.hit.memory_id for item in first] == [MEMORY_B, MEMORY_A]
    assert [item.final_rank for item in first] == [1, 2]
    assert first[0].final_score - first[0].base.final_score <= 0.05
    assert first[1].final_score == first[1].base.final_score


def test_ties_use_base_rank_then_memory_uuid() -> None:
    base_a = base_result(MEMORY_A, final_rank=2, final_score=0.8)
    base_b = base_result(MEMORY_B, final_rank=1, final_score=0.8)
    neutral = {
        MEMORY_A: learning_evidence(MEMORY_A, contribution_count=0),
        MEMORY_B: learning_evidence(MEMORY_B, contribution_count=0),
    }

    results = BoundedInheritedReranker().rerank(
        space_id=SPACE,
        base_results=(base_a, base_b),
        learning_evidence=neutral,
    )

    assert [item.base.hit.memory_id for item in results] == [MEMORY_B, MEMORY_A]


@pytest.mark.parametrize(
    ("base_results", "evidence_map", "message"),
    [
        (
            (base_result(MEMORY_A),),
            {},
            "missing",
        ),
        (
            (base_result(MEMORY_A),),
            {
                MEMORY_A: learning_evidence(MEMORY_A),
                MEMORY_B: learning_evidence(MEMORY_B),
            },
            "unexpected",
        ),
        (
            (base_result(MEMORY_A), base_result(MEMORY_A, final_rank=2)),
            {MEMORY_A: learning_evidence(MEMORY_A)},
            "duplicate",
        ),
        (
            (base_result(MEMORY_A, final_rank=2),),
            {MEMORY_A: learning_evidence(MEMORY_A)},
            "contiguous",
        ),
        (
            (
                base_result(MEMORY_A, final_rank=1),
                base_result(MEMORY_B, final_rank=1),
            ),
            {
                MEMORY_A: learning_evidence(MEMORY_A),
                MEMORY_B: learning_evidence(MEMORY_B),
            },
            "rank",
        ),
    ],
)
def test_reranker_fails_closed_on_candidate_evidence_or_rank_mismatch(
    base_results: tuple[RerankedMemory, ...],
    evidence_map: dict[UUID, NodeLearningEvidence],
    message: str,
) -> None:
    with pytest.raises(BoundedInheritedRerankerValidationError, match=message):
        BoundedInheritedReranker().rerank(
            space_id=SPACE,
            base_results=base_results,
            learning_evidence=evidence_map,
        )


def test_reranker_rejects_scope_and_mapping_key_mismatch() -> None:
    with pytest.raises(BoundedInheritedRerankerValidationError, match="space"):
        BoundedInheritedReranker().rerank(
            space_id=SPACE,
            base_results=(base_result(),),
            learning_evidence={
                MEMORY_A: learning_evidence(space_id=OTHER_SPACE)
            },
        )
    with pytest.raises(BoundedInheritedRerankerValidationError, match="key"):
        BoundedInheritedReranker().rerank(
            space_id=SPACE,
            base_results=(base_result(),),
            learning_evidence={MEMORY_A: learning_evidence(MEMORY_B)},
        )


def test_reranker_rejects_non_uuid_scope_non_mapping_evidence_and_nonfinite_base_score() -> None:
    with pytest.raises(BoundedInheritedRerankerValidationError, match="space_id"):
        BoundedInheritedReranker().rerank(
            space_id="bad",  # type: ignore[arg-type]
            base_results=(base_result(),),
            learning_evidence={MEMORY_A: learning_evidence()},
        )
    with pytest.raises(BoundedInheritedRerankerValidationError, match="mapping"):
        BoundedInheritedReranker().rerank(
            space_id=SPACE,
            base_results=(base_result(),),
            learning_evidence=[],  # type: ignore[arg-type]
        )
    malformed = replace(base_result(), final_score=float("nan"))
    with pytest.raises(BoundedInheritedRerankerValidationError, match="finite"):
        BoundedInheritedReranker().rerank(
            space_id=SPACE,
            base_results=(malformed,),
            learning_evidence={MEMORY_A: learning_evidence()},
        )


def test_result_contracts_are_immutable_and_preserve_base() -> None:
    base = base_result()
    result = BoundedInheritedReranker().rerank(
        space_id=SPACE,
        base_results=(base,),
        learning_evidence={MEMORY_A: learning_evidence()},
    )[0]

    assert isinstance(result, InheritedAwareRerankedMemory)
    assert isinstance(result.inherited_breakdown, InheritedScoreBreakdown)
    assert result.base is base
    assert result.base.score_breakdown is base.score_breakdown
    assert result.base.utility_evidence is base.utility_evidence
    with pytest.raises(FrozenInstanceError):
        result.final_score = 0.0  # type: ignore[misc]
