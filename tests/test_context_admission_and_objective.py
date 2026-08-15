from __future__ import annotations

import hashlib
from uuid import UUID

import pytest

from nextgen_memory.integrated_context_compiler import (
    CanonicalContextPool,
    ContextCompilerValidationError,
    ContextCoverageDemand,
    ContextDependencyError,
    ContextFidelity,
    ContextInteractionKind,
    ContextObjectivePolicy,
    ContextOmissionReason,
    ContextPairInteraction,
    ContextSetEvaluator,
    IntegratedContextCompileRequest,
    IntegratedContextEvidence,
)

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
OTHER_SPACE_ID = UUID("00000000-0000-5000-8000-000000000099")
MEMORY_A = UUID("00000000-0000-5000-8000-000000000001")
MEMORY_B = UUID("00000000-0000-5000-8000-000000000002")
MEMORY_C = UUID("00000000-0000-5000-8000-000000000003")
MEMORY_D = UUID("00000000-0000-5000-8000-000000000004")
GROUP_A = UUID("00000000-0000-5000-8000-000000000011")
GROUP_B = UUID("00000000-0000-5000-8000-000000000012")


def digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def item(memory_id: UUID, **overrides: object) -> IntegratedContextEvidence:
    content = str(overrides.pop("content", f"evidence:{memory_id}"))
    values: dict[str, object] = {
        "memory_id": memory_id,
        "space_id": SPACE_ID,
        "expert": "research",
        "subject_key": f"subject:{memory_id}",
        "source_cluster_key": f"source:{memory_id}",
        "content": content,
        "content_hash": digest(content),
        "backend_ref": f"memory:{memory_id}",
        "source_uri": None,
        "fidelity": ContextFidelity.EXACT,
        "estimated_tokens": 100,
        "original_rank": int(str(memory_id)[-1], 16) or 1,
        "coverage_keys": frozenset(),
        "prerequisite_memory_ids": frozenset(),
        "mandatory": False,
        "relevance": 0.5,
        "utility": 0.0,
        "direct_credit": 0.0,
        "inherited_credit": 0.0,
        "harm_risk": 0.0,
        "authority": 1.0,
        "confidence": 1.0,
    }
    values.update(overrides)
    return IntegratedContextEvidence(**values)


def request(**overrides: object) -> IntegratedContextCompileRequest:
    values: dict[str, object] = {
        "space_id": SPACE_ID,
        "token_budget": 1000,
        "envelope_tokens": 100,
        "max_items": 8,
        "coverage_demands": (),
        "min_authority": 0.0,
        "min_confidence": 0.0,
    }
    values.update(overrides)
    return IntegratedContextCompileRequest(**values)


def interaction(
    left: UUID,
    right: UUID,
    *,
    kind: ContextInteractionKind,
    value: float,
    group: UUID = GROUP_A,
) -> ContextPairInteraction:
    return ContextPairInteraction(
        left_memory_id=left,
        right_memory_id=right,
        kind=kind,
        value=value,
        standard_error=0.01,
        trial_count=4,
        evidence_group_id=group,
    )


def omission_map(pool: CanonicalContextPool):
    return {entry.memory_id: entry for entry in pool.omissions}


def test_pool_rejects_mixed_scope_and_conflicting_identity() -> None:
    mixed = item(MEMORY_B, space_id=OTHER_SPACE_ID)
    with pytest.raises(ContextCompilerValidationError, match="space_id"):
        CanonicalContextPool.build(request(), (item(MEMORY_A), mixed))

    first = item(MEMORY_A, content="first")
    conflicting = item(MEMORY_A, content="second")
    with pytest.raises(ContextCompilerValidationError, match="conflicting identity"):
        CanonicalContextPool.build(request(), (first, conflicting))


