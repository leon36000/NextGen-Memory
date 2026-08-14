from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest
from nextgen_memory.provenance_credit import (
    ConservativeProvenancePropagator,
    CreditSourceKind,
    DirectCreditEvidence,
    PropagationBlockReason,
    PropagationConfig,
    PropagationDirection,
    ProvenanceCreditAbstentionReason,
    ProvenanceCreditValidationError,
    ProvenanceEdge,
    ProvenanceNode,
    ProvenanceRelationPolicy,
    TypedProvenanceGraph,
    project_relation_policies_v0,
    select_preferred_direct_credits,
)

SPACE = UUID("11111111-1111-1111-1111-111111111111")
OTHER_SPACE = UUID("22222222-2222-2222-2222-222222222222")
A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
C = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
D = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
E = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
GROUP = UUID("10000000-0000-0000-0000-000000000001")
GROUP_2 = UUID("10000000-0000-0000-0000-000000000002")
DIRECT_A = UUID("20000000-0000-0000-0000-000000000001")
DIRECT_B = UUID("20000000-0000-0000-0000-000000000002")
EDGE_AB = UUID("30000000-0000-0000-0000-000000000001")
EDGE_AC = UUID("30000000-0000-0000-0000-000000000002")
EDGE_BD = UUID("30000000-0000-0000-0000-000000000003")
EDGE_CD = UUID("30000000-0000-0000-0000-000000000004")
EVIDENCE_ID = UUID("40000000-0000-0000-0000-000000000001")
HASH_1 = "1" * 64
HASH_2 = "2" * 64


def node(
    memory_id: UUID,
    *,
    space_id: UUID = SPACE,
    authorized: bool = True,
    currently_valid: bool = True,
) -> ProvenanceNode:
    return ProvenanceNode(
        memory_id=memory_id,
        space_id=space_id,
        authorized=authorized,
        currently_valid=currently_valid,
    )


def edge(
    edge_id: UUID,
    from_node_id: UUID,
    to_node_id: UUID,
    *,
    relation: str = "supported_by",
    space_id: UUID = SPACE,
    confidence: float = 1.0,
    local_attribution: float | None = None,
    evidence_id: UUID | None = None,
) -> ProvenanceEdge:
    return ProvenanceEdge(
        edge_id=edge_id,
        space_id=space_id,
        from_node_id=from_node_id,
        to_node_id=to_node_id,
        relation=relation,
        confidence=confidence,
        local_attribution=local_attribution,
        evidence_id=evidence_id,
    )


def direct(
    *,
    direct_credit_id: UUID = DIRECT_A,
    evidence_group_id: UUID = GROUP,
    root_memory_id: UUID = A,
    source_kind: CreditSourceKind = CreditSourceKind.INTERACTION,
    value: float = 1.0,
    standard_error: float = 0.1,
    space_id: UUID = SPACE,
) -> DirectCreditEvidence:
    return DirectCreditEvidence(
        direct_credit_id=direct_credit_id,
        evidence_group_id=evidence_group_id,
        space_id=space_id,
        root_memory_id=root_memory_id,
        source_kind=source_kind,
        value=value,
        standard_error=standard_error,
        trial_count=3,
        context_set_hash=HASH_1,
        continuation_set_hash=HASH_2,
    )


def supported_policy(**overrides: object) -> ProvenanceRelationPolicy:
    values: dict[str, object] = {
        "relation": "supported_by",
        "direction": PropagationDirection.FORWARD,
        "allow_positive": True,
        "allow_negative": False,
        "relation_weight": 1.0,
        "requires_local_attribution": False,
        "maximum_depth": None,
    }
    values.update(overrides)
    return ProvenanceRelationPolicy(**values)


def graph(
    nodes: tuple[ProvenanceNode, ...],
    edges: tuple[ProvenanceEdge, ...],
) -> TypedProvenanceGraph:
    return TypedProvenanceGraph(nodes=nodes, edges=edges)


def propagate(
    provenance_graph: TypedProvenanceGraph,
    credits: tuple[DirectCreditEvidence, ...] = (direct(),),
    *,
    policies: tuple[ProvenanceRelationPolicy, ...] = (supported_policy(),),
    config: PropagationConfig | None = None,
):
    return ConservativeProvenancePropagator(config).propagate(
        provenance_graph,
        credits,
        policies,
    )


