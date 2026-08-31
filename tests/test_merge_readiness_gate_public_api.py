from __future__ import annotations

import importlib

_merge_gate = importlib.import_module("nextgen_memory.merge_readiness_gate")
ExactReviewReadinessEvidence = _merge_gate.ExactReviewReadinessEvidence
ExactShaMergeReadinessGate = _merge_gate.ExactShaMergeReadinessGate
MergeCandidateIdentity = _merge_gate.MergeCandidateIdentity
MergeDependencyIdentity = _merge_gate.MergeDependencyIdentity
MergeDependencyReadiness = _merge_gate.MergeDependencyReadiness
MergeReadinessConfig = _merge_gate.MergeReadinessConfig
MergeReadinessReason = _merge_gate.MergeReadinessReason
MergeReadinessRecord = _merge_gate.MergeReadinessRecord
MergeReadinessRequest = _merge_gate.MergeReadinessRequest
MergeReadinessState = _merge_gate.MergeReadinessState
MergeReadinessValidationError = _merge_gate.MergeReadinessValidationError
MergeVerificationEvidence = _merge_gate.MergeVerificationEvidence


def test_merge_readiness_gate_contract_is_exported_from_package_root() -> None:
    nextgen_memory = importlib.import_module("nextgen_memory")
    expected = {
        "ExactReviewReadinessEvidence": ExactReviewReadinessEvidence,
        "ExactShaMergeReadinessGate": ExactShaMergeReadinessGate,
        "MergeCandidateIdentity": MergeCandidateIdentity,
        "MergeDependencyIdentity": MergeDependencyIdentity,
        "MergeDependencyReadiness": MergeDependencyReadiness,
        "MergeReadinessConfig": MergeReadinessConfig,
        "MergeReadinessReason": MergeReadinessReason,
        "MergeReadinessRecord": MergeReadinessRecord,
        "MergeReadinessRequest": MergeReadinessRequest,
        "MergeReadinessState": MergeReadinessState,
        "MergeReadinessValidationError": MergeReadinessValidationError,
        "MergeVerificationEvidence": MergeVerificationEvidence,
    }

    for name, value in expected.items():
        assert getattr(nextgen_memory, name) is value
        assert nextgen_memory.__all__.count(name) == 1
