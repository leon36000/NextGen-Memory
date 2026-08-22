from __future__ import annotations

import hashlib
import importlib
from uuid import UUID

import pytest

from nextgen_memory.context_compiler_contracts import (
    ContextCompilerValidationError,
    ContextCoverageDemand,
    ContextDependencyError,
    ContextInteractionKind,
    ContextOmissionReason,
    ContextPairInteraction,
    EvidenceFidelity,
    IntegratedContextCompileRequest,
    IntegratedContextEvidence,
)

objective_module = importlib.import_module("nextgen_memory.context_objective")
CanonicalContextProblem = objective_module.CanonicalContextProblem
ContextSelectionSolution = objective_module.ContextSelectionSolution
ContextSetEvaluation = objective_module.ContextSetEvaluation
canonicalize_context_problem = objective_module.canonicalize_context_problem
dependency_closure = objective_module.dependency_closure
evaluate_context_set = objective_module.evaluate_context_set
is_better_context_set = objective_module.is_better_context_set
order_selected_evidence = objective_module.order_selected_evidence

SPACE_ID = UUID("11111111-1111-5111-8111-111111111111")
OTHER_SPACE_ID = UUID("22222222-2222-5222-8222-222222222222")
MEMORY_A = UUID("aaaaaaaa-aaaa-5aaa-8aaa-aaaaaaaaaaaa")
MEMORY_B = UUID("bbbbbbbb-bbbb-5bbb-8bbb-bbbbbbbbbbbb")
MEMORY_C = UUID("cccccccc-cccc-5ccc-8ccc-cccccccccccc")
MEMORY_D = UUID("dddddddd-dddd-5ddd-8ddd-dddddddddddd")
MEMORY_E = UUID("eeeeeeee-eeee-5eee-8eee-eeeeeeeeeeee")
GROUP_ID = UUID("99999999-9999-5999-8999-999999999999")


def request(**overrides: object) -> IntegratedContextCompileRequest:
    values: dict[str, object] = {
        "space_id": SPACE_ID,
        "token_budget": 700,
        "envelope_tokens": 100,
        "max_items": 6,
        "coverage_demands": (
            ContextCoverageDemand("cause", 2.0, True),
            ContextCoverageDemand("time", 1.5, False),
        ),
    }
    values.update(overrides)
    return IntegratedContextCompileRequest(**values)


