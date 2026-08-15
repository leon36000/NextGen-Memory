"""Integrated exact/heuristic context compilation façade."""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Sequence
from math import isclose
from uuid import UUID, uuid5

from .context_compiler_contracts import (
    CompiledContextEvidence,
    ContextBudgetError,
    ContextCompilerValidationError,
    ContextCoverageDemand,
    ContextDependencyError,
    ContextInteractionKind,
    ContextObjectiveBreakdown,
    ContextObjectivePolicy,
    ContextOmission,
    ContextOmissionReason,
    ContextOptimizationError,
    ContextPairInteraction,
    ContextSelectionPhase,
    ContextSolverMode,
    EvidenceFidelity,
    IntegratedContextCompileRequest,
    IntegratedContextEvidence,
    IntegratedContextPacket,
    canonical_json,
)
from .context_exact_solver import ExactContextSolver
from .context_heuristic_solver import HeuristicContextSolver
from .context_objective import (
    CanonicalContextProblem,
    ContextSelectionSolution,
    ContextSetEvaluation,
    canonicalize_context_problem,
    dependency_closure,
    evaluate_context_set,
    order_selected_evidence,
)

__all__ = [
    "CompiledContextEvidence",
    "ContextBudgetError",
    "ContextCompilerValidationError",
    "ContextCoverageDemand",
    "ContextDependencyError",
    "ContextInteractionKind",
    "ContextObjectiveBreakdown",
    "ContextObjectivePolicy",
    "ContextOmission",
    "ContextOmissionReason",
    "ContextOptimizationError",
    "ContextPairInteraction",
    "ContextSelectionPhase",
    "ContextSolverMode",
    "EvidenceFidelity",
    "IntegratedContextCompileRequest",
    "IntegratedContextCompiler",
    "IntegratedContextEvidence",
    "IntegratedContextPacket",
]


class IntegratedContextCompiler:
    """Compile canonical evidence into a deterministic whole-item packet."""

    def compile(
        self,
        request: IntegratedContextCompileRequest,
        candidates: Sequence[IntegratedContextEvidence],
        interactions: Sequence[ContextPairInteraction] = (),
    ) -> IntegratedContextPacket:
        """Canonicalize, optimize, order, audit, and render one context set."""

        problem = canonicalize_context_problem(
            request,
            candidates,
            interactions,
        )
        solver = (
            ExactContextSolver()
            if len(problem.candidates) <= request.exact_candidate_limit
            else HeuristicContextSolver()
        )
        solution = solver.solve(problem)
        final_evaluation = evaluate_context_set(
            problem,
            solution.selected_ids,
        )
        ordered_ids = order_selected_evidence(
            problem,
            solution.selected_ids,
        )
        selected = _build_selected_audit(
            problem,
            solution,
            ordered_ids,
        )
        omissions = _build_omissions(
            problem,
            solution,
            final_evaluation,
        )
        dependency_map = {
            memory_id: tuple(
                sorted(
                    problem.prerequisite_closure[memory_id],
                    key=str,
                )
            )
            for memory_id in ordered_ids
        }
        packet_id = _packet_id(
            problem,
            solution,
            selected,
            omissions,
            final_evaluation,
            dependency_map,
        )
        packet = IntegratedContextPacket(
            packet_id=packet_id,
            space_id=request.space_id,
            policy_version=request.objective_policy.policy_version,
            solver_mode=solution.solver_mode,
            optimality_gap=solution.optimality_gap,
            token_budget=request.token_budget,
            envelope_tokens=request.envelope_tokens,
            selected=selected,
            omissions=omissions,
            required_coverage_keys=request.required_coverage_keys,
            covered_required_keys=final_evaluation.covered_required_keys,
            uncovered_required_keys=(
                final_evaluation.uncovered_required_keys
            ),
            covered_optional_keys=final_evaluation.covered_optional_keys,
            dependency_closure=dependency_map,
            objective=final_evaluation.breakdown,
        )
        _verify_packet(
            problem,
            solution,
            final_evaluation,
            packet,
        )
        return packet


def _build_selected_audit(
    problem: CanonicalContextProblem,
    solution: ContextSelectionSolution,
    ordered_ids: tuple[UUID, ...],
) -> tuple[CompiledContextEvidence, ...]:
    selected_set = frozenset(solution.selected_ids)
    policy = problem.request.objective_policy
    prefix: frozenset[UUID] = frozenset()
    before = evaluate_context_set(
        problem,
        prefix,
        require_feasible=False,
    )
    selected: list[CompiledContextEvidence] = []

    for position, memory_id in enumerate(ordered_ids, start=1):
        item = problem.candidate_by_id[memory_id]
        after_ids = prefix | {memory_id}
        after = evaluate_context_set(
            problem,
            after_ids,
            require_feasible=False,
        )
        before_coverage = set(before.covered_required_keys) | set(
            before.covered_optional_keys
        )
        after_coverage = set(after.covered_required_keys) | set(
            after.covered_optional_keys
        )
        trigger = _audit_trigger(
            problem,
            solution,
            memory_id,
            selected_set,
        )
        phase = solution.phase_by_id.get(
            trigger,
            solution.phase_by_id[memory_id],
        )
        inherited = _clamp(
            policy.inherited_credit_weight * item.inherited_credit,
            -policy.inherited_contribution_cap,
            policy.inherited_contribution_cap,
        )
        selected.append(
            CompiledContextEvidence(
                evidence=item,
                final_position=position,
                phase=phase,
                trigger_memory_id=trigger,
                prerequisite_memory_ids=tuple(
                    sorted(
                        problem.prerequisite_closure[memory_id],
                        key=str,
                    )
                ),
                newly_covered_keys=tuple(
                    sorted(after_coverage.difference(before_coverage))
                ),
                marginal_set_value=(
                    after.breakdown.total_set_value
                    - before.breakdown.total_set_value
                ),
                marginal_tokens=item.estimated_tokens,
                direct_credit_contribution=(
                    policy.direct_credit_weight * item.direct_credit
                ),
                inherited_credit_contribution=inherited,
            )
        )
        prefix = after_ids
        before = after
    return tuple(selected)


