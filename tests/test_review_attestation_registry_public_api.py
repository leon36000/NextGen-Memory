from __future__ import annotations

import importlib

from nextgen_memory.review_attestation_registry import (
    ExactShaReviewAttestation,
    ExactShaReviewRequest,
    InMemoryExactShaReviewAttestationRegistry,
    ReviewAdvisoryState,
    ReviewAttestationConflictError,
    ReviewAttestationDecision,
    ReviewAttestationRegistrySummary,
    ReviewAttestationStateError,
    ReviewAttestationValidationError,
    ReviewAttestationVerdict,
    ReviewerIdentity,
    ReviewFindingCode,
    ReviewModel,
)


def test_review_attestation_registry_contract_is_exported_from_package_root() -> None:
    nextgen_memory = importlib.import_module("nextgen_memory")
    expected = {
        "ExactShaReviewAttestation": ExactShaReviewAttestation,
        "ExactShaReviewRequest": ExactShaReviewRequest,
        "InMemoryExactShaReviewAttestationRegistry": (
            InMemoryExactShaReviewAttestationRegistry
        ),
        "ReviewAdvisoryState": ReviewAdvisoryState,
        "ReviewAttestationConflictError": ReviewAttestationConflictError,
        "ReviewAttestationDecision": ReviewAttestationDecision,
        "ReviewAttestationRegistrySummary": ReviewAttestationRegistrySummary,
        "ReviewAttestationStateError": ReviewAttestationStateError,
        "ReviewAttestationValidationError": ReviewAttestationValidationError,
        "ReviewAttestationVerdict": ReviewAttestationVerdict,
        "ReviewFindingCode": ReviewFindingCode,
        "ReviewerIdentity": ReviewerIdentity,
        "ReviewModel": ReviewModel,
    }

    for name, value in expected.items():
        assert getattr(nextgen_memory, name) is value
        assert nextgen_memory.__all__.count(name) == 1
