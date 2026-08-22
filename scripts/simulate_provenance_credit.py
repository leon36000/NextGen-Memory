"""Compare naive branch-multiplying credit with typed mass conservation."""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from math import isfinite
from uuid import UUID

from nextgen_memory.provenance_credit import (
    ConservativeProvenancePropagator,
    CreditSourceKind,
    DirectCreditEvidence,
    PropagationConfig,
    ProvenanceEdge,
    ProvenanceNode,
    TypedProvenanceGraph,
    project_relation_policies_v0,
)

SPACE = UUID("70000000-0000-0000-0000-000000000001")
ROOT = UUID("70000000-0000-0000-0000-000000000010")
BRANCH_A = UUID("70000000-0000-0000-0000-000000000011")
BRANCH_B = UUID("70000000-0000-0000-0000-000000000012")
EDGE_A = UUID("70000000-0000-0000-0000-000000000101")
EDGE_B = UUID("70000000-0000-0000-0000-000000000102")
DIRECT_BRANCH = UUID("70000000-0000-0000-0000-000000000201")
DIRECT_BLOCKED = UUID("70000000-0000-0000-0000-000000000202")
DIRECT_NEGATIVE = UUID("70000000-0000-0000-0000-000000000203")
GROUP_BRANCH = UUID("70000000-0000-0000-0000-000000000301")
GROUP_BLOCKED = UUID("70000000-0000-0000-0000-000000000302")
GROUP_NEGATIVE = UUID("70000000-0000-0000-0000-000000000303")
CONTEXT_HASH = "a" * 64
CONTINUATION_HASH = "b" * 64


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Fixed controls for the deterministic provenance-credit experiment."""

    seed: int = 20_260_814
    propagation_budget_fraction: float = 0.50

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if (
            not isfinite(self.propagation_budget_fraction)
            or not 0.0 <= self.propagation_budget_fraction <= 1.0
        ):
            raise ValueError(
                "propagation_budget_fraction must be finite and between zero and one"
            )


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Controlled evidence for branch inflation, false credit, and false blame."""

    config: SimulationConfig
    naive_branch_propagated: float
    conservative_branch_propagated: float
    naive_branch_inflation_ratio: float
    conservative_branch_inflation_ratio: float
    naive_blocked_relation_false_credit: float
    conservative_blocked_relation_false_credit: float
    naive_negative_false_blame: float
    conservative_negative_false_blame: float
    conservative_max_conservation_residual: float

    def __post_init__(self) -> None:
        for name in (
            "naive_branch_propagated",
            "conservative_branch_propagated",
            "naive_branch_inflation_ratio",
            "conservative_branch_inflation_ratio",
            "naive_blocked_relation_false_credit",
            "conservative_blocked_relation_false_credit",
            "naive_negative_false_blame",
            "conservative_negative_false_blame",
            "conservative_max_conservation_residual",
        ):
            value = getattr(self, name)
            if not isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")

    def to_json(self) -> str:
        """Return deterministic compact JSON for a reproducible artifact."""

        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


