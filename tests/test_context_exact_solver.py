from __future__ import annotations

import hashlib
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
    CanonicalContextProblem,
    ContextSetEvaluation,
    canonicalize_context_problem,
    dependency_closure,
    evaluate_context_set,
    is_better_context_set,
)

solver_module = importlib.import_module("nextgen_memory.context_exact_solver")
ExactContextSolver = solver_module.ExactContextSolver

SPACE_ID = UUID("11111111-1111-5111-8111-111111111111")
GROUP_ID = UUID("99999999-9999-5999-8999-999999999999")


def memory_id(index: int) -> UUID:
    return UUID(f"00000000-0000-5000-8000-{index:012d}")


def evidence(index: int, **overrides: object) -> IntegratedContextEvidence:
    item_id = memory_id(index)
    values: dict[str, object] = {
        "memory_id": item_id,
        "space_id": SPACE_ID,
        "expert": f"expert-{index % 3}",
        "subject_key": f"subject-{index % 4}",
        "source_cluster_key": f"source-{index % 5}",
        "content": f"evidence-{index}",
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
    if "content_hash" not in overrides:
        content = values.get("content")
        normalized_content = (
            content.strip() if isinstance(content, str) else ""
        )
        values["content_hash"] = hashlib.sha256(
            normalized_content.encode("utf-8")
        ).hexdigest()
    return IntegratedContextEvidence(**values)


def request(**overrides: object) -> IntegratedContextCompileRequest:
    values: dict[str, object] = {
        "space_id": SPACE_ID,
        "token_budget": 400,
        "envelope_tokens": 50,
        "max_items": 6,
        "coverage_demands": (),
        "exact_candidate_limit": 18,
    }
    values.update(overrides)
    return IntegratedContextCompileRequest(**values)


def pair(
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


def brute_force_best(problem: CanonicalContextProblem) -> ContextSetEvaluation:
    optional = tuple(
        item_id
        for item_id in problem.candidate_by_id
        if item_id not in problem.mandatory_closure
    )
    best: ContextSetEvaluation | None = None
    for mask in range(1 << len(optional)):
        roots = frozenset(
            optional[index]
            for index in range(len(optional))
            if mask & (1 << index)
        )
        selected = dependency_closure(
            problem,
            problem.mandatory_closure | roots,
        )
        try:
            evaluation = evaluate_context_set(problem, selected)
        except ValueError:
            continue
        if is_better_context_set(
            evaluation,
            best,
            problem.request.objective_policy.comparison_tolerance,
        ):
            best = evaluation
    assert best is not None
    return best


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
    return problem, ExactContextSolver().solve(problem)


def test_empty_optional_pool_returns_mandatory_closure() -> None:
    problem, solution = solve(
        request(),
        (
            evidence(1, mandatory=True),
            evidence(
                2,
                prerequisite_memory_ids=(memory_id(1),),
                mandatory=True,
            ),
        ),
    )

    assert solution.selected_ids == problem.mandatory_closure
    assert solution.solver_mode is ContextSolverMode.EXACT
    assert solution.optimality_gap == 0.0
    assert set(solution.phase_by_id.values()) == {
        ContextSelectionPhase.MANDATORY
    }


def test_required_coverage_beats_higher_optional_value() -> None:
    compile_request = request(
        token_budget=160,
        envelope_tokens=50,
        max_items=1,
        coverage_demands=(ContextCoverageDemand("cause", 3.0, True),),
    )
    problem, solution = solve(
        compile_request,
        (
            evidence(1, relevance=1.0),
            evidence(2, relevance=0.1, coverage_keys=("cause",)),
        ),
    )

    assert solution.selected_ids == frozenset({memory_id(2)})
    assert solution.selected_ids == brute_force_best(problem).selected_ids


def test_exact_solver_selects_positive_joint_synergy_with_negative_singletons() -> None:
    policy = ContextObjectivePolicy(
        new_expert_bonus=0.0,
        new_subject_bonus=0.0,
        new_source_cluster_bonus=0.0,
        pair_interaction_weight=1.0,
        pair_interaction_cap=1.0,
    )
    problem, solution = solve(
        request(objective_policy=policy),
        (
            evidence(1, relevance=0.0, harm_risk=0.08),
            evidence(2, relevance=0.0, harm_risk=0.08),
        ),
        (pair(1, 2, kind=ContextInteractionKind.SYNERGY, value=0.2),),
    )

    assert solution.selected_ids == frozenset({memory_id(1), memory_id(2)})
    assert solution.selected_ids == brute_force_best(problem).selected_ids


def test_redundancy_and_budget_select_only_one_representative() -> None:
    problem, solution = solve(
        request(token_budget=120, envelope_tokens=50, max_items=1),
        (
            evidence(1, relevance=0.8, estimated_tokens=60),
            evidence(2, relevance=0.8, estimated_tokens=60),
        ),
        (
            pair(
                1,
                2,
                kind=ContextInteractionKind.REDUNDANCY,
                value=-0.5,
            ),
        ),
    )

    assert solution.selected_ids == frozenset({memory_id(1)})
    assert solution.selected_ids == brute_force_best(problem).selected_ids


def test_harmful_evidence_is_excluded_and_budget_can_remain_unused() -> None:
    policy = ContextObjectivePolicy(
        new_expert_bonus=0.0,
        new_subject_bonus=0.0,
        new_source_cluster_bonus=0.0,
    )
    problem, solution = solve(
        request(objective_policy=policy),
        (
            evidence(
                1,
                relevance=1.0,
                utility=-1.0,
                direct_credit=-1.0,
                inherited_credit=-1.0,
                harm_risk=1.0,
            ),
            evidence(2, relevance=0.4),
        ),
    )
    evaluation = evaluate_context_set(problem, solution.selected_ids)

    assert solution.selected_ids == frozenset({memory_id(2)})
    assert evaluation.evidence_tokens < problem.request.usable_evidence_tokens


def test_prerequisite_chain_is_selected_atomically() -> None:
    problem, solution = solve(
        request(),
        (
            evidence(1, relevance=0.0),
            evidence(
                2,
                relevance=0.0,
                prerequisite_memory_ids=(memory_id(1),),
            ),
            evidence(
                3,
                relevance=1.0,
                prerequisite_memory_ids=(memory_id(2),),
            ),
        ),
    )

    assert solution.selected_ids == frozenset(
        {memory_id(1), memory_id(2), memory_id(3)}
    )
    assert solution.selected_ids == brute_force_best(problem).selected_ids


def test_optional_expert_cap_is_respected() -> None:
    problem, solution = solve(
        request(max_items_per_expert=1),
        (
            evidence(1, expert="shared", relevance=0.8),
            evidence(2, expert="shared", relevance=0.7),
            evidence(3, expert="other", relevance=0.6),
        ),
    )
    selected_experts = [
        problem.candidate_by_id[item].expert for item in solution.selected_ids
    ]

    assert selected_experts.count("shared") == 1
    assert solution.selected_ids == brute_force_best(problem).selected_ids


def test_tie_breaks_prefer_tokens_then_items_then_uuid() -> None:
    policy = ContextObjectivePolicy(
        new_expert_bonus=0.0,
        new_subject_bonus=0.0,
        new_source_cluster_bonus=0.0,
    )

    token_problem, token_solution = solve(
        request(max_items=1, objective_policy=policy),
        (
            evidence(1, relevance=0.5, estimated_tokens=60),
            evidence(2, relevance=0.5, estimated_tokens=50),
        ),
    )
    assert token_solution.selected_ids == frozenset({memory_id(2)})
    assert token_solution.selected_ids == brute_force_best(token_problem).selected_ids

    item_problem, item_solution = solve(
        request(
            token_budget=100,
            envelope_tokens=50,
            max_items=2,
            objective_policy=policy,
        ),
        (
            evidence(1, relevance=0.5, estimated_tokens=50),
            evidence(2, relevance=0.25, estimated_tokens=25),
            evidence(3, relevance=0.25, estimated_tokens=25),
        ),
    )
    assert item_solution.selected_ids == frozenset({memory_id(1)})
    assert item_solution.selected_ids == brute_force_best(item_problem).selected_ids

    uuid_problem, uuid_solution = solve(
        request(max_items=1, objective_policy=policy),
        (
            evidence(1, relevance=0.5, estimated_tokens=50),
            evidence(2, relevance=0.5, estimated_tokens=50),
        ),
    )
    assert uuid_solution.selected_ids == frozenset({memory_id(1)})
    assert uuid_solution.selected_ids == brute_force_best(uuid_problem).selected_ids


def test_solution_phases_and_input_order_are_deterministic() -> None:
    candidates = (
        evidence(1, mandatory=True, relevance=0.0),
        evidence(2, relevance=0.9),
        evidence(3, relevance=0.8),
    )
    first_problem, first = solve(request(), candidates)
    second_problem, second = solve(request(), tuple(reversed(candidates)))

    assert first.selected_ids == second.selected_ids
    assert first.selected_ids == brute_force_best(first_problem).selected_ids
    assert second.selected_ids == brute_force_best(second_problem).selected_ids
    assert first.phase_by_id[memory_id(1)] is ContextSelectionPhase.MANDATORY
    assert all(
        first.phase_by_id[item] is ContextSelectionPhase.EXACT
        for item in first.selected_ids - {memory_id(1)}
    )
    assert all(first.trigger_by_id[item] == item for item in first.selected_ids)


def test_exact_solver_matches_oracle_on_500_generated_problems() -> None:
    rng = random.Random(20260814)
    solver = ExactContextSolver()

    for case_index in range(500):
        count = rng.randint(2, 7)
        ids = tuple(
            memory_id(case_index * 10 + index + 1)
            for index in range(count)
        )
        generated: list[IntegratedContextEvidence] = []
        for index, item_id in enumerate(ids):
            prerequisites = ()
            if index and rng.random() < 0.25:
                prerequisites = (ids[rng.randrange(index)],)
            content = f"case-{case_index}-item-{index}"
            generated.append(
                IntegratedContextEvidence(
                    memory_id=item_id,
                    space_id=SPACE_ID,
                    expert=f"expert-{rng.randrange(3)}",
                    subject_key=f"subject-{rng.randrange(4)}",
                    source_cluster_key=f"source-{rng.randrange(5)}",
                    content=content,
                    content_hash=hashlib.sha256(
                        content.encode("utf-8")
                    ).hexdigest(),
                    backend_ref=f"case:{case_index}:{index}",
                    source_uri=None,
                    fidelity=EvidenceFidelity.EXACT,
                    estimated_tokens=rng.randint(20, 100),
                    original_rank=index + 1,
                    coverage_keys=("required",) if rng.random() < 0.25 else (),
                    prerequisite_memory_ids=prerequisites,
                    mandatory=False,
                    relevance=rng.random(),
                    utility=rng.uniform(-1.0, 1.0),
                    direct_credit=rng.uniform(-1.0, 1.0),
                    inherited_credit=rng.uniform(-1.0, 1.0),
                    harm_risk=rng.random(),
                    authority=1.0,
                    confidence=1.0,
                )
            )
        generated_interactions: list[ContextPairInteraction] = []
        for left_index in range(count):
            for right_index in range(left_index + 1, count):
                if rng.random() >= 0.12:
                    continue
                kind = (
                    ContextInteractionKind.SYNERGY
                    if rng.random() < 0.5
                    else ContextInteractionKind.REDUNDANCY
                )
                magnitude = rng.uniform(0.0, 0.6)
                generated_interactions.append(
                    ContextPairInteraction(
                        ids[left_index],
                        ids[right_index],
                        kind,
                        magnitude
                        if kind is ContextInteractionKind.SYNERGY
                        else -magnitude,
                        0.01,
                        3,
                        GROUP_ID,
                    )
                )
        compile_request = IntegratedContextCompileRequest(
            space_id=SPACE_ID,
            token_budget=rng.randint(180, 450),
            envelope_tokens=50,
            max_items=rng.randint(2, count),
            coverage_demands=(
                ContextCoverageDemand("required", 2.0, True),
            ),
            exact_candidate_limit=18,
        )
        problem = canonicalize_context_problem(
            compile_request,
            tuple(generated),
            tuple(generated_interactions),
        )

        assert solver.solve(problem).selected_ids == brute_force_best(
            problem
        ).selected_ids


def test_exact_solver_rejects_invalid_problem_and_large_pool() -> None:
    with pytest.raises(ContextCompilerValidationError, match="problem"):
        ExactContextSolver().solve(object())

    problem = canonicalize_context_problem(
        request(exact_candidate_limit=3),
        tuple(evidence(index) for index in range(1, 5)),
        (),
    )
    with pytest.raises(ContextCompilerValidationError, match="exact_candidate_limit"):
        ExactContextSolver().solve(problem)