def test_contracts_are_normalized_immutable_and_fail_closed() -> None:
    item = edge(
        EDGE_AB,
        A,
        B,
        relation=" supported_by ",
        confidence=0.8,
    )
    policy = supported_policy(relation=" supported_by ")

    assert item.relation == "supported_by"
    assert policy.relation == "supported_by"
    with pytest.raises(FrozenInstanceError):
        item.confidence = 0.5  # type: ignore[misc]

    with pytest.raises(ProvenanceCreditValidationError, match="relation"):
        supported_policy(relation=" ")
    with pytest.raises(ProvenanceCreditValidationError, match="confidence"):
        edge(EDGE_AB, A, B, confidence=1.1)
    with pytest.raises(ProvenanceCreditValidationError, match="local_attribution"):
        edge(EDGE_AB, A, B, local_attribution=0.5)
    with pytest.raises(ProvenanceCreditValidationError, match="standard_error"):
        direct(standard_error=-0.1)
    with pytest.raises(ProvenanceCreditValidationError, match="trial_count"):
        DirectCreditEvidence(
            direct_credit_id=DIRECT_A,
            evidence_group_id=GROUP,
            space_id=SPACE,
            root_memory_id=A,
            source_kind=CreditSourceKind.CAUSAL,
            value=1.0,
            standard_error=0.1,
            trial_count=0,
            context_set_hash=HASH_1,
            continuation_set_hash=HASH_2,
        )


def test_graph_canonicalizes_input_order_and_rejects_cross_space_edges() -> None:
    first = graph(
        (node(B), node(A)),
        (edge(EDGE_AB, A, B),),
    )
    second = graph(
        (node(A), node(B)),
        (edge(EDGE_AB, A, B),),
    )

    assert first == second
    assert first.nodes == (node(A), node(B))
    assert first.edges == (edge(EDGE_AB, A, B),)

    with pytest.raises(ProvenanceCreditValidationError, match="space"):
        graph(
            (node(A), node(B)),
            (edge(EDGE_AB, A, B, space_id=OTHER_SPACE),),
        )
    with pytest.raises(ProvenanceCreditValidationError, match="unknown node"):
        graph((node(A),), (edge(EDGE_AB, A, B),))


def test_direct_selector_prefers_interaction_over_causal_without_adding_values() -> None:
    causal = direct(
        direct_credit_id=DIRECT_A,
        source_kind=CreditSourceKind.CAUSAL,
        value=0.7,
    )
    interaction = direct(
        direct_credit_id=DIRECT_B,
        source_kind=CreditSourceKind.INTERACTION,
        value=0.4,
    )

    selected = select_preferred_direct_credits((causal, interaction))

    assert selected == (interaction,)
    assert selected[0].value == 0.4


def test_direct_selector_deduplicates_exact_retries_and_rejects_conflicts() -> None:
    item = direct(source_kind=CreditSourceKind.CAUSAL)
    assert select_preferred_direct_credits((item, item)) == (item,)

    conflict = direct(
        direct_credit_id=DIRECT_B,
        source_kind=CreditSourceKind.CAUSAL,
        value=0.6,
    )
    with pytest.raises(ProvenanceCreditValidationError, match="conflicting direct"):
        select_preferred_direct_credits((item, conflict))


def test_direct_selector_keeps_independent_evidence_groups_separate() -> None:
    first = direct(evidence_group_id=GROUP)
    second = direct(
        direct_credit_id=DIRECT_B,
        evidence_group_id=GROUP_2,
        value=0.3,
    )

    assert select_preferred_direct_credits((second, first)) == (first, second)


def test_simple_positive_leaf_receives_exact_bounded_budget() -> None:
    result = propagate(
        graph((node(A), node(B)), (edge(EDGE_AB, A, B, confidence=0.8),))
    )

    assert result.direct_credits == (direct(),)
    assert len(result.contributions) == 1
    contribution = result.contributions[0]
    assert contribution.root_memory_id == A
    assert contribution.target_memory_id == B
    assert contribution.propagated_value == pytest.approx(0.5)
    assert contribution.propagated_standard_error == pytest.approx(0.05)
    assert contribution.structural_confidence == pytest.approx(0.8)
    assert contribution.minimum_edge_confidence == pytest.approx(0.8)
    assert contribution.depth == 1
    assert contribution.relation_path == ("supported_by",)
    assert contribution.edge_path == (EDGE_AB,)
    assert len(contribution.path_fingerprint) == 64

    ledger = result.mass_ledgers[0]
    assert ledger.propagation_budget == pytest.approx(0.5)
    assert ledger.propagated_value == pytest.approx(0.5)
    assert ledger.dropped_value == 0.0
    assert ledger.unallocated_value == 0.0
    assert ledger.conservation_residual == pytest.approx(0.0)


