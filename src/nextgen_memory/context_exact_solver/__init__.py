"""Exact dependency-aware context optimization for small canonical pools."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

from ..integrated_context_compiler import (
    CanonicalContextPool,
    ContextBudgetError,
    ContextCompilerValidationError,
    ContextObjectiveBreakdown,
    ContextOptimizationError,
    ContextSelectionPhase,
    ContextSetEvaluator,
    IntegratedContextCompileRequest,
)


@dataclass(frozen=True, slots=True)
class ContextSelectionSolution:
    """One feasible selected set and its exact objective evidence."""

    selected_ids: tuple[UUID, ...]
    objective: ContextObjectiveBreakdown
    phase_by_id: Mapping[UUID, ContextSelectionPhase]
    optimality_gap: float | None

    def __post_init__(self) -> None:
        ordered = tuple(sorted(self.selected_ids, key=str))
        if ordered != self.selected_ids or len(set(ordered)) != len(ordered):
            raise ContextOptimizationError(
                "selected_ids must be unique and canonically ordered"
            )
        if not isinstance(self.objective, ContextObjectiveBreakdown):
            raise ContextOptimizationError(
                "objective must be a ContextObjectiveBreakdown"
            )
        normalized: dict[UUID, ContextSelectionPhase] = {}
        for memory_id, phase in self.phase_by_id.items():
            if memory_id not in ordered:
                raise ContextOptimizationError(
                    "phase_by_id references an unselected memory"
                )
            if not isinstance(phase, ContextSelectionPhase):
                raise ContextOptimizationError(
                    "phase_by_id values must be ContextSelectionPhase"
                )
            normalized[memory_id] = phase
        if set(normalized) != set(ordered):
            raise ContextOptimizationError(
                "phase_by_id must cover every selected memory"
            )
        object.__setattr__(
            self,
            "phase_by_id",
            MappingProxyType(
                {memory_id: normalized[memory_id] for memory_id in ordered}
            ),
        )
        if self.optimality_gap is not None and self.optimality_gap < 0:
            raise ContextOptimizationError(
                "optimality_gap must be non-negative when supplied"
            )


class ExactContextSolver:
    """Enumerate dependency-closed choices with deterministic hard pruning."""

    def solve(
        self,
        pool: CanonicalContextPool,
        request: IntegratedContextCompileRequest,
        evaluator: ContextSetEvaluator,
    ) -> ContextSelectionSolution:
        _validate_solver_inputs(pool, request, evaluator)
        if len(pool.candidates) > request.exact_candidate_limit:
            raise ContextOptimizationError(
                "canonical pool exceeds exact_candidate_limit"
            )

        mandatory = mandatory_context_closure(pool)
        if not is_context_set_feasible(
            pool,
            request,
            mandatory,
            mandatory_closure=mandatory,
        ):
            raise ContextBudgetError(
                "mandatory evidence and prerequisite closure cannot fit"
            )

        optional_ids = tuple(
            memory_id
            for memory_id in pool.evidence_by_id
            if memory_id not in mandatory
        )
        best_ids = mandatory
        best_objective = evaluator.evaluate(best_ids)
        best_key = evaluator.objective_key(best_ids)
        seen: set[tuple[int, frozenset[UUID]]] = set()

        def visit(index: int, selected: frozenset[UUID]) -> None:
            nonlocal best_ids, best_objective, best_key
            state_key = (index, selected)
            if state_key in seen:
                return
            seen.add(state_key)
            if not is_context_set_feasible(
                pool,
                request,
                selected,
                mandatory_closure=mandatory,
            ):
                return
            if index >= len(optional_ids):
                key = evaluator.objective_key(selected)
                if key > best_key:
                    best_ids = selected
                    best_objective = evaluator.evaluate(selected)
                    best_key = key
                return

            memory_id = optional_ids[index]
            visit(index + 1, selected)
            if memory_id in selected:
                return
            added = frozenset(
                {memory_id} | set(pool.prerequisite_closure[memory_id])
            )
            visit(index + 1, selected.union(added))

        visit(0, mandatory)
        ordered = tuple(sorted(best_ids, key=str))
        phases = {
            memory_id: (
                ContextSelectionPhase.MANDATORY
                if memory_id in mandatory
                else ContextSelectionPhase.EXACT
            )
            for memory_id in ordered
        }
        return ContextSelectionSolution(
            selected_ids=ordered,
            objective=best_objective,
            phase_by_id=phases,
            optimality_gap=0.0,
        )


def mandatory_context_closure(
    pool: CanonicalContextPool,
) -> frozenset[UUID]:
    """Return mandatory identities plus their transitive prerequisites."""

    closure = set(pool.mandatory_ids)
    for memory_id in pool.mandatory_ids:
        closure.update(pool.prerequisite_closure[memory_id])
    return frozenset(closure)


def is_context_set_feasible(
    pool: CanonicalContextPool,
    request: IntegratedContextCompileRequest,
    selected_ids: frozenset[UUID],
    *,
    mandatory_closure: frozenset[UUID] | None = None,
) -> bool:
    """Evaluate only hard set constraints, independently of optional value."""

    if not isinstance(selected_ids, frozenset):
        raise ContextCompilerValidationError("selected_ids must be a frozenset")
    if not selected_ids.issubset(pool.evidence_by_id):
        return False
    mandatory = (
        mandatory_context_closure(pool)
        if mandatory_closure is None
        else mandatory_closure
    )
    if not mandatory.issubset(selected_ids):
        return False
    if any(
        not pool.prerequisite_closure[memory_id].issubset(selected_ids)
        for memory_id in selected_ids
    ):
        return False
    selected = tuple(pool.evidence_by_id[memory_id] for memory_id in selected_ids)
    if sum(item.estimated_tokens for item in selected) > request.evidence_token_budget:
        return False
    if len(selected) > request.max_items:
        return False

    optional_counts: dict[str, int] = {}
    for item in selected:
        if item.memory_id in mandatory:
            continue
        optional_counts[item.expert] = optional_counts.get(item.expert, 0) + 1
    return all(
        optional_counts.get(expert, 0) <= cap
        for expert, cap in request.max_items_per_expert.items()
    )


def _validate_solver_inputs(
    pool: CanonicalContextPool,
    request: IntegratedContextCompileRequest,
    evaluator: ContextSetEvaluator,
) -> None:
    if not isinstance(pool, CanonicalContextPool):
        raise ContextCompilerValidationError(
            "pool must be a CanonicalContextPool"
        )
    if not isinstance(request, IntegratedContextCompileRequest):
        raise ContextCompilerValidationError(
            "request must be an IntegratedContextCompileRequest"
        )
    if not isinstance(evaluator, ContextSetEvaluator):
        raise ContextCompilerValidationError(
            "evaluator must be a ContextSetEvaluator"
        )
    if evaluator.pool != pool or evaluator.request != request:
        raise ContextCompilerValidationError(
            "evaluator must reference the supplied pool and request"
        )
