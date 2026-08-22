"""Exact dependency-closed context-set optimization."""

from __future__ import annotations

from math import isclose
from uuid import UUID

from .context_compiler_contracts import (
    ContextBudgetError,
    ContextCompilerValidationError,
    ContextDependencyError,
    ContextOptimizationError,
    ContextSelectionPhase,
    ContextSolverMode,
)
from .context_objective import (
    CanonicalContextProblem,
    ContextSelectionSolution,
    ContextSetEvaluation,
    dependency_closure,
    evaluate_context_set,
    is_better_context_set,
)


class ExactContextSolver:
    """Enumerate every reachable feasible dependency-closed evidence set."""

    def solve(
        self,
        problem: CanonicalContextProblem,
    ) -> ContextSelectionSolution:
        """Return the globally best feasible set under the declared objective."""

        if not isinstance(problem, CanonicalContextProblem):
            raise ContextCompilerValidationError(
                "problem must be a CanonicalContextProblem"
            )
        if len(problem.candidates) > problem.request.exact_candidate_limit:
            raise ContextCompilerValidationError(
                "candidate count exceeds exact_candidate_limit"
            )

        try:
            mandatory_evaluation = evaluate_context_set(
                problem,
                problem.mandatory_closure,
            )
        except (ContextCompilerValidationError, ContextDependencyError) as exc:
            raise ContextBudgetError(
                "mandatory evidence closure is infeasible"
            ) from exc

        best = mandatory_evaluation
        optional_ids = tuple(
            memory_id
            for memory_id in problem.candidate_by_id
            if memory_id not in problem.mandatory_closure
        )
        seen_states: set[tuple[int, frozenset[UUID]]] = set()
        tolerance = problem.request.objective_policy.comparison_tolerance

        def visit(index: int, selected_ids: frozenset[UUID]) -> None:
            nonlocal best

            state = (index, selected_ids)
            if state in seen_states:
                return
            seen_states.add(state)

            try:
                evaluation = evaluate_context_set(problem, selected_ids)
            except (ContextCompilerValidationError, ContextDependencyError):
                # Tokens, item count, expert caps, and dependency closure are
                # monotone under additions, so this branch cannot recover.
                return

            if is_better_context_set(evaluation, best, tolerance):
                best = evaluation
            if index >= len(optional_ids):
                return

            memory_id = optional_ids[index]
            visit(index + 1, selected_ids)
            if memory_id not in selected_ids:
                addition = dependency_closure(problem, (memory_id,))
                visit(index + 1, selected_ids | addition)

        visit(0, problem.mandatory_closure)
        self._verify_final(problem, best, tolerance)

        phase_by_id = {
            memory_id: (
                ContextSelectionPhase.MANDATORY
                if memory_id in problem.mandatory_closure
                else ContextSelectionPhase.EXACT
            )
            for memory_id in best.selected_ids
        }
        trigger_by_id = {
            memory_id: memory_id for memory_id in best.selected_ids
        }
        return ContextSelectionSolution(
            selected_ids=best.selected_ids,
            solver_mode=ContextSolverMode.EXACT,
            phase_by_id=phase_by_id,
            trigger_by_id=trigger_by_id,
            optimality_gap=0.0,
        )

    @staticmethod
    def _verify_final(
        problem: CanonicalContextProblem,
        best: ContextSetEvaluation,
        tolerance: float,
    ) -> None:
        recomputed = evaluate_context_set(problem, best.selected_ids)
        if recomputed.selected_ids != best.selected_ids:
            raise ContextOptimizationError(
                "exact solver selected-set recomputation mismatch"
            )
        if not isclose(
            recomputed.covered_required_weight,
            best.covered_required_weight,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ContextOptimizationError(
                "exact solver required-coverage recomputation mismatch"
            )
        if not isclose(
            recomputed.breakdown.total_set_value,
            best.breakdown.total_set_value,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ContextOptimizationError(
                "exact solver objective recomputation mismatch"
            )