def evidence(memory_id: UUID, **overrides: object) -> IntegratedContextEvidence:
    suffix = str(memory_id)[0]
    values: dict[str, object] = {
        "memory_id": memory_id,
        "space_id": SPACE_ID,
        "expert": f"expert-{suffix}",
        "subject_key": f"subject-{suffix}",
        "source_cluster_key": f"source-{suffix}",
        "content": f"evidence-{memory_id}",
        "backend_ref": f"memory:{memory_id}",
        "source_uri": f"https://example.invalid/{memory_id}",
        "fidelity": EvidenceFidelity.EXACT,
        "estimated_tokens": 100,
        "original_rank": 1,
        "coverage_keys": (),
        "prerequisite_memory_ids": (),
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
    if "content_hash" not in overrides:
        content = values.get("content")
        normalized_content = (
            content.strip() if isinstance(content, str) else ""
        )
        values["content_hash"] = hashlib.sha256(
            normalized_content.encode("utf-8")
        ).hexdigest()
    return IntegratedContextEvidence(**values)


def interaction(
    left: UUID,
    right: UUID,
    *,
    kind: ContextInteractionKind = ContextInteractionKind.SYNERGY,
    value: float = 0.2,
    evidence_group_id: UUID = GROUP_ID,
) -> ContextPairInteraction:
    return ContextPairInteraction(
        left_memory_id=left,
        right_memory_id=right,
        kind=kind,
        value=value,
        standard_error=0.01,
        trial_count=3,
        evidence_group_id=evidence_group_id,
    )


def test_canonicalization_rejects_scope_identity_unknown_prerequisite_and_cycle() -> None:
    with pytest.raises(ContextCompilerValidationError, match="space_id"):
        canonicalize_context_problem(
            request(),
            (evidence(MEMORY_A), evidence(MEMORY_B, space_id=OTHER_SPACE_ID)),
            (),
        )
    with pytest.raises(ContextCompilerValidationError, match="immutable identity"):
        canonicalize_context_problem(
            request(),
            (
                evidence(MEMORY_A),
                evidence(MEMORY_A, content="conflict"),
            ),
            (),
        )
    with pytest.raises(ContextDependencyError, match="unknown prerequisite"):
        canonicalize_context_problem(
            request(),
            (evidence(MEMORY_A, prerequisite_memory_ids=(MEMORY_E,)),),
            (),
        )
    with pytest.raises(ContextDependencyError, match="cycle"):
        canonicalize_context_problem(
            request(),
            (
                evidence(MEMORY_A, prerequisite_memory_ids=(MEMORY_B,)),
                evidence(MEMORY_B, prerequisite_memory_ids=(MEMORY_A,)),
            ),
            (),
        )


def test_duplicate_candidates_choose_best_dynamic_representative() -> None:
    low = evidence(MEMORY_A, relevance=0.2, original_rank=2)
    high = evidence(MEMORY_A, relevance=0.9, original_rank=1)

    problem = canonicalize_context_problem(request(), (low, high, high), ())

    assert problem.candidates == (high,)
    assert [item.reason for item in problem.initial_omissions] == [
        ContextOmissionReason.DUPLICATE_CANDIDATE,
        ContextOmissionReason.DUPLICATE_CANDIDATE,
    ]


def test_content_dedup_preserves_structural_anchor() -> None:
    prerequisite = evidence(
        MEMORY_A,
        content="same",
        relevance=0.1,
    )
    stronger_duplicate = evidence(
        MEMORY_B,
        content="same",
        relevance=0.9,
    )
    dependent = evidence(
        MEMORY_C,
        prerequisite_memory_ids=(MEMORY_A,),
        mandatory=True,
    )

    problem = canonicalize_context_problem(
        request(),
        (prerequisite, stronger_duplicate, dependent),
        (),
    )

    assert set(problem.candidate_by_id) == {MEMORY_A, MEMORY_C}
    assert problem.mandatory_closure == frozenset({MEMORY_A, MEMORY_C})
    assert problem.initial_omissions[0].reason is ContextOmissionReason.DUPLICATE_CONTENT


def test_ambiguous_mandatory_same_content_fails() -> None:
    with pytest.raises(ContextCompilerValidationError, match="mandatory duplicate"):
        canonicalize_context_problem(
            request(),
            (
                evidence(
                    MEMORY_A,
                    mandatory=True,
                    content="same",
                                coverage_keys=("cause",),
                ),
                evidence(
                    MEMORY_B,
                    mandatory=True,
                    content="same",
                                coverage_keys=("cause",),
                ),
            ),
            (),
        )


def test_thresholds_omit_optional_and_propagate_dependency_unavailability() -> None:
    problem = canonicalize_context_problem(
        request(minimum_authority=0.8, minimum_confidence=0.8),
        (
            evidence(MEMORY_A, authority=0.7),
            evidence(MEMORY_B, confidence=0.7),
            evidence(MEMORY_C, prerequisite_memory_ids=(MEMORY_B,)),
            evidence(MEMORY_D),
        ),
        (),
    )

    assert tuple(problem.candidate_by_id) == (MEMORY_D,)
    by_id = {item.memory_id: item.reason for item in problem.initial_omissions}
    assert by_id[MEMORY_A] is ContextOmissionReason.BELOW_AUTHORITY
    assert by_id[MEMORY_B] is ContextOmissionReason.BELOW_CONFIDENCE
    assert by_id[MEMORY_C] is ContextOmissionReason.DEPENDENCY_UNAVAILABLE

    with pytest.raises(ContextCompilerValidationError, match="mandatory"):
        canonicalize_context_problem(
            request(minimum_authority=0.8),
            (
                evidence(MEMORY_A, authority=0.7),
                evidence(
                    MEMORY_B,
                    mandatory=True,
                    prerequisite_memory_ids=(MEMORY_A,),
                ),
            ),
            (),
        )


def test_interactions_are_validated_deduplicated_and_filtered() -> None:
    duplicate = interaction(MEMORY_A, MEMORY_B)
    problem = canonicalize_context_problem(
        request(minimum_confidence=0.8),
        (
            evidence(MEMORY_A),
            evidence(MEMORY_B),
            evidence(MEMORY_C, confidence=0.5),
        ),
        (duplicate, duplicate, interaction(MEMORY_A, MEMORY_C)),
    )

    assert tuple(problem.interactions) == ((MEMORY_A, MEMORY_B),)

    with pytest.raises(ContextCompilerValidationError, match="unknown candidate"):
        canonicalize_context_problem(
            request(),
            (evidence(MEMORY_A), evidence(MEMORY_B)),
            (interaction(MEMORY_A, MEMORY_E),),
        )
    with pytest.raises(ContextCompilerValidationError, match="conflicting interaction"):
        canonicalize_context_problem(
            request(),
            (evidence(MEMORY_A), evidence(MEMORY_B)),
            (
                interaction(MEMORY_A, MEMORY_B, value=0.2),
                interaction(MEMORY_A, MEMORY_B, value=0.3),
            ),
        )


def test_dependency_closure_is_transitive_and_immutable() -> None:
    problem = canonicalize_context_problem(
        request(),
        (
            evidence(MEMORY_A),
            evidence(MEMORY_B, prerequisite_memory_ids=(MEMORY_A,)),
            evidence(MEMORY_C, prerequisite_memory_ids=(MEMORY_B,)),
        ),
        (),
    )

    assert problem.prerequisite_closure[MEMORY_C] == frozenset({MEMORY_A, MEMORY_B})
    assert dependency_closure(problem, (MEMORY_C,)) == frozenset(
        {MEMORY_A, MEMORY_B, MEMORY_C}
    )
    with pytest.raises(TypeError):
        problem.prerequisite_closure[MEMORY_A] = frozenset()


def test_objective_separates_signals_and_saturates_coverage() -> None:
    item_a = evidence(
        MEMORY_A,
        expert="research",
        subject_key="cause",
        source_cluster_key="source-a",
        coverage_keys=("cause", "time"),
        relevance=0.8,
        utility=0.2,
        direct_credit=0.3,
        inherited_credit=1.0,
        harm_risk=0.1,
    )
    item_b = evidence(
        MEMORY_B,
        expert="repository",
        subject_key="time",
        source_cluster_key="source-b",
        coverage_keys=("cause",),
        relevance=0.4,
        utility=-0.2,
        direct_credit=-0.1,
        inherited_credit=-1.0,
        harm_risk=0.2,
    )
    problem = canonicalize_context_problem(
        request(),
        (item_a, item_b),
        (interaction(MEMORY_A, MEMORY_B, value=0.5),),
    )

    evaluation = evaluate_context_set(problem, (MEMORY_A, MEMORY_B))
    breakdown = evaluation.breakdown

    assert evaluation.covered_required_weight == pytest.approx(2.0)
    assert evaluation.covered_required_keys == ("cause",)
    assert evaluation.covered_optional_keys == ("time",)
    assert breakdown.relevance_value == pytest.approx(1.2)
    assert breakdown.utility_value == pytest.approx(0.0)
    assert breakdown.direct_credit_value == pytest.approx(0.09)
    assert breakdown.inherited_credit_value == pytest.approx(0.0)
    assert breakdown.harm_penalty == pytest.approx(-0.225)
    assert breakdown.required_coverage_value == pytest.approx(2.0)
    assert breakdown.optional_coverage_value == pytest.approx(1.5)
    assert breakdown.expert_diversity_bonus == pytest.approx(0.10)
    assert breakdown.subject_diversity_bonus == pytest.approx(0.06)
    assert breakdown.source_diversity_bonus == pytest.approx(0.08)
    assert breakdown.synergy_bonus == pytest.approx(0.0625)
    assert breakdown.total_set_value == pytest.approx(4.8675)
    assert breakdown.value_per_token == pytest.approx(4.8675 / 200)


def test_harm_and_redundancy_can_make_value_negative() -> None:
    harmful = evidence(
        MEMORY_A,
        relevance=1.0,
        utility=-1.0,
        direct_credit=-1.0,
        inherited_credit=-1.0,
        harm_risk=1.0,
    )
    neutral = evidence(MEMORY_B, relevance=0.0)
    problem = canonicalize_context_problem(
        request(coverage_demands=()),
        (harmful, neutral),
        (
            interaction(
                MEMORY_A,
                MEMORY_B,
                kind=ContextInteractionKind.REDUNDANCY,
                value=-1.0,
            ),
        ),
    )

    one = evaluate_context_set(problem, (MEMORY_A,))
    both = evaluate_context_set(problem, (MEMORY_A, MEMORY_B))

    assert one.breakdown.total_set_value < 0
    assert both.breakdown.redundancy_penalty == pytest.approx(-0.0625)


def test_feasibility_rejects_unknown_dependency_cap_and_budget() -> None:
    problem = canonicalize_context_problem(
        request(
            token_budget=350,
            envelope_tokens=100,
            max_items=2,
            max_items_per_expert=1,
        ),
        (
            evidence(MEMORY_A, expert="shared", estimated_tokens=100),
            evidence(
                MEMORY_B,
                expert="shared",
                prerequisite_memory_ids=(MEMORY_A,),
                estimated_tokens=100,
            ),
            evidence(MEMORY_C, estimated_tokens=200),
        ),
        (),
    )

    with pytest.raises(ContextCompilerValidationError, match="unknown"):
        evaluate_context_set(problem, (MEMORY_E,))
    with pytest.raises(ContextDependencyError, match="prerequisite"):
        evaluate_context_set(problem, (MEMORY_B,))
    with pytest.raises(ContextCompilerValidationError, match="expert cap"):
        evaluate_context_set(problem, (MEMORY_A, MEMORY_B))
    with pytest.raises(ContextCompilerValidationError, match="token budget"):
        evaluate_context_set(problem, (MEMORY_A, MEMORY_C))


def test_set_comparison_is_lexicographic_and_prefers_fewer_tokens() -> None:
    problem = canonicalize_context_problem(
        request(),
        (
            evidence(MEMORY_A, coverage_keys=("cause",), relevance=0.1),
            evidence(MEMORY_B, relevance=1.0, estimated_tokens=50),
            evidence(
                MEMORY_C,
                coverage_keys=("cause",),
                relevance=0.1,
                estimated_tokens=80,
            ),
        ),
        (),
    )
    a = evaluate_context_set(problem, (MEMORY_A,))
    b = evaluate_context_set(problem, (MEMORY_B,))
    c = evaluate_context_set(problem, (MEMORY_C,))

    assert is_better_context_set(a, b, 1e-12) is True
    assert is_better_context_set(b, a, 1e-12) is False
    assert is_better_context_set(c, a, 1e-12) is True
    assert is_better_context_set(a, c, 1e-12) is False
    assert is_better_context_set(a, None, 1e-12) is True


def test_ordering_is_topological_and_uses_declared_priorities() -> None:
    problem = canonicalize_context_problem(
        request(),
        (
            evidence(MEMORY_A, original_rank=3),
            evidence(
                MEMORY_B,
                prerequisite_memory_ids=(MEMORY_A,),
                coverage_keys=("cause",),
                original_rank=2,
            ),
            evidence(MEMORY_C, mandatory=True, original_rank=1),
            evidence(MEMORY_D, relevance=0.9, original_rank=4),
        ),
        (),
    )

    ordered = order_selected_evidence(
        problem,
        (MEMORY_A, MEMORY_B, MEMORY_C, MEMORY_D),
    )

    assert ordered.index(MEMORY_A) < ordered.index(MEMORY_B)
    assert ordered[:2] == (MEMORY_A, MEMORY_C)
    assert set(ordered) == {MEMORY_A, MEMORY_B, MEMORY_C, MEMORY_D}


def test_internal_problem_and_solution_contracts_are_immutable() -> None:
    problem = canonicalize_context_problem(
        request(),
        (evidence(MEMORY_A),),
        (),
    )
    evaluation = evaluate_context_set(problem, (MEMORY_A,))
    solution = ContextSelectionSolution(
        selected_ids=frozenset({MEMORY_A}),
        solver_mode=objective_module.ContextSolverMode.EXACT,
        phase_by_id={MEMORY_A: objective_module.ContextSelectionPhase.EXACT},
        trigger_by_id={MEMORY_A: MEMORY_A},
        optimality_gap=0.0,
    )

    assert isinstance(problem, CanonicalContextProblem)
    assert isinstance(evaluation, ContextSetEvaluation)
    assert solution.selected_ids == frozenset({MEMORY_A})
    with pytest.raises(TypeError):
        solution.phase_by_id[MEMORY_A] = objective_module.ContextSelectionPhase.GREEDY
