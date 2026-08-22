"""Deterministic scalable context selection with bounded local improvement."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .context_compiler_contracts import (
    ContextBudgetError,
    ContextCompilerValidationError,
    ContextDependencyError,
    ContextInteractionKind,
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


@dataclass(frozen=True, slots=True)
class _Addition:
    roots: frozenset[UUID]
    added_ids: frozenset[UUID]


@dataclass(slots=True)
class _HeuristicState:
    roots: frozenset[UUID]
    root_phase: dict[UUID, ContextSelectionPhase]
    evaluation: ContextSetEvaluation


class HeuristicContextSolver:
    """Coverage-first marginal construction plus deterministic local search."""

    def solve(
        self,
        problem: CanonicalContextProblem,
    ) -> ContextSelectionSolution:
        if not isinstance(problem, CanonicalContextProblem):
            raise ContextCompilerValidationError(
                "problem must be a CanonicalContextProblem"
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

        state = _HeuristicState(
            roots=frozenset(),
            root_phase={},
            evaluation=mandatory_evaluation,
        )
        mandatory_state = _copy_state(state)
        state = self._required_coverage_phase(problem, state)
        coverage_state = _copy_state(state)
        state = self._positive_fill_phase(problem, state)
        state = self._local_improvement(problem, state)
        best_single = self._best_single_addition(problem, mandatory_state)

        final_state = mandatory_state
        for candidate_state in (
            coverage_state,
            state,
            best_single,
        ):
            if is_better_context_set(
                candidate_state.evaluation,
                final_state.evaluation,
                problem.request.objective_policy.comparison_tolerance,
            ):
                final_state = candidate_state
        return _build_solution(problem, final_state)

    def _required_coverage_phase(
        self,
        problem: CanonicalContextProblem,
        initial: _HeuristicState,
    ) -> _HeuristicState:
        state = _copy_state(initial)
        tolerance = problem.request.objective_policy.comparison_tolerance
        while state.evaluation.uncovered_required_keys:
            options: list[
                tuple[
                    tuple[float, float, float, int, tuple[str, ...]],
                    _Addition,
                    ContextSetEvaluation,
                ]
            ] = []
            for addition in _candidate_addition_records(
                problem,
                state.evaluation.selected_ids,
            ):
                after = _evaluate_addition(problem, state, addition)
                if after is None:
                    continue
                required_gain = (
                    after.covered_required_weight
                    - state.evaluation.covered_required_weight
                )
                if required_gain <= tolerance:
                    continue
                marginal = (
                    after.breakdown.total_set_value
                    - state.evaluation.breakdown.total_set_value
                )
                added_tokens = (
                    after.evidence_tokens - state.evaluation.evidence_tokens
                )
                key = (
                    required_gain,
                    marginal / added_tokens,
                    marginal,
                    -added_tokens,
                    tuple(sorted(str(item) for item in addition.added_ids)),
                )
                options.append((key, addition, after))
            if not options:
                break
            _, addition, after = max(
                options,
                key=lambda item: (
                    item[0][0],
                    item[0][1],
                    item[0][2],
                    item[0][3],
                    tuple(_invert_string(value) for value in item[0][4]),
                ),
            )
            state = _admit(
                state,
                addition,
                after,
                ContextSelectionPhase.COVERAGE,
            )
        return state

    def _positive_fill_phase(
        self,
        problem: CanonicalContextProblem,
        initial: _HeuristicState,
    ) -> _HeuristicState:
        state = _copy_state(initial)
        tolerance = problem.request.objective_policy.comparison_tolerance
        while True:
            options: list[
                tuple[
                    tuple[float, float, int, tuple[str, ...]],
                    _Addition,
                    ContextSetEvaluation,
                ]
            ] = []
            for addition in _candidate_addition_records(
                problem,
                state.evaluation.selected_ids,
            ):
                after = _evaluate_addition(problem, state, addition)
                if after is None:
                    continue
                marginal = (
                    after.breakdown.total_set_value
                    - state.evaluation.breakdown.total_set_value
                )
                if marginal <= tolerance:
                    continue
                added_tokens = (
                    after.evidence_tokens - state.evaluation.evidence_tokens
                )
                key = (
                    marginal / added_tokens,
                    marginal,
                    -added_tokens,
                    tuple(sorted(str(item) for item in addition.added_ids)),
                )
                options.append((key, addition, after))
            if not options:
                break
            _, addition, after = max(
                options,
                key=lambda item: (
                    item[0][0],
                    item[0][1],
                    item[0][2],
                    tuple(_invert_string(value) for value in item[0][3]),
                ),
            )
            state = _admit(
                state,
                addition,
                after,
                ContextSelectionPhase.GREEDY,
            )
        return state

    def _local_improvement(
        self,
        problem: CanonicalContextProblem,
        initial: _HeuristicState,
    ) -> _HeuristicState:
        state = _copy_state(initial)
        tolerance = problem.request.objective_policy.comparison_tolerance
        for _ in range(problem.request.local_search_pass_limit):
            best = state

            for addition in _candidate_addition_records(
                problem,
                state.evaluation.selected_ids,
            ):
                candidate = _state_with_roots(
                    problem,
                    state.roots | addition.roots,
                    {
                        **state.root_phase,
                        **{
                            root: ContextSelectionPhase.LOCAL_IMPROVEMENT
                            for root in addition.roots
                        },
                    },
                )
                if candidate is not None and is_better_context_set(
                    candidate.evaluation,
                    best.evaluation,
                    tolerance,
                ):
                    best = candidate

            for root in sorted(state.roots, key=str):
                phases = dict(state.root_phase)
                phases.pop(root, None)
                candidate = _state_with_roots(
                    problem,
                    state.roots.difference({root}),
                    phases,
                )
                if candidate is not None and is_better_context_set(
                    candidate.evaluation,
                    best.evaluation,
                    tolerance,
                ):
                    best = candidate

            for removed in sorted(state.roots, key=str):
                remaining_roots = state.roots.difference({removed})
                remaining_selected = _selected_from_roots(
                    problem,
                    remaining_roots,
                )
                for addition in _candidate_addition_records(
                    problem,
                    remaining_selected,
                ):
                    new_roots = remaining_roots | addition.roots
                    if new_roots == state.roots:
                        continue
                    phases = {
                        root: phase
                        for root, phase in state.root_phase.items()
                        if root != removed
                    }
                    phases.update(
                        {
                            root: ContextSelectionPhase.LOCAL_IMPROVEMENT
                            for root in addition.roots
                        }
                    )
                    candidate = _state_with_roots(
                        problem,
                        new_roots,
                        phases,
                    )
                    if candidate is not None and is_better_context_set(
                        candidate.evaluation,
                        best.evaluation,
                        tolerance,
                    ):
                        best = candidate

            if best is state or not is_better_context_set(
                best.evaluation,
                state.evaluation,
                tolerance,
            ):
                break
            state = best
        return state

    @staticmethod
    def _best_single_addition(
        problem: CanonicalContextProblem,
        mandatory: _HeuristicState,
    ) -> _HeuristicState:
        best = mandatory
        tolerance = problem.request.objective_policy.comparison_tolerance
        for addition in _candidate_addition_records(
            problem,
            mandatory.evaluation.selected_ids,
        ):
            candidate = _state_with_roots(
                problem,
                addition.roots,
                {
                    root: ContextSelectionPhase.GREEDY
                    for root in addition.roots
                },
            )
            if candidate is not None and is_better_context_set(
                candidate.evaluation,
                best.evaluation,
                tolerance,
            ):
                best = candidate
        return best


def candidate_additions(
    problem: CanonicalContextProblem,
    selected_ids: frozenset[UUID],
) -> tuple[frozenset[UUID], ...]:
    """Return unique dependency-closed atomic additions for audit and tests."""

    if not isinstance(problem, CanonicalContextProblem):
        raise ContextCompilerValidationError(
            "problem must be a CanonicalContextProblem"
        )
    return tuple(
        record.added_ids
        for record in _candidate_addition_records(problem, selected_ids)
    )


def _candidate_addition_records(
    problem: CanonicalContextProblem,
    selected_ids: frozenset[UUID],
) -> tuple[_Addition, ...]:
    selected = frozenset(selected_ids)
    records: dict[frozenset[UUID], _Addition] = {}

    def register(roots: frozenset[UUID]) -> None:
        closure = dependency_closure(problem, roots)
        added = closure.difference(selected)
        if not added:
            return
        candidate = _Addition(roots=roots, added_ids=added)
        existing = records.get(added)
        if existing is None or _uuid_tuple(roots) < _uuid_tuple(existing.roots):
            records[added] = candidate

    for memory_id in problem.candidate_by_id:
        if memory_id not in selected:
            register(frozenset({memory_id}))
    for pair, interaction in problem.interactions.items():
        if interaction.kind is not ContextInteractionKind.SYNERGY:
            continue
        if interaction.value <= 0 or any(item in selected for item in pair):
            continue
        register(frozenset(pair))
    return tuple(
        records[key]
        for key in sorted(records, key=_uuid_tuple)
    )


def _evaluate_addition(
    problem: CanonicalContextProblem,
    state: _HeuristicState,
    addition: _Addition,
) -> ContextSetEvaluation | None:
    selected = state.evaluation.selected_ids | addition.added_ids
    try:
        return evaluate_context_set(problem, selected)
    except (ContextCompilerValidationError, ContextDependencyError):
        return None


def _admit(
    state: _HeuristicState,
    addition: _Addition,
    evaluation: ContextSetEvaluation,
    phase: ContextSelectionPhase,
) -> _HeuristicState:
    phases = dict(state.root_phase)
    for root in addition.roots:
        phases.setdefault(root, phase)
    return _HeuristicState(
        roots=state.roots | addition.roots,
        root_phase=phases,
        evaluation=evaluation,
    )


def _state_with_roots(
    problem: CanonicalContextProblem,
    roots: frozenset[UUID],
    root_phase: dict[UUID, ContextSelectionPhase],
) -> _HeuristicState | None:
    selected = _selected_from_roots(problem, roots)
    try:
        evaluation = evaluate_context_set(problem, selected)
    except (ContextCompilerValidationError, ContextDependencyError):
        return None
    phases = {
        root: root_phase.get(
            root,
            ContextSelectionPhase.LOCAL_IMPROVEMENT,
        )
        for root in roots
    }
    return _HeuristicState(
        roots=frozenset(roots),
        root_phase=phases,
        evaluation=evaluation,
    )


def _selected_from_roots(
    problem: CanonicalContextProblem,
    roots: frozenset[UUID],
) -> frozenset[UUID]:
    return problem.mandatory_closure | dependency_closure(problem, roots)


def _build_solution(
    problem: CanonicalContextProblem,
    state: _HeuristicState,
) -> ContextSelectionSolution:
    phase_by_id: dict[UUID, ContextSelectionPhase] = {}
    trigger_by_id: dict[UUID, UUID] = {}
    mandatory_roots = tuple(
        item.memory_id
        for item in problem.candidates
        if item.mandatory
    )

    for memory_id in state.evaluation.selected_ids:
        if memory_id in problem.mandatory_closure:
            phase_by_id[memory_id] = ContextSelectionPhase.MANDATORY
            triggers = tuple(
                root
                for root in mandatory_roots
                if root == memory_id
                or memory_id in problem.prerequisite_closure[root]
            )
            trigger_by_id[memory_id] = min(triggers or (memory_id,), key=str)
            continue
        if memory_id in state.roots:
            phase_by_id[memory_id] = state.root_phase[memory_id]
            trigger_by_id[memory_id] = memory_id
            continue
        triggers = tuple(
            root
            for root in state.roots
            if memory_id in problem.prerequisite_closure[root]
        )
        if not triggers:
            raise ContextCompilerValidationError(
                "selected prerequisite has no admitting root"
            )
        trigger = min(
            triggers,
            key=lambda root: (
                _phase_priority(state.root_phase[root]),
                str(root),
            ),
        )
        phase_by_id[memory_id] = state.root_phase[trigger]
        trigger_by_id[memory_id] = trigger

    return ContextSelectionSolution(
        selected_ids=state.evaluation.selected_ids,
        solver_mode=ContextSolverMode.HEURISTIC,
        phase_by_id=phase_by_id,
        trigger_by_id=trigger_by_id,
        optimality_gap=None,
    )


def _copy_state(state: _HeuristicState) -> _HeuristicState:
    return _HeuristicState(
        roots=frozenset(state.roots),
        root_phase=dict(state.root_phase),
        evaluation=state.evaluation,
    )


def _phase_priority(phase: ContextSelectionPhase) -> int:
    return {
        ContextSelectionPhase.COVERAGE: 0,
        ContextSelectionPhase.GREEDY: 1,
        ContextSelectionPhase.LOCAL_IMPROVEMENT: 2,
        ContextSelectionPhase.EXACT: 3,
        ContextSelectionPhase.MANDATORY: -1,
    }[phase]


def _uuid_tuple(values: frozenset[UUID]) -> tuple[str, ...]:
    return tuple(sorted(str(value) for value in values))


def _invert_string(value: str) -> tuple[int, ...]:
    return tuple(-ord(character) for character in value)
