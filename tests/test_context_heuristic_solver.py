from __future__ import annotations

import importlib
import random
from uuid import UUID

import pytest

from nextgen_memory.context_compiler_contracts import (
    ContextCompilerValidationError,
    ContextCoverageDemand,
    ContextInteractionKind,
    ContextObjectivePolicy,
    ContextPairInteraction,
    ContextSelectionPhase,
    ContextSolverMode,
    EvidenceFidelity,
    IntegratedContextCompileRequest,
    IntegratedContextEvidence,
)
from nextgen_memory.context_objective import (
    canonicalize_context_problem,
    evaluate_context_set,
)

heuristic_module = importlib.import_module(
    "nextgen_memory.context_heuristic_solver"
)
HeuristicContextSolver = heuristic_module.HeuristicContextSolver
candidate_additions = heuristic_module.candidate_additions

SPACE_ID = UUID("11111111-1111-5111-8111-111111111111")
GROUP_ID = UUID("99999999-9999-5999-8999-999999999999")


def memory_id(index: int) -> UUID:
    return UUID(f"00000000-0000-5000-8000-{index:012d}")


def evidence(index: int, **overrides: object) -> IntegratedContextEvidence:
    character = "0123456789abcdef"[index % 16]
    values: dict[str, object] = {
        "memory_id": memory_id(index),
        "space_id": SPACE_ID,
        "expert": f"expert-{index % 3}",
        "subject_key": f"subject-{index % 4}",
        "source_cluster_key": f"source-{index % 5}",
        "content": f"evidence-{index}",
        "content_hash": character * 64,
        "backend_ref": f"memory:{index}",
        "source_uri": None,
        "fidelity": EvidenceFidelity.EXACT,
        "estimated_tokens": 50,
        "original_rank": index,
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
    return IntegratedContextEvidence(**values)


def request(**overrides: object) -> IntegratedContextCompileRequest:
    values: dict[str, object] = {
        "space_id": SPACE_ID,
        "token_budget": 500,
        "envelope_tokens": 50,
        "max_items": 8,
        "coverage_demands": (),
        "exact_candidate_limit": 1,
        "local_search_pass_limit": 4,
    }
    values.update(overrides)
    return IntegratedContextCompileRequest(**values)


def interaction(
    left: int,
    right: int,
    *,
    kind: ContextInteractionKind,
    value: float,
) -> ContextPairInteraction:
    return ContextPairInteraction(
        memory_id(left),
        memory_id(right),
        kind,
        value,
        0.01,
        3,
        GROUP_ID,
    )


def solve(
    compile_request: IntegratedContextCompileRequest,
    candidates: tuple[IntegratedContextEvidence, ...],
    interactions: tuple[ContextPairInteraction, ...] = (),
):
    problem = canonicalize_context_problem(
        compile_request,
        candidates,
        interactions,
    )
    return problem, HeuristicContextSolver().solve(problem)


def test_mandatory_seed_and_prerequisites_are_never_dropped() -> None:
    problem, solution = solve(
        request(),
        (
            evidence(1),
            evidence(
                2,
                mandatory=True,
                prerequisite_memory_ids=(memory_id(1),),
                relevance=0.0,
            ),
            evidence(3, relevance=-0.0, harm_risk=1.0),
        ),
    )

    assert problem.mandatory_closure == frozenset({memory_id(1), memory_id(2)})
    assert problem.mandatory_closure.issubset(solution.selected_ids)
    assert solution.phase_by_id[memory_id(1)] is ContextSelectionPhase.MANDATORY
    assert solution.phase_by_id[memory_id(2)] is ContextSelectionPhase.MANDATORY


def test_required_coverage_uses_weight_before_optional_value() -> None:
    compile_request = request(
        token_budget=110,
        envelope_tokens=50,
        max_items=1,
        coverage_demands=(
            ContextCoverageDemand("major", 3.0, True),
            ContextCoverageDemand("minor", 1.0, True),
        ),
    )
    problem, solution = solve(
        compile_request,
        (
            evidence(1, coverage_keys=("minor",), relevance=1.0),
            evidence(2, coverage_keys=("major",), relevance=0.0),
        ),
    )

    assert solution.selected_ids == frozenset({memory_id(2)})
    assert solution.phase_by_id[memory_id(2)] is ContextSelectionPhase.COVERAGE
    evaluation = evaluate_context_set(problem, solution.selected_ids)
    assert evaluation.covered_required_weight == pytest.approx(3.0)
    assert evaluation.uncovered_required_keys == ("minor",)


def test_required_phase_adds_candidate_with_missing_prerequisite_atomically() -> None:
    _, solution = solve(
        request(
            coverage_demands=(ContextCoverageDemand("cause", 2.0, True),)
        ),
        (
            evidence(1, relevance=0.0),
            evidence(
                2,
                prerequisite_memory_ids=(memory_id(1),),
                coverage_keys=("cause",),
                relevance=0.0,
            ),
        ),
    )

    assert solution.selected_ids == frozenset({memory_id(1), memory_id(2)})
    assert solution.phase_by_id[memory_id(1)] is ContextSelectionPhase.COVERAGE
    assert solution.trigger_by_id[memory_id(1)] == memory_id(2)


def test_required_phase_can_return_incomplete_without_raising() -> None:
    problem, solution = solve(
        request(
            token_budget=100,
            envelope_tokens=50,
            max_items=1,
            coverage_demands=(ContextCoverageDemand("missing", 2.0, True),),
        ),
        (evidence(1, relevance=0.4),),
    )

    assert evaluate_context_set(
        problem,
        solution.selected_ids,
    ).uncovered_required_keys == ("missing",)


def test_optional_fill_uses_positive_marginal_value_per_added_token() -> None:
    policy = ContextObjectivePolicy(
        new_expert_bonus=0.0,
        new_subject_bonus=0.0,
        new_source_cluster_bonus=0.0,
    )
    problem, solution = solve(
        request(
            token_budget=130,
            envelope_tokens=50,
            max_items=1,
            objective_policy=policy,
        ),
        (
            evidence(1, relevance=0.8, estimated_tokens=80),
            evidence(2, relevance=0.6, estimated_tokens=40),
        ),
    )

    assert solution.selected_ids == frozenset({memory_id(2)})
    assert solution.phase_by_id[memory_id(2)] is ContextSelectionPhase.GREEDY
    assert evaluate_context_set(problem, solution.selected_ids).evidence_tokens == 40


def test_non_positive_optional_evidence_is_not_admitted() -> None:
    policy = ContextObjectivePolicy(
        new_expert_bonus=0.0,
        new_subject_bonus=0.0,
        new_source_cluster_bonus=0.0,
    )
    problem, solution = solve(
        request(objective_policy=policy),
        (
            evidence(1, relevance=0.4),
            evidence(
                2,
                relevance=0.0,
                utility=-1.0,
                direct_credit=-1.0,
                inherited_credit=-1.0,
                harm_risk=1.0,
            ),
        ),
    )

    assert solution.selected_ids == frozenset({memory_id(1)})
    assert evaluate_context_set(
        problem,
        solution.selected_ids,
    ).evidence_tokens < problem.request.usable_evidence_tokens


def test_positive_synergy_pair_is_considered_as_joint_addition() -> None:
    policy = ContextObjectivePolicy(
        new_expert_bonus=0.0,
        new_subject_bonus=0.0,
        new_source_cluster_bonus=0.0,
        pair_interaction_weight=1.0,
        pair_interaction_cap=1.0,
    )
    problem = canonicalize_context_problem(
        request(objective_policy=policy),
        (
            evidence(1, relevance=0.0, harm_risk=0.08),
            evidence(2, relevance=0.0, harm_risk=0.08),
        ),
        (
            interaction(
                1,
                2,
                kind=ContextInteractionKind.SYNERGY,
                value=0.2,
            ),
        ),
    )

    additions = candidate_additions(problem, frozenset())
    solution = HeuristicContextSolver().solve(problem)

    assert frozenset({memory_id(1), memory_id(2)}) in additions
    assert solution.selected_ids == frozenset({memory_id(1), memory_id(2)})


def test_redundancy_stops_duplicate_fill() -> None:
    policy = ContextObjectivePolicy(
        new_expert_bonus=0.0,
        new_subject_bonus=0.0,
        new_source_cluster_bonus=0.0,
        pair_interaction_weight=2.0,
        pair_interaction_cap=1.0,
    )
    problem, solution = solve(
        request(objective_policy=policy),
        (evidence(1, relevance=0.4), evidence(2, relevance=0.4)),
        (
            interaction(
                1,
                2,
                kind=ContextInteractionKind.REDUNDANCY,
                value=-0.3,
            ),
        ),
    )

    assert solution.selected_ids == frozenset({memory_id(1)})
    assert evaluate_context_set(
        problem,
        solution.selected_ids,
    ).breakdown.total_set_value > 0


def test_local_search_can_replace_coverage_item_with_cheaper_peer() -> None:
    policy = ContextObjectivePolicy(
        new_expert_bonus=0.0,
        new_subject_bonus=0.0,
        new_source_cluster_bonus=0.0,
    )
    problem, solution = solve(
        request(
            token_budget=150,
            envelope_tokens=50,
            max_items=1,
            coverage_demands=(ContextCoverageDemand("cause", 2.0, True),),
            objective_policy=policy,
        ),
        (
            evidence(
                1,
                coverage_keys=("cause",),
                relevance=0.5,
                estimated_tokens=90,
            ),
            evidence(
                2,
                coverage_keys=("cause",),
                relevance=0.5,
                estimated_tokens=40,
            ),
        ),
    )

    assert solution.selected_ids == frozenset({memory_id(2)})
    assert evaluate_context_set(problem, solution.selected_ids).evidence_tokens == 40


def test_heuristic_preserves_dependencies_and_mandatory_items() -> None:
    problem, solution = solve(
        request(local_search_pass_limit=8),
        (
            evidence(1, mandatory=True, relevance=0.0),
            evidence(
                2,
                prerequisite_memory_ids=(memory_id(1),),
                relevance=0.8,
            ),
            evidence(
                3,
                prerequisite_memory_ids=(memory_id(2),),
                relevance=0.7,
            ),
        ),
    )

    assert memory_id(1) in solution.selected_ids
    for item_id in solution.selected_ids:
        assert problem.prerequisite_closure[item_id].issubset(solution.selected_ids)


def test_fallbacks_make_result_no_worse_than_best_single_addition() -> None:
    problem, solution = solve(
        request(),
        (
            evidence(1, mandatory=True, relevance=0.0),
            evidence(2, relevance=0.7),
            evidence(3, relevance=0.6),
        ),
    )
    final = evaluate_context_set(problem, solution.selected_ids)
    mandatory = evaluate_context_set(problem, problem.mandatory_closure)

    assert final.breakdown.total_set_value >= mandatory.breakdown.total_set_value
    for addition in candidate_additions(problem, problem.mandatory_closure):
        try:
            candidate = evaluate_context_set(
                problem,
                problem.mandatory_closure | addition,
            )
        except ValueError:
            continue
        assert not (
            candidate.covered_required_weight > final.covered_required_weight
            or (
                candidate.covered_required_weight == final.covered_required_weight
                and candidate.breakdown.total_set_value
                > final.breakdown.total_set_value
            )
        )


def test_solver_is_permutation_invariant_on_1000_orders() -> None:
    candidates = tuple(
        evidence(
            index,
            relevance=0.2 + index * 0.05,
            coverage_keys=("cause",) if index % 3 == 0 else (),
            prerequisite_memory_ids=(memory_id(index - 1),)
            if index in {4, 7}
            else (),
        )
        for index in range(1, 9)
    )
    interactions = (
        interaction(2, 5, kind=ContextInteractionKind.SYNERGY, value=0.3),
        interaction(3, 6, kind=ContextInteractionKind.REDUNDANCY, value=-0.2),
    )
    compile_request = request(
        coverage_demands=(ContextCoverageDemand("cause", 2.0, True),)
    )
    baseline_problem, baseline = solve(
        compile_request,
        candidates,
        interactions,
    )
    baseline_value = evaluate_context_set(
        baseline_problem,
        baseline.selected_ids,
    ).breakdown.total_set_value
    rng = random.Random(20260814)

    for _ in range(1000):
        shuffled_candidates = list(candidates)
        shuffled_interactions = list(interactions)
        rng.shuffle(shuffled_candidates)
        rng.shuffle(shuffled_interactions)
        problem, result = solve(
            compile_request,
            tuple(shuffled_candidates),
            tuple(shuffled_interactions),
        )
        assert result.selected_ids == baseline.selected_ids
        assert dict(result.phase_by_id) == dict(baseline.phase_by_id)
        assert dict(result.trigger_by_id) == dict(baseline.trigger_by_id)
        assert evaluate_context_set(
            problem,
            result.selected_ids,
        ).breakdown.total_set_value == pytest.approx(baseline_value)


def test_solver_rejects_invalid_problem() -> None:
    with pytest.raises(ContextCompilerValidationError, match="problem"):
        HeuristicContextSolver().solve(object())
    assert ContextSolverMode.HEURISTIC.value == "heuristic"
