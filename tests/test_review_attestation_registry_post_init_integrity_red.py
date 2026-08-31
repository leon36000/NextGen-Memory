from __future__ import annotations

import hashlib

import pytest

from nextgen_memory import (
    ExactShaReviewAttestation,
    ExactShaReviewRequest,
    InMemoryExactShaReviewAttestationRegistry,
    ReviewAdvisoryState,
    ReviewAttestationValidationError,
    ReviewAttestationVerdict,
    ReviewerIdentity,
    ReviewFindingCode,
    ReviewModel,
)

REVIEWER_A = "a" * 64
REVIEWER_B = "b" * 64


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def request(*, minimum_approvals: int = 2) -> ExactShaReviewRequest:
    return ExactShaReviewRequest(
        repository="leon36000/NextGen-Memory",
        pull_request_number=185,
        base_sha="1" * 40,
        candidate_sha="2" * 40,
        diff_sha256=digest("diff"),
        review_packet_sha256=digest("packet"),
        acceptance_criteria_sha256=digest("criteria"),
        required_model=ReviewModel.GPT_5_6_SOL,
        trusted_reviewer_fingerprints=(REVIEWER_A, REVIEWER_B),
        minimum_approvals=minimum_approvals,
    )


def reviewer(fingerprint: str) -> ReviewerIdentity:
    return ReviewerIdentity(
        model=ReviewModel.GPT_5_6_SOL,
        reviewer_key_fingerprint=fingerprint,
    )


def approve(
    review_request: ExactShaReviewRequest,
    fingerprint: str,
    suffix: str,
) -> ExactShaReviewAttestation:
    return ExactShaReviewAttestation(
        request_id=review_request.id,
        request_content_hash=review_request.content_hash,
        repository=review_request.repository,
        pull_request_number=review_request.pull_request_number,
        candidate_sha=review_request.candidate_sha,
        reviewer=reviewer(fingerprint),
        verdict=ReviewAttestationVerdict.APPROVE,
        finding_codes=(),
        review_artifact_sha256=digest(f"review:{suffix}"),
        evidence_artifact_sha256s=(digest(f"evidence:{suffix}"),),
        authenticated_envelope_sha256=digest(f"envelope:{suffix}"),
    )


def assert_integrity_rejection(operation: object) -> None:
    with pytest.raises(ReviewAttestationValidationError, match="integrity") as caught:
        operation()  # type: ignore[operator]
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_request_tampering_before_registration_is_rejected() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = request()
    original_hash = review_request.content_hash
    original_id = review_request.id

    object.__setattr__(review_request, "minimum_approvals", 1)

    assert review_request.content_hash == original_hash
    assert review_request.id == original_id
    assert_integrity_rejection(lambda: registry.register_request(review_request))


def test_request_tampering_after_registration_cannot_change_decision() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(request())
    registry.record_attestation(approve(review_request, REVIEWER_A, "a"))
    assert registry.decision(review_request.id).state is ReviewAdvisoryState.PENDING

    object.__setattr__(review_request, "minimum_approvals", 1)

    assert_integrity_rejection(lambda: registry.decision(review_request.id))


def test_reviewer_tampering_is_rejected_before_attestation_identity_is_built() -> None:
    review_request = request()
    identity = reviewer(REVIEWER_A)
    original_hash = identity.content_hash
    object.__setattr__(identity, "reviewer_key_fingerprint", REVIEWER_B)
    assert identity.content_hash == original_hash

    assert_integrity_rejection(
        lambda: ExactShaReviewAttestation(
            request_id=review_request.id,
            request_content_hash=review_request.content_hash,
            repository=review_request.repository,
            pull_request_number=review_request.pull_request_number,
            candidate_sha=review_request.candidate_sha,
            reviewer=identity,
            verdict=ReviewAttestationVerdict.APPROVE,
            finding_codes=(),
            review_artifact_sha256=digest("review:reviewer-tamper"),
            evidence_artifact_sha256s=(digest("evidence:reviewer-tamper"),),
            authenticated_envelope_sha256=digest("envelope:reviewer-tamper"),
        )
    )


def test_attestation_tampering_before_record_is_rejected() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(request(minimum_approvals=1))
    value = approve(review_request, REVIEWER_A, "a")
    original_hash = value.content_hash
    original_id = value.id

    object.__setattr__(value, "verdict", ReviewAttestationVerdict.CHANGES_REQUIRED)
    object.__setattr__(value, "finding_codes", (ReviewFindingCode.CONTRACT_VIOLATION,))

    assert value.content_hash == original_hash
    assert value.id == original_id
    assert_integrity_rejection(lambda: registry.record_attestation(value))
    assert registry.attestations(review_request.id) == ()


def test_attestation_tampering_after_record_cannot_rewrite_registry_history() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(request(minimum_approvals=1))
    value = registry.record_attestation(approve(review_request, REVIEWER_A, "a"))
    assert registry.decision(review_request.id).state is ReviewAdvisoryState.APPROVED

    object.__setattr__(value, "verdict", ReviewAttestationVerdict.CHANGES_REQUIRED)
    object.__setattr__(value, "finding_codes", (ReviewFindingCode.CONTRACT_VIOLATION,))

    assert_integrity_rejection(lambda: registry.decision(review_request.id))