def test_exact_duplicate_retry_is_deduplicated_deterministically() -> None:
    candidate = item(MEMORY_A)

    pool = CanonicalContextPool.build(request(), (candidate, candidate))

    assert pool.candidates == (candidate,)
    assert pool.evidence_by_id[MEMORY_A] == candidate
    assert len(pool.omissions) == 1
    assert pool.omissions[0].memory_id == MEMORY_A
    assert pool.omissions[0].reason is ContextOmissionReason.DUPLICATE_CANDIDATE
    assert pool.omissions[0].related_memory_id == MEMORY_A


def test_same_content_optional_representations_keep_deterministic_best_candidate() -> None:
    shared = "same exact content"
    weaker = item(
        MEMORY_B,
        content=shared,
        relevance=0.4,
        confidence=0.8,
        authority=0.8,
        original_rank=2,
    )
    stronger = item(
        MEMORY_A,
        content=shared,
        relevance=0.8,
        confidence=0.9,
        authority=0.9,
        original_rank=1,
    )

    pool = CanonicalContextPool.build(request(), (weaker, stronger))

    assert tuple(pool.evidence_by_id) == (MEMORY_A,)
    omission = omission_map(pool)[MEMORY_B]
    assert omission.reason is ContextOmissionReason.DUPLICATE_CONTENT
    assert omission.related_memory_id == MEMORY_A


def test_same_content_mandatory_ambiguity_fails_closed() -> None:
    shared = "same mandatory evidence"
    with pytest.raises(ContextCompilerValidationError, match="mandatory duplication"):
        CanonicalContextPool.build(
            request(
                coverage_demands=(
                    ContextCoverageDemand("state", 1.0, True),
                )
            ),
            (
                item(MEMORY_A, content=shared, mandatory=True, coverage_keys={"state"}),
                item(MEMORY_B, content=shared, mandatory=True, coverage_keys={"state"}),
            ),
        )


def test_same_content_mandatory_candidates_are_allowed_for_disjoint_required_demands() -> None:
    shared = "same mandatory evidence"
    pool = CanonicalContextPool.build(
        request(
            coverage_demands=(
                ContextCoverageDemand("state", 1.0, True),
                ContextCoverageDemand("failure", 2.0, True),
            )
        ),
        (
            item(MEMORY_A, content=shared, mandatory=True, coverage_keys={"state"}),
            item(MEMORY_B, content=shared, mandatory=True, coverage_keys={"failure"}),
        ),
    )

    assert pool.mandatory_ids == frozenset({MEMORY_A, MEMORY_B})
    assert pool.omissions == ()


def test_thresholds_omit_optional_candidates_and_their_dependents() -> None:
    weak = item(MEMORY_A, authority=0.4)
    dependent = item(MEMORY_B, prerequisite_memory_ids={MEMORY_A})
    low_confidence = item(MEMORY_C, confidence=0.3)
    survivor = item(MEMORY_D)

    pool = CanonicalContextPool.build(
        request(min_authority=0.7, min_confidence=0.6),
        (dependent, survivor, weak, low_confidence),
    )
    omissions = omission_map(pool)

    assert tuple(pool.evidence_by_id) == (MEMORY_D,)
    assert omissions[MEMORY_A].reason is ContextOmissionReason.BELOW_AUTHORITY
    assert omissions[MEMORY_C].reason is ContextOmissionReason.BELOW_CONFIDENCE
    assert omissions[MEMORY_B].reason is ContextOmissionReason.DEPENDENCY_UNAVAILABLE
    assert omissions[MEMORY_B].related_memory_id == MEMORY_A


def test_mandatory_or_mandatory_prerequisite_threshold_failure_is_hard_error() -> None:
    with pytest.raises(ContextCompilerValidationError, match="mandatory.*authority"):
        CanonicalContextPool.build(
            request(min_authority=0.8),
            (item(MEMORY_A, mandatory=True, authority=0.5),),
        )

    prerequisite = item(MEMORY_A, confidence=0.4)
    mandatory = item(
        MEMORY_B,
        mandatory=True,
        prerequisite_memory_ids={MEMORY_A},
    )
    with pytest.raises(ContextCompilerValidationError, match="mandatory prerequisite"):
        CanonicalContextPool.build(
            request(min_confidence=0.8),
            (mandatory, prerequisite),
        )


