"""Pure deterministic exact-SHA merge-readiness gate."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from uuid import NAMESPACE_URL, UUID, uuid5

from .review_attestation_registry import (
    ExactShaReviewRequest,
    ReviewAdvisoryState,
    ReviewAttestationDecision,
    ReviewAttestationRegistrySummary,
    ReviewAttestationValidationError,
)

_SCHEMA = "nextgen-memory-exact-sha-merge-readiness-v0"
_POLICY_VERSION = "exact-sha-merge-readiness-v0"
_MAX_REPOSITORY_LENGTH = 200
_MAX_COMPONENT_KEY_LENGTH = 100
_MAX_DEPENDENCIES = 64
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_COMPONENT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,99}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class MergeReadinessValidationError(ValueError):
    """An immutable merge-readiness value is malformed."""


class MergeReadinessState(StrEnum):
    """Advisory merge-readiness states."""

    READY = "READY"
    HOLD = "HOLD"
    BLOCKED = "BLOCKED"


class MergeReadinessReason(StrEnum):
    """Bounded readiness reasons in canonical precedence order."""

    REPOSITORY_MISMATCH = "repository_mismatch"
    PULL_REQUEST_MISMATCH = "pull_request_mismatch"
    BASE_SHA_DRIFT = "base_sha_drift"
    CANDIDATE_SHA_DRIFT = "candidate_sha_drift"
    DIFF_SHA_DRIFT = "diff_sha_drift"
    DEPENDENCY_CHAIN_MISMATCH = "dependency_chain_mismatch"
    REVIEW_BLOCKED = "review_blocked"
    REVIEW_EVIDENCE_BLOCKED = "review_evidence_blocked"
    UNAUTHENTICATED_APPROVAL = "unauthenticated_approval"
    REVIEW_REQUEST_IDENTITY_MISMATCH = "review_request_identity_mismatch"
    REVIEW_SUMMARY_IDENTITY_MISMATCH = "review_summary_identity_mismatch"
    REVIEW_DECISION_IDENTITY_MISMATCH = "review_decision_identity_mismatch"
    STATIC_ANALYSIS_FAILED = "static_analysis_failed"
    COMPILE_FAILED = "compile_failed"
    FULL_SUITE_FAILED = "full_suite_failed"
    ARTIFACT_INTEGRITY_FAILED = "artifact_integrity_failed"
    ISOLATED_WHEEL_FAILED = "isolated_wheel_failed"
    INTEGRATION_REHEARSAL_FAILED = "integration_rehearsal_failed"
    CROSS_PYTHON_IDENTITY_FAILED = "cross_python_identity_failed"
    POSTGRES_REPLAY_FAILED = "postgres_replay_failed"
    EQUIVALENT_DEPENDENCY_REF_INCLUDED = "equivalent_dependency_ref_included"
    SINGLE_WRITER_POLICY_VIOLATION = "single_writer_policy_violation"
    PROTECTED_BRANCH_POLICY_VIOLATION = "protected_branch_policy_violation"
    REVIEW_PENDING = "review_pending"
    INSUFFICIENT_APPROVALS = "insufficient_approvals"
    MISSING_AUTHENTICATED_ENVELOPE = "missing_authenticated_envelope"
    VERIFICATION_EVIDENCE_STALE = "verification_evidence_stale"
    INSUFFICIENT_FULL_SUITE_TEST_COUNT = "insufficient_full_suite_test_count"
    PREREQUISITES_NOT_INTEGRATED = "prerequisites_not_integrated"
    INSUFFICIENT_MIGRATION_PASSES = "insufficient_migration_passes"
    MISSING_VERIFICATION_ARTIFACT = "missing_verification_artifact"
    MISSING_INTEGRATION_CHECKPOINT = "missing_integration_checkpoint"
    ALL_GATES_PASSED = "all_gates_passed"


_BLOCK_REASONS = (
    MergeReadinessReason.REPOSITORY_MISMATCH,
    MergeReadinessReason.PULL_REQUEST_MISMATCH,
    MergeReadinessReason.BASE_SHA_DRIFT,
    MergeReadinessReason.CANDIDATE_SHA_DRIFT,
    MergeReadinessReason.DIFF_SHA_DRIFT,
    MergeReadinessReason.DEPENDENCY_CHAIN_MISMATCH,
    MergeReadinessReason.REVIEW_BLOCKED,
    MergeReadinessReason.REVIEW_EVIDENCE_BLOCKED,
    MergeReadinessReason.UNAUTHENTICATED_APPROVAL,
    MergeReadinessReason.REVIEW_REQUEST_IDENTITY_MISMATCH,
    MergeReadinessReason.REVIEW_SUMMARY_IDENTITY_MISMATCH,
    MergeReadinessReason.REVIEW_DECISION_IDENTITY_MISMATCH,
    MergeReadinessReason.STATIC_ANALYSIS_FAILED,
    MergeReadinessReason.COMPILE_FAILED,
    MergeReadinessReason.FULL_SUITE_FAILED,
    MergeReadinessReason.ARTIFACT_INTEGRITY_FAILED,
    MergeReadinessReason.ISOLATED_WHEEL_FAILED,
    MergeReadinessReason.INTEGRATION_REHEARSAL_FAILED,
    MergeReadinessReason.CROSS_PYTHON_IDENTITY_FAILED,
    MergeReadinessReason.POSTGRES_REPLAY_FAILED,
    MergeReadinessReason.EQUIVALENT_DEPENDENCY_REF_INCLUDED,
    MergeReadinessReason.SINGLE_WRITER_POLICY_VIOLATION,
    MergeReadinessReason.PROTECTED_BRANCH_POLICY_VIOLATION,
)
_HOLD_REASONS = (
    MergeReadinessReason.REVIEW_PENDING,
    MergeReadinessReason.INSUFFICIENT_APPROVALS,
    MergeReadinessReason.MISSING_AUTHENTICATED_ENVELOPE,
    MergeReadinessReason.VERIFICATION_EVIDENCE_STALE,
    MergeReadinessReason.INSUFFICIENT_FULL_SUITE_TEST_COUNT,
    MergeReadinessReason.PREREQUISITES_NOT_INTEGRATED,
    MergeReadinessReason.INSUFFICIENT_MIGRATION_PASSES,
    MergeReadinessReason.MISSING_VERIFICATION_ARTIFACT,
    MergeReadinessReason.MISSING_INTEGRATION_CHECKPOINT,
)


def _raise(message: str) -> None:
    raise MergeReadinessValidationError(message) from None


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
    except (TypeError, ValueError):
        _raise("canonical merge-readiness payload is invalid")
    raise AssertionError("unreachable")


def _hash_payload(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stable_uuid(kind: str, content_hash: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"nextgen-memory:exact-sha-merge-readiness-{kind}-v0:{content_hash}",
    )


def _exact_str(name: str, value: object) -> str:
    if type(value) is not str:
        _raise(f"{name} must be an exact string")
    return value


def _repository(value: object) -> str:
    value = _exact_str("repository", value)
    if (
        not value
        or value != value.strip()
        or len(value) > _MAX_REPOSITORY_LENGTH
        or _REPOSITORY_RE.fullmatch(value) is None
    ):
        _raise("repository is invalid")
    owner, repository = value.split("/", 1)
    if owner in {".", ".."} or repository in {".", ".."}:
        _raise("repository is invalid")
    return value


def _component_key(value: object) -> str:
    value = _exact_str("component key", value)
    if (
        not value
        or len(value) > _MAX_COMPONENT_KEY_LENGTH
        or _COMPONENT_KEY_RE.fullmatch(value) is None
    ):
        _raise("component key is invalid")
    return value


def _git_sha(name: str, value: object) -> str:
    if type(value) is not str or _GIT_SHA_RE.fullmatch(value) is None:
        _raise(f"{name} must be a lowercase 40-character Git SHA")
    return value


def _sha256(name: str, value: object) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _raise(f"{name} must be a lowercase SHA-256")
    return value


def _optional_sha256(name: str, value: object) -> str | None:
    if value is None:
        return None
    return _sha256(name, value)


def _positive_int(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        _raise(f"{name} must be a positive integer")
    return value


def _nonnegative_int(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        _raise(f"{name} must be a non-negative integer")
    return value


def _exact_bool(name: str, value: object) -> bool:
    if type(value) is not bool:
        _raise(f"{name} must be a boolean")
    return value


def _finite_number(name: str, value: object) -> float:
    if type(value) not in (int, float):
        _raise(f"{name} must be a finite number")
    normalized = float(value)
    if not isfinite(normalized):
        _raise(f"{name} must be a finite number")
    return normalized


def _positive_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized <= 0.0:
        _raise(f"{name} must be positive")
    return normalized


def _nonnegative_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized < 0.0:
        _raise(f"{name} must be non-negative")
    return normalized


def _policy_version(value: object) -> str:
    value = _exact_str("gate policy version", value)
    if value != _POLICY_VERSION:
        _raise("gate policy version is unsupported")
    return value


def _exact_uuid(name: str, value: object) -> UUID:
    if type(value) is not UUID:
        _raise(f"{name} must be an exact UUID")
    return value


def _r4_integrity(value: object) -> bool:
    try:
        if type(value) not in (
            ExactShaReviewRequest,
            ReviewAttestationRegistrySummary,
            ReviewAttestationDecision,
        ):
            return False
        value.to_dict()
    except ReviewAttestationValidationError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class MergeReadinessConfig:
    maximum_evidence_age_seconds: float
    minimum_full_suite_test_count: int
    minimum_migration_pass_count: int
    gate_policy_version: str = _POLICY_VERSION
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "maximum_evidence_age_seconds",
            _positive_number("maximum evidence age", self.maximum_evidence_age_seconds),
        )
        object.__setattr__(
            self,
            "minimum_full_suite_test_count",
            _positive_int(
                "minimum full-suite test count", self.minimum_full_suite_test_count
            ),
        )
        object.__setattr__(
            self,
            "minimum_migration_pass_count",
            _nonnegative_int(
                "minimum migration pass count", self.minimum_migration_pass_count
            ),
        )
        object.__setattr__(
            self, "gate_policy_version", _policy_version(self.gate_policy_version)
        )
        object.__setattr__(self, "content_hash", _hash_payload(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "gate_policy_version": self.gate_policy_version,
            "maximum_evidence_age_seconds": self.maximum_evidence_age_seconds,
            "minimum_full_suite_test_count": self.minimum_full_suite_test_count,
            "minimum_migration_pass_count": self.minimum_migration_pass_count,
            "schema": _SCHEMA,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "content_hash": self.content_hash}

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class MergeCandidateIdentity:
    repository: str
    pull_request_number: int
    expected_base_sha: str
    observed_base_head_sha: str
    expected_candidate_sha: str
    observed_candidate_head_sha: str
    expected_diff_sha256: str
    observed_diff_sha256: str
    expected_dependency_chain_sha256: str
    merge_policy_version: str
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository", _repository(self.repository))
        object.__setattr__(
            self,
            "pull_request_number",
            _positive_int("pull request number", self.pull_request_number),
        )
        for name in (
            "expected_base_sha",
            "observed_base_head_sha",
            "expected_candidate_sha",
            "observed_candidate_head_sha",
        ):
            object.__setattr__(
                self,
                name,
                _git_sha(name.replace("_", " "), getattr(self, name)),
            )
        for name in (
            "expected_diff_sha256",
            "observed_diff_sha256",
            "expected_dependency_chain_sha256",
        ):
            object.__setattr__(
                self,
                name,
                _sha256(name.replace("_", " "), getattr(self, name)),
            )
        object.__setattr__(
            self, "merge_policy_version", _policy_version(self.merge_policy_version)
        )
        object.__setattr__(self, "content_hash", _hash_payload(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "expected_base_sha": self.expected_base_sha,
            "expected_candidate_sha": self.expected_candidate_sha,
            "expected_dependency_chain_sha256": self.expected_dependency_chain_sha256,
            "expected_diff_sha256": self.expected_diff_sha256,
            "merge_policy_version": self.merge_policy_version,
            "observed_base_head_sha": self.observed_base_head_sha,
            "observed_candidate_head_sha": self.observed_candidate_head_sha,
            "observed_diff_sha256": self.observed_diff_sha256,
            "pull_request_number": self.pull_request_number,
            "repository": self.repository,
            "schema": _SCHEMA,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "content_hash": self.content_hash}

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class ExactReviewReadinessEvidence:
    request: ExactShaReviewRequest
    summary: ReviewAttestationRegistrySummary
    decision: ReviewAttestationDecision
    authenticated_envelope_evidence_sha256: str | None
    authentication_verified: bool
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.request) is not ExactShaReviewRequest:
            _raise("review request must be an exact ExactShaReviewRequest")
        if type(self.summary) is not ReviewAttestationRegistrySummary:
            _raise("review summary must be an exact ReviewAttestationRegistrySummary")
        if type(self.decision) is not ReviewAttestationDecision:
            _raise("review decision must be an exact ReviewAttestationDecision")
        object.__setattr__(
            self,
            "authenticated_envelope_evidence_sha256",
            _optional_sha256(
                "authenticated envelope evidence",
                self.authenticated_envelope_evidence_sha256,
            ),
        )
        object.__setattr__(
            self,
            "authentication_verified",
            _exact_bool("authentication verified", self.authentication_verified),
        )
        object.__setattr__(self, "content_hash", _hash_payload(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "authenticated_envelope_evidence_sha256": (
                self.authenticated_envelope_evidence_sha256
            ),
            "authentication_verified": self.authentication_verified,
            "decision_content_hash": self.decision.content_hash,
            "request_content_hash": self.request.content_hash,
            "schema": _SCHEMA,
            "summary_content_hash": self.summary.content_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "content_hash": self.content_hash}

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class MergeVerificationEvidence:
    base_sha: str
    candidate_sha: str
    diff_sha256: str
    static_analysis_passed: bool
    compile_passed: bool
    full_suite_passed: bool
    full_suite_test_count: int
    artifact_integrity_passed: bool
    isolated_wheel_passed: bool
    integration_rehearsal_passed: bool
    cross_python_semantic_identity_passed: bool
    postgres_replay_required: bool
    postgres_replay_passed: bool
    migration_pass_count: int
    verification_artifact_sha256: str | None
    integration_checkpoint_sha256: str | None
    evidence_age_seconds: float
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_sha", _git_sha("base SHA", self.base_sha))
        object.__setattr__(
            self, "candidate_sha", _git_sha("candidate SHA", self.candidate_sha)
        )
        object.__setattr__(
            self, "diff_sha256", _sha256("diff SHA-256", self.diff_sha256)
        )
        for name in (
            "static_analysis_passed",
            "compile_passed",
            "full_suite_passed",
            "artifact_integrity_passed",
            "isolated_wheel_passed",
            "integration_rehearsal_passed",
            "cross_python_semantic_identity_passed",
            "postgres_replay_required",
            "postgres_replay_passed",
        ):
            object.__setattr__(
                self,
                name,
                _exact_bool(name.replace("_", " "), getattr(self, name)),
            )
        object.__setattr__(
            self,
            "full_suite_test_count",
            _nonnegative_int("full-suite test count", self.full_suite_test_count),
        )
        object.__setattr__(
            self,
            "migration_pass_count",
            _nonnegative_int("migration pass count", self.migration_pass_count),
        )
        object.__setattr__(
            self,
            "verification_artifact_sha256",
            _optional_sha256(
                "verification artifact", self.verification_artifact_sha256
            ),
        )
        object.__setattr__(
            self,
            "integration_checkpoint_sha256",
            _optional_sha256(
                "integration checkpoint", self.integration_checkpoint_sha256
            ),
        )
        object.__setattr__(
            self,
            "evidence_age_seconds",
            _nonnegative_number("evidence age", self.evidence_age_seconds),
        )
        object.__setattr__(self, "content_hash", _hash_payload(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "artifact_integrity_passed": self.artifact_integrity_passed,
            "base_sha": self.base_sha,
            "candidate_sha": self.candidate_sha,
            "compile_passed": self.compile_passed,
            "cross_python_semantic_identity_passed": (
                self.cross_python_semantic_identity_passed
            ),
            "diff_sha256": self.diff_sha256,
            "evidence_age_seconds": self.evidence_age_seconds,
            "full_suite_passed": self.full_suite_passed,
            "full_suite_test_count": self.full_suite_test_count,
            "integration_checkpoint_sha256": self.integration_checkpoint_sha256,
            "integration_rehearsal_passed": self.integration_rehearsal_passed,
            "isolated_wheel_passed": self.isolated_wheel_passed,
            "migration_pass_count": self.migration_pass_count,
            "postgres_replay_passed": self.postgres_replay_passed,
            "postgres_replay_required": self.postgres_replay_required,
            "schema": _SCHEMA,
            "static_analysis_passed": self.static_analysis_passed,
            "verification_artifact_sha256": self.verification_artifact_sha256,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "content_hash": self.content_hash}

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class MergeDependencyIdentity:
    ordinal: int
    component_key: str
    candidate_sha: str
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordinal", _positive_int("ordinal", self.ordinal))
        object.__setattr__(self, "component_key", _component_key(self.component_key))
        object.__setattr__(
            self, "candidate_sha", _git_sha("candidate SHA", self.candidate_sha)
        )
        object.__setattr__(self, "content_hash", _hash_payload(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "candidate_sha": self.candidate_sha,
            "component_key": self.component_key,
            "ordinal": self.ordinal,
            "schema": _SCHEMA,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "content_hash": self.content_hash}

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class MergeDependencyReadiness:
    dependencies: tuple[MergeDependencyIdentity, ...]
    observed_dependency_chain_sha256: str
    prerequisites_integrated_into_observed_base: bool
    equivalent_duplicate_refs_excluded: bool
    single_writer_reservation_active: bool
    protected_branch_policy_satisfied: bool
    computed_dependency_chain_sha256: str = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.dependencies) is not tuple:
            _raise("dependencies must be an exact tuple")
        dependencies = self.dependencies
        if not dependencies or len(dependencies) > _MAX_DEPENDENCIES:
            _raise("dependencies must contain 1..64 entries")
        if any(type(item) is not MergeDependencyIdentity for item in dependencies):
            _raise("dependencies must contain exact MergeDependencyIdentity values")
        if tuple(item.ordinal for item in dependencies) != tuple(
            range(1, len(dependencies) + 1)
        ):
            _raise("dependencies must have contiguous ordinals")
        component_keys = tuple(item.component_key for item in dependencies)
        shas = tuple(item.candidate_sha for item in dependencies)
        if len(component_keys) != len(set(component_keys)) or len(shas) != len(
            set(shas)
        ):
            _raise("dependencies must have unique component keys and candidate SHAs")
        object.__setattr__(
            self,
            "observed_dependency_chain_sha256",
            _sha256("observed dependency chain", self.observed_dependency_chain_sha256),
        )
        for name in (
            "prerequisites_integrated_into_observed_base",
            "equivalent_duplicate_refs_excluded",
            "single_writer_reservation_active",
            "protected_branch_policy_satisfied",
        ):
            object.__setattr__(
                self,
                name,
                _exact_bool(name.replace("_", " "), getattr(self, name)),
            )
        computed = _hash_payload(
            {
                "dependencies": [
                    {
                        "candidate_sha": item.candidate_sha,
                        "component_key": item.component_key,
                        "ordinal": item.ordinal,
                    }
                    for item in dependencies
                ],
                "schema": _SCHEMA,
            }
        )
        object.__setattr__(self, "computed_dependency_chain_sha256", computed)
        object.__setattr__(self, "content_hash", _hash_payload(self._payload()))

    def _payload(self) -> dict[str, object]:
        return {
            "computed_dependency_chain_sha256": self.computed_dependency_chain_sha256,
            "dependencies": [item.to_dict() for item in self.dependencies],
            "equivalent_duplicate_refs_excluded": self.equivalent_duplicate_refs_excluded,
            "observed_dependency_chain_sha256": self.observed_dependency_chain_sha256,
            "prerequisites_integrated_into_observed_base": (
                self.prerequisites_integrated_into_observed_base
            ),
            "protected_branch_policy_satisfied": self.protected_branch_policy_satisfied,
            "schema": _SCHEMA,
            "single_writer_reservation_active": self.single_writer_reservation_active,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "content_hash": self.content_hash}

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class MergeReadinessRequest:
    candidate: MergeCandidateIdentity
    review: ExactReviewReadinessEvidence
    verification: MergeVerificationEvidence
    dependencies: MergeDependencyReadiness
    id: UUID = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.candidate) is not MergeCandidateIdentity:
            _raise("candidate must be an exact MergeCandidateIdentity")
        if type(self.review) is not ExactReviewReadinessEvidence:
            _raise("review must be an exact ExactReviewReadinessEvidence")
        if type(self.verification) is not MergeVerificationEvidence:
            _raise("verification must be an exact MergeVerificationEvidence")
        if type(self.dependencies) is not MergeDependencyReadiness:
            _raise("dependencies must be an exact MergeDependencyReadiness")
        content_hash = _hash_payload(self._payload())
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "id", _stable_uuid("request", content_hash))

    def _payload(self) -> dict[str, object]:
        return {
            "candidate_content_hash": self.candidate.content_hash,
            "dependency_content_hash": self.dependencies.content_hash,
            "review_content_hash": self.review.content_hash,
            "schema": _SCHEMA,
            "verification_content_hash": self.verification.content_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._payload(),
            "content_hash": self.content_hash,
            "id": str(self.id),
        }

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class MergeReadinessRecord:
    request_id: UUID
    request_content_hash: str
    config_content_hash: str
    candidate_content_hash: str
    review_content_hash: str
    verification_content_hash: str
    dependency_content_hash: str
    state: MergeReadinessState
    reasons: tuple[MergeReadinessReason, ...]
    advisory_only: bool = True
    id: UUID = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "request_id", _exact_uuid("request id", self.request_id)
        )
        for name in (
            "request_content_hash",
            "config_content_hash",
            "candidate_content_hash",
            "review_content_hash",
            "verification_content_hash",
            "dependency_content_hash",
        ):
            object.__setattr__(
                self,
                name,
                _sha256(name.replace("_", " "), getattr(self, name)),
            )
        if type(self.state) is not MergeReadinessState:
            _raise("state must be an exact MergeReadinessState")
        if type(self.reasons) is not tuple or not self.reasons:
            _raise("reasons must be a non-empty exact tuple")
        if any(type(item) is not MergeReadinessReason for item in self.reasons):
            _raise("reasons must contain exact MergeReadinessReason values")
        if len(set(self.reasons)) != len(self.reasons):
            _raise("reasons must not contain duplicates")
        if self.state is MergeReadinessState.BLOCKED:
            if (
                tuple(item for item in _BLOCK_REASONS if item in self.reasons)
                != self.reasons
            ):
                _raise("blocked reasons are not canonical")
        elif self.state is MergeReadinessState.HOLD:
            if (
                tuple(item for item in _HOLD_REASONS if item in self.reasons)
                != self.reasons
            ):
                _raise("hold reasons are not canonical")
        elif self.reasons != (MergeReadinessReason.ALL_GATES_PASSED,):
            _raise("ready reasons are invalid")
        if self.advisory_only is not True:
            _raise("merge-readiness records must remain advisory only")
        content_hash = _hash_payload(self._payload())
        object.__setattr__(self, "content_hash", content_hash)
        object.__setattr__(self, "id", _stable_uuid("record", content_hash))

    def _payload(self) -> dict[str, object]:
        return {
            "advisory_only": self.advisory_only,
            "candidate_content_hash": self.candidate_content_hash,
            "config_content_hash": self.config_content_hash,
            "dependency_content_hash": self.dependency_content_hash,
            "reasons": [item.value for item in self.reasons],
            "request_content_hash": self.request_content_hash,
            "request_id": str(self.request_id),
            "review_content_hash": self.review_content_hash,
            "schema": _SCHEMA,
            "state": self.state.value,
            "verification_content_hash": self.verification_content_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            **self._payload(),
            "content_hash": self.content_hash,
            "id": str(self.id),
        }

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


def _derived_review_state(
    request: ExactShaReviewRequest,
    summary: ReviewAttestationRegistrySummary,
) -> ReviewAdvisoryState:
    if summary.changes_required_count > 0:
        return ReviewAdvisoryState.BLOCKED
    if summary.evidence_blocked_count > 0:
        return ReviewAdvisoryState.EVIDENCE_BLOCKED
    if summary.approval_count >= request.minimum_approvals:
        return ReviewAdvisoryState.APPROVED
    return ReviewAdvisoryState.PENDING


def _append_once(
    values: list[MergeReadinessReason], reason: MergeReadinessReason
) -> None:
    if reason not in values:
        values.append(reason)


class ExactShaMergeReadinessGate:
    """Evaluate complete exact-SHA evidence without executing a merge."""

    __slots__ = ()

    def evaluate(
        self,
        request: MergeReadinessRequest,
        config: MergeReadinessConfig,
    ) -> MergeReadinessRecord:
        if type(request) is not MergeReadinessRequest:
            _raise("request must be an exact MergeReadinessRequest")
        if type(config) is not MergeReadinessConfig:
            _raise("config must be an exact MergeReadinessConfig")

        candidate = request.candidate
        review = request.review
        verification = request.verification
        dependencies = request.dependencies
        review_request = review.request
        summary = review.summary
        decision = review.decision

        block: list[MergeReadinessReason] = []
        hold: list[MergeReadinessReason] = []

        request_integrity = _r4_integrity(review_request)
        summary_integrity = _r4_integrity(summary)
        decision_integrity = _r4_integrity(decision)

        if request_integrity:
            if review_request.repository != candidate.repository:
                _append_once(block, MergeReadinessReason.REPOSITORY_MISMATCH)
            if review_request.pull_request_number != candidate.pull_request_number:
                _append_once(block, MergeReadinessReason.PULL_REQUEST_MISMATCH)
        if (
            candidate.expected_base_sha != candidate.observed_base_head_sha
            or verification.base_sha != candidate.expected_base_sha
            or (
                request_integrity
                and review_request.base_sha != candidate.expected_base_sha
            )
        ):
            _append_once(block, MergeReadinessReason.BASE_SHA_DRIFT)
        if (
            candidate.expected_candidate_sha != candidate.observed_candidate_head_sha
            or verification.candidate_sha != candidate.expected_candidate_sha
            or (
                request_integrity
                and review_request.candidate_sha != candidate.expected_candidate_sha
            )
        ):
            _append_once(block, MergeReadinessReason.CANDIDATE_SHA_DRIFT)
        if (
            candidate.expected_diff_sha256 != candidate.observed_diff_sha256
            or verification.diff_sha256 != candidate.expected_diff_sha256
            or (
                request_integrity
                and review_request.diff_sha256 != candidate.expected_diff_sha256
            )
        ):
            _append_once(block, MergeReadinessReason.DIFF_SHA_DRIFT)
        if (
            candidate.expected_dependency_chain_sha256
            != dependencies.observed_dependency_chain_sha256
            or dependencies.observed_dependency_chain_sha256
            != dependencies.computed_dependency_chain_sha256
        ):
            _append_once(block, MergeReadinessReason.DEPENDENCY_CHAIN_MISMATCH)

        if not request_integrity:
            _append_once(block, MergeReadinessReason.REVIEW_REQUEST_IDENTITY_MISMATCH)
        if not summary_integrity:
            _append_once(block, MergeReadinessReason.REVIEW_SUMMARY_IDENTITY_MISMATCH)
        if not decision_integrity:
            _append_once(block, MergeReadinessReason.REVIEW_DECISION_IDENTITY_MISMATCH)

        if request_integrity and summary_integrity:
            expected_missing = max(
                0, review_request.minimum_approvals - summary.approval_count
            )
            if (
                summary.request_id != review_request.id
                or summary.request_content_hash != review_request.content_hash
            ):
                _append_once(
                    block, MergeReadinessReason.REVIEW_REQUEST_IDENTITY_MISMATCH
                )
            if summary.missing_approval_count != expected_missing:
                _append_once(
                    block, MergeReadinessReason.REVIEW_SUMMARY_IDENTITY_MISMATCH
                )

        if request_integrity and summary_integrity and decision_integrity:
            expected_state = _derived_review_state(review_request, summary)
            if (
                decision.request_id != review_request.id
                or decision.request_content_hash != review_request.content_hash
            ):
                _append_once(
                    block, MergeReadinessReason.REVIEW_DECISION_IDENTITY_MISMATCH
                )
            if decision.summary_content_hash != summary.content_hash:
                _append_once(
                    block, MergeReadinessReason.REVIEW_SUMMARY_IDENTITY_MISMATCH
                )
            if decision.state is not expected_state:
                _append_once(
                    block, MergeReadinessReason.REVIEW_DECISION_IDENTITY_MISMATCH
                )

        if decision_integrity:
            if decision.state is ReviewAdvisoryState.BLOCKED:
                _append_once(block, MergeReadinessReason.REVIEW_BLOCKED)
            elif decision.state is ReviewAdvisoryState.EVIDENCE_BLOCKED:
                _append_once(block, MergeReadinessReason.REVIEW_EVIDENCE_BLOCKED)
            elif (
                decision.state is ReviewAdvisoryState.APPROVED
                and not review.authentication_verified
            ):
                _append_once(block, MergeReadinessReason.UNAUTHENTICATED_APPROVAL)
            elif decision.state is ReviewAdvisoryState.PENDING:
                _append_once(hold, MergeReadinessReason.REVIEW_PENDING)

        if (
            summary_integrity
            and request_integrity
            and (
                summary.approval_count < review_request.minimum_approvals
                or summary.missing_approval_count != 0
            )
        ):
            _append_once(hold, MergeReadinessReason.INSUFFICIENT_APPROVALS)
        if review.authenticated_envelope_evidence_sha256 is None:
            _append_once(hold, MergeReadinessReason.MISSING_AUTHENTICATED_ENVELOPE)

        if not verification.static_analysis_passed:
            _append_once(block, MergeReadinessReason.STATIC_ANALYSIS_FAILED)
        if not verification.compile_passed:
            _append_once(block, MergeReadinessReason.COMPILE_FAILED)
        if not verification.full_suite_passed:
            _append_once(block, MergeReadinessReason.FULL_SUITE_FAILED)
        if not verification.artifact_integrity_passed:
            _append_once(block, MergeReadinessReason.ARTIFACT_INTEGRITY_FAILED)
        if not verification.isolated_wheel_passed:
            _append_once(block, MergeReadinessReason.ISOLATED_WHEEL_FAILED)
        if not verification.integration_rehearsal_passed:
            _append_once(block, MergeReadinessReason.INTEGRATION_REHEARSAL_FAILED)
        if not verification.cross_python_semantic_identity_passed:
            _append_once(block, MergeReadinessReason.CROSS_PYTHON_IDENTITY_FAILED)
        if (
            verification.postgres_replay_required
            and not verification.postgres_replay_passed
        ):
            _append_once(block, MergeReadinessReason.POSTGRES_REPLAY_FAILED)

        if verification.evidence_age_seconds > config.maximum_evidence_age_seconds:
            _append_once(hold, MergeReadinessReason.VERIFICATION_EVIDENCE_STALE)
        if (
            verification.full_suite_passed
            and verification.full_suite_test_count
            < config.minimum_full_suite_test_count
        ):
            _append_once(hold, MergeReadinessReason.INSUFFICIENT_FULL_SUITE_TEST_COUNT)
        if verification.migration_pass_count < config.minimum_migration_pass_count:
            _append_once(hold, MergeReadinessReason.INSUFFICIENT_MIGRATION_PASSES)
        if verification.verification_artifact_sha256 is None:
            _append_once(hold, MergeReadinessReason.MISSING_VERIFICATION_ARTIFACT)
        if verification.integration_checkpoint_sha256 is None:
            _append_once(hold, MergeReadinessReason.MISSING_INTEGRATION_CHECKPOINT)

        if not dependencies.equivalent_duplicate_refs_excluded:
            _append_once(block, MergeReadinessReason.EQUIVALENT_DEPENDENCY_REF_INCLUDED)
        if not dependencies.single_writer_reservation_active:
            _append_once(block, MergeReadinessReason.SINGLE_WRITER_POLICY_VIOLATION)
        if not dependencies.protected_branch_policy_satisfied:
            _append_once(block, MergeReadinessReason.PROTECTED_BRANCH_POLICY_VIOLATION)
        if not dependencies.prerequisites_integrated_into_observed_base:
            _append_once(hold, MergeReadinessReason.PREREQUISITES_NOT_INTEGRATED)

        if block:
            state = MergeReadinessState.BLOCKED
            reasons = tuple(reason for reason in _BLOCK_REASONS if reason in block)
        elif hold:
            state = MergeReadinessState.HOLD
            reasons = tuple(reason for reason in _HOLD_REASONS if reason in hold)
        else:
            state = MergeReadinessState.READY
            reasons = (MergeReadinessReason.ALL_GATES_PASSED,)

        return MergeReadinessRecord(
            request_id=request.id,
            request_content_hash=request.content_hash,
            config_content_hash=config.content_hash,
            candidate_content_hash=candidate.content_hash,
            review_content_hash=review.content_hash,
            verification_content_hash=verification.content_hash,
            dependency_content_hash=dependencies.content_hash,
            state=state,
            reasons=reasons,
            advisory_only=True,
        )


__all__ = [
    "ExactReviewReadinessEvidence",
    "ExactShaMergeReadinessGate",
    "MergeCandidateIdentity",
    "MergeDependencyIdentity",
    "MergeDependencyReadiness",
    "MergeReadinessConfig",
    "MergeReadinessReason",
    "MergeReadinessRecord",
    "MergeReadinessRequest",
    "MergeReadinessState",
    "MergeReadinessValidationError",
    "MergeVerificationEvidence",
]
