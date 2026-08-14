from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace
from types import MappingProxyType
from typing import Any
from uuid import UUID

import pytest

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
    INHERITED_ACCOUNTING_INSERT_SQL,
    INHERITED_ACCOUNTING_SELECT_SQL,
    INHERITED_CONTRIBUTION_INSERT_SQL,
    INHERITED_CONTRIBUTION_SELECT_SQL,
    INHERITED_EVALUATION_INSERT_SQL,
    INHERITED_EVALUATION_SELECT_SQL,
    INHERITED_OBSERVATION_INSERT_SQL,
    INHERITED_OBSERVATION_SELECT_SQL,
    InheritedCreditContributionRecord,
    ProvenanceCreditAccountingRecord,
    ProvenanceCreditBatch,
    ProvenanceCreditEvaluationRecord,
    ProvenanceCreditObservationRecord,
    ProvenanceCreditPersistenceConflictError,
    ProvenanceCreditPersistenceValidationError,
    ProvenanceCreditPersistenceWriter,
    build_provenance_credit_batch,
    fingerprint_provenance_graph,
    fingerprint_provenance_policy,
)

SPACE = UUID("11111111-1111-1111-1111-111111111111")
OTHER_SPACE = UUID("22222222-2222-2222-2222-222222222222")
A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
C = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
D = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
E = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
EDGE_AB = UUID("30000000-0000-0000-0000-000000000001")
EDGE_AC = UUID("30000000-0000-0000-0000-000000000002")
EDGE_DE = UUID("30000000-0000-0000-0000-000000000003")
DIRECT_A = UUID("40000000-0000-0000-0000-000000000001")
DIRECT_D = UUID("40000000-0000-0000-0000-000000000002")
GROUP_A = UUID("50000000-0000-0000-0000-000000000001")
GROUP_D = UUID("50000000-0000-0000-0000-000000000002")
HASH_A = "a" * 64
HASH_B = "b" * 64


def graph(*, confidence: float = 1.0) -> TypedProvenanceGraph:
    return TypedProvenanceGraph(
        nodes=tuple(
            ProvenanceNode(memory_id, SPACE)
            for memory_id in (A, B, C, D, E)
        ),
        edges=(
            ProvenanceEdge(
                EDGE_AB,
                SPACE,
                A,
                B,
                "supported_by",
                confidence=confidence,
            ),
            ProvenanceEdge(EDGE_AC, SPACE, A, C, "followed_by"),
            ProvenanceEdge(EDGE_DE, SPACE, D, E, "followed_by"),
        ),
    )


def direct(
    direct_credit_id: UUID,
    evidence_group_id: UUID,
    root_memory_id: UUID,
    *,
    value: float,
    source_kind: CreditSourceKind,
) -> DirectCreditEvidence:
    return DirectCreditEvidence(
        direct_credit_id=direct_credit_id,
        evidence_group_id=evidence_group_id,
        space_id=SPACE,
        root_memory_id=root_memory_id,
        source_kind=source_kind,
        value=value,
        standard_error=0.1,
        trial_count=3,
        context_set_hash=HASH_A,
        continuation_set_hash=HASH_B,
    )


def inputs(*, confidence: float = 1.0, config: PropagationConfig | None = None):
    provenance_graph = graph(confidence=confidence)
    policies = project_relation_policies_v0()
    propagation_config = config or PropagationConfig()
    direct_credits = (
        direct(
            DIRECT_A,
            GROUP_A,
            A,
            value=1.0,
            source_kind=CreditSourceKind.INTERACTION,
        ),
        direct(
            DIRECT_D,
            GROUP_D,
            D,
            value=0.4,
            source_kind=CreditSourceKind.CAUSAL,
        ),
    )
    result = ConservativeProvenancePropagator(propagation_config).propagate(
        provenance_graph,
        direct_credits,
        policies,
    )
    return provenance_graph, policies, propagation_config, result


def batch(**overrides: object) -> ProvenanceCreditBatch:
    provenance_graph, policies, config, result = inputs()
    values: dict[str, object] = {
        "graph": provenance_graph,
        "policies": policies,
        "config": config,
        "result": result,
    }
    values.update(overrides)
    return build_provenance_credit_batch(**values)


class FakeCursor:
    def __init__(self, responses: list[list[Mapping[str, Any]]]) -> None:
        self.responses = list(responses)
        self.executemany_calls: list[
            tuple[str, list[Mapping[str, Any]]]
        ] = []
        self.execute_calls: list[tuple[str, Mapping[str, Any]]] = []
        self.current: list[Mapping[str, Any]] = []

    def executemany(
        self,
        sql: str,
        rows: list[Mapping[str, Any]],
    ) -> None:
        self.executemany_calls.append((sql, rows))

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        self.execute_calls.append((sql, params))
        if not self.responses:
            raise AssertionError("unexpected verification query")
        self.current = self.responses.pop(0)

    def fetchall(self) -> Iterable[Mapping[str, Any]]:
        return list(self.current)


