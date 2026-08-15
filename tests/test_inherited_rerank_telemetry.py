from __future__ import annotations

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
from nextgen_memory.inherited_rerank_telemetry import (
    InMemoryInheritedRerankTelemetrySink,
    InheritedRerankObservation,
    InheritedRerankSummary,
    InheritedRerankTelemetryBatch,
    InheritedRerankTelemetryConflictError,
    InheritedRerankTelemetryValidationError,
    build_inherited_rerank_telemetry,
    fingerprint_bounded_inherited_policy,
)
from nextgen_memory.retrieval import ResearchRetrievalHit
from nextgen_memory.utility_reranker import (
    RerankedMemory,
    UtilityScoreBreakdown,
)

SPACE = UUID("11111111-1111-1111-1111-111111111111")
OTHER_SPACE = UUID("22222222-2222-2222-2222-222222222222")
DECISION = UUID("33333333-3333-3333-3333-333333333333")
MEMORY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
MEMORY_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
MEMORY_C = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


def base_result(
    memory_id: UUID,
    *,
    rank: int,
    score: float,
) -> RerankedMemory:
    hit = ResearchRetrievalHit(
        memory_id=memory_id,
        backend_ref=f"paper:{memory_id}",
        rank=rank,
        score=score,
        title=f"Paper {memory_id}",
        source_uri=f"https://example.invalid/{memory_id}",
        tags=("memory",),
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


def breakdown(
    *,
    disposition: InheritedEvidenceDisposition,
    applied_component: float,
    contribution_count: int = 4,
    value_sum: float | None = 0.8,
    absolute_value_sum: float | None = 0.8,
    standard_error_sum: float | None = 0.1,
    minimum_structural_confidence: float | None = 0.9,
    uncapped_component: float | None = None,
    policy_version: str = "bounded-inherited-reranker-v0",
) -> InheritedScoreBreakdown:
    if contribution_count == 0:
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
    assert value_sum is not None
    assert absolute_value_sum is not None
    assert standard_error_sum is not None
    assert minimum_structural_confidence is not None
    return InheritedScoreBreakdown(
        contribution_count=contribution_count,
        value_sum=value_sum,
        absolute_value_sum=absolute_value_sum,
        standard_error_sum=standard_error_sum,
        minimum_structural_confidence=minimum_structural_confidence,
        inherited_mean=value_sum / contribution_count,
        signed_signal=0.5,
        count_shrinkage=0.5,
        path_coherence=(
            1.0
            if absolute_value_sum == 0.0 and value_sum == 0.0
            else abs(value_sum) / absolute_value_sum
        ),
        uncertainty_reliability=0.8,
        confidence_reliability=minimum_structural_confidence,
        uncapped_component=(
            applied_component
            if uncapped_component is None
            else uncapped_component
        ),
        applied_component=applied_component,
        disposition=disposition,
        policy_version=policy_version,
    )


def reranked_results() -> tuple[InheritedAwareRerankedMemory, ...]:
    base_a = base_result(MEMORY_A, rank=1, score=0.80)
    base_b = base_result(MEMORY_B, rank=2, score=0.79)
    base_c = base_result(MEMORY_C, rank=3, score=0.70)
    return (
        InheritedAwareRerankedMemory(
            base=base_b,
            final_rank=1,
            final_score=0.82,
            inherited_breakdown=breakdown(
                disposition=InheritedEvidenceDisposition.APPLIED,
                applied_component=0.03,
            ),
        ),
        InheritedAwareRerankedMemory(
            base=base_a,
            final_rank=2,
            final_score=0.80,
            inherited_breakdown=breakdown(
                disposition=InheritedEvidenceDisposition.NO_EVIDENCE,
                applied_component=0.0,
                contribution_count=0,
                value_sum=None,
                absolute_value_sum=None,
                standard_error_sum=None,
                minimum_structural_confidence=None,
            ),
        ),
        InheritedAwareRerankedMemory(
            base=base_c,
            final_rank=3,
            final_score=0.70,
            inherited_breakdown=breakdown(
                disposition=(
                    InheritedEvidenceDisposition.BELOW_MINIMUM_CONFIDENCE
                ),
                applied_component=0.0,
                contribution_count=3,
                value_sum=0.4,
                absolute_value_sum=0.6,
                standard_error_sum=0.2,
                minimum_structural_confidence=0.4,
            ),
        ),
    )


def build_batch(
    *,
    config: BoundedInheritedRerankerConfig | None = None,
    results: tuple[InheritedAwareRerankedMemory, ...] | None = None,
) -> InheritedRerankTelemetryBatch:
    return build_inherited_rerank_telemetry(
        space_id=SPACE,
        router_decision_id=DECISION,
        config=config or BoundedInheritedRerankerConfig(),
        results=reranked_results() if results is None else results,
    )


def test_policy_fingerprint_is_deterministic_and_policy_sensitive() -> None:
    config = BoundedInheritedRerankerConfig()
    first = fingerprint_bounded_inherited_policy(config)
    second = fingerprint_bounded_inherited_policy(config)
    changed = fingerprint_bounded_inherited_policy(
        replace(config, inherited_weight=0.2, maximum_absolute_adjustment=0.05)
    )

    assert first == second
    assert len(first) == 64
    assert first != changed


def test_builder_creates_complete_deterministic_batch() -> None:
    first = build_batch()
    second = build_batch(results=tuple(reversed(reranked_results())))

    assert first == second
    assert first.render_json() == second.render_json()
    assert first.space_id == SPACE
    assert first.router_decision_id == DECISION
    assert first.policy_version == "bounded-inherited-reranker-v0"
    assert len(first.id.hex) == 32
    assert len(first.content_hash) == 64
    assert [item.final_rank for item in first.observations] == [1, 2, 3]
    assert [item.memory_id for item in first.observations] == [
        MEMORY_B,
        MEMORY_A,
        MEMORY_C,
    ]
    assert len({item.id for item in first.observations}) == 3
    assert all(item.batch_id == first.id for item in first.observations)


def test_observations_preserve_aggregate_only_breakdown_and_rank_delta() -> None:
    batch = build_batch()
    by_memory = {item.memory_id: item for item in batch.observations}

    applied = by_memory[MEMORY_B]
    assert isinstance(applied, InheritedRerankObservation)
    assert applied.base_rank == 2
    assert applied.final_rank == 1
    assert applied.rank_delta == 1
    assert applied.base_score == 0.79
    assert applied.final_score == 0.82
    assert applied.applied_component == 0.03
    assert applied.uncapped_component == 0.03
    assert applied.disposition is InheritedEvidenceDisposition.APPLIED
    assert applied.contribution_count == 4
    assert applied.value_sum == 0.8
    assert applied.absolute_value_sum == 0.8
    assert applied.standard_error_sum == 0.1
    assert applied.minimum_structural_confidence == 0.9

    neutral = by_memory[MEMORY_A]
    assert neutral.rank_delta == -1
    assert neutral.disposition is InheritedEvidenceDisposition.NO_EVIDENCE
    assert neutral.contribution_count == 0
    assert neutral.value_sum is None
    assert neutral.applied_component == 0.0

    with pytest.raises(FrozenInstanceError):
        applied.final_score = 0.0  # type: ignore[misc]


def test_summary_partitions_candidates_and_detects_top_change() -> None:
    summary = build_batch().summary

    assert isinstance(summary, InheritedRerankSummary)
    assert summary.candidate_count == 3
    assert summary.applied_count == 1
    assert summary.no_evidence_count == 1
    assert summary.below_minimum_count == 0
    assert summary.below_minimum_confidence == 1
    assert summary.promoted_count == 1
    assert summary.demoted_count == 1
    assert summary.unchanged_count == 1
    assert summary.top_changed is True
    assert summary.base_top_memory_id == MEMORY_A
    assert summary.final_top_memory_id == MEMORY_B
    assert summary.signed_adjustment_sum == pytest.approx(0.03)
    assert summary.absolute_adjustment_sum == pytest.approx(0.03)
    assert summary.maximum_absolute_adjustment_observed == pytest.approx(0.03)
    assert summary.configured_hard_cap == 0.05
    assert len(summary.content_hash) == 64


def test_empty_batch_is_explicit_deterministic_and_private() -> None:
    first = build_batch(results=())
    second = build_batch(results=())

    assert first == second
    assert first.observations == ()
    assert first.summary.candidate_count == 0
    assert first.summary.base_top_memory_id is None
    assert first.summary.final_top_memory_id is None
    assert first.summary.top_changed is False
    assert first.summary.maximum_absolute_adjustment_observed == 0.0
    assert json.loads(first.render_json())["observations"] == []


def test_changed_result_or_policy_changes_batch_identity() -> None:
    baseline = build_batch()
    changed_results = list(reranked_results())
    changed_results[0] = replace(
        changed_results[0],
        final_score=0.83,
        inherited_breakdown=replace(
            changed_results[0].inherited_breakdown,
            applied_component=0.04,
            uncapped_component=0.04,
        ),
    )
    changed_result_batch = build_batch(results=tuple(changed_results))
    changed_policy_batch = build_batch(
        config=BoundedInheritedRerankerConfig(
            inherited_weight=0.2,
            maximum_absolute_adjustment=0.05,
        )
    )

    assert baseline.id != changed_result_batch.id
    assert baseline.content_hash != changed_result_batch.content_hash
    assert baseline.id != changed_policy_batch.id
    assert baseline.policy_fingerprint != changed_policy_batch.policy_fingerprint


def test_rendered_json_contains_no_direct_or_raw_content_fields() -> None:
    rendered = build_batch().render_json().lower()

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
        "token",
        "api_key",
        "feedback_note",
        "direct_reward",
        "avg_reward",
        "positive_count",
        "negative_count",
        "relation_path",
        "edge_path",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize(
    ("results", "config", "message"),
    [
        (
            (
                reranked_results()[0],
                replace(
                    reranked_results()[1],
                    base=replace(
                        reranked_results()[1].base,
                        hit=replace(
                            reranked_results()[1].base.hit,
                            memory_id=MEMORY_B,
                        ),
                    ),
                ),
            ),
            BoundedInheritedRerankerConfig(),
            "duplicate",
        ),
        (
            (replace(reranked_results()[0], final_rank=2),),
            BoundedInheritedRerankerConfig(),
            "contiguous",
        ),
        (
            (
                replace(
                    reranked_results()[0],
                    base=replace(reranked_results()[0].base, final_rank=2),
                ),
            ),
            BoundedInheritedRerankerConfig(),
            "base rank",
        ),
        (
            (
                replace(
                    reranked_results()[0],
                    final_score=0.90,
                ),
            ),
            BoundedInheritedRerankerConfig(),
            "score equation",
        ),
        (
            (
                replace(
                    reranked_results()[0],
                    final_score=0.89,
                    inherited_breakdown=replace(
                        reranked_results()[0].inherited_breakdown,
                        applied_component=0.10,
                    ),
                ),
            ),
            BoundedInheritedRerankerConfig(),
            "cap",
        ),
        (
            (
                replace(
                    reranked_results()[0],
                    inherited_breakdown=replace(
                        reranked_results()[0].inherited_breakdown,
                        policy_version="other",
                    ),
                ),
            ),
            BoundedInheritedRerankerConfig(),
            "policy",
        ),
    ],
)
def test_builder_fails_closed_on_invalid_result_contracts(
    results: tuple[InheritedAwareRerankedMemory, ...],
    config: BoundedInheritedRerankerConfig,
    message: str,
) -> None:
    with pytest.raises(InheritedRerankTelemetryValidationError, match=message):
        build_inherited_rerank_telemetry(
            space_id=SPACE,
            router_decision_id=DECISION,
            config=config,
            results=results,
        )


def test_builder_rejects_invalid_context_and_result_types() -> None:
    with pytest.raises(InheritedRerankTelemetryValidationError, match="space_id"):
        build_inherited_rerank_telemetry(
            space_id="bad",  # type: ignore[arg-type]
            router_decision_id=DECISION,
            config=BoundedInheritedRerankerConfig(),
            results=(),
        )
    with pytest.raises(
        InheritedRerankTelemetryValidationError,
        match="router_decision_id",
    ):
        build_inherited_rerank_telemetry(
            space_id=SPACE,
            router_decision_id="bad",  # type: ignore[arg-type]
            config=BoundedInheritedRerankerConfig(),
            results=(),
        )
    with pytest.raises(InheritedRerankTelemetryValidationError, match="config"):
        build_inherited_rerank_telemetry(
            space_id=SPACE,
            router_decision_id=DECISION,
            config=None,  # type: ignore[arg-type]
            results=(),
        )
    with pytest.raises(InheritedRerankTelemetryValidationError, match="results"):
        build_inherited_rerank_telemetry(
            space_id=SPACE,
            router_decision_id=DECISION,
            config=BoundedInheritedRerankerConfig(),
            results=("bad",),  # type: ignore[arg-type]
        )


def test_in_memory_sink_is_idempotent_sorted_and_conflict_safe() -> None:
    sink = InMemoryInheritedRerankTelemetrySink()
    first = build_batch()
    second = build_inherited_rerank_telemetry(
        space_id=OTHER_SPACE,
        router_decision_id=DECISION,
        config=BoundedInheritedRerankerConfig(),
        results=(),
    )

    sink.record(first)
    sink.record(first)
    sink.record(second)

    assert sink.batches == tuple(sorted((first, second), key=lambda item: str(item.id)))

    conflicting = replace(first, content_hash="f" * 64)
    with pytest.raises(InheritedRerankTelemetryConflictError, match="conflict"):
        sink.record(conflicting)
    with pytest.raises(InheritedRerankTelemetryValidationError, match="batch"):
        sink.record("bad")  # type: ignore[arg-type]
