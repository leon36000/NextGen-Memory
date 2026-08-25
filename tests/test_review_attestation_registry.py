from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest
from nextgen_memory.review_attestation_registry import (
    ExactShaReviewAttestation,
    ExactShaReviewRequest,
    InMemoryExactShaReviewAttestationRegistry,
    ReviewAdvisoryState,
    ReviewAttestationConflictError,
    ReviewAttestationStateError,
    ReviewAttestationValidationError,
    ReviewAttestationVerdict,
    ReviewerIdentity,
    ReviewFindingCode,
    ReviewModel,
)

BASE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
REVIEWER_A = "a" * 64
REVIEWER_B = "b" * 64
REVIEWER_C = "c" * 64
REVIEWER_D = "d" * 64


def reviewer(fingerprint: str = REVIEWER_A) -> ReviewerIdentity:
    return ReviewerIdentity(
        model=ReviewModel.GPT_5_6_SOL,
        reviewer_key_fingerprint=fingerprint,
    )


def request(**overrides: object) -> ExactShaReviewRequest:
    values: dict[str, object] = {
        "repository": "leon36000/NextGen-Memory",
        "pull_request_number": 172,
        "base_sha": BASE_SHA,
        "candidate_sha": CANDIDATE_SHA,
        "diff_sha256": "3" * 64,
        "review_packet_sha256": "4" * 64,
        "acceptance_criteria_sha256": "5" * 64,
        "required_model": ReviewModel.GPT_5_6_SOL,
        "trusted_reviewer_fingerprints": (
            REVIEWER_A,
            REVIEWER_B,
            REVIEWER_C,
        ),
        "minimum_approvals": 2,
    }
    values.update(overrides)
    return ExactShaReviewRequest(**values)  # type: ignore[arg-type]


def attestation(
    review_request: ExactShaReviewRequest,
    *,
    fingerprint: str = REVIEWER_A,
    verdict: ReviewAttestationVerdict = ReviewAttestationVerdict.APPROVE,
    findings: object = (),
    suffix: str = "6",
    **overrides: object,
) -> ExactShaReviewAttestation:
    values: dict[str, object] = {
        "request_id": review_request.id,
        "request_content_hash": review_request.content_hash,
        "repository": review_request.repository,
        "pull_request_number": review_request.pull_request_number,
        "candidate_sha": review_request.candidate_sha,
        "reviewer": reviewer(fingerprint),
        "verdict": verdict,
        "finding_codes": findings,
        "review_artifact_sha256": suffix * 64,
        "evidence_artifact_sha256s": ("7" * 64, "8" * 64),
        "authenticated_envelope_sha256": suffix * 64,
    }
    values.update(overrides)
    return ExactShaReviewAttestation(**values)  # type: ignore[arg-type]


def approve(
    registry: InMemoryExactShaReviewAttestationRegistry,
    review_request: ExactShaReviewRequest,
    fingerprint: str,
    suffix: str,
) -> ExactShaReviewAttestation:
    return registry.record_attestation(
        attestation(review_request, fingerprint=fingerprint, suffix=suffix)
    )


def test_pending_approved_evidence_blocked_and_blocked_precedence() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(
        request(
            trusted_reviewer_fingerprints=(
                REVIEWER_A,
                REVIEWER_B,
                REVIEWER_C,
                REVIEWER_D,
            )
        )
    )
    assert registry.decision(review_request.id).state is ReviewAdvisoryState.PENDING

    approve(registry, review_request, REVIEWER_A, "a")
    assert registry.decision(review_request.id).state is ReviewAdvisoryState.PENDING

    approve(registry, review_request, REVIEWER_B, "b")
    assert registry.decision(review_request.id).state is ReviewAdvisoryState.APPROVED

    registry.record_attestation(
        attestation(
            review_request,
            fingerprint=REVIEWER_C,
            verdict=ReviewAttestationVerdict.BLOCKED_BY_EVIDENCE,
            findings=(ReviewFindingCode.MISSING_ARTIFACT,),
            suffix="c",
        )
    )
    assert registry.decision(review_request.id).state is ReviewAdvisoryState.EVIDENCE_BLOCKED

    registry.record_attestation(
        attestation(
            review_request,
            fingerprint=REVIEWER_D,
            verdict=ReviewAttestationVerdict.CHANGES_REQUIRED,
            findings=(ReviewFindingCode.CONTRACT_VIOLATION,),
            suffix="d",
        )
    )
    summary = registry.summary(review_request.id)
    assert summary.registered_attestation_count == 4
    assert summary.approval_count == 2
    assert summary.evidence_blocked_count == 1
    assert summary.changes_required_count == 1
    assert registry.decision(review_request.id).state is ReviewAdvisoryState.BLOCKED


