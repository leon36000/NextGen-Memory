from __future__ import annotations

from uuid import UUID, uuid5

from nextgen_memory.provenance_credit import (
    ConservativeProvenancePropagator,
    CreditSourceKind,
    DirectCreditEvidence,
    ProvenanceEdge,
    ProvenanceNode,
    TypedProvenanceGraph,
    project_relation_policies_v0,
)
from nextgen_memory.provenance_credit_persistence import (
    INHERITED_EVALUATION_INSERT_SQL,
    INHERITED_EVALUATION_SELECT_SQL,
    build_provenance_credit_batch,
)

SPACE = UUID("11111111-1111-1111-1111-111111111111")
ROOT = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TARGET = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
EDGE = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
DIRECT = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
GROUP = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")


def test_evaluation_points_to_its_exact_deterministic_accounting_row() -> None:
    graph = TypedProvenanceGraph(
        nodes=(
            ProvenanceNode(ROOT, SPACE),
            ProvenanceNode(TARGET, SPACE),
        ),
        edges=(
            ProvenanceEdge(
                EDGE,
                SPACE,
                ROOT,
                TARGET,
                "supported_by",
            ),
        ),
    )
    direct = DirectCreditEvidence(
        direct_credit_id=DIRECT,
        evidence_group_id=GROUP,
        space_id=SPACE,
        root_memory_id=ROOT,
        source_kind=CreditSourceKind.INTERACTION,
        value=1.0,
        standard_error=0.1,
        trial_count=3,
        context_set_hash="a" * 64,
        continuation_set_hash="b" * 64,
    )
    policies = project_relation_policies_v0()
    propagator = ConservativeProvenancePropagator()
    result = propagator.propagate(graph, (direct,), policies)
    batch = build_provenance_credit_batch(
        graph=graph,
        policies=policies,
        config=propagator.config,
        result=result,
    )

    evaluation = batch.evaluations[0]
    accounting = batch.accounting[0]
    expected_accounting_id = uuid5(evaluation.id, "mass-ledger")

    assert evaluation.accounting_id == expected_accounting_id
    assert accounting.id == expected_accounting_id
    assert accounting.evaluation_id == evaluation.id
    assert evaluation.to_db_params()["accounting_id"] == accounting.id
    assert "accounting_id" in INHERITED_EVALUATION_INSERT_SQL
    assert "accounting_id" in INHERITED_EVALUATION_SELECT_SQL
