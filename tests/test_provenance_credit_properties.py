from __future__ import annotations

import random
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

SPACE = UUID("90000000-0000-0000-0000-000000000001")
CONTEXT_HASH = "a" * 64
CONTINUATION_HASH = "b" * 64


def _uuid(namespace: int, value: int) -> UUID:
    return UUID(int=(namespace << 96) + value + 1)


def _case(seed: int):
    rng = random.Random(seed)
    node_count = rng.randint(1, 7)
    node_ids = tuple(_uuid(1, seed * 16 + index) for index in range(node_count))
    nodes = tuple(
        ProvenanceNode(
            memory_id=memory_id,
            space_id=SPACE,
            authorized=(index == 0 or rng.random() > 0.08),
            currently_valid=(index == 0 or rng.random() > 0.08),
        )
        for index, memory_id in enumerate(node_ids)
    )
    edges: list[ProvenanceEdge] = []
    edge_index = 0
    for source_index in range(node_count):
        for target_index in range(source_index + 1, node_count):
            if rng.random() > 0.28:
                continue
            relation = "supported_by" if rng.random() < 0.75 else "followed_by"
            edges.append(
                ProvenanceEdge(
                    edge_id=_uuid(2, seed * 64 + edge_index),
                    space_id=SPACE,
                    from_node_id=node_ids[source_index],
                    to_node_id=node_ids[target_index],
                    relation=relation,
                    confidence=round(rng.uniform(0.1, 1.0), 8),
                )
            )
            edge_index += 1
    graph = TypedProvenanceGraph(nodes=nodes, edges=tuple(edges))
    direct = DirectCreditEvidence(
        direct_credit_id=_uuid(3, seed),
        evidence_group_id=_uuid(4, seed),
        space_id=SPACE,
        root_memory_id=node_ids[0],
        source_kind=CreditSourceKind.INTERACTION,
        value=round(rng.uniform(0.05, 1.0), 8),
        standard_error=round(rng.uniform(0.0, 0.2), 8),
        trial_count=rng.randint(2, 8),
        context_set_hash=CONTEXT_HASH,
        continuation_set_hash=CONTINUATION_HASH,
    )
    config = PropagationConfig(
        positive_budget_fraction=round(rng.uniform(0.1, 1.0), 8),
        transmission_fraction=round(rng.uniform(0.0, 1.0), 8),
        maximum_depth=rng.randint(1, 4),
        minimum_absolute_mass=10 ** (-rng.randint(4, 8)),
        conservation_tolerance=1e-10,
    )
    return graph, direct, config


def test_5000_random_dags_preserve_scope_mass_and_determinism() -> None:
    policies = project_relation_policies_v0()
    cases_with_contributions = 0
    cases_with_blocked_edges = 0

    for seed in range(5000):
        graph, direct, config = _case(seed)
        propagator = ConservativeProvenancePropagator(config)

        first = propagator.propagate(graph, (direct,), policies)
        permuted_graph = TypedProvenanceGraph(
            nodes=tuple(reversed(graph.nodes)),
            edges=tuple(reversed(graph.edges)),
        )
        second = propagator.propagate(
            permuted_graph,
            (direct,),
            tuple(reversed(policies)),
        )

        assert first == second
        assert first.render_json() == second.render_json()
        assert first.direct_credits == (direct,)
        assert len(first.mass_ledgers) == 1

        ledger = first.mass_ledgers[0]
        accounted = (
            ledger.propagated_value
            + ledger.dropped_value
            + ledger.unallocated_value
        )
        assert abs(ledger.propagation_budget - accounted) <= 1e-10
        assert abs(ledger.conservation_residual) <= 1e-10
        assert abs(ledger.propagated_value) <= abs(ledger.propagation_budget) + 1e-10

        node_map = graph.node_map
        contribution_ids = {
            item.target_memory_id for item in first.contributions
        }
        assert direct.root_memory_id not in contribution_ids
        assert all(
            node_map[item.target_memory_id].space_id == SPACE
            and node_map[item.target_memory_id].authorized
            and node_map[item.target_memory_id].currently_valid
            and 1 <= item.depth <= config.maximum_depth
            and len(item.relation_path) == item.depth
            and len(item.edge_path) == item.depth
            and item.propagated_value > 0
            and item.propagated_standard_error >= 0
            for item in first.contributions
        )

        for summary in first.target_credits:
            paths = tuple(
                item
                for item in first.contributions
                if item.direct_credit_id == summary.direct_credit_id
                and item.target_memory_id == summary.target_memory_id
            )
            assert summary.path_count == len(paths)
            assert abs(
                summary.propagated_value
                - sum(item.propagated_value for item in paths)
            ) <= 1e-12
            assert abs(
                summary.propagated_standard_error
                - sum(item.propagated_standard_error for item in paths)
            ) <= 1e-12

        cases_with_contributions += bool(first.contributions)
        cases_with_blocked_edges += bool(first.blocked)

    assert cases_with_contributions > 1000
    assert cases_with_blocked_edges > 1000