def _audit_trigger(
    problem: CanonicalContextProblem,
    solution: ContextSelectionSolution,
    memory_id: UUID,
    selected_ids: frozenset[UUID],
) -> UUID:
    configured = solution.trigger_by_id[memory_id]
    if configured != memory_id:
        return configured

    dependents = {
        candidate_id
        for candidate_id in selected_ids
        if candidate_id != memory_id
        and memory_id in problem.prerequisite_closure[candidate_id]
    }
    if not dependents:
        return memory_id

    terminal_dependents = tuple(
        candidate_id
        for candidate_id in dependents
        if not any(
            candidate_id in problem.prerequisite_closure[other]
            for other in dependents
            if other != candidate_id
        )
    )
    return min(terminal_dependents or tuple(dependents), key=str)


def _build_omissions(
    problem: CanonicalContextProblem,
    solution: ContextSelectionSolution,
    final_evaluation: ContextSetEvaluation,
) -> tuple[ContextOmission, ...]:
    omissions = list(problem.initial_omissions)
    selected = solution.selected_ids
    tolerance = problem.request.objective_policy.comparison_tolerance

    for memory_id in sorted(
        set(problem.candidate_by_id).difference(selected),
        key=str,
    ):
        addition = dependency_closure(problem, (memory_id,)).difference(
            selected
        )
        candidate_ids = selected | addition
        hard_reason = _hard_omission_reason(
            problem,
            candidate_ids,
        )
        if hard_reason is not None:
            omissions.append(
                ContextOmission(
                    memory_id,
                    hard_reason,
                    "candidate closure violates a hard compile constraint",
                )
            )
            continue

        candidate_evaluation = evaluate_context_set(
            problem,
            candidate_ids,
        )
        marginal = (
            candidate_evaluation.breakdown.total_set_value
            - final_evaluation.breakdown.total_set_value
        )
        if marginal <= tolerance:
            reason = (
                ContextOmissionReason.REDUNDANCY_DOMINATED
                if _has_selected_redundancy(
                    problem,
                    addition,
                    selected,
                )
                else ContextOmissionReason.NON_POSITIVE_MARGINAL_VALUE
            )
            omissions.append(
                ContextOmission(
                    memory_id,
                    reason,
                    "adding the candidate closure does not improve set value",
                )
            )
            continue

        newly_required = (
            candidate_evaluation.covered_required_weight
            - final_evaluation.covered_required_weight
        )
        if newly_required <= tolerance and _covers_selected_required_demand(
            problem,
            memory_id,
            final_evaluation,
        ):
            reason = ContextOmissionReason.REQUIRED_COVERAGE_DOMINATED
        elif solution.solver_mode is ContextSolverMode.EXACT:
            reason = ContextOmissionReason.NOT_SELECTED_BY_EXACT_SOLVER
        else:
            reason = ContextOmissionReason.NOT_SELECTED_BY_HEURISTIC
        omissions.append(
            ContextOmission(
                memory_id,
                reason,
                "candidate was feasible but not present in the optimized packet",
            )
        )

    return tuple(
        sorted(
            omissions,
            key=lambda item: (
                str(item.memory_id),
                item.reason.value,
                item.detail,
            ),
        )
    )


def _hard_omission_reason(
    problem: CanonicalContextProblem,
    candidate_ids: frozenset[UUID],
) -> ContextOmissionReason | None:
    request = problem.request
    items = tuple(
        problem.candidate_by_id[memory_id]
        for memory_id in candidate_ids
    )
    cap = request.max_items_per_expert
    if cap is not None:
        counts = Counter(
            item.expert
            for item in items
            if item.memory_id not in problem.mandatory_closure
        )
        if any(count > cap for count in counts.values()):
            return ContextOmissionReason.EXPERT_CAP
    if sum(item.estimated_tokens for item in items) > request.usable_evidence_tokens:
        return ContextOmissionReason.TOKEN_BUDGET
    if len(items) > request.max_items:
        return ContextOmissionReason.ITEM_LIMIT
    return None