def test_request_and_attestation_exact_retries_are_idempotent() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = request()
    assert registry.register_request(review_request) is review_request
    assert registry.register_request(review_request) is review_request

    value = attestation(review_request)
    assert registry.record_attestation(value) is value
    assert registry.record_attestation(value) is value
    assert registry.attestations(review_request.id) == (value,)


def test_changed_request_or_reviewer_retry_conflicts_without_mutation() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(request())
    value = registry.record_attestation(attestation(review_request))
    before = registry.summary(review_request.id)

    with pytest.raises(ReviewAttestationConflictError, match="request key conflict"):
        registry.register_request(request(review_packet_sha256="f" * 64))
    with pytest.raises(
        ReviewAttestationConflictError,
        match="reviewer attestation conflict",
    ):
        registry.record_attestation(attestation(review_request, review_artifact_sha256="f" * 64))

    assert registry.summary(review_request.id) == before
    assert registry.attestations(review_request.id) == (value,)


@pytest.mark.parametrize(
    ("overrides", "error_type", "match"),
    [
        (
            {"request_content_hash": "f" * 64},
            ReviewAttestationValidationError,
            "request content hash",
        ),
        (
            {"repository": "other/repository"},
            ReviewAttestationValidationError,
            "repository",
        ),
        (
            {"pull_request_number": 173},
            ReviewAttestationValidationError,
            "pull request",
        ),
        (
            {"candidate_sha": "3" * 40},
            ReviewAttestationValidationError,
            "candidate SHA",
        ),
        (
            {"reviewer": reviewer(REVIEWER_D)},
            ReviewAttestationValidationError,
            "trusted reviewer",
        ),
        (
            {"request_id": UUID("00000000-0000-5000-8000-000000000999")},
            ReviewAttestationStateError,
            "not registered",
        ),
    ],
)
def test_wrong_bindings_fail_before_mutation(
    overrides: dict[str, object],
    error_type: type[Exception],
    match: str,
) -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(request())
    before = registry.summary(review_request.id)

    with pytest.raises(error_type, match=match):
        registry.record_attestation(attestation(review_request, **overrides))

    assert registry.summary(review_request.id) == before
    assert registry.attestations(review_request.id) == ()


def test_unknown_request_read_methods_fail_closed() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    unknown = UUID("00000000-0000-5000-8000-000000000999")
    for operation in (
        registry.get_request,
        registry.attestations,
        registry.summary,
        registry.decision,
    ):
        with pytest.raises(ReviewAttestationStateError, match="not registered"):
            operation(unknown)


@pytest.mark.parametrize(
    ("verdict", "findings", "valid"),
    [
        (ReviewAttestationVerdict.APPROVE, (), True),
        (
            ReviewAttestationVerdict.APPROVE,
            (ReviewFindingCode.CONTRACT_VIOLATION,),
            False,
        ),
        (ReviewAttestationVerdict.CHANGES_REQUIRED, (), False),
        (
            ReviewAttestationVerdict.CHANGES_REQUIRED,
            (ReviewFindingCode.MISSING_ARTIFACT,),
            False,
        ),
        (
            ReviewAttestationVerdict.CHANGES_REQUIRED,
            (ReviewFindingCode.CONTRACT_VIOLATION,),
            True,
        ),
        (ReviewAttestationVerdict.BLOCKED_BY_EVIDENCE, (), False),
        (
            ReviewAttestationVerdict.BLOCKED_BY_EVIDENCE,
            (ReviewFindingCode.CONTRACT_VIOLATION,),
            False,
        ),
        (
            ReviewAttestationVerdict.BLOCKED_BY_EVIDENCE,
            (ReviewFindingCode.MISSING_ARTIFACT,),
            True,
        ),
    ],
)
def test_verdict_and_finding_compatibility(
    verdict: ReviewAttestationVerdict,
    findings: tuple[ReviewFindingCode, ...],
    valid: bool,
) -> None:
    review_request = request()
    if valid:
        value = attestation(
            review_request,
            verdict=verdict,
            findings=findings,
        )
        assert value.verdict is verdict
    else:
        with pytest.raises(ReviewAttestationValidationError, match="verdict"):
            attestation(
                review_request,
                verdict=verdict,
                findings=findings,
            )


