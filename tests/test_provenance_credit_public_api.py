from __future__ import annotations

import nextgen_memory
from nextgen_memory.provenance_credit import (
    BlockedPropagation,
    ConservativeProvenancePropagator,
    CreditSourceKind,
    DirectCreditEvidence,
    PropagatedCreditContribution,
    PropagatedTargetCredit,
    PropagationBlockReason,
    PropagationConfig,
    PropagationDirection,
    PropagationMassLedger,
    ProvenanceCreditAbstention,
    ProvenanceCreditAbstentionReason,
    ProvenanceCreditResult,
    ProvenanceCreditValidationError,
    ProvenanceEdge,
    ProvenanceNode,
    ProvenanceRelationPolicy,
    TypedProvenanceGraph,
    project_relation_policies_v0,
    select_preferred_direct_credits,
)


def test_package_exports_stable_provenance_credit_v0_api() -> None:
    expected = {
        "BlockedPropagation": BlockedPropagation,
        "ConservativeProvenancePropagator": ConservativeProvenancePropagator,
        "CreditSourceKind": CreditSourceKind,
        "DirectCreditEvidence": DirectCreditEvidence,
        "PropagatedCreditContribution": PropagatedCreditContribution,
        "PropagatedTargetCredit": PropagatedTargetCredit,
        "PropagationBlockReason": PropagationBlockReason,
        "PropagationConfig": PropagationConfig,
        "PropagationDirection": PropagationDirection,
        "PropagationMassLedger": PropagationMassLedger,
        "ProvenanceCreditAbstention": ProvenanceCreditAbstention,
        "ProvenanceCreditAbstentionReason": ProvenanceCreditAbstentionReason,
        "ProvenanceCreditResult": ProvenanceCreditResult,
        "ProvenanceCreditValidationError": ProvenanceCreditValidationError,
        "ProvenanceEdge": ProvenanceEdge,
        "ProvenanceNode": ProvenanceNode,
        "ProvenanceRelationPolicy": ProvenanceRelationPolicy,
        "TypedProvenanceGraph": TypedProvenanceGraph,
        "project_relation_policies_v0": project_relation_policies_v0,
        "select_preferred_direct_credits": select_preferred_direct_credits,
    }

    for name, value in expected.items():
        assert getattr(nextgen_memory, name) is value
        assert name in nextgen_memory.__all__