def _has_selected_redundancy(
    problem: CanonicalContextProblem,
    addition: frozenset[UUID],
    selected: frozenset[UUID],
) -> bool:
    for pair, interaction in problem.interactions.items():
        if interaction.kind is not ContextInteractionKind.REDUNDANCY:
            continue
        left, right = pair
        if (
            (left in addition and right in selected)
            or (right in addition and left in selected)
        ) and interaction.value < 0:
            return True
    return False


def _covers_selected_required_demand(
    problem: CanonicalContextProblem,
    memory_id: UUID,
    final_evaluation: ContextSetEvaluation,
) -> bool:
    required = set(problem.request.required_coverage_keys)
    candidate_required = required.intersection(
        problem.candidate_by_id[memory_id].coverage_keys
    )
    return bool(candidate_required) and candidate_required.issubset(
        final_evaluation.covered_required_keys
    )


def _packet_id(
    problem: CanonicalContextProblem,
    solution: ContextSelectionSolution,
    selected: tuple[CompiledContextEvidence, ...],
    omissions: tuple[ContextOmission, ...],
    final_evaluation: ContextSetEvaluation,
    dependency_map: dict[UUID, tuple[UUID, ...]],
) -> UUID:
    request = problem.request
    policy = request.objective_policy
    identity_payload = {
        "schema": "nextgen-memory-context-integrated-v0-identity",
        "space_id": str(request.space_id),
        "request": {
            "token_budget": request.token_budget,
            "envelope_tokens": request.envelope_tokens,
            "max_items": request.max_items,
            "max_items_per_expert": request.max_items_per_expert,
            "minimum_authority": request.minimum_authority,
            "minimum_confidence": request.minimum_confidence,
            "exact_candidate_limit": request.exact_candidate_limit,
            "local_search_pass_limit": request.local_search_pass_limit,
            "coverage_demands": [
                {
                    "coverage_key": item.coverage_key,
                    "weight": item.weight,
                    "required": item.required,
                }
                for item in request.coverage_demands
            ],
            "objective_policy": {
                name: getattr(policy, name)
                for name in policy.__dataclass_fields__
            },
        },
        "solver_mode": solution.solver_mode.value,
        "optimality_gap": solution.optimality_gap,
        "selected": [
            {
                "memory_id": str(item.evidence.memory_id),
                "content_hash": item.evidence.content_hash,
                "final_position": item.final_position,
                "phase": item.phase.value,
                "trigger_memory_id": str(item.trigger_memory_id),
                "prerequisites": [
                    str(value) for value in item.prerequisite_memory_ids
                ],
                "newly_covered_keys": list(item.newly_covered_keys),
                "marginal_set_value": item.marginal_set_value,
                "marginal_tokens": item.marginal_tokens,
                "direct_credit_contribution": (
                    item.direct_credit_contribution
                ),
                "inherited_credit_contribution": (
                    item.inherited_credit_contribution
                ),
            }
            for item in selected
        ],
        "omissions": [
            {
                "memory_id": str(item.memory_id),
                "reason": item.reason.value,
                "detail": item.detail,
            }
            for item in omissions
        ],
        "coverage": {
            "covered_required": list(
                final_evaluation.covered_required_keys
            ),
            "uncovered_required": list(
                final_evaluation.uncovered_required_keys
            ),
            "covered_optional": list(
                final_evaluation.covered_optional_keys
            ),
        },
        "dependency_closure": {
            str(memory_id): [str(value) for value in prerequisites]
            for memory_id, prerequisites in dependency_map.items()
        },
        "objective": final_evaluation.breakdown.to_dict(),
    }
    digest = hashlib.sha256(
        canonical_json(identity_payload).encode()
    ).hexdigest()
    return uuid5(
        request.space_id,
        f"integrated-context-v0:{digest}",
    )


def _verify_packet(
    problem: CanonicalContextProblem,
    solution: ContextSelectionSolution,
    final_evaluation: ContextSetEvaluation,
    packet: IntegratedContextPacket,
) -> None:
    tolerance = problem.request.objective_policy.comparison_tolerance
    if frozenset(packet.selected_memory_ids) != solution.selected_ids:
        raise ContextOptimizationError(
            "packet selected IDs differ from solver output"
        )
    recomputed = evaluate_context_set(problem, packet.selected_memory_ids)
    if not isclose(
        recomputed.breakdown.total_set_value,
        final_evaluation.breakdown.total_set_value,
        rel_tol=0.0,
        abs_tol=tolerance,
    ):
        raise ContextOptimizationError(
            "packet objective recomputation mismatch"
        )
    marginal_total = sum(
        item.marginal_set_value for item in packet.selected
    )
    if not isclose(
        marginal_total,
        final_evaluation.breakdown.total_set_value,
        rel_tol=0.0,
        abs_tol=max(tolerance, 1e-12),
    ):
        raise ContextOptimizationError(
            "packet marginal values do not telescope to the final objective"
        )
    placed: set[UUID] = set()
    for item in packet.selected:
        if not set(item.prerequisite_memory_ids).issubset(placed):
            raise ContextOptimizationError(
                "packet evidence order violates prerequisite closure"
            )
        placed.add(item.evidence.memory_id)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