def test_unknown_prerequisite_and_dependency_cycle_fail_closed() -> None:
    with pytest.raises(ContextDependencyError, match="unknown prerequisite"):
        CanonicalContextPool.build(
            request(),
            (item(MEMORY_A, prerequisite_memory_ids={MEMORY_D}),),
        )

    with pytest.raises(ContextDependencyError, match="cycle"):
        CanonicalContextPool.build(
            request(),
            (
                item(MEMORY_A, prerequisite_memory_ids={MEMORY_B}),
                item(MEMORY_B, prerequisite_memory_ids={MEMORY_A}),
            ),
        )


def test_prerequisite_closure_and_dependents_are_frozen_and_deterministic() -> None:
    pool = CanonicalContextPool.build(
        request(),
        (
            item(MEMORY_C, prerequisite_memory_ids={MEMORY_B}),
            item(MEMORY_A),
            item(MEMORY_B, prerequisite_memory_ids={MEMORY_A}),
        ),
    )

    assert pool.prerequisite_closure[MEMORY_A] == frozenset()
    assert pool.prerequisite_closure[MEMORY_B] == frozenset({MEMORY_A})
    assert pool.prerequisite_closure[MEMORY_C] == frozenset({MEMORY_A, MEMORY_B})
    assert pool.dependents[MEMORY_A] == frozenset({MEMORY_B, MEMORY_C})
    assert pool.dependents[MEMORY_B] == frozenset({MEMORY_C})
    with pytest.raises(TypeError):
        pool.prerequisite_closure[MEMORY_A] = frozenset()


def test_interactions_reject_unknown_endpoints_and_conflicts() -> None:
    candidates = (item(MEMORY_A), item(MEMORY_B))
    with pytest.raises(ContextCompilerValidationError, match="unknown candidate"):
        CanonicalContextPool.build(
            request(),
            candidates,
            interactions=(
                interaction(
                    MEMORY_A,
                    MEMORY_C,
                    kind=ContextInteractionKind.SYNERGY,
                    value=0.4,
                ),
            ),
        )

    with pytest.raises(ContextCompilerValidationError, match="conflicting interaction"):
        CanonicalContextPool.build(
            request(),
            candidates,
            interactions=(
                interaction(
                    MEMORY_A,
                    MEMORY_B,
                    kind=ContextInteractionKind.SYNERGY,
                    value=0.4,
                    group=GROUP_A,
                ),
                interaction(
                    MEMORY_A,
                    MEMORY_B,
                    kind=ContextInteractionKind.REDUNDANCY,
                    value=-0.4,
                    group=GROUP_B,
                ),
            ),
        )


def test_identical_interaction_retries_are_deduplicated() -> None:
    signal = interaction(
        MEMORY_A,
        MEMORY_B,
        kind=ContextInteractionKind.SYNERGY,
        value=0.4,
    )
    pool = CanonicalContextPool.build(
        request(),
        (item(MEMORY_A), item(MEMORY_B)),
        interactions=(signal, signal),
    )

    assert pool.interactions == (signal,)
    assert pool.interaction_by_pair[(MEMORY_A, MEMORY_B)] == signal


