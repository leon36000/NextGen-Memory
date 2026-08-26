"""Pure deterministic exact-SHA review-attestation registry."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from itertools import islice
from uuid import NAMESPACE_URL, UUID, uuid5

_SCHEMA = "nextgen-memory-exact-sha-review-attestation-registry-v0"
_MAX_REPOSITORY_LENGTH = 200
_MAX_TRUSTED_REVIEWERS = 64
_MAX_FINDINGS = 32
_MAX_EVIDENCE_ARTIFACTS = 64
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class ReviewAttestationValidationError(ValueError):
    """An immutable review value or binding is invalid."""


class ReviewAttestationConflictError(RuntimeError):
    """An immutable registry key was reused with changed content."""


class ReviewAttestationStateError(RuntimeError):
    """A requested review-registry state does not exist."""


class ReviewModel(StrEnum):
    """Models accepted by the v0 review contract."""

    GPT_5_6_SOL = "gpt-5.6-sol"


class ReviewAttestationVerdict(StrEnum):
    """Bounded external review verdicts."""

    APPROVE = "APPROVE"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    BLOCKED_BY_EVIDENCE = "BLOCKED_BY_EVIDENCE"


class ReviewAdvisoryState(StrEnum):
    """Advisory aggregate review states."""

    PENDING = "pending"
    APPROVED = "approved"
    EVIDENCE_BLOCKED = "evidence_blocked"
    BLOCKED = "blocked"


class ReviewFindingCode(StrEnum):
    """Bounded defect and evidence finding codes."""

    CONTRACT_VIOLATION = "contract_violation"
    SAFETY_VIOLATION = "safety_violation"
    IDENTITY_MISMATCH = "identity_mismatch"
    TEST_FAILURE = "test_failure"
    PRIVACY_RISK = "privacy_risk"
    SIDE_EFFECT_RISK = "side_effect_risk"
    MISSING_ARTIFACT = "missing_artifact"
    ARTIFACT_INTEGRITY_UNPROVEN = "artifact_integrity_unproven"
    INCOMPLETE_TEST_MATRIX = "incomplete_test_matrix"
    STALE_OR_EXPIRED_EVIDENCE = "stale_or_expired_evidence"


_DEFECT_FINDINGS = frozenset(
    {
        ReviewFindingCode.CONTRACT_VIOLATION,
        ReviewFindingCode.SAFETY_VIOLATION,
        ReviewFindingCode.IDENTITY_MISMATCH,
        ReviewFindingCode.TEST_FAILURE,
        ReviewFindingCode.PRIVACY_RISK,
        ReviewFindingCode.SIDE_EFFECT_RISK,
    }
)
_EVIDENCE_FINDINGS = frozenset(
    {
        ReviewFindingCode.MISSING_ARTIFACT,
        ReviewFindingCode.ARTIFACT_INTEGRITY_UNPROVEN,
        ReviewFindingCode.INCOMPLETE_TEST_MATRIX,
        ReviewFindingCode.STALE_OR_EXPIRED_EVIDENCE,
    }
)


def _canonical_json(value: object) -> str:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
    except (TypeError, ValueError) as exc:
        raise ReviewAttestationValidationError("canonical review payload is invalid") from exc


def _hash_payload(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stable_uuid(kind: str, content_hash: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"nextgen-memory:{kind}-v0:{content_hash}")


def _require_repository(value: object) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > _MAX_REPOSITORY_LENGTH
        or _REPOSITORY_RE.fullmatch(value) is None
    ):
        raise ReviewAttestationValidationError("repository is invalid")
    owner, name = value.split("/", 1)
    if owner in {".", ".."} or name in {".", ".."}:
        raise ReviewAttestationValidationError("repository is invalid")
    return value


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReviewAttestationValidationError(f"{name} must be a positive integer")
    return value


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReviewAttestationValidationError(f"{name} must be a nonnegative integer")
    return value


def _require_uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise ReviewAttestationValidationError(f"{name} must be a UUID")
    return value


def _require_sha256(name: str, value: object) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ReviewAttestationValidationError(f"{name} must be a lowercase SHA-256")
    return value


def _require_git_sha(name: str, value: object) -> str:
    if not isinstance(value, str) or _GIT_SHA_RE.fullmatch(value) is None:
        raise ReviewAttestationValidationError(f"{name} must be a lowercase 40-character Git SHA")
    return value


def _require_enum[T](name: str, value: object, enum_type: type[T]) -> T:
    if not isinstance(value, enum_type):
        raise ReviewAttestationValidationError(f"{name} must use the bounded enum")
    return value


def _bounded_unique[T](
    name: str,
    values: object,
    *,
    limit: int,
    validator: Callable[[str, object], T],
    sort_key: Callable[[T], str],
    require_nonempty: bool,
) -> tuple[T, ...]:
    if isinstance(values, (str, bytes, bytearray, Mapping)):
        raise ReviewAttestationValidationError(f"{name} must be a bounded iterable")
    try:
        iterator = iter(values)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ReviewAttestationValidationError(f"{name} must be a bounded iterable") from exc
    raw = tuple(islice(iterator, limit + 1))
    if len(raw) > limit:
        raise ReviewAttestationValidationError(f"{name} exceeds its limit")
    if require_nonempty and not raw:
        raise ReviewAttestationValidationError(f"{name} must not be empty")
    normalized = tuple(validator(name, item) for item in raw)
    if len(set(normalized)) != len(normalized):
        raise ReviewAttestationValidationError(f"{name} must not contain duplicates")
    return tuple(sorted(normalized, key=sort_key))


def _require_reviewer_fingerprint(name: str, value: object) -> str:
    return _require_sha256(name, value)


def _require_finding(name: str, value: object) -> ReviewFindingCode:
    return _require_enum(name, value, ReviewFindingCode)


@dataclass(frozen=True, slots=True)
class ReviewerIdentity:
    """Bounded reviewer model and externally authenticated key fingerprint."""

    model: ReviewModel
    reviewer_key_fingerprint: str
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        model = _require_enum("reviewer model", self.model, ReviewModel)
        fingerprint = _require_reviewer_fingerprint(
            "reviewer key fingerprint", self.reviewer_key_fingerprint
        )
        object.__setattr__(self, "model", model)
        object.__setattr__(self, "reviewer_key_fingerprint", fingerprint)
        object.__setattr__(self, "content_hash", _hash_payload(self._identity_payload()))

    def _identity_payload(self) -> dict[str, object]:
        return {
            "kind": "reviewer_identity",
            "model": self.model.value,
            "reviewer_key_fingerprint": self.reviewer_key_fingerprint,
            "schema": _SCHEMA,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "content_hash": self.content_hash,
        }

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExactShaReviewRequest:
    """Immutable request for review of one exact candidate SHA."""

    repository: str
    pull_request_number: int
    base_sha: str
    candidate_sha: str
    diff_sha256: str
    review_packet_sha256: str
    acceptance_criteria_sha256: str
    required_model: ReviewModel
    trusted_reviewer_fingerprints: object
    minimum_approvals: int
    id: UUID = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        repository = _require_repository(self.repository)
        pull_request_number = _positive_integer("pull request number", self.pull_request_number)
        base_sha = _require_git_sha("base SHA", self.base_sha)
        candidate_sha = _require_git_sha("candidate SHA", self.candidate_sha)
        if base_sha == candidate_sha:
            raise ReviewAttestationValidationError("base SHA and candidate SHA must differ")
        diff_sha256 = _require_sha256("diff SHA-256", self.diff_sha256)
        review_packet_sha256 = _require_sha256("review packet SHA-256", self.review_packet_sha256)
        acceptance_criteria_sha256 = _require_sha256(
            "acceptance criteria SHA-256", self.acceptance_criteria_sha256
        )
        required_model = _require_enum("required model", self.required_model, ReviewModel)
        trusted = _bounded_unique(
            "trusted reviewers",
            self.trusted_reviewer_fingerprints,
            limit=_MAX_TRUSTED_REVIEWERS,
            validator=_require_reviewer_fingerprint,
            sort_key=lambda item: item,
            require_nonempty=True,
        )
        minimum_approvals = _positive_integer("minimum approvals", self.minimum_approvals)
        if minimum_approvals > len(trusted):
            raise ReviewAttestationValidationError("minimum approvals exceeds trusted reviewers")
        object.__setattr__(self, "repository", repository)
        object.__setattr__(self, "pull_request_number", pull_request_number)
        object.__setattr__(self, "base_sha", base_sha)
        object.__setattr__(self, "candidate_sha", candidate_sha)
        object.__setattr__(self, "diff_sha256", diff_sha256)
        object.__setattr__(self, "review_packet_sha256", review_packet_sha256)
        object.__setattr__(self, "acceptance_criteria_sha256", acceptance_criteria_sha256)
        object.__setattr__(self, "required_model", required_model)
        object.__setattr__(self, "trusted_reviewer_fingerprints", trusted)
        object.__setattr__(self, "minimum_approvals", minimum_approvals)
        content_hash = _hash_payload(self._identity_payload())
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "id", _stable_uuid("exact-sha-review-request", content_hash))

    @property
    def registry_key(self) -> tuple[str, int, str]:
        return (self.repository, self.pull_request_number, self.candidate_sha)

    def _identity_payload(self) -> dict[str, object]:
        return {
            "acceptance_criteria_sha256": self.acceptance_criteria_sha256,
            "base_sha": self.base_sha,
            "candidate_sha": self.candidate_sha,
            "diff_sha256": self.diff_sha256,
            "kind": "review_request",
            "minimum_approvals": self.minimum_approvals,
            "pull_request_number": self.pull_request_number,
            "repository": self.repository,
            "required_model": self.required_model.value,
            "review_packet_sha256": self.review_packet_sha256,
            "schema": _SCHEMA,
            "trusted_reviewer_fingerprints": list(self.trusted_reviewer_fingerprints),
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "content_hash": self.content_hash,
            "id": str(self.id),
        }

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExactShaReviewAttestation:
    """Immutable exact request-bound review attestation."""

    request_id: UUID
    request_content_hash: str
    repository: str
    pull_request_number: int
    candidate_sha: str
    reviewer: ReviewerIdentity
    verdict: ReviewAttestationVerdict
    finding_codes: object
    review_artifact_sha256: str
    evidence_artifact_sha256s: object
    authenticated_envelope_sha256: str
    id: UUID = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        request_id = _require_uuid("request id", self.request_id)
        request_content_hash = _require_sha256("request content hash", self.request_content_hash)
        repository = _require_repository(self.repository)
        pull_request_number = _positive_integer("pull request number", self.pull_request_number)
        candidate_sha = _require_git_sha("candidate SHA", self.candidate_sha)
        if not isinstance(self.reviewer, ReviewerIdentity):
            raise ReviewAttestationValidationError("reviewer must be a ReviewerIdentity")
        verdict = _require_enum("verdict", self.verdict, ReviewAttestationVerdict)
        findings = _bounded_unique(
            "finding codes",
            self.finding_codes,
            limit=_MAX_FINDINGS,
            validator=_require_finding,
            sort_key=lambda item: item.value,
            require_nonempty=False,
        )
        review_artifact_sha256 = _require_sha256(
            "review artifact SHA-256", self.review_artifact_sha256
        )
        evidence_artifacts = _bounded_unique(
            "evidence artifacts",
            self.evidence_artifact_sha256s,
            limit=_MAX_EVIDENCE_ARTIFACTS,
            validator=_require_sha256,
            sort_key=lambda item: item,
            require_nonempty=True,
        )
        authenticated_envelope_sha256 = _require_sha256(
            "authenticated envelope SHA-256", self.authenticated_envelope_sha256
        )
        defect_findings = _DEFECT_FINDINGS.intersection(findings)
        evidence_findings = _EVIDENCE_FINDINGS.intersection(findings)
        if verdict is ReviewAttestationVerdict.APPROVE and findings:
            raise ReviewAttestationValidationError("verdict APPROVE must not contain findings")
        if verdict is ReviewAttestationVerdict.CHANGES_REQUIRED and not defect_findings:
            raise ReviewAttestationValidationError(
                "verdict CHANGES_REQUIRED requires a defect finding"
            )
        if verdict is ReviewAttestationVerdict.BLOCKED_BY_EVIDENCE and (
            not evidence_findings or defect_findings
        ):
            raise ReviewAttestationValidationError(
                "verdict BLOCKED_BY_EVIDENCE requires only evidence findings"
            )
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "request_content_hash", request_content_hash)
        object.__setattr__(self, "repository", repository)
        object.__setattr__(self, "pull_request_number", pull_request_number)
        object.__setattr__(self, "candidate_sha", candidate_sha)
        object.__setattr__(self, "verdict", verdict)
        object.__setattr__(self, "finding_codes", findings)
        object.__setattr__(self, "review_artifact_sha256", review_artifact_sha256)
        object.__setattr__(self, "evidence_artifact_sha256s", evidence_artifacts)
        object.__setattr__(self, "authenticated_envelope_sha256", authenticated_envelope_sha256)
        content_hash = _hash_payload(self._identity_payload())
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(
            self,
            "id",
            _stable_uuid("exact-sha-review-attestation", content_hash),
        )

    def _identity_payload(self) -> dict[str, object]:
        return {
            "authenticated_envelope_sha256": self.authenticated_envelope_sha256,
            "candidate_sha": self.candidate_sha,
            "evidence_artifact_sha256s": list(self.evidence_artifact_sha256s),
            "finding_codes": [item.value for item in self.finding_codes],
            "kind": "review_attestation",
            "pull_request_number": self.pull_request_number,
            "repository": self.repository,
            "request_content_hash": self.request_content_hash,
            "request_id": str(self.request_id),
            "review_artifact_sha256": self.review_artifact_sha256,
            "reviewer": self.reviewer.to_dict(),
            "schema": _SCHEMA,
            "verdict": self.verdict.value,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "content_hash": self.content_hash,
            "id": str(self.id),
        }

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ReviewAttestationRegistrySummary:
    """Deterministic bounded aggregate for one registered request."""

    request_id: UUID
    request_content_hash: str
    attestation_ids: tuple[UUID, ...]
    registered_attestation_count: int
    approval_count: int
    changes_required_count: int
    evidence_blocked_count: int
    distinct_reviewer_count: int
    missing_approval_count: int
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        request_id = _require_uuid("request id", self.request_id)
        request_content_hash = _require_sha256("request content hash", self.request_content_hash)
        if not isinstance(self.attestation_ids, tuple) or any(
            not isinstance(item, UUID) for item in self.attestation_ids
        ):
            raise ReviewAttestationValidationError("attestation ids must be a UUID tuple")
        if len(set(self.attestation_ids)) != len(self.attestation_ids):
            raise ReviewAttestationValidationError("attestation ids must not contain duplicates")
        registered = _nonnegative_integer(
            "registered attestation count", self.registered_attestation_count
        )
        approval = _nonnegative_integer("approval count", self.approval_count)
        changes = _nonnegative_integer("changes required count", self.changes_required_count)
        evidence = _nonnegative_integer("evidence blocked count", self.evidence_blocked_count)
        distinct = _nonnegative_integer("distinct reviewer count", self.distinct_reviewer_count)
        missing = _nonnegative_integer("missing approval count", self.missing_approval_count)
        if len(self.attestation_ids) != registered:
            raise ReviewAttestationValidationError(
                "registered attestation count does not match ids"
            )
        if approval + changes + evidence != registered:
            raise ReviewAttestationValidationError(
                "attestation verdict counts do not partition the registry"
            )
        if distinct != registered:
            raise ReviewAttestationValidationError(
                "distinct reviewer count does not match attestations"
            )
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "request_content_hash", request_content_hash)
        object.__setattr__(self, "registered_attestation_count", registered)
        object.__setattr__(self, "approval_count", approval)
        object.__setattr__(self, "changes_required_count", changes)
        object.__setattr__(self, "evidence_blocked_count", evidence)
        object.__setattr__(self, "distinct_reviewer_count", distinct)
        object.__setattr__(self, "missing_approval_count", missing)
        object.__setattr__(self, "content_hash", _hash_payload(self._identity_payload()))

    def _identity_payload(self) -> dict[str, object]:
        return {
            "approval_count": self.approval_count,
            "attestation_ids": [str(item) for item in self.attestation_ids],
            "changes_required_count": self.changes_required_count,
            "distinct_reviewer_count": self.distinct_reviewer_count,
            "evidence_blocked_count": self.evidence_blocked_count,
            "kind": "registry_summary",
            "missing_approval_count": self.missing_approval_count,
            "registered_attestation_count": self.registered_attestation_count,
            "request_content_hash": self.request_content_hash,
            "request_id": str(self.request_id),
            "schema": _SCHEMA,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "content_hash": self.content_hash,
        }

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ReviewAttestationDecision:
    """Pure advisory decision derived from one deterministic summary."""

    request_id: UUID
    request_content_hash: str
    state: ReviewAdvisoryState
    summary_content_hash: str
    advisory_only: bool = True
    id: UUID = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        request_id = _require_uuid("request id", self.request_id)
        request_content_hash = _require_sha256("request content hash", self.request_content_hash)
        state = _require_enum("advisory state", self.state, ReviewAdvisoryState)
        summary_content_hash = _require_sha256("summary content hash", self.summary_content_hash)
        if self.advisory_only is not True:
            raise ReviewAttestationValidationError("review decision must be advisory only")
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "request_content_hash", request_content_hash)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "summary_content_hash", summary_content_hash)
        content_hash = _hash_payload(self._identity_payload())
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "id", _stable_uuid("review-attestation-decision", content_hash))

    def _identity_payload(self) -> dict[str, object]:
        return {
            "advisory_only": self.advisory_only,
            "kind": "review_decision",
            "request_content_hash": self.request_content_hash,
            "request_id": str(self.request_id),
            "schema": _SCHEMA,
            "state": self.state.value,
            "summary_content_hash": self.summary_content_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_payload(),
            "content_hash": self.content_hash,
            "id": str(self.id),
        }

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


class InMemoryExactShaReviewAttestationRegistry:
    """In-memory immutable-key registry with no I/O or activation surface."""

    __slots__ = (
        "_attestations_by_request",
        "_request_ids_by_key",
        "_requests_by_id",
    )

    def __init__(self) -> None:
        self._requests_by_id: dict[UUID, ExactShaReviewRequest] = {}
        self._request_ids_by_key: dict[tuple[str, int, str], UUID] = {}
        self._attestations_by_request: dict[UUID, dict[str, ExactShaReviewAttestation]] = {}

    def register_request(self, request: ExactShaReviewRequest) -> ExactShaReviewRequest:
        if not isinstance(request, ExactShaReviewRequest):
            raise ReviewAttestationValidationError("request must be an ExactShaReviewRequest")
        existing_id = self._request_ids_by_key.get(request.registry_key)
        if existing_id is not None:
            existing = self._requests_by_id[existing_id]
            if existing == request:
                return existing
            raise ReviewAttestationConflictError("review request key conflict")
        existing_by_id = self._requests_by_id.get(request.id)
        if existing_by_id is not None:
            if existing_by_id == request:
                return existing_by_id
            raise ReviewAttestationConflictError("review request identity conflict")
        self._requests_by_id[request.id] = request
        self._request_ids_by_key[request.registry_key] = request.id
        self._attestations_by_request[request.id] = {}
        return request

    def _require_registered_request(self, request_id: UUID) -> ExactShaReviewRequest:
        normalized_id = _require_uuid("request id", request_id)
        try:
            return self._requests_by_id[normalized_id]
        except KeyError as exc:
            raise ReviewAttestationStateError("review request is not registered") from exc

    def get_request(self, request_id: UUID) -> ExactShaReviewRequest:
        return self._require_registered_request(request_id)

    def record_attestation(
        self, attestation: ExactShaReviewAttestation
    ) -> ExactShaReviewAttestation:
        if not isinstance(attestation, ExactShaReviewAttestation):
            raise ReviewAttestationValidationError(
                "attestation must be an ExactShaReviewAttestation"
            )
        request = self._require_registered_request(attestation.request_id)
        if attestation.request_content_hash != request.content_hash:
            raise ReviewAttestationValidationError(
                "request content hash does not match registered request"
            )
        if attestation.repository != request.repository:
            raise ReviewAttestationValidationError("repository does not match registered request")
        if attestation.pull_request_number != request.pull_request_number:
            raise ReviewAttestationValidationError("pull request does not match registered request")
        if attestation.candidate_sha != request.candidate_sha:
            raise ReviewAttestationValidationError(
                "candidate SHA does not match registered request"
            )
        if attestation.reviewer.model is not request.required_model:
            raise ReviewAttestationValidationError("reviewer model does not match required model")
        fingerprint = attestation.reviewer.reviewer_key_fingerprint
        if fingerprint not in request.trusted_reviewer_fingerprints:
            raise ReviewAttestationValidationError("reviewer is not a trusted reviewer")
        reviewer_attestations = self._attestations_by_request[request.id]
        existing = reviewer_attestations.get(fingerprint)
        if existing is not None:
            if existing == attestation:
                return existing
            raise ReviewAttestationConflictError("reviewer attestation conflict")
        reviewer_attestations[fingerprint] = attestation
        return attestation

    def attestations(self, request_id: UUID) -> tuple[ExactShaReviewAttestation, ...]:
        request = self._require_registered_request(request_id)
        return tuple(
            sorted(
                self._attestations_by_request[request.id].values(),
                key=lambda item: (
                    item.reviewer.reviewer_key_fingerprint,
                    str(item.id),
                ),
            )
        )

    def summary(self, request_id: UUID) -> ReviewAttestationRegistrySummary:
        request = self._require_registered_request(request_id)
        values = self.attestations(request.id)
        approval_count = sum(item.verdict is ReviewAttestationVerdict.APPROVE for item in values)
        changes_required_count = sum(
            item.verdict is ReviewAttestationVerdict.CHANGES_REQUIRED for item in values
        )
        evidence_blocked_count = sum(
            item.verdict is ReviewAttestationVerdict.BLOCKED_BY_EVIDENCE for item in values
        )
        return ReviewAttestationRegistrySummary(
            request_id=request.id,
            request_content_hash=request.content_hash,
            attestation_ids=tuple(item.id for item in values),
            registered_attestation_count=len(values),
            approval_count=approval_count,
            changes_required_count=changes_required_count,
            evidence_blocked_count=evidence_blocked_count,
            distinct_reviewer_count=len(
                {item.reviewer.reviewer_key_fingerprint for item in values}
            ),
            missing_approval_count=max(0, request.minimum_approvals - approval_count),
        )

    def decision(self, request_id: UUID) -> ReviewAttestationDecision:
        request = self._require_registered_request(request_id)
        summary = self.summary(request.id)
        if summary.changes_required_count > 0:
            state = ReviewAdvisoryState.BLOCKED
        elif summary.evidence_blocked_count > 0:
            state = ReviewAdvisoryState.EVIDENCE_BLOCKED
        elif summary.approval_count >= request.minimum_approvals:
            state = ReviewAdvisoryState.APPROVED
        else:
            state = ReviewAdvisoryState.PENDING
        return ReviewAttestationDecision(
            request_id=request.id,
            request_content_hash=request.content_hash,
            state=state,
            summary_content_hash=summary.content_hash,
            advisory_only=True,
        )