def stored_rows(records: Iterable[Any]) -> list[dict[str, Any]]:
    return [record.to_db_params() for record in records]


def writer_responses(value: ProvenanceCreditBatch) -> list[list[dict[str, Any]]]:
    return [
        stored_rows(value.evaluations),
        stored_rows(value.contributions),
        stored_rows(value.observations),
        stored_rows(value.accounting),
    ]


def test_graph_and_policy_fingerprints_are_permutation_invariant() -> None:
    provenance_graph, policies, config, _ = inputs()
    permuted_graph = TypedProvenanceGraph(
        nodes=tuple(reversed(provenance_graph.nodes)),
        edges=tuple(reversed(provenance_graph.edges)),
    )

    assert fingerprint_provenance_graph(provenance_graph) == (
        fingerprint_provenance_graph(permuted_graph)
    )
    assert fingerprint_provenance_policy(policies, config) == (
        fingerprint_provenance_policy(tuple(reversed(policies)), config)
    )


def test_batch_is_complete_deterministic_and_keeps_evidence_classes_separate() -> None:
    first = batch()
    second = batch()

    assert first == second
    assert len(first.evaluations) == 2
    assert len(first.contributions) == 1
    assert len(first.observations) == 3
    assert len(first.accounting) == 2
    assert first.space_id == SPACE
    assert isinstance(first.evaluations, tuple)
    assert isinstance(first.contributions, tuple)
    assert isinstance(first.observations, tuple)
    assert isinstance(first.accounting, tuple)

    evaluation_by_direct = {
        item.direct_credit_id: item for item in first.evaluations
    }
    contribution = first.contributions[0]
    assert contribution.target_node_id == B
    assert contribution.evaluation_id == evaluation_by_direct[DIRECT_A].id
    assert contribution.path_fingerprint
    assert contribution.content_hash

    blocked = [item for item in first.observations if item.kind == "blocked"]
    abstained = [
        item for item in first.observations if item.kind == "abstention"
    ]
    assert len(blocked) == 2
    assert len(abstained) == 1
    assert abstained[0].evaluation_id == evaluation_by_direct[DIRECT_D].id
    assert all(item.content_hash for item in first.observations)

    assert {item.evaluation_id for item in first.accounting} == {
        item.id for item in first.evaluations
    }
    assert all(item.result_hash for item in first.evaluations)
    assert "memory_feedback" not in repr(first).lower()


def test_graph_or_policy_change_creates_new_evaluation_identities() -> None:
    baseline = batch()
    changed_graph, policies, config, result = inputs(confidence=0.8)
    graph_changed = build_provenance_credit_batch(
        graph=changed_graph,
        policies=policies,
        config=config,
        result=result,
    )
    original_graph, policies, _, _ = inputs()
    changed_config = PropagationConfig(positive_budget_fraction=0.4)
    changed_result = ConservativeProvenancePropagator(changed_config).propagate(
        original_graph,
        tuple(baseline.direct_credits),
        policies,
    )
    policy_changed = build_provenance_credit_batch(
        graph=original_graph,
        policies=policies,
        config=changed_config,
        result=changed_result,
    )

    assert baseline.graph_fingerprint != graph_changed.graph_fingerprint
    assert baseline.policy_fingerprint != policy_changed.policy_fingerprint
    assert {item.id for item in baseline.evaluations}.isdisjoint(
        item.id for item in graph_changed.evaluations
    )
    assert {item.id for item in baseline.evaluations}.isdisjoint(
        item.id for item in policy_changed.evaluations
    )


def test_record_contracts_are_frozen_and_db_params_are_plain_values() -> None:
    value = batch()
    evaluation = value.evaluations[0]
    contribution = value.contributions[0]
    observation = value.observations[0]
    accounting = value.accounting[0]

    assert isinstance(evaluation, ProvenanceCreditEvaluationRecord)
    assert isinstance(contribution, InheritedCreditContributionRecord)
    assert isinstance(observation, ProvenanceCreditObservationRecord)
    assert isinstance(accounting, ProvenanceCreditAccountingRecord)
    assert isinstance(evaluation.to_db_params(), dict)
    assert isinstance(contribution.to_db_params()["relation_path"], list)
    assert isinstance(contribution.to_db_params()["edge_path"], list)
    assert isinstance(observation.to_db_params(), dict)
    assert isinstance(accounting.to_db_params(), dict)
    assert isinstance(value.evaluation_map, MappingProxyType)
    with pytest.raises(TypeError):
        value.evaluation_map[evaluation.id] = evaluation  # type: ignore[index]


def test_builder_rejects_result_policy_mismatch_and_unknown_references() -> None:
    provenance_graph, policies, config, result = inputs()
    with pytest.raises(
        ProvenanceCreditPersistenceValidationError,
        match="policy_version",
    ):
        build_provenance_credit_batch(
            graph=provenance_graph,
            policies=policies,
            config=replace(config, policy_version="different"),
            result=result,
        )

    broken_contribution = replace(
        result.contributions[0],
        target_memory_id=UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
    )
    broken_result = replace(result, contributions=(broken_contribution,))
    with pytest.raises(
        ProvenanceCreditPersistenceValidationError,
        match="target",
    ):
        build_provenance_credit_batch(
            graph=provenance_graph,
            policies=policies,
            config=config,
            result=broken_result,
        )


