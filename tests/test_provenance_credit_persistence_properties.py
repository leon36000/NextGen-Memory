from __future__ import annotations

import json
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
from nextgen_memory.provenance_credit_persistence import (
    build_provenance_credit_batch,
)

SPACE = UUID("90000000-0000-0000-0000-000000000001")
CONTEXT_HASH = "a" * 64
CONTINUATION_HASH = "b" * 64
FORBIDDEN = (
    "query",
    "prompt",
    "answer",
    "command",
    "stdout",
    "stderr",
    "secret",
    "token",
    "patch",
    "environment",
    "memory_body",
    "feedback_note",
)


def _uuid(namespace: int, value: int) -> UUID:
    return UUID(int=(namespace << 96) + value + 1)


def _generated_case(seed: int):
    rng = random.Random(seed)
    node_count = rng.randint(1, 7)
    node_ids = tuple(_uuid(1, seed * 16 + index) for index in range(node_count))
    nodes = tuple(ProvenanceNode(memory_id, SPACE) for memory_id in node_ids)

    edges: list[ProvenanceEdge] = []
    edge_index = 0
    for source_index in range(node_count):
        for target_index in range(source_index + 1, node_count):
            if rng.random() > 0.30:
                continue
            relation = "supported_by" if rng.random() < 0.72 else "followed_by"
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
        source_kind=(
            CreditSourceKind.INTERACTION
            if seed % 3
            else CreditSourceKind.CAUSAL
        ),
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
        policy_version="provenance-credit-v0",
    )
    policies = project_relation_policies_v0()
    result = ConservativeProvenancePropagator(config).propagate(
        graph,
        (direct,),
        policies,
    )
    return graph, policies, config, result


def _serialized_params(batch) -> str:
    payload = {
        "evaluations": [item.to_db_params() for item in batch.evaluations],
        "contributions": [item.to_db_params() for item in batch.contributions],
        "observations": [item.to_db_params() for item in batch.observations],
        "accounting": [item.to_db_params() for item in batch.accounting],
    }
    return json.dumps(payload, default=str, sort_keys=True).lower()


def test_2000_generated_batches_preserve_identity_completeness_and_privacy() -> None:
    propagated_cases = 0
    abstained_cases = 0
    blocked_cases = 0

    for seed in range(2000):
        graph, policies, config, result = _generated_case(seed)
        first = build_provenance_credit_batch(
            graph=graph,
            policies=policies,
            config=config,
            result=result,
        )
        permuted_graph = TypedProvenanceGraph(
            nodes=tuple(reversed(graph.nodes)),
            edges=tuple(reversed(graph.edges)),
        )
        second = build_provenance_credit_batch(
            graph=permuted_graph,
            policies=tuple(reversed(policies)),
            config=config,
            result=result,
        )

        assert first == second
        assert first.space_id == SPACE
        assert len(first.evaluations) == 1
        assert len(first.accounting) == 1
        assert first.evaluations[0].accounting_id == first.accounting[0].id
        assert first.accounting[0].evaluation_id == first.evaluations[0].id
        assert first.evaluations[0].direct_credit_id == result.direct_credits[0].direct_credit_id
        assert first.evaluations[0].root_node_id == result.direct_credits[0].root_memory_id
        assert first.accounting[0].direct_value == result.mass_ledgers[0].direct_value
        assert first.accounting[0].propagation_budget == result.mass_ledgers[0].propagation_budget
        assert first.accounting[0].propagated_value == result.mass_ledgers[0].propagated_value
        assert first.accounting[0].dropped_value == result.mass_ledgers[0].dropped_value
        assert first.accounting[0].unallocated_value == result.mass_ledgers[0].unallocated_value
        assert first.accounting[0].conservation_residual == result.mass_ledgers[0].conservation_residual

        evaluation_ids = {item.id for item in first.evaluations}
        child_ids = [
            *(item.id for item in first.contributions),
            *(item.id for item in first.observations),
            *(item.id for item in first.accounting),
        ]
        assert len(child_ids) == len(set(child_ids))
        assert all(
            item.evaluation_id in evaluation_ids
            for item in (
                *first.contributions,
                *first.observations,
                *first.accounting,
            )
        )
        assert all(
            item.target_node_id in graph.node_map
            for item in first.contributions
        )
        assert all(
            len(item.relation_path) == item.depth
            and len(item.edge_path) == item.depth
            for item in first.contributions
        )
        serialized = _serialized_params(first)
        assert all(term not in serialized for term in FORBIDDEN)

        propagated_cases += bool(first.contributions)
        abstained_cases += first.evaluations[0].status == "abstained"
        blocked_cases += any(
            item.kind == "blocked" for item in first.observations
        )

    assert propagated_cases > 400
    assert abstained_cases > 400
    assert blocked_cases > 400
