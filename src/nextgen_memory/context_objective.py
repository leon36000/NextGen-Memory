"""Canonicalization, feasibility, objective, and ordering for context sets."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from math import isclose
from types import MappingProxyType
from uuid import UUID

from .context_compiler_contracts import (
    ContextCompilerValidationError,
    ContextDependencyError,
    ContextInteractionKind,
    ContextObjectiveBreakdown,
    ContextOmission,
    ContextOmissionReason,
    ContextPairInteraction,
    ContextSelectionPhase,
    ContextSolverMode,
    IntegratedContextCompileRequest,
    IntegratedContextEvidence,
)


@dataclass(frozen=True, slots=True)
class CanonicalContextProblem:
    """A deterministic, thresholded, dependency-safe compiler problem."""

    request: IntegratedContextCompileRequest
    candidates: tuple[IntegratedContextEvidence, ...]
    candidate_by_id: Mapping[UUID, IntegratedContextEvidence]
    interactions: Mapping[tuple[UUID, UUID], ContextPairInteraction]
    prerequisite_closure: Mapping[UUID, frozenset[UUID]]
    mandatory_closure: frozenset[UUID]
    initial_omissions: tuple[ContextOmission, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.request, IntegratedContextCompileRequest):
            raise ContextCompilerValidationError(
                "request must be an IntegratedContextCompileRequest"
            )
        candidates = tuple(self.candidates)
        if any(
            not isinstance(item, IntegratedContextEvidence)
            for item in candidates
        ):
            raise ContextCompilerValidationError(
                "candidates must contain IntegratedContextEvidence instances"
            )
        ordered = tuple(sorted(candidates, key=lambda item: str(item.memory_id)))
        if candidates != ordered:
            raise ContextCompilerValidationError(
                "canonical candidates must be sorted by memory_id"
            )
        if len({item.memory_id for item in candidates}) != len(candidates):
            raise ContextCompilerValidationError(
                "canonical candidates must have unique memory IDs"
            )
        expected_ids = {item.memory_id for item in candidates}
        if set(self.candidate_by_id) != expected_ids:
            raise ContextCompilerValidationError(
                "candidate_by_id must cover canonical candidates exactly"
            )
        if set(self.prerequisite_closure) != expected_ids:
            raise ContextCompilerValidationError(
                "prerequisite_closure must cover canonical candidates exactly"
            )
        if not self.mandatory_closure.issubset(expected_ids):
            raise ContextCompilerValidationError(
                "mandatory_closure must contain canonical candidate IDs"
            )
        object.__setattr__(self, "candidates", candidates)
        object.__setattr__(
            self,
            "candidate_by_id",
            MappingProxyType(
                {
                    memory_id: self.candidate_by_id[memory_id]
                    for memory_id in sorted(self.candidate_by_id, key=str)
                }
            ),
        )
        object.__setattr__(
            self,
            "interactions",
            MappingProxyType(
                {
                    pair: self.interactions[pair]
                    for pair in sorted(
                        self.interactions,
                        key=lambda value: tuple(map(str, value)),
                    )
                }
            ),
        )
        object.__setattr__(
            self,
            "prerequisite_closure",
            MappingProxyType(
                {
                    memory_id: frozenset(
                        self.prerequisite_closure[memory_id]
                    )
                    for memory_id in sorted(
                        self.prerequisite_closure,
                        key=str,
                    )
                }
            ),
        )
        object.__setattr__(
            self,
            "initial_omissions",
            tuple(self.initial_omissions),
        )


@dataclass(frozen=True, slots=True)
class ContextSetEvaluation:
    """Exact recomputation of feasibility and set-level utility."""

    selected_ids: frozenset[UUID]
    covered_required_weight: float
    total_required_weight: float
    covered_required_keys: tuple[str, ...]
    uncovered_required_keys: tuple[str, ...]
    covered_optional_keys: tuple[str, ...]
    evidence_tokens: int
    item_count: int
    breakdown: ContextObjectiveBreakdown

    @property
    def selected_uuid_tuple(self) -> tuple[str, ...]:
        return tuple(sorted(str(memory_id) for memory_id in self.selected_ids))


@dataclass(frozen=True, slots=True)
class ContextSelectionSolution:
    """Solver-selected IDs and deterministic admission provenance."""

    selected_ids: frozenset[UUID]
    solver_mode: ContextSolverMode
    phase_by_id: Mapping[UUID, ContextSelectionPhase]
    trigger_by_id: Mapping[UUID, UUID]
    optimality_gap: float | None

    def __post_init__(self) -> None:
        selected_ids = frozenset(self.selected_ids)
        if any(not isinstance(memory_id, UUID) for memory_id in selected_ids):
            raise ContextCompilerValidationError(
                "selected_ids must contain UUID values"
            )
        if not isinstance(self.solver_mode, ContextSolverMode):
            raise ContextCompilerValidationError(
                "solver_mode must be a ContextSolverMode"
            )
        if set(self.phase_by_id) != set(selected_ids):
            raise ContextCompilerValidationError(
                "phase_by_id must cover selected_ids exactly"
            )
        if set(self.trigger_by_id) != set(selected_ids):
            raise ContextCompilerValidationError(
                "trigger_by_id must cover selected_ids exactly"
            )
        for memory_id, phase in self.phase_by_id.items():
            if not isinstance(memory_id, UUID) or not isinstance(
                phase,
                ContextSelectionPhase,
            ):
                raise ContextCompilerValidationError(
                    "phase_by_id contains invalid values"
                )
        for memory_id, trigger in self.trigger_by_id.items():
            if not isinstance(memory_id, UUID) or not isinstance(trigger, UUID):
                raise ContextCompilerValidationError(
                    "trigger_by_id contains invalid values"
                )
        if self.solver_mode is ContextSolverMode.EXACT:
            if self.optimality_gap != 0.0:
                raise ContextCompilerValidationError(
                    "exact solution optimality_gap must be zero"
                )
        elif self.optimality_gap is not None:
            raise ContextCompilerValidationError(
                "heuristic solution optimality_gap must be None"
            )
        object.__setattr__(self, "selected_ids", selected_ids)
        object.__setattr__(
            self,
            "phase_by_id",
            MappingProxyType(
                {
                    memory_id: self.phase_by_id[memory_id]
                    for memory_id in sorted(self.phase_by_id, key=str)
                }
            ),
        )
        object.__setattr__(
            self,
            "trigger_by_id",
            MappingProxyType(
                {
                    memory_id: self.trigger_by_id[memory_id]
                    for memory_id in sorted(self.trigger_by_id, key=str)
                }
            ),
        )


def canonicalize_context_problem(
    request: IntegratedContextCompileRequest,
    candidates: Sequence[IntegratedContextEvidence],
    interactions: Sequence[ContextPairInteraction],
) -> CanonicalContextProblem:
    """Validate and canonicalize candidates before any optimization."""

    if not isinstance(request, IntegratedContextCompileRequest):
        raise ContextCompilerValidationError(
            "request must be an IntegratedContextCompileRequest"
        )
    raw_candidates = tuple(candidates)
    if any(
        not isinstance(item, IntegratedContextEvidence)
        for item in raw_candidates
    ):
        raise ContextCompilerValidationError(
            "candidates must contain IntegratedContextEvidence instances"
        )
    if any(item.space_id != request.space_id for item in raw_candidates):
        raise ContextCompilerValidationError(
            "candidate space_id must match request space_id"
        )

    omissions: list[ContextOmission] = []
    representatives = _deduplicate_memory_ids(raw_candidates, omissions)
    original_ids = frozenset(representatives)
    full_closure = _build_prerequisite_closure(representatives)
    mandatory_ids = frozenset(
        memory_id
        for memory_id, item in representatives.items()
        if item.mandatory
    )
    mandatory_closure = _close_ids(full_closure, mandatory_ids)

    for memory_id in mandatory_closure:
        item = representatives[memory_id]
        if item.authority < request.minimum_authority:
            raise ContextCompilerValidationError(
                "mandatory evidence or prerequisite is below authority threshold"
            )
        if item.confidence < request.minimum_confidence:
            raise ContextCompilerValidationError(
                "mandatory evidence or prerequisite is below confidence threshold"
            )

    removed: set[UUID] = set()
    for memory_id, item in representatives.items():
        if memory_id in mandatory_closure:
            continue
        if item.authority < request.minimum_authority:
            removed.add(memory_id)
            omissions.append(
                ContextOmission(
                    memory_id,
                    ContextOmissionReason.BELOW_AUTHORITY,
                    "candidate authority is below the compile threshold",
                )
            )
        elif item.confidence < request.minimum_confidence:
            removed.add(memory_id)
            omissions.append(
                ContextOmission(
                    memory_id,
                    ContextOmissionReason.BELOW_CONFIDENCE,
                    "candidate confidence is below the compile threshold",
                )
            )

    changed = True
    while changed:
        changed = False
        for memory_id in sorted(representatives, key=str):
            if memory_id in removed or memory_id in mandatory_closure:
                continue
            unavailable = full_closure[memory_id].intersection(removed)
            if unavailable:
                removed.add(memory_id)
                omissions.append(
                    ContextOmission(
                        memory_id,
                        ContextOmissionReason.DEPENDENCY_UNAVAILABLE,
                        "a prerequisite was removed during admission",
                    )
                )
                changed = True

    surviving = {
        memory_id: item
        for memory_id, item in representatives.items()
        if memory_id not in removed
    }
    anchor_ids = mandatory_closure | frozenset(
        prerequisite
        for memory_id in surviving
        for prerequisite in full_closure[memory_id]
    )
    surviving = _deduplicate_content(
        request,
        surviving,
        full_closure,
        anchor_ids,
        omissions,
    )

    # Anchor preservation guarantees surviving dependencies remain available.
    closure = {
        memory_id: frozenset(
            prerequisite
            for prerequisite in full_closure[memory_id]
            if prerequisite in surviving
        )
        for memory_id in surviving
    }
    for memory_id, item in surviving.items():
        missing = set(item.prerequisite_memory_ids).difference(surviving)
        if missing:
            if memory_id in mandatory_closure:
                raise ContextDependencyError(
                    "mandatory evidence has a missing prerequisite"
                )
            raise ContextDependencyError(
                "canonical candidate has a missing prerequisite"
            )

    active_interactions = _canonicalize_interactions(
        interactions,
        original_ids,
        frozenset(surviving),
    )
    canonical_candidates = tuple(
        surviving[memory_id]
        for memory_id in sorted(surviving, key=str)
    )
    canonical_mandatory = mandatory_closure.intersection(surviving)
    sorted_omissions = tuple(
        sorted(
            omissions,
            key=lambda item: (
                str(item.memory_id),
                item.reason.value,
                item.detail,
            ),
        )
    )
    return CanonicalContextProblem(
        request=request,
        candidates=canonical_candidates,
        candidate_by_id=surviving,
        interactions=active_interactions,
        prerequisite_closure=closure,
        mandatory_closure=frozenset(canonical_mandatory),
        initial_omissions=sorted_omissions,
    )


def dependency_closure(
    problem: CanonicalContextProblem,
    memory_ids: Collection[UUID],
) -> frozenset[UUID]:
    """Return selected roots plus every transitive prerequisite."""

    roots = frozenset(memory_ids)
    unknown = roots.difference(problem.candidate_by_id)
    if unknown:
        raise ContextCompilerValidationError(
            "dependency closure contains an unknown candidate"
        )
    return _close_ids(problem.prerequisite_closure, roots)


def evaluate_context_set(
    problem: CanonicalContextProblem,
    selected_ids: Collection[UUID],
    *,
    require_feasible: bool = True,
) -> ContextSetEvaluation:
    """Recompute hard feasibility and every objective component."""

    selected = frozenset(selected_ids)
    unknown = selected.difference(problem.candidate_by_id)
    if unknown:
        raise ContextCompilerValidationError(
            "selected set contains an unknown candidate"
        )
    if require_feasible:
        if not problem.mandatory_closure.issubset(selected):
            raise ContextDependencyError(
                "selected set omits mandatory evidence or prerequisite"
            )
        for memory_id in selected:
            if not problem.prerequisite_closure[memory_id].issubset(selected):
                raise ContextDependencyError(
                    "selected set omits a prerequisite"
                )

    items = tuple(
        problem.candidate_by_id[memory_id]
        for memory_id in sorted(selected, key=str)
    )
    evidence_tokens = sum(item.estimated_tokens for item in items)
    if require_feasible:
        if evidence_tokens > problem.request.usable_evidence_tokens:
            raise ContextCompilerValidationError(
                "selected set exceeds the evidence token budget"
            )
        if len(items) > problem.request.max_items:
            raise ContextCompilerValidationError(
                "selected set exceeds the item limit"
            )
        cap = problem.request.max_items_per_expert
        if cap is not None:
            counts = Counter(
                item.expert
                for item in items
                if item.memory_id not in problem.mandatory_closure
            )
            if any(count > cap for count in counts.values()):
                raise ContextCompilerValidationError(
                    "selected set exceeds the optional expert cap"
                )

    policy = problem.request.objective_policy
    relevance_value = sum(policy.relevance_weight * item.relevance for item in items)
    utility_value = sum(policy.utility_weight * item.utility for item in items)
    direct_credit_value = sum(
        policy.direct_credit_weight * item.direct_credit for item in items
    )
    inherited_credit_value = sum(
        _clamp(
            policy.inherited_credit_weight * item.inherited_credit,
            -policy.inherited_contribution_cap,
            policy.inherited_contribution_cap,
        )
        for item in items
    )
    harm_penalty = -sum(policy.harm_weight * item.harm_risk for item in items)

    covered_keys = frozenset(
        key for item in items for key in item.coverage_keys
    )
    required_demands = tuple(
        demand
        for demand in problem.request.coverage_demands
        if demand.required
    )
    optional_demands = tuple(
        demand
        for demand in problem.request.coverage_demands
        if not demand.required
    )
    covered_required_keys = tuple(
        demand.coverage_key
        for demand in required_demands
        if demand.coverage_key in covered_keys
    )
    uncovered_required_keys = tuple(
        demand.coverage_key
        for demand in required_demands
        if demand.coverage_key not in covered_keys
    )
    covered_optional_keys = tuple(
        demand.coverage_key
        for demand in optional_demands
        if demand.coverage_key in covered_keys
    )
    required_coverage_value = sum(
        demand.weight
        for demand in required_demands
        if demand.coverage_key in covered_keys
    )
    optional_coverage_value = sum(
        demand.weight
        for demand in optional_demands
        if demand.coverage_key in covered_keys
    )
    total_required_weight = sum(demand.weight for demand in required_demands)

    expert_diversity_bonus = policy.new_expert_bonus * len(
        {item.expert for item in items}
    )
    subject_diversity_bonus = policy.new_subject_bonus * len(
        {item.subject_key for item in items}
    )
    source_diversity_bonus = policy.new_source_cluster_bonus * len(
        {item.source_cluster_key for item in items}
    )

    synergy_bonus = 0.0
    redundancy_penalty = 0.0
    for (left, right), pair in problem.interactions.items():
        if left not in selected or right not in selected:
            continue
        bounded = _clamp(
            pair.value,
            -policy.pair_interaction_cap,
            policy.pair_interaction_cap,
        )
        contribution = policy.pair_interaction_weight * bounded
        if pair.kind is ContextInteractionKind.SYNERGY:
            synergy_bonus += contribution
        else:
            redundancy_penalty += contribution

    components = (
        relevance_value,
        utility_value,
        direct_credit_value,
        inherited_credit_value,
        harm_penalty,
        required_coverage_value,
        optional_coverage_value,
        expert_diversity_bonus,
        subject_diversity_bonus,
        source_diversity_bonus,
        synergy_bonus,
        redundancy_penalty,
    )
    total_set_value = sum(components)
    value_per_token = total_set_value / evidence_tokens if evidence_tokens else 0.0
    breakdown = ContextObjectiveBreakdown(
        relevance_value=relevance_value,
        utility_value=utility_value,
        direct_credit_value=direct_credit_value,
        inherited_credit_value=inherited_credit_value,
        harm_penalty=harm_penalty,
        required_coverage_value=required_coverage_value,
        optional_coverage_value=optional_coverage_value,
        expert_diversity_bonus=expert_diversity_bonus,
        subject_diversity_bonus=subject_diversity_bonus,
        source_diversity_bonus=source_diversity_bonus,
        synergy_bonus=synergy_bonus,
        redundancy_penalty=redundancy_penalty,
        total_set_value=total_set_value,
        evidence_tokens=evidence_tokens,
        value_per_token=value_per_token,
    )
    return ContextSetEvaluation(
        selected_ids=selected,
        covered_required_weight=required_coverage_value,
        total_required_weight=total_required_weight,
        covered_required_keys=covered_required_keys,
        uncovered_required_keys=uncovered_required_keys,
        covered_optional_keys=covered_optional_keys,
        evidence_tokens=evidence_tokens,
        item_count=len(items),
        breakdown=breakdown,
    )


def is_better_context_set(
    left: ContextSetEvaluation,
    right: ContextSetEvaluation | None,
    tolerance: float,
) -> bool:
    """Compare feasible sets using the approved lexicographic objective."""

    if right is None:
        return True
    coverage_difference = (
        left.covered_required_weight - right.covered_required_weight
    )
    if abs(coverage_difference) > tolerance:
        return coverage_difference > 0
    value_difference = (
        left.breakdown.total_set_value - right.breakdown.total_set_value
    )
    if abs(value_difference) > tolerance:
        return value_difference > 0
    if left.evidence_tokens != right.evidence_tokens:
        return left.evidence_tokens < right.evidence_tokens
    if left.item_count != right.item_count:
        return left.item_count < right.item_count
    return left.selected_uuid_tuple < right.selected_uuid_tuple


def order_selected_evidence(
    problem: CanonicalContextProblem,
    selected_ids: Collection[UUID],
) -> tuple[UUID, ...]:
    """Return a deterministic topological evidence order."""

    selected = frozenset(selected_ids)
    unknown = selected.difference(problem.candidate_by_id)
    if unknown:
        raise ContextCompilerValidationError(
            "ordering set contains an unknown candidate"
        )
    for memory_id in selected:
        if not problem.prerequisite_closure[memory_id].issubset(selected):
            raise ContextDependencyError(
                "ordering set omits a prerequisite"
            )

    selected_dependents: dict[UUID, set[UUID]] = defaultdict(set)
    for memory_id in selected:
        for prerequisite in problem.prerequisite_closure[memory_id]:
            if prerequisite in selected:
                selected_dependents[prerequisite].add(memory_id)

    full_evaluation = evaluate_context_set(
        problem,
        selected,
        require_feasible=False,
    )
    marginal_by_id = {
        memory_id: (
            full_evaluation.breakdown.total_set_value
            - evaluate_context_set(
                problem,
                selected.difference({memory_id}),
                require_feasible=False,
            ).breakdown.total_set_value
        )
        for memory_id in selected
    }

    ordered: list[UUID] = []
    placed: set[UUID] = set()
    covered_required: set[str] = set()
    required_keys = set(problem.request.required_coverage_keys)
    while len(ordered) < len(selected):
        available = tuple(
            memory_id
            for memory_id in selected
            if memory_id not in placed
            and problem.prerequisite_closure[memory_id].issubset(placed)
        )
        if not available:
            raise ContextDependencyError(
                "selected dependency graph cannot be topologically ordered"
            )

        def priority(memory_id: UUID) -> tuple[object, ...]:
            item = problem.candidate_by_id[memory_id]
            closes_required = bool(
                required_keys
                .intersection(item.coverage_keys)
                .difference(covered_required)
            )
            return (
                -int(bool(selected_dependents.get(memory_id))),
                -int(memory_id in problem.mandatory_closure),
                -int(closes_required),
                -marginal_by_id[memory_id],
                item.original_rank,
                str(memory_id),
            )

        chosen = min(available, key=priority)
        ordered.append(chosen)
        placed.add(chosen)
        covered_required.update(
            required_keys.intersection(
                problem.candidate_by_id[chosen].coverage_keys
            )
        )
    return tuple(ordered)


def _deduplicate_memory_ids(
    candidates: Sequence[IntegratedContextEvidence],
    omissions: list[ContextOmission],
) -> dict[UUID, IntegratedContextEvidence]:
    grouped: dict[UUID, list[IntegratedContextEvidence]] = defaultdict(list)
    for item in candidates:
        grouped[item.memory_id].append(item)
    representatives: dict[UUID, IntegratedContextEvidence] = {}
    for memory_id in sorted(grouped, key=str):
        values = grouped[memory_id]
        identity = values[0].immutable_identity
        if any(item.immutable_identity != identity for item in values[1:]):
            raise ContextCompilerValidationError(
                "one memory_id was reused with conflicting immutable identity"
            )
        representative = min(values, key=_representative_key)
        representatives[memory_id] = representative
        for _ in range(len(values) - 1):
            omissions.append(
                ContextOmission(
                    memory_id,
                    ContextOmissionReason.DUPLICATE_CANDIDATE,
                    "identical canonical candidate was deduplicated",
                )
            )
    return representatives


def _deduplicate_content(
    request: IntegratedContextCompileRequest,
    candidates: Mapping[UUID, IntegratedContextEvidence],
    closure: Mapping[UUID, frozenset[UUID]],
    anchor_ids: frozenset[UUID],
    omissions: list[ContextOmission],
) -> dict[UUID, IntegratedContextEvidence]:
    grouped: dict[str, list[IntegratedContextEvidence]] = defaultdict(list)
    for item in candidates.values():
        grouped[item.content_hash].append(item)
    surviving = dict(candidates)
    required_keys = set(request.required_coverage_keys)
    for content_hash in sorted(grouped):
        values = grouped[content_hash]
        contents = {item.content for item in values}
        if len(contents) > 1:
            raise ContextCompilerValidationError(
                "one content_hash maps to conflicting exact content"
            )
        if len(values) == 1:
            continue
        mandatory = tuple(item for item in values if item.mandatory)
        if len(mandatory) > 1:
            for index, left in enumerate(mandatory):
                for right in mandatory[index + 1 :]:
                    structurally_related = (
                        left.memory_id in closure[right.memory_id]
                        or right.memory_id in closure[left.memory_id]
                    )
                    left_required = required_keys.intersection(
                        left.coverage_keys
                    )
                    right_required = required_keys.intersection(
                        right.coverage_keys
                    )
                    if not structurally_related and not left_required.isdisjoint(
                        right_required
                    ):
                        raise ContextCompilerValidationError(
                            "mandatory duplicate content is ambiguous"
                        )
        anchors = tuple(
            item for item in values if item.memory_id in anchor_ids
        )
        keep_ids = (
            {item.memory_id for item in anchors}
            if anchors
            else {min(values, key=_representative_key).memory_id}
        )
        for item in values:
            if item.memory_id in keep_ids:
                continue
            surviving.pop(item.memory_id, None)
            omissions.append(
                ContextOmission(
                    item.memory_id,
                    ContextOmissionReason.DUPLICATE_CONTENT,
                    "a stronger or structural same-content representation survived",
                )
            )
    return surviving


def _build_prerequisite_closure(
    candidates: Mapping[UUID, IntegratedContextEvidence],
) -> dict[UUID, frozenset[UUID]]:
    all_ids = frozenset(candidates)
    for item in candidates.values():
        unknown = set(item.prerequisite_memory_ids).difference(all_ids)
        if unknown:
            raise ContextDependencyError(
                "candidate references an unknown prerequisite"
            )
    closure: dict[UUID, frozenset[UUID]] = {}
    visiting: set[UUID] = set()

    def resolve(memory_id: UUID) -> frozenset[UUID]:
        existing = closure.get(memory_id)
        if existing is not None:
            return existing
        if memory_id in visiting:
            raise ContextDependencyError(
                "candidate prerequisite graph contains a cycle"
            )
        visiting.add(memory_id)
        result: set[UUID] = set()
        for prerequisite in candidates[memory_id].prerequisite_memory_ids:
            result.add(prerequisite)
            result.update(resolve(prerequisite))
        visiting.remove(memory_id)
        frozen = frozenset(result)
        closure[memory_id] = frozen
        return frozen

    for memory_id in sorted(candidates, key=str):
        resolve(memory_id)
    return closure


def _canonicalize_interactions(
    interactions: Sequence[ContextPairInteraction],
    original_ids: frozenset[UUID],
    surviving_ids: frozenset[UUID],
) -> dict[tuple[UUID, UUID], ContextPairInteraction]:
    active: dict[tuple[UUID, UUID], ContextPairInteraction] = {}
    seen: dict[tuple[UUID, UUID], ContextPairInteraction] = {}
    for item in interactions:
        if not isinstance(item, ContextPairInteraction):
            raise ContextCompilerValidationError(
                "interactions must contain ContextPairInteraction instances"
            )
        pair = (item.left_memory_id, item.right_memory_id)
        if not set(pair).issubset(original_ids):
            raise ContextCompilerValidationError(
                "interaction references an unknown candidate"
            )
        if item.kind is ContextInteractionKind.SYNERGY and item.value < 0:
            raise ContextCompilerValidationError(
                "synergy interaction value must be non-negative"
            )
        if item.kind is ContextInteractionKind.REDUNDANCY and item.value > 0:
            raise ContextCompilerValidationError(
                "redundancy interaction value must be non-positive"
            )
        existing = seen.get(pair)
        if existing is not None and existing != item:
            raise ContextCompilerValidationError(
                "conflicting interaction evidence exists for one pair"
            )
        seen[pair] = item
        if set(pair).issubset(surviving_ids):
            active[pair] = item
    return active


def _close_ids(
    closure: Mapping[UUID, frozenset[UUID]],
    roots: Collection[UUID],
) -> frozenset[UUID]:
    selected = set(roots)
    for memory_id in tuple(roots):
        selected.update(closure[memory_id])
    return frozenset(selected)


def _representative_key(item: IntegratedContextEvidence) -> tuple[object, ...]:
    return (
        -int(item.mandatory),
        -item.relevance,
        -item.direct_credit,
        -item.utility,
        item.harm_risk,
        item.original_rank,
        str(item.memory_id),
    )


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