def test_batch_rejects_mixed_space_and_duplicate_child_ids() -> None:
    value = batch()
    other_evaluation = replace(value.evaluations[0], space_id=OTHER_SPACE)
    with pytest.raises(
        ProvenanceCreditPersistenceValidationError,
        match="space",
    ):
        ProvenanceCreditBatch(
            graph_fingerprint=value.graph_fingerprint,
            policy_fingerprint=value.policy_fingerprint,
            direct_credits=value.direct_credits,
            evaluations=(other_evaluation, *value.evaluations[1:]),
            contributions=value.contributions,
            observations=value.observations,
            accounting=value.accounting,
        )

    with pytest.raises(
        ProvenanceCreditPersistenceValidationError,
        match="duplicate",
    ):
        ProvenanceCreditBatch(
            graph_fingerprint=value.graph_fingerprint,
            policy_fingerprint=value.policy_fingerprint,
            direct_credits=value.direct_credits,
            evaluations=value.evaluations,
            contributions=(
                value.contributions[0],
                value.contributions[0],
            ),
            observations=value.observations,
            accounting=value.accounting,
        )


def test_writer_uses_four_insert_then_readback_phases() -> None:
    value = batch()
    cursor = FakeCursor(writer_responses(value))

    written = ProvenanceCreditPersistenceWriter().write(cursor, value)

    assert written == (
        len(value.evaluations)
        + len(value.contributions)
        + len(value.observations)
        + len(value.accounting)
    )
    assert [call[0] for call in cursor.executemany_calls] == [
        INHERITED_EVALUATION_INSERT_SQL,
        INHERITED_CONTRIBUTION_INSERT_SQL,
        INHERITED_OBSERVATION_INSERT_SQL,
        INHERITED_ACCOUNTING_INSERT_SQL,
    ]
    assert [call[0] for call in cursor.execute_calls] == [
        INHERITED_EVALUATION_SELECT_SQL,
        INHERITED_CONTRIBUTION_SELECT_SQL,
        INHERITED_OBSERVATION_SELECT_SQL,
        INHERITED_ACCOUNTING_SELECT_SQL,
    ]
    assert all(
        call[1]["space_id"] == SPACE for call in cursor.execute_calls
    )


def test_writer_accepts_empty_batch_without_sql() -> None:
    empty = ProvenanceCreditBatch(
        graph_fingerprint="0" * 64,
        policy_fingerprint="1" * 64,
        direct_credits=(),
        evaluations=(),
        contributions=(),
        observations=(),
        accounting=(),
    )
    cursor = FakeCursor([])

    assert ProvenanceCreditPersistenceWriter().write(cursor, empty) == 0
    assert cursor.executemany_calls == []
    assert cursor.execute_calls == []


def test_writer_rejects_missing_unexpected_duplicate_and_conflicting_rows() -> None:
    value = batch()

    missing_responses = writer_responses(value)
    missing_responses[1] = []
    with pytest.raises(
        ProvenanceCreditPersistenceConflictError,
        match="missing",
    ):
        ProvenanceCreditPersistenceWriter().write(
            FakeCursor(missing_responses),
            value,
        )

    unexpected_responses = writer_responses(value)
    unexpected = dict(unexpected_responses[0][0])
    unexpected["id"] = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
    unexpected_responses[0].append(unexpected)
    with pytest.raises(
        ProvenanceCreditPersistenceConflictError,
        match="unexpected",
    ):
        ProvenanceCreditPersistenceWriter().write(
            FakeCursor(unexpected_responses),
            value,
        )

    duplicate_responses = writer_responses(value)
    duplicate_responses[2].append(dict(duplicate_responses[2][0]))
    with pytest.raises(
        ProvenanceCreditPersistenceConflictError,
        match="duplicate",
    ):
        ProvenanceCreditPersistenceWriter().write(
            FakeCursor(duplicate_responses),
            value,
        )

    conflicting_responses = writer_responses(value)
    conflicting_responses[3][0]["propagated_value"] += 0.1
    with pytest.raises(
        ProvenanceCreditPersistenceConflictError,
        match="differs",
    ):
        ProvenanceCreditPersistenceWriter().write(
            FakeCursor(conflicting_responses),
            value,
        )


def test_writer_rejects_non_mapping_readback_rows() -> None:
    value = batch()
    responses: list[list[Any]] = writer_responses(value)
    responses[0] = [("not", "a", "mapping")]

    with pytest.raises(
        ProvenanceCreditPersistenceConflictError,
        match="mapping",
    ):
        ProvenanceCreditPersistenceWriter().write(
            FakeCursor(responses),  # type: ignore[arg-type]
            value,
        )