def test_chain_retains_half_at_each_reached_non_leaf() -> None:
    result = propagate(
        graph(
            (node(A), node(B), node(C)),
            (
                edge(EDGE_AB, A, B),
                edge(EDGE_BD, B, C),
            ),
        )
    )

    values = {
        (item.target_memory_id, item.depth): item.propagated_value
        for item in result.contributions
    }
    assert values == {
        (B, 1): pytest.approx(0.25),
        (C, 2): pytest.approx(0.25),
    }
    assert result.mass_ledgers[0].propagated_value == pytest.approx(0.5)


def test_equal_branch_redistributes_budget_without_multiplication() -> None:
    result = propagate(
        graph(
            (node(A), node(B), node(C)),
            (
                edge(EDGE_AB, A, B),
                edge(EDGE_AC, A, C),
            ),
        )
    )

    assert {
        item.target_memory_id: item.propagated_value
        for item in result.contributions
    } == {B: pytest.approx(0.25), C: pytest.approx(0.25)}
    assert sum(item.propagated_value for item in result.contributions) == pytest.approx(
        0.5
    )
    assert result.mass_ledgers[0].conservation_residual == pytest.approx(0.0)


def test_unequal_confidence_weights_split_one_fixed_budget() -> None:
    result = propagate(
        graph(
            (node(A), node(B), node(C)),
            (
                edge(EDGE_AB, A, B, confidence=0.75),
                edge(EDGE_AC, A, C, confidence=0.25),
            ),
        )
    )

    values = {
        item.target_memory_id: item.propagated_value
        for item in result.contributions
    }
    assert values[B] == pytest.approx(0.375)
    assert values[C] == pytest.approx(0.125)
    assert sum(values.values()) == pytest.approx(0.5)


def test_converging_paths_remain_separate_with_conservative_target_uncertainty() -> None:
    result = propagate(
        graph(
            (node(A), node(B), node(C), node(D)),
            (
                edge(EDGE_AB, A, B),
                edge(EDGE_AC, A, C),
                edge(EDGE_BD, B, D),
                edge(EDGE_CD, C, D),
            ),
        )
    )

    paths_to_d = tuple(
        item for item in result.contributions if item.target_memory_id == D
    )
    assert len(paths_to_d) == 2
    assert {item.edge_path for item in paths_to_d} == {
        (EDGE_AB, EDGE_BD),
        (EDGE_AC, EDGE_CD),
    }
    summary = next(item for item in result.target_credits if item.target_memory_id == D)
    assert summary.propagated_value == pytest.approx(0.25)
    assert summary.propagated_standard_error == pytest.approx(0.025)
    assert summary.path_count == 2


def test_depth_limit_retains_all_mass_at_boundary_node() -> None:
    result = propagate(
        graph(
            (node(A), node(B), node(C)),
            (
                edge(EDGE_AB, A, B),
                edge(EDGE_BD, B, C),
            ),
        ),
        config=PropagationConfig(maximum_depth=1),
    )

    assert len(result.contributions) == 1
    assert result.contributions[0].target_memory_id == B
    assert result.contributions[0].propagated_value == pytest.approx(0.5)


def test_below_floor_mass_is_explicitly_dropped() -> None:
    result = propagate(
        graph((node(A), node(B)), (edge(EDGE_AB, A, B),)),
        config=PropagationConfig(minimum_absolute_mass=0.6),
    )

    assert result.contributions == ()
    ledger = result.mass_ledgers[0]
    assert ledger.propagated_value == 0.0
    assert ledger.dropped_value == pytest.approx(0.5)
    assert ledger.unallocated_value == 0.0
    assert ledger.conservation_residual == pytest.approx(0.0)


def test_blocked_relation_produces_no_credit_and_explicit_root_abstention() -> None:
    policies = tuple(project_relation_policies_v0())
    result = propagate(
        graph(
            (node(A), node(B)),
            (edge(EDGE_AB, A, B, relation="followed_by"),),
        ),
        policies=policies,
    )

    assert result.contributions == ()
    assert result.blocked[0].reason is PropagationBlockReason.RELATION_BLOCKED
    assert (
        result.abstentions[0].reason
        is ProvenanceCreditAbstentionReason.NO_ADMISSIBLE_PATH
    )
    assert result.mass_ledgers[0].unallocated_value == pytest.approx(0.5)


