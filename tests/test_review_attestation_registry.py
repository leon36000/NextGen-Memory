from __future__ import annotations

import importlib
import json
from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

_review_attestation_registry = importlib.import_module("nextgen_memory.review_attestation_registry")
ExactShaReviewAttestation = _review_attestation_registry.ExactShaReviewAttestation
ExactShaReviewRequest = _review_attestation_registry.ExactShaReviewRequest
InMemoryExactShaReviewAttestationRegistry = (
    _review_attestation_registry.InMemoryExactShaReviewAttestationRegistry
)
ReviewAdvisoryState = _review_attestation_registry.ReviewAdvisoryState
ReviewAttestationConflictError = _review_attestation_registry.ReviewAttestationConflictError
ReviewAttestationStateError = _review_attestation_registry.ReviewAttestationStateError
ReviewAttestationValidationError = _review_attestation_registry.ReviewAttestationValidationError
ReviewAttestationVerdict = _review_attestation_registry.ReviewAttestationVerdict
ReviewerIdentity = _review_attestation_registry.ReviewerIdentity
ReviewFindingCode = _review_attestation_registry.ReviewFindingCode
ReviewModel = _review_attestation_registry.ReviewModel

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


class ExplodingCollection:
    def __iter__(self) -> ExplodingCollection:
        return self

    def __next__(self) -> object:
        raise RuntimeError("SECRET-ITERATOR-SENTINEL")


class RawPayloadReviewer(ReviewerIdentity):
    def to_dict(self) -> dict[str, object]:
        return {"raw_review": "SECRET-REVIEW-SENTINEL"}


class RequestSubclass(ExactShaReviewRequest):
    pass


class AttestationSubclass(ExactShaReviewAttestation):
    pass


class ExplosiveRepository(str):
    def strip(self, chars: str | None = None) -> str:
        del chars
        raise RuntimeError("SECRET-REPOSITORY-SENTINEL")


class ExplosiveInteger(int):
    def __le__(self, other: object) -> bool:
        del other
        raise RuntimeError("SECRET-INTEGER-SENTINEL")


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (
            lambda: request(trusted_reviewer_fingerprints=ExplodingCollection()),
            "trusted reviewers must be a bounded iterable",
        ),
        (
            lambda: attestation(
                request(),
                verdict=ReviewAttestationVerdict.CHANGES_REQUIRED,
                findings=ExplodingCollection(),
            ),
            "finding codes must be a bounded iterable",
        ),
        (
            lambda: attestation(
                request(),
                evidence_artifact_sha256s=ExplodingCollection(),
            ),
            "evidence artifacts must be a bounded iterable",
        ),
    ],
)
def test_collection_iteration_failures_are_bounded_and_privacy_safe(
    factory: object,
    message: str,
) -> None:
    with pytest.raises(ReviewAttestationValidationError) as caught:
        factory()  # type: ignore[operator]
    assert str(caught.value) == message
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "SECRET" not in str(caught.value)


def test_reviewer_subclass_cannot_inject_raw_payload() -> None:
    review_request = request()
    malicious = RawPayloadReviewer(
        model=ReviewModel.GPT_5_6_SOL,
        reviewer_key_fingerprint=REVIEWER_A,
    )
    with pytest.raises(
        ReviewAttestationValidationError,
        match="reviewer must be an exact ReviewerIdentity",
    ):
        attestation(review_request, reviewer=malicious)


def test_registry_rejects_contract_subclasses_before_mutation() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = request()
    request_subclass = RequestSubclass(
        repository=review_request.repository,
        pull_request_number=review_request.pull_request_number,
        base_sha=review_request.base_sha,
        candidate_sha=review_request.candidate_sha,
        diff_sha256=review_request.diff_sha256,
        review_packet_sha256=review_request.review_packet_sha256,
        acceptance_criteria_sha256=(review_request.acceptance_criteria_sha256),
        required_model=review_request.required_model,
        trusted_reviewer_fingerprints=(review_request.trusted_reviewer_fingerprints),
        minimum_approvals=review_request.minimum_approvals,
    )
    with pytest.raises(
        ReviewAttestationValidationError,
        match="request must be an exact ExactShaReviewRequest",
    ):
        registry.register_request(request_subclass)
    with pytest.raises(ReviewAttestationStateError):
        registry.get_request(review_request.id)

    registry.register_request(review_request)
    value = attestation(review_request)
    attestation_subclass = AttestationSubclass(
        request_id=value.request_id,
        request_content_hash=value.request_content_hash,
        repository=value.repository,
        pull_request_number=value.pull_request_number,
        candidate_sha=value.candidate_sha,
        reviewer=value.reviewer,
        verdict=value.verdict,
        finding_codes=value.finding_codes,
        review_artifact_sha256=value.review_artifact_sha256,
        evidence_artifact_sha256s=value.evidence_artifact_sha256s,
        authenticated_envelope_sha256=(value.authenticated_envelope_sha256),
    )
    with pytest.raises(
        ReviewAttestationValidationError,
        match=("attestation must be an exact ExactShaReviewAttestation"),
    ):
        registry.record_attestation(attestation_subclass)
    assert registry.attestations(review_request.id) == ()


def test_primitive_subclasses_are_rejected_before_overridden_behavior() -> None:
    with pytest.raises(
        ReviewAttestationValidationError,
        match="repository is invalid",
    ) as repository_error:
        request(repository=ExplosiveRepository("leon36000/NextGen-Memory"))
    assert repository_error.value.__context__ is None

    with pytest.raises(
        ReviewAttestationValidationError,
        match=("pull request number must be a positive integer"),
    ) as integer_error:
        request(pull_request_number=ExplosiveInteger(172))
    assert integer_error.value.__context__ is None


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
    approve(registry, review_request, REVIEWER_A, "a")
    assert registry.decision(review_request.id).state is ReviewAdvisoryState.PENDING
    object.__setattr__(review_request, "minimum_approvals", 1)
    assert_integrity_rejection(lambda: registry.decision(review_request.id))


def test_reviewer_tampering_is_rejected_before_attestation_identity_is_built() -> None:
    review_request = request()
    identity = reviewer(REVIEWER_A)
    original_hash = identity.content_hash
    object.__setattr__(identity, "reviewer_key_fingerprint", REVIEWER_B)
    assert identity.content_hash == original_hash
    assert_integrity_rejection(lambda: attestation(review_request, reviewer=identity))


def test_attestation_tampering_before_record_is_rejected() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(request(minimum_approvals=1))
    value = attestation(review_request, suffix="a")
    original_hash = value.content_hash
    original_id = value.id
    object.__setattr__(value, "verdict", ReviewAttestationVerdict.CHANGES_REQUIRED)
    object.__setattr__(
        value,
        "finding_codes",
        (ReviewFindingCode.CONTRACT_VIOLATION,),
    )
    assert value.content_hash == original_hash
    assert value.id == original_id
    assert_integrity_rejection(lambda: registry.record_attestation(value))
    assert registry.attestations(review_request.id) == ()


def test_attestation_tampering_after_record_cannot_rewrite_registry_history() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(request(minimum_approvals=1))
    value = approve(registry, review_request, REVIEWER_A, "a")
    assert registry.decision(review_request.id).state is ReviewAdvisoryState.APPROVED
    object.__setattr__(value, "verdict", ReviewAttestationVerdict.CHANGES_REQUIRED)
    object.__setattr__(
        value,
        "finding_codes",
        (ReviewFindingCode.CONTRACT_VIOLATION,),
    )
    assert_integrity_rejection(lambda: registry.decision(review_request.id))