@pytest.mark.parametrize(
    "overrides",
    [
        {"repository": ""},
        {"repository": " owner/repo"},
        {"repository": "owner/repo "},
        {"repository": "owner"},
        {"repository": "owner/repo/extra"},
        {"repository": "owner/repo path"},
        {"pull_request_number": True},
        {"pull_request_number": 0},
        {"base_sha": "A" * 40},
        {"base_sha": "1" * 39},
        {"candidate_sha": BASE_SHA},
        {"candidate_sha": "g" * 40},
        {"diff_sha256": "A" * 64},
        {"review_packet_sha256": "4" * 63},
        {"acceptance_criteria_sha256": "z" * 64},
        {"required_model": "gpt-5.6-sol"},
        {"trusted_reviewer_fingerprints": ()},
        {"trusted_reviewer_fingerprints": (REVIEWER_A, REVIEWER_A)},
        {"minimum_approvals": True},
        {"minimum_approvals": 0},
        {"minimum_approvals": 4},
    ],
)
def test_request_rejects_malformed_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ReviewAttestationValidationError):
        request(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"request_id": "not-a-uuid"},
        {"request_content_hash": "A" * 64},
        {"repository": "invalid"},
        {"pull_request_number": True},
        {"candidate_sha": "2" * 39},
        {"reviewer": object()},
        {"verdict": "APPROVE"},
        {"finding_codes": (ReviewFindingCode.MISSING_ARTIFACT,) * 2},
        {"review_artifact_sha256": "A" * 64},
        {"evidence_artifact_sha256s": ()},
        {"evidence_artifact_sha256s": ("7" * 64, "7" * 64)},
        {"authenticated_envelope_sha256": "9" * 63},
    ],
)
def test_attestation_rejects_malformed_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ReviewAttestationValidationError):
        attestation(request(), **overrides)


class GuardedHashes:
    def __init__(self) -> None:
        self.pulls = 0

    def __iter__(self) -> GuardedHashes:
        return self

    def __next__(self) -> str:
        self.pulls += 1
        if self.pulls <= 65:
            return f"{self.pulls:064x}"
        raise AssertionError("hash iterator was consumed beyond limit plus one")


class GuardedFindings:
    def __init__(self) -> None:
        self.pulls = 0

    def __iter__(self) -> GuardedFindings:
        return self

    def __next__(self) -> ReviewFindingCode:
        self.pulls += 1
        if self.pulls <= 33:
            return ReviewFindingCode.CONTRACT_VIOLATION
        raise AssertionError("finding iterator was consumed beyond limit plus one")


def test_collection_iterators_are_hard_bounded() -> None:
    trusted = GuardedHashes()
    with pytest.raises(ReviewAttestationValidationError, match="trusted reviewers"):
        request(trusted_reviewer_fingerprints=trusted)
    assert trusted.pulls == 65

    evidence = GuardedHashes()
    with pytest.raises(ReviewAttestationValidationError, match="evidence artifacts"):
        attestation(request(), evidence_artifact_sha256s=evidence)
    assert evidence.pulls == 65

    findings = GuardedFindings()
    with pytest.raises(ReviewAttestationValidationError, match="finding codes"):
        attestation(
            request(),
            verdict=ReviewAttestationVerdict.CHANGES_REQUIRED,
            findings=findings,
        )
    assert findings.pulls == 33


def test_collection_permutations_are_identity_invariant() -> None:
    first_request = request(trusted_reviewer_fingerprints=(REVIEWER_A, REVIEWER_B, REVIEWER_C))
    second_request = request(trusted_reviewer_fingerprints={REVIEWER_C, REVIEWER_A, REVIEWER_B})
    assert first_request == second_request

    first = attestation(
        first_request,
        verdict=ReviewAttestationVerdict.CHANGES_REQUIRED,
        findings=(
            ReviewFindingCode.TEST_FAILURE,
            ReviewFindingCode.CONTRACT_VIOLATION,
        ),
        evidence_artifact_sha256s=("7" * 64, "8" * 64),
    )
    second = attestation(
        second_request,
        verdict=ReviewAttestationVerdict.CHANGES_REQUIRED,
        findings={
            ReviewFindingCode.CONTRACT_VIOLATION,
            ReviewFindingCode.TEST_FAILURE,
        },
        evidence_artifact_sha256s={"8" * 64, "7" * 64},
    )
    assert first == second


def test_material_changes_change_identity() -> None:
    review_request = request()
    changed_request = request(diff_sha256="f" * 64)
    value = attestation(review_request)
    changed_value = attestation(review_request, review_artifact_sha256="f" * 64)

    assert changed_request.id != review_request.id
    assert changed_request.content_hash != review_request.content_hash
    assert changed_value.id != value.id
    assert changed_value.content_hash != value.content_hash


def test_public_values_are_frozen_and_canonical() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(request())
    value = registry.record_attestation(attestation(review_request))
    summary = registry.summary(review_request.id)
    decision = registry.decision(review_request.id)

    for item in (reviewer(), review_request, value, summary, decision):
        raw = item.render_json()
        assert raw == (
            json.dumps(
                json.loads(raw),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        assert not hasattr(item, "__dict__")

    with pytest.raises((AttributeError, FrozenInstanceError)):
        decision.content_hash = "0" * 64  # type: ignore[misc]
    assert replace(review_request, diff_sha256="f" * 64).id != review_request.id