def test_unknown_relation_policy_fails_closed_without_implicit_semantics() -> None:
    result = propagate(
        graph(
            (node(A), node(B)),
            (edge(EDGE_AB, A, B, relation="mysterious_relation"),),
        ),
        policies=(),
    )

    assert result.contributions == ()
    assert result.blocked[0].reason is PropagationBlockReason.POLICY_MISSING


def test_unauthorized_edge_target_is_blocked_and_other_edges_receive_full_share() -> None:
    result = propagate(
        graph(
            (node(A), node(B, authorized=False), node(C)),
            (
                edge(EDGE_AB, A, B),
                edge(EDGE_AC, A, C),
            ),
        )
    )

    assert result.contributions[0].target_memory_id == C
    assert result.contributions[0].propagated_value == pytest.approx(0.5)
    assert result.blocked[0].target_memory_id == B
    assert result.blocked[0].reason is PropagationBlockReason.TARGET_UNAUTHORIZED


def test_invalid_target_is_a_hard_gate() -> None:
    result = propagate(
        graph(
            (node(A), node(B, currently_valid=False)),
            (edge(EDGE_AB, A, B),),
        )
    )

    assert result.contributions == ()
    assert result.blocked[0].reason is PropagationBlockReason.TARGET_INVALID


def test_supported_cycle_fails_closed_before_propagation() -> None:
    cyclic = graph(
        (node(A), node(B)),
        (
            edge(EDGE_AB, A, B),
            edge(EDGE_AC, B, A),
        ),
    )

    with pytest.raises(ProvenanceCreditValidationError, match="cycle"):
        propagate(cyclic)


def test_negative_credit_is_disabled_by_default() -> None:
    result = propagate(
        graph((node(A), node(B)), (edge(EDGE_AB, A, B),)),
        credits=(direct(value=-1.0),),
    )

    assert result.contributions == ()
    assert (
        result.abstentions[0].reason
        is ProvenanceCreditAbstentionReason.NEGATIVE_PROPAGATION_DISABLED
    )
    assert result.mass_ledgers[0].propagation_budget == -0.0


def test_negative_credit_requires_explicit_local_attribution_evidence() -> None:
    policy = supported_policy(
        allow_negative=True,
        requires_local_attribution=True,
    )
    config = PropagationConfig(negative_budget_fraction=0.25)

    blocked = propagate(
        graph((node(A), node(B)), (edge(EDGE_AB, A, B),)),
        credits=(direct(value=-1.0),),
        policies=(policy,),
        config=config,
    )
    assert blocked.contributions == ()
    assert (
        blocked.blocked[0].reason
        is PropagationBlockReason.LOCAL_ATTRIBUTION_REQUIRED
    )

    allowed = propagate(
        graph(
            (node(A), node(B)),
            (
                edge(
                    EDGE_AB,
                    A,
                    B,
                    local_attribution=0.8,
                    evidence_id=EVIDENCE_ID,
                ),
            ),
        ),
        credits=(direct(value=-1.0),),
        policies=(policy,),
        config=config,
    )
    assert allowed.contributions[0].propagated_value == pytest.approx(-0.25)
    assert allowed.mass_ledgers[0].conservation_residual == pytest.approx(0.0)


def test_direct_root_never_receives_inherited_credit() -> None:
    result = propagate(
        graph(
            (node(A), node(B)),
            (edge(EDGE_AB, A, B),),
        )
    )

    assert all(item.target_memory_id != A for item in result.contributions)
    assert result.direct_credits[0].root_memory_id == A


def test_result_is_deterministic_and_json_is_byte_identical_under_input_permutation() -> None:
    policies = tuple(reversed(project_relation_policies_v0()))
    first_graph = graph(
        (node(D), node(C), node(B), node(A)),
        (
            edge(EDGE_CD, C, D),
            edge(EDGE_BD, B, D),
            edge(EDGE_AC, A, C),
            edge(EDGE_AB, A, B),
        ),
    )
    second_graph = graph(
        (node(A), node(B), node(C), node(D)),
        (
            edge(EDGE_AB, A, B),
            edge(EDGE_AC, A, C),
            edge(EDGE_BD, B, D),
            edge(EDGE_CD, C, D),
        ),
    )

    first = propagate(first_graph, policies=policies)
    second = propagate(second_graph, policies=tuple(project_relation_policies_v0()))

    assert first == second
    assert first.render_json() == second.render_json()
    payload = json.loads(first.render_json())
    assert payload["schema"] == "nextgen-memory-provenance-credit-v0"
    assert payload["direct_credits"][0]["root_memory_id"] == str(A)
    assert "content" not in first.render_json().lower()
    assert "query" not in first.render_json().lower()