def simulate(config: SimulationConfig) -> SimulationResult:
    """Run three controlled cases against naive and conservative propagation."""

    rng = random.Random(config.seed)
    policies = project_relation_policies_v0()
    propagation_config = PropagationConfig(
        positive_budget_fraction=config.propagation_budget_fraction,
        negative_budget_fraction=0.0,
        transmission_fraction=0.5,
        maximum_depth=4,
        minimum_absolute_mass=0.0001,
    )
    propagator = ConservativeProvenancePropagator(propagation_config)

    branch_graph = _graph(
        rng,
        relations=("supported_by", "supported_by"),
    )
    branch_direct = _direct(
        direct_credit_id=DIRECT_BRANCH,
        evidence_group_id=GROUP_BRANCH,
        value=1.0,
    )
    branch_result = propagator.propagate(
        branch_graph,
        (branch_direct,),
        policies,
    )
    branch_budget = branch_direct.value * config.propagation_budget_fraction
    naive_branch = _naive_relation_blind_leaf_mass(
        branch_graph,
        ROOT,
        branch_budget,
    )
    conservative_branch = sum(
        item.propagated_value for item in branch_result.contributions
    )

    blocked_graph = _single_edge_graph(rng, relation="followed_by")
    blocked_direct = _direct(
        direct_credit_id=DIRECT_BLOCKED,
        evidence_group_id=GROUP_BLOCKED,
        value=1.0,
    )
    blocked_result = propagator.propagate(
        blocked_graph,
        (blocked_direct,),
        policies,
    )
    blocked_budget = blocked_direct.value * config.propagation_budget_fraction
    naive_blocked = _naive_relation_blind_leaf_mass(
        blocked_graph,
        ROOT,
        blocked_budget,
    )
    conservative_blocked = sum(
        abs(item.propagated_value) for item in blocked_result.contributions
    )

    negative_graph = _single_edge_graph(rng, relation="supported_by")
    negative_direct = _direct(
        direct_credit_id=DIRECT_NEGATIVE,
        evidence_group_id=GROUP_NEGATIVE,
        value=-1.0,
    )
    negative_result = propagator.propagate(
        negative_graph,
        (negative_direct,),
        policies,
    )
    naive_negative = abs(
        _naive_relation_blind_leaf_mass(
            negative_graph,
            ROOT,
            negative_direct.value * config.propagation_budget_fraction,
        )
    )
    conservative_negative = sum(
        abs(item.propagated_value) for item in negative_result.contributions
    )

    conservative_ledgers = (
        *branch_result.mass_ledgers,
        *blocked_result.mass_ledgers,
        *negative_result.mass_ledgers,
    )
    return SimulationResult(
        config=config,
        naive_branch_propagated=naive_branch,
        conservative_branch_propagated=conservative_branch,
        naive_branch_inflation_ratio=_ratio(naive_branch, branch_budget),
        conservative_branch_inflation_ratio=_ratio(
            conservative_branch,
            branch_budget,
        ),
        naive_blocked_relation_false_credit=naive_blocked,
        conservative_blocked_relation_false_credit=conservative_blocked,
        naive_negative_false_blame=naive_negative,
        conservative_negative_false_blame=conservative_negative,
        conservative_max_conservation_residual=max(
            abs(item.conservation_residual) for item in conservative_ledgers
        ),
    )


def _graph(
    rng: random.Random,
    *,
    relations: tuple[str, str],
) -> TypedProvenanceGraph:
    nodes = [
        ProvenanceNode(ROOT, SPACE),
        ProvenanceNode(BRANCH_A, SPACE),
        ProvenanceNode(BRANCH_B, SPACE),
    ]
    edges = [
        ProvenanceEdge(
            EDGE_A,
            SPACE,
            ROOT,
            BRANCH_A,
            relations[0],
        ),
        ProvenanceEdge(
            EDGE_B,
            SPACE,
            ROOT,
            BRANCH_B,
            relations[1],
        ),
    ]
    rng.shuffle(nodes)
    rng.shuffle(edges)
    return TypedProvenanceGraph(tuple(nodes), tuple(edges))


def _single_edge_graph(
    rng: random.Random,
    *,
    relation: str,
) -> TypedProvenanceGraph:
    nodes = [ProvenanceNode(ROOT, SPACE), ProvenanceNode(BRANCH_A, SPACE)]
    rng.shuffle(nodes)
    return TypedProvenanceGraph(
        tuple(nodes),
        (
            ProvenanceEdge(
                EDGE_A,
                SPACE,
                ROOT,
                BRANCH_A,
                relation,
            ),
        ),
    )


def _direct(
    *,
    direct_credit_id: UUID,
    evidence_group_id: UUID,
    value: float,
) -> DirectCreditEvidence:
    return DirectCreditEvidence(
        direct_credit_id=direct_credit_id,
        evidence_group_id=evidence_group_id,
        space_id=SPACE,
        root_memory_id=ROOT,
        source_kind=CreditSourceKind.INTERACTION,
        value=value,
        standard_error=0.1,
        trial_count=3,
        context_set_hash=CONTEXT_HASH,
        continuation_set_hash=CONTINUATION_HASH,
    )


def _naive_relation_blind_leaf_mass(
    graph: TypedProvenanceGraph,
    root_memory_id: UUID,
    budget: float,
) -> float:
    """Copy the full incoming mass down every edge, ignoring relation semantics."""

    adjacency: dict[UUID, tuple[UUID, ...]] = {}
    for node in graph.nodes:
        adjacency[node.memory_id] = tuple(
            sorted(
                (
                    edge.to_node_id
                    for edge in graph.edges
                    if edge.from_node_id == node.memory_id
                ),
                key=str,
            )
        )

    def visit(memory_id: UUID, mass: float) -> float:
        targets = adjacency[memory_id]
        if not targets:
            return mass
        return sum(visit(target, mass) for target in targets)

    return visit(root_memory_id, budget)


def _ratio(value: float, budget: float) -> float:
    if budget == 0:
        return 0.0
    return abs(value / budget)


if __name__ == "__main__":
    print(simulate(SimulationConfig()).to_json())
