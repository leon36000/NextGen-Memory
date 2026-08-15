from __future__ import annotations

import hashlib
import random
from collections import Counter
from uuid import UUID

import pytest

from nextgen_memory.context_compiler import IntegratedContextCompiler
from nextgen_memory.context_compiler_contracts import (
    ContextBudgetError,
    ContextCompilerValidationError,
    ContextCoverageDemand,
    ContextDependencyError,
    ContextInteractionKind,
    ContextPairInteraction,
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

SPACE_ID = UUID("11111111-1111-5111-8111-111111111111")
OTHER_SPACE_ID = UUID("22222222-2222-5222-8222-222222222222")
GROUP_ID = UUID("99999999-9999-5999-8999-999999999999")
SEED = 20_260_814


def memory_id(case_index: int, item_index: int) -> UUID:
    suffix = case_index * 32 + item_index + 1
    return UUID(f"00000000-0000-5000-8000-{suffix:012d}")


def content_hash(case_index: int, item_index: int) -> str:
    return hashlib.sha256(
        f"context-property:{case_index}:{item_index}".encode()
    ).hexdigest()


def build_case(
    rng: random.Random,
    case_index: int,
    *,
    force_exact: bool | None = None,
) -> tuple[
    IntegratedContextCompileRequest,
    tuple[IntegratedContextEvidence, ...],
    tuple[ContextPairInteraction, ...],
]:
    count = rng.randint(1, 12)
    ids = tuple(memory_id(case_index, index) for index in range(count))
    prerequisites: list[tuple[UUID, ...]] = []
    for index in range(count):
        if index == 0 or rng.random() >= 0.28:
            prerequisites.append(())
            continue
        possible = list(range(index))
        rng.shuffle(possible)
        parent_count = 1 if rng.random() < 0.85 else min(2, index)
        prerequisites.append(
            tuple(sorted((ids[parent] for parent in possible[:parent_count]), key=str))
        )

    mandatory_roots = {
        index
        for index in range(count)
        if rng.random() < 0.08
    }
    if case_index % 37 == 0:
        mandatory_roots.add(rng.randrange(count))

    closure_cache: dict[int, set[int]] = {}

    def index_closure(index: int) -> set[int]:
        existing = closure_cache.get(index)
        if existing is not None:
            return set(existing)
        values = {index}
        for prerequisite_id in prerequisites[index]:
            parent_index = ids.index(prerequisite_id)
            values.update(index_closure(parent_index))
        closure_cache[index] = values
        return set(values)

    mandatory_indexes = set()
    for root in mandatory_roots:
        mandatory_indexes.update(index_closure(root))

    demand_keys = tuple(f"need-{value}" for value in range(rng.randint(0, 4)))
    demands = tuple(
        ContextCoverageDemand(
            key,
            weight=round(rng.uniform(0.5, 3.0), 4),
            required=rng.random() < 0.65,
        )
        for key in demand_keys
    )
    if demands and not any(item.required for item in demands):
        first = demands[0]
        demands = (
            ContextCoverageDemand(first.coverage_key, first.weight, True),
            *demands[1:],
        )

    candidates: list[IntegratedContextEvidence] = []
    for index, item_id in enumerate(ids):
        coverage = tuple(
            key for key in demand_keys if rng.random() < 0.28
        )
        candidates.append(
            IntegratedContextEvidence(
                memory_id=item_id,
                space_id=SPACE_ID,
                expert=f"expert-{rng.randrange(4)}",
                subject_key=f"subject-{rng.randrange(5)}",
                source_cluster_key=f"source-{rng.randrange(6)}",
                content=f"property evidence {case_index}:{index}",
                content_hash=content_hash(case_index, index),
                backend_ref=f"property:{case_index}:{index}",
                source_uri=None,
                fidelity=(
                    EvidenceFidelity.EXACT
                    if rng.random() < 0.8
                    else EvidenceFidelity.DERIVED
                ),
                estimated_tokens=rng.randint(6, 28),
                original_rank=index + 1,
                coverage_keys=coverage,
                prerequisite_memory_ids=prerequisites[index],
                mandatory=index in mandatory_roots,
                relevance=round(rng.random(), 6),
                utility=round(rng.uniform(-1.0, 1.0), 6),
                direct_credit=round(rng.uniform(-1.0, 1.0), 6),
                inherited_credit=round(rng.uniform(-1.0, 1.0), 6),
                harm_risk=round(rng.random(), 6),
                authority=(
                    1.0
                    if index in mandatory_indexes
                    else round(rng.uniform(0.55, 1.0), 6)
                ),
                confidence=(
                    1.0
                    if index in mandatory_indexes
                    else round(rng.uniform(0.55, 1.0), 6)
                ),
            )
        )

    interactions: list[ContextPairInteraction] = []
    for left in range(count):
        for right in range(left + 1, count):
            if rng.random() >= 0.08:
                continue
            kind = (
                ContextInteractionKind.SYNERGY
                if rng.random() < 0.5
                else ContextInteractionKind.REDUNDANCY
            )
            magnitude = round(rng.uniform(0.01, 0.55), 6)
            interactions.append(
                ContextPairInteraction(
                    ids[left],
                    ids[right],
                    kind,
                    magnitude
                    if kind is ContextInteractionKind.SYNERGY
                    else -magnitude,
                    standard_error=0.02,
                    trial_count=3,
                    evidence_group_id=GROUP_ID,
                )
            )

    mandatory_tokens = sum(
        candidates[index].estimated_tokens
        for index in mandatory_indexes
    )
    total_tokens = sum(item.estimated_tokens for item in candidates)
    envelope_tokens = 32
    usable_budget = rng.randint(
        max(1, mandatory_tokens),
        max(max(1, mandatory_tokens), total_tokens),
    )
    mandatory_items = len(mandatory_indexes)
    max_items = rng.randint(
        max(1, mandatory_items),
        max(max(1, mandatory_items), count),
    )
    threshold = round(rng.uniform(0.0, 0.72), 6)
    exact_mode = (
        force_exact
        if force_exact is not None
        else case_index % 23 == 0 and count <= 8
    )
    compile_request = IntegratedContextCompileRequest(
        space_id=SPACE_ID,
        token_budget=envelope_tokens + usable_budget,
        envelope_tokens=envelope_tokens,
        max_items=max_items,
        coverage_demands=demands,
        max_items_per_expert=(None if rng.random() < 0.75 else rng.randint(1, 4)),
        minimum_authority=threshold,
        minimum_confidence=threshold,
        exact_candidate_limit=(count if exact_mode else 1),
        local_search_pass_limit=2,
    )
    return compile_request, tuple(candidates), tuple(interactions)


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


def assert_packet_invariants(
    compile_request: IntegratedContextCompileRequest,
    candidates: tuple[IntegratedContextEvidence, ...],
    interactions: tuple[ContextPairInteraction, ...],
) -> None:
    compiler = IntegratedContextCompiler()
    packet = compiler.compile(compile_request, candidates, interactions)
    problem = canonicalize_context_problem(
        compile_request,
        candidates,
        interactions,
    )
    evaluation = evaluate_context_set(problem, packet.selected_memory_ids)
    candidate_by_id = {item.memory_id: item for item in candidates}

    assert packet.total_estimated_tokens <= compile_request.token_budget
    assert len(packet.selected) <= compile_request.max_items
    assert len(packet.selected_memory_ids) == len(set(packet.selected_memory_ids))
    assert set(packet.covered_required_keys) | set(
        packet.uncovered_required_keys
    ) == set(compile_request.required_coverage_keys)
    assert set(packet.covered_required_keys).isdisjoint(
        packet.uncovered_required_keys
    )
    assert packet.objective.total_set_value == pytest.approx(
        evaluation.breakdown.total_set_value,
        abs=1e-10,
    )
    assert packet.objective.direct_credit_value == pytest.approx(
        evaluation.breakdown.direct_credit_value,
        abs=1e-10,
    )
    assert packet.objective.inherited_credit_value == pytest.approx(
        evaluation.breakdown.inherited_credit_value,
        abs=1e-10,
    )
    assert packet.render_json() == packet.render_json()

    selected_set = frozenset(packet.selected_memory_ids)
    assert problem.mandatory_closure.issubset(selected_set)
    for item_id in selected_set:
        assert problem.prerequisite_closure[item_id].issubset(selected_set)
    for selected in packet.selected:
        original = candidate_by_id[selected.evidence.memory_id]
        assert selected.evidence.content == original.content
        assert selected.evidence.content_hash == original.content_hash
    if compile_request.max_items_per_expert is not None:
        counts = Counter(
            problem.candidate_by_id[item_id].expert
            for item_id in selected_set
            if item_id not in problem.mandatory_closure
        )
        assert all(
            value <= compile_request.max_items_per_expert
            for value in counts.values()
        )

    shuffled_candidates = list(candidates)
    shuffled_interactions = list(interactions)
    random.Random(13).shuffle(shuffled_candidates)
    random.Random(17).shuffle(shuffled_interactions)
    permuted = compiler.compile(
        compile_request,
        tuple(shuffled_candidates),
        tuple(shuffled_interactions),
    )
    assert permuted.packet_id == packet.packet_id
    assert permuted.selected_memory_ids == packet.selected_memory_ids
    assert permuted.render_json() == packet.render_json()


def test_compiler_properties_hold_on_5000_generated_instances() -> None:
    rng = random.Random(SEED)

    for case_index in range(5000):
        compile_request, candidates, interactions = build_case(rng, case_index)
        assert_packet_invariants(compile_request, candidates, interactions)


def test_exact_mode_matches_independent_oracle_on_250_generated_cases() -> None:
    rng = random.Random(SEED + 1)
    compared = 0
    case_index = 10_000

    while compared < 250:
        compile_request, candidates, interactions = build_case(
            rng,
            case_index,
            force_exact=True,
        )
        case_index += 1
        if len(candidates) > 8:
            continue
        problem = canonicalize_context_problem(
            compile_request,
            candidates,
            interactions,
        )
        packet = IntegratedContextCompiler().compile(
            compile_request,
            candidates,
            interactions,
        )
        expected = brute_force_best(problem)

        assert packet.solver_mode is ContextSolverMode.EXACT
        assert frozenset(packet.selected_memory_ids) == expected.selected_ids
        assert packet.objective.total_set_value == pytest.approx(
            expected.breakdown.total_set_value,
            abs=1e-10,
        )
        compared += 1


def test_generated_fail_closed_cases_raise_stable_error_classes() -> None:
    base = IntegratedContextEvidence(
        memory_id=memory_id(20_000, 0),
        space_id=SPACE_ID,
        expert="research",
        subject_key="subject",
        source_cluster_key="source",
        content="base",
        content_hash=content_hash(20_000, 0),
        backend_ref="base",
        source_uri=None,
        fidelity=EvidenceFidelity.EXACT,
        estimated_tokens=20,
        original_rank=1,
        mandatory=False,
        authority=1.0,
        confidence=1.0,
    )
    compile_request = IntegratedContextCompileRequest(
        space_id=SPACE_ID,
        token_budget=100,
        envelope_tokens=20,
    )

    with pytest.raises(ContextCompilerValidationError, match="space_id"):
        IntegratedContextCompiler().compile(
            compile_request,
            (
                base,
                IntegratedContextEvidence(
                    **{
                        **{
                            field: getattr(base, field)
                            for field in base.__dataclass_fields__
                        },
                        "memory_id": memory_id(20_000, 1),
                        "space_id": OTHER_SPACE_ID,
                        "content": "other",
                        "content_hash": content_hash(20_000, 1),
                    }
                ),
            ),
        )

    unknown = memory_id(20_000, 9)
    with pytest.raises(ContextDependencyError, match="unknown prerequisite"):
        IntegratedContextCompiler().compile(
            compile_request,
            (
                IntegratedContextEvidence(
                    **{
                        **{
                            field: getattr(base, field)
                            for field in base.__dataclass_fields__
                        },
                        "prerequisite_memory_ids": (unknown,),
                    }
                ),
            ),
        )

    first_id = memory_id(20_001, 0)
    second_id = memory_id(20_001, 1)
    first = IntegratedContextEvidence(
        **{
            **{
                field: getattr(base, field)
                for field in base.__dataclass_fields__
            },
            "memory_id": first_id,
            "content": "first",
            "content_hash": content_hash(20_001, 0),
            "prerequisite_memory_ids": (second_id,),
        }
    )
    second = IntegratedContextEvidence(
        **{
            **{
                field: getattr(base, field)
                for field in base.__dataclass_fields__
            },
            "memory_id": second_id,
            "content": "second",
            "content_hash": content_hash(20_001, 1),
            "prerequisite_memory_ids": (first_id,),
        }
    )
    with pytest.raises(ContextDependencyError, match="cycle"):
        IntegratedContextCompiler().compile(
            compile_request,
            (first, second),
        )

    mandatory = IntegratedContextEvidence(
        **{
            **{
                field: getattr(base, field)
                for field in base.__dataclass_fields__
            },
            "mandatory": True,
            "estimated_tokens": 90,
        }
    )
    with pytest.raises(ContextBudgetError, match="mandatory"):
        IntegratedContextCompiler().compile(
            compile_request,
            (mandatory,),
        )
