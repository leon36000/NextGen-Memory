from __future__ import annotations

import nextgen_memory
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


def test_package_exports_stable_inherited_credit_ledger_v0_api() -> None:
    expected = {
        "INHERITED_ACCOUNTING_INSERT_SQL": INHERITED_ACCOUNTING_INSERT_SQL,
        "INHERITED_ACCOUNTING_SELECT_SQL": INHERITED_ACCOUNTING_SELECT_SQL,
        "INHERITED_CONTRIBUTION_INSERT_SQL": INHERITED_CONTRIBUTION_INSERT_SQL,
        "INHERITED_CONTRIBUTION_SELECT_SQL": INHERITED_CONTRIBUTION_SELECT_SQL,
        "INHERITED_EVALUATION_INSERT_SQL": INHERITED_EVALUATION_INSERT_SQL,
        "INHERITED_EVALUATION_SELECT_SQL": INHERITED_EVALUATION_SELECT_SQL,
        "INHERITED_OBSERVATION_INSERT_SQL": INHERITED_OBSERVATION_INSERT_SQL,
        "INHERITED_OBSERVATION_SELECT_SQL": INHERITED_OBSERVATION_SELECT_SQL,
        "InheritedCreditContributionRecord": InheritedCreditContributionRecord,
        "ProvenanceCreditAccountingRecord": ProvenanceCreditAccountingRecord,
        "ProvenanceCreditBatch": ProvenanceCreditBatch,
        "ProvenanceCreditEvaluationRecord": ProvenanceCreditEvaluationRecord,
        "ProvenanceCreditObservationRecord": ProvenanceCreditObservationRecord,
        "ProvenanceCreditPersistenceConflictError": ProvenanceCreditPersistenceConflictError,
        "ProvenanceCreditPersistenceValidationError": ProvenanceCreditPersistenceValidationError,
        "ProvenanceCreditPersistenceWriter": ProvenanceCreditPersistenceWriter,
        "build_provenance_credit_batch": build_provenance_credit_batch,
        "fingerprint_provenance_graph": fingerprint_provenance_graph,
        "fingerprint_provenance_policy": fingerprint_provenance_policy,
    }

    for name, value in expected.items():
        assert getattr(nextgen_memory, name) is value
        assert name in nextgen_memory.__all__