def test_objective_breakdown_exactly_separates_every_component() -> None:
    policy = ContextObjectivePolicy(
        relevance_weight=1.0,
        utility_weight=0.5,
        direct_credit_weight=0.4,
        inherited_credit_weight=0.2,
        harm_weight=0.8,
        new_expert_bonus=0.10,
        new_subject_bonus=0.05,
        new_source_cluster_bonus=0.03,
        pair_interaction_weight=0.5,
        inherited_contribution_cap=0.10,
        pair_value_cap=0.25,
    )
    compile_request = request(
        objective_policy=policy,
        coverage_demands=(
            ContextCoverageDemand("required", 2.0, True),
            ContextCoverageDemand("optional", 0.5, False),
        ),
    )
    first = item(
        MEMORY_A,
        expert="research",
        subject_key="subject-a",
        source_cluster_key="source-a",
        coverage_keys={"required"},
        estimated_tokens=100,
        relevance=0.8,
        utility=0.4,
        direct_credit=0.5,
        inherited_credit=1.0,
        harm_risk=0.1,
    )
    second = item(
        MEMORY_B,
        expert="causal",
        subject_key="subject-b",
        source_cluster_key="source-b",
        coverage_keys={"required", "optional"},
        estimated_tokens=200,
        relevance=0.6,
        utility=-0.2,
        direct_credit=-0.25,
        inherited_credit=-1.0,
        harm_risk=0.2,
    )
    pair = interaction(
        MEMORY_A,
        MEMORY_B,
        kind=ContextInteractionKind.SYNERGY,
        value=0.8,
    )
    pool = CanonicalContextPool.build(
        compile_request,
        (second, first),
        interactions=(pair,),
    )
    breakdown = ContextSetEvaluator(pool, compile_request).evaluate(
        {MEMORY_A, MEMORY_B}
    )

    assert breakdown.relevance_contribution == pytest.approx(1.4)
    assert breakdown.utility_contribution == pytest.approx(0.1)
    assert breakdown.direct_credit_contribution == pytest.approx(0.1)
    assert breakdown.inherited_credit_contribution == pytest.approx(0.0)
    assert breakdown.harm_penalty == pytest.approx(-0.24)
    assert breakdown.required_coverage_weight == pytest.approx(2.0)
    assert breakdown.optional_coverage_weight == pytest.approx(0.5)
    assert breakdown.expert_diversity_bonus == pytest.approx(0.20)
    assert breakdown.subject_diversity_bonus == pytest.approx(0.10)
    assert breakdown.source_diversity_bonus == pytest.approx(0.06)
    assert breakdown.synergy_bonus == pytest.approx(0.125)
    assert breakdown.redundancy_penalty == pytest.approx(0.0)
    assert breakdown.selected_base_value == pytest.approx(1.36)
    assert breakdown.total_set_value == pytest.approx(4.345)
    assert breakdown.evidence_tokens == 300
    assert breakdown.item_count == 2
    assert breakdown.value_per_token == pytest.approx(4.345 / 300)


def test_coverage_and_diversity_saturate_and_pair_requires_both_endpoints() -> None:
    compile_request = request(
        coverage_demands=(ContextCoverageDemand("state", 2.0, True),)
    )
    first = item(
        MEMORY_A,
        expert="research",
        subject_key="same",
        source_cluster_key="same",
        coverage_keys={"state"},
    )
    second = item(
        MEMORY_B,
        expert="research",
        subject_key="same",
        source_cluster_key="same",
        coverage_keys={"state"},
    )
    pair = interaction(
        MEMORY_A,
        MEMORY_B,
        kind=ContextInteractionKind.REDUNDANCY,
        value=-0.2,
    )
    pool = CanonicalContextPool.build(
        compile_request,
        (first, second),
        interactions=(pair,),
    )
    evaluator = ContextSetEvaluator(pool, compile_request)
    one = evaluator.evaluate({MEMORY_A})
    two = evaluator.evaluate({MEMORY_A, MEMORY_B})

    assert one.required_coverage_weight == 2.0
    assert two.required_coverage_weight == 2.0
    assert one.expert_diversity_bonus == two.expert_diversity_bonus
    assert one.subject_diversity_bonus == two.subject_diversity_bonus
    assert one.source_diversity_bonus == two.source_diversity_bonus
    assert one.redundancy_penalty == 0.0
    assert two.redundancy_penalty < 0.0


def test_evaluator_rejects_unknown_or_dependency_open_sets() -> None:
    pool = CanonicalContextPool.build(
        request(),
        (
            item(MEMORY_A),
            item(MEMORY_B, prerequisite_memory_ids={MEMORY_A}),
        ),
    )
    evaluator = ContextSetEvaluator(pool, request())

    with pytest.raises(ContextCompilerValidationError, match="unknown selected"):
        evaluator.evaluate({MEMORY_D})
    with pytest.raises(ContextDependencyError, match="dependency-closed"):
        evaluator.evaluate({MEMORY_B})


