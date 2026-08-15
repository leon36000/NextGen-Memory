"""Independent brute-force oracle for Integrated Context Compiler tests."""

from __future__ import annotations

from itertools import combinations
from math import isfinite
from uuid import UUID

from nextgen_memory.integrated_context_compiler import (
    CanonicalContextPool,
    ContextInteractionKind,
    IntegratedContextCompileRequest,
)


def solve_context_oracle(
    pool: CanonicalContextPool,
    request: IntegratedContextCompileRequest,
) -> tuple[UUID, ...]:
    """Enumerate every feasible subset and recompute the objective independently."""

    ids = tuple(pool.evidence_by_id)
    best_ids: tuple[UUID, ...] | None = None
    best_key: tuple[object, ...] | None = None
    for size in range(len(ids) + 1):
        for selected_tuple in combinations(ids, size):
            selected = frozenset(selected_tuple)
            if not _is_feasible(pool, request, selected):
                continue
            key = _objective_key(pool, request, selected)
            if best_key is None or key > best_key:
                best_key = key
                best_ids = tuple(sorted(selected, key=str))
    if best_ids is None:
        raise AssertionError("oracle found no feasible context set")
    return best_ids


def _is_feasible(
    pool: CanonicalContextPool,
    request: IntegratedContextCompileRequest,
    selected: frozenset[UUID],
) -> bool:
    if not pool.mandatory_ids.issubset(selected):
        return False
    if any(
        not pool.prerequisite_closure[memory_id].issubset(selected)
        for memory_id in selected
    ):
        return False
    evidence = tuple(pool.evidence_by_id[memory_id] for memory_id in selected)
    if sum(item.estimated_tokens for item in evidence) > request.evidence_token_budget:
        return False
    if len(evidence) > request.max_items:
        return False
    optional_counts: dict[str, int] = {}
    for item in evidence:
        if item.mandatory:
            continue
        optional_counts[item.expert] = optional_counts.get(item.expert, 0) + 1
    return all(
        optional_counts.get(expert, 0) <= cap
        for expert, cap in request.max_items_per_expert.items()
    )


def _objective_key(
    pool: CanonicalContextPool,
    request: IntegratedContextCompileRequest,
    selected: frozenset[UUID],
) -> tuple[object, ...]:
    policy = request.objective_policy
    evidence = tuple(pool.evidence_by_id[memory_id] for memory_id in selected)
    covered = {
        key
        for item in evidence
        for key in item.coverage_keys
    }
    required_weight = sum(
        demand.weight
        for demand in request.coverage_demands
        if demand.required and demand.coverage_key in covered
    )
    optional_weight = sum(
        demand.weight
        for demand in request.coverage_demands
        if not demand.required and demand.coverage_key in covered
    )
    relevance = policy.relevance_weight * sum(item.relevance for item in evidence)
    utility = policy.utility_weight * sum(item.utility for item in evidence)
    direct = policy.direct_credit_weight * sum(
        item.direct_credit for item in evidence
    )
    inherited = sum(
        _clamp(
            policy.inherited_credit_weight * item.inherited_credit,
            -policy.inherited_contribution_cap,
            policy.inherited_contribution_cap,
        )
        for item in evidence
    )
    harm = -policy.harm_weight * sum(item.harm_risk for item in evidence)
    diversity = (
        policy.new_expert_bonus * len({item.expert for item in evidence})
        + policy.new_subject_bonus * len({item.subject_key for item in evidence})
        + policy.new_source_cluster_bonus
        * len({item.source_cluster_key for item in evidence})
    )
    pair_value = 0.0
    for pair in pool.interactions:
        if pair.left_memory_id not in selected or pair.right_memory_id not in selected:
            continue
        contribution = policy.pair_interaction_weight * _clamp(
            pair.value,
            -policy.pair_value_cap,
            policy.pair_value_cap,
        )
        if pair.kind is ContextInteractionKind.SYNERGY:
            pair_value += contribution
        else:
            pair_value += contribution
    total = (
        relevance
        + utility
        + direct
        + inherited
        + harm
        + required_weight
        + optional_weight
        + diversity
        + pair_value
    )
    assert isfinite(total)
    tokens = sum(item.estimated_tokens for item in evidence)
    ordered = tuple(sorted(selected, key=str))
    return (
        int(pool.mandatory_ids.issubset(selected)),
        required_weight,
        total,
        -tokens,
        -len(selected),
        tuple(-memory_id.int for memory_id in ordered),
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))