def test_objective_key_prioritizes_required_coverage_before_larger_optional_value() -> None:
    compile_request = request(
        coverage_demands=(ContextCoverageDemand("required", 1.0, True),)
    )
    required = item(
        MEMORY_A,
        coverage_keys={"required"},
        relevance=0.05,
        estimated_tokens=300,
    )
    attractive = item(
        MEMORY_B,
        relevance=1.0,
        utility=1.0,
        direct_credit=1.0,
        estimated_tokens=50,
    )
    pool = CanonicalContextPool.build(compile_request, (required, attractive))
    evaluator = ContextSetEvaluator(pool, compile_request)

    assert evaluator.objective_key({MEMORY_A}) > evaluator.objective_key({MEMORY_B})


def test_objective_key_breaks_equal_value_ties_by_tokens_items_and_uuid() -> None:
    compile_request = request()
    first = item(MEMORY_A, relevance=0.5, estimated_tokens=50)
    second = item(MEMORY_B, relevance=0.5, estimated_tokens=100)
    pool = CanonicalContextPool.build(compile_request, (first, second))
    evaluator = ContextSetEvaluator(pool, compile_request)

    assert evaluator.objective_key({MEMORY_A}) > evaluator.objective_key({MEMORY_B})

    equal_a = item(MEMORY_A, relevance=0.5, estimated_tokens=50)
    equal_b = item(MEMORY_B, relevance=0.5, estimated_tokens=50)
    equal_pool = CanonicalContextPool.build(compile_request, (equal_b, equal_a))
    equal_evaluator = ContextSetEvaluator(equal_pool, compile_request)
    assert equal_evaluator.objective_key({MEMORY_A}) > equal_evaluator.objective_key(
        {MEMORY_B}
    )


def test_marginal_value_uses_exact_set_interactions_and_coverage() -> None:
    compile_request = request(
        coverage_demands=(ContextCoverageDemand("state", 1.0, True),)
    )
    first = item(MEMORY_A, relevance=0.2, coverage_keys={"state"})
    second = item(MEMORY_B, relevance=0.2, coverage_keys={"state"})
    pair = interaction(
        MEMORY_A,
        MEMORY_B,
        kind=ContextInteractionKind.REDUNDANCY,
        value=-0.25,
    )
    pool = CanonicalContextPool.build(
        compile_request,
        (first, second),
        interactions=(pair,),
    )
    evaluator = ContextSetEvaluator(pool, compile_request)

    singleton_gain = evaluator.marginal_value(frozenset(), {MEMORY_B})
    redundant_gain = evaluator.marginal_value({MEMORY_A}, {MEMORY_B})

    assert redundant_gain < singleton_gain


def test_pool_and_objective_are_invariant_to_input_order() -> None:
    compile_request = request(
        coverage_demands=(ContextCoverageDemand("state", 1.0, True),)
    )
    candidates = (
        item(MEMORY_A, coverage_keys={"state"}),
        item(MEMORY_B, prerequisite_memory_ids={MEMORY_A}),
        item(MEMORY_C),
    )
    interactions = (
        interaction(
            MEMORY_A,
            MEMORY_B,
            kind=ContextInteractionKind.SYNERGY,
            value=0.2,
        ),
    )
    first_pool = CanonicalContextPool.build(
        compile_request,
        candidates,
        interactions=interactions,
    )
    second_pool = CanonicalContextPool.build(
        compile_request,
        tuple(reversed(candidates)),
        interactions=tuple(reversed(interactions)),
    )

    assert first_pool == second_pool
    first = ContextSetEvaluator(first_pool, compile_request).evaluate(
        {MEMORY_A, MEMORY_B}
    )
    second = ContextSetEvaluator(second_pool, compile_request).evaluate(
        {MEMORY_A, MEMORY_B}
    )
    assert first == second
