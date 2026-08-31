from __future__ import annotations

import hashlib
import importlib
import json
import math
from dataclasses import FrozenInstanceError, replace
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from nextgen_memory import (
    ExactShaReviewRequest,
    ReviewAdvisoryState,
    ReviewAttestationDecision,
    ReviewAttestationRegistrySummary,
    ReviewModel,
)

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

BASE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
DIFF_SHA = "3" * 64
OTHER_GIT_SHA = "4" * 40
POLICY_VERSION = "exact-sha-merge-readiness-v0"


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def canonical_json(value: object) -> str:
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


def exact_review_request(**overrides: object) -> ExactShaReviewRequest:
    values: dict[str, object] = {
        "repository": "leon36000/NextGen-Memory",
        "pull_request_number": 185,
        "base_sha": BASE_SHA,
        "candidate_sha": CANDIDATE_SHA,
        "diff_sha256": DIFF_SHA,
        "review_packet_sha256": digest("review-packet"),
        "acceptance_criteria_sha256": digest("acceptance-criteria"),
        "required_model": ReviewModel.GPT_5_6_SOL,
        "trusted_reviewer_fingerprints": (
            digest("reviewer-a"),
            digest("reviewer-b"),
        ),
        "minimum_approvals": 2,
    }
    values.update(overrides)
    return ExactShaReviewRequest(**values)  # type: ignore[arg-type]


def exact_review_summary(
    request: ExactShaReviewRequest,
    *,
    approval_count: int = 2,
    changes_required_count: int = 0,
    evidence_blocked_count: int = 0,
    missing_approval_count: int | None = None,
    request_id: UUID | None = None,
    request_content_hash: str | None = None,
) -> ReviewAttestationRegistrySummary:
    registered = approval_count + changes_required_count + evidence_blocked_count
    ids = tuple(
        uuid5(NAMESPACE_URL, f"merge-readiness-test-attestation:{index}")
        for index in range(registered)
    )
    missing = (
        max(0, request.minimum_approvals - approval_count)
        if missing_approval_count is None
        else missing_approval_count
    )
    return ReviewAttestationRegistrySummary(
        request_id=request.id if request_id is None else request_id,
        request_content_hash=(
            request.content_hash if request_content_hash is None else request_content_hash
        ),
        attestation_ids=ids,
        registered_attestation_count=registered,
        approval_count=approval_count,
        changes_required_count=changes_required_count,
        evidence_blocked_count=evidence_blocked_count,
        distinct_reviewer_count=registered,
        missing_approval_count=missing,
    )


def derived_review_state(
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


def exact_review_decision(
    request: ExactShaReviewRequest,
    summary: ReviewAttestationRegistrySummary,
    *,
    state: ReviewAdvisoryState | None = None,
    request_id: UUID | None = None,
    request_content_hash: str | None = None,
    summary_content_hash: str | None = None,
) -> ReviewAttestationDecision:
    return ReviewAttestationDecision(
        request_id=request.id if request_id is None else request_id,
        request_content_hash=(
            request.content_hash if request_content_hash is None else request_content_hash
        ),
        state=derived_review_state(request, summary) if state is None else state,
        summary_content_hash=(
            summary.content_hash if summary_content_hash is None else summary_content_hash
        ),
        advisory_only=True,
    )


def exact_review_evidence(
    *,
    request: ExactShaReviewRequest | None = None,
    summary: ReviewAttestationRegistrySummary | None = None,
    decision: ReviewAttestationDecision | None = None,
    authenticated_envelope_evidence_sha256: str | None = None,
    authentication_verified: bool = True,
) -> ExactReviewReadinessEvidence:
    review_request = exact_review_request() if request is None else request
    review_summary = exact_review_summary(review_request) if summary is None else summary
    review_decision = (
        exact_review_decision(review_request, review_summary) if decision is None else decision
    )
    envelope = (
        digest("authenticated-envelope")
        if authenticated_envelope_evidence_sha256 is None
        else authenticated_envelope_evidence_sha256
    )
    return ExactReviewReadinessEvidence(
        request=review_request,
        summary=review_summary,
        decision=review_decision,
        authenticated_envelope_evidence_sha256=envelope,
        authentication_verified=authentication_verified,
    )


def exact_dependencies(
    *,
    dependencies: tuple[MergeDependencyIdentity, ...] | None = None,
    observed_dependency_chain_sha256: str | None = None,
    prerequisites_integrated_into_observed_base: bool = True,
    equivalent_duplicate_refs_excluded: bool = True,
    single_writer_reservation_active: bool = True,
    protected_branch_policy_satisfied: bool = True,
) -> MergeDependencyReadiness:
    values = dependencies or (
        MergeDependencyIdentity(
            ordinal=1,
            component_key="policy-promotion-gate-v0",
            candidate_sha="5" * 40,
        ),
        MergeDependencyIdentity(
            ordinal=2,
            component_key="review-attestation-registry-v0",
            candidate_sha=CANDIDATE_SHA,
        ),
    )
    initial = MergeDependencyReadiness(
        dependencies=values,
        observed_dependency_chain_sha256=(
            digest("temporary-chain")
            if observed_dependency_chain_sha256 is None
            else observed_dependency_chain_sha256
        ),
        prerequisites_integrated_into_observed_base=(prerequisites_integrated_into_observed_base),
        equivalent_duplicate_refs_excluded=equivalent_duplicate_refs_excluded,
        single_writer_reservation_active=single_writer_reservation_active,
        protected_branch_policy_satisfied=protected_branch_policy_satisfied,
    )
    if observed_dependency_chain_sha256 is not None:
        return initial
    return replace(
        initial,
        observed_dependency_chain_sha256=(initial.computed_dependency_chain_sha256),
    )


def exact_candidate(
    dependencies: MergeDependencyReadiness,
    **overrides: object,
) -> MergeCandidateIdentity:
    values: dict[str, object] = {
        "repository": "leon36000/NextGen-Memory",
        "pull_request_number": 185,
        "expected_base_sha": BASE_SHA,
        "observed_base_head_sha": BASE_SHA,
        "expected_candidate_sha": CANDIDATE_SHA,
        "observed_candidate_head_sha": CANDIDATE_SHA,
        "expected_diff_sha256": DIFF_SHA,
        "observed_diff_sha256": DIFF_SHA,
        "expected_dependency_chain_sha256": (dependencies.computed_dependency_chain_sha256),
        "merge_policy_version": POLICY_VERSION,
    }
    values.update(overrides)
    return MergeCandidateIdentity(**values)  # type: ignore[arg-type]


def exact_verification(**overrides: object) -> MergeVerificationEvidence:
    values: dict[str, object] = {
        "base_sha": BASE_SHA,
        "candidate_sha": CANDIDATE_SHA,
        "diff_sha256": DIFF_SHA,
        "static_analysis_passed": True,
        "compile_passed": True,
        "full_suite_passed": True,
        "full_suite_test_count": 521,
        "artifact_integrity_passed": True,
        "isolated_wheel_passed": True,
        "integration_rehearsal_passed": True,
        "cross_python_semantic_identity_passed": True,
        "postgres_replay_required": True,
        "postgres_replay_passed": True,
        "migration_pass_count": 2,
        "verification_artifact_sha256": digest("verification-artifact"),
        "integration_checkpoint_sha256": digest("integration-checkpoint"),
        "evidence_age_seconds": 60.0,
    }
    values.update(overrides)
    return MergeVerificationEvidence(**values)  # type: ignore[arg-type]


def exact_config(**overrides: object) -> MergeReadinessConfig:
    values: dict[str, object] = {
        "maximum_evidence_age_seconds": 3600.0,
        "minimum_full_suite_test_count": 500,
        "minimum_migration_pass_count": 2,
        "gate_policy_version": POLICY_VERSION,
    }
    values.update(overrides)
    return MergeReadinessConfig(**values)  # type: ignore[arg-type]


def exact_ready_request(
    *,
    candidate: MergeCandidateIdentity | None = None,
    review: ExactReviewReadinessEvidence | None = None,
    verification: MergeVerificationEvidence | None = None,
    dependencies: MergeDependencyReadiness | None = None,
) -> MergeReadinessRequest:
    dependency_value = exact_dependencies() if dependencies is None else dependencies
    return MergeReadinessRequest(
        candidate=(exact_candidate(dependency_value) if candidate is None else candidate),
        review=exact_review_evidence() if review is None else review,
        verification=(exact_verification() if verification is None else verification),
        dependencies=dependency_value,
    )


def test_complete_exact_evidence_is_ready_and_advisory_only() -> None:
    gate = ExactShaMergeReadinessGate()
    request = exact_ready_request()
    config = exact_config()

    first = gate.evaluate(request, config)
    second = gate.evaluate(request, config)

    assert first == second
    assert first.state is MergeReadinessState.READY
    assert first.reasons == (MergeReadinessReason.ALL_GATES_PASSED,)
    assert first.advisory_only is True
    assert first.render_json() == second.render_json()
    assert not hasattr(gate, "merge")
    assert not hasattr(first, "merge")
    assert not hasattr(first, "deploy")
    assert not hasattr(first, "activate")


BLOCK_CASES = (
    ("repository_mismatch", MergeReadinessReason.REPOSITORY_MISMATCH),
    ("pull_request_mismatch", MergeReadinessReason.PULL_REQUEST_MISMATCH),
    ("base_sha_drift", MergeReadinessReason.BASE_SHA_DRIFT),
    ("candidate_sha_drift", MergeReadinessReason.CANDIDATE_SHA_DRIFT),
    ("diff_sha_drift", MergeReadinessReason.DIFF_SHA_DRIFT),
    ("dependency_chain_mismatch", MergeReadinessReason.DEPENDENCY_CHAIN_MISMATCH),
    ("review_blocked", MergeReadinessReason.REVIEW_BLOCKED),
    ("review_evidence_blocked", MergeReadinessReason.REVIEW_EVIDENCE_BLOCKED),
    ("unauthenticated_approval", MergeReadinessReason.UNAUTHENTICATED_APPROVAL),
    (
        "review_request_identity_mismatch",
        MergeReadinessReason.REVIEW_REQUEST_IDENTITY_MISMATCH,
    ),
    (
        "review_summary_identity_mismatch",
        MergeReadinessReason.REVIEW_SUMMARY_IDENTITY_MISMATCH,
    ),
    (
        "review_decision_identity_mismatch",
        MergeReadinessReason.REVIEW_DECISION_IDENTITY_MISMATCH,
    ),
    ("static_analysis_failed", MergeReadinessReason.STATIC_ANALYSIS_FAILED),
    ("compile_failed", MergeReadinessReason.COMPILE_FAILED),
    ("full_suite_failed", MergeReadinessReason.FULL_SUITE_FAILED),
    (
        "artifact_integrity_failed",
        MergeReadinessReason.ARTIFACT_INTEGRITY_FAILED,
    ),
    ("isolated_wheel_failed", MergeReadinessReason.ISOLATED_WHEEL_FAILED),
    (
        "integration_rehearsal_failed",
        MergeReadinessReason.INTEGRATION_REHEARSAL_FAILED,
    ),
    (
        "cross_python_identity_failed",
        MergeReadinessReason.CROSS_PYTHON_IDENTITY_FAILED,
    ),
    ("postgres_replay_failed", MergeReadinessReason.POSTGRES_REPLAY_FAILED),
    (
        "equivalent_dependency_ref_included",
        MergeReadinessReason.EQUIVALENT_DEPENDENCY_REF_INCLUDED,
    ),
    (
        "single_writer_policy_violation",
        MergeReadinessReason.SINGLE_WRITER_POLICY_VIOLATION,
    ),
    (
        "protected_branch_policy_violation",
        MergeReadinessReason.PROTECTED_BRANCH_POLICY_VIOLATION,
    ),
)


def request_with_block_case(case: str) -> MergeReadinessRequest:
    request = exact_ready_request()
    if case == "repository_mismatch":
        return replace(
            request,
            candidate=replace(request.candidate, repository="other/repository"),
        )
    if case == "pull_request_mismatch":
        return replace(
            request,
            candidate=replace(request.candidate, pull_request_number=186),
        )
    if case == "base_sha_drift":
        return replace(
            request,
            candidate=replace(
                request.candidate,
                observed_base_head_sha=OTHER_GIT_SHA,
            ),
        )
    if case == "candidate_sha_drift":
        return replace(
            request,
            candidate=replace(
                request.candidate,
                observed_candidate_head_sha=OTHER_GIT_SHA,
            ),
        )
    if case == "diff_sha_drift":
        return replace(
            request,
            candidate=replace(
                request.candidate,
                observed_diff_sha256=digest("other-diff"),
            ),
        )
    if case == "dependency_chain_mismatch":
        return replace(
            request,
            dependencies=replace(
                request.dependencies,
                observed_dependency_chain_sha256=digest("other-chain"),
            ),
        )
    if case in {"review_blocked", "review_evidence_blocked"}:
        review_request = request.review.request
        summary = exact_review_summary(
            review_request,
            approval_count=0,
            changes_required_count=1 if case == "review_blocked" else 0,
            evidence_blocked_count=(1 if case == "review_evidence_blocked" else 0),
        )
        review = exact_review_evidence(
            request=review_request,
            summary=summary,
            decision=exact_review_decision(review_request, summary),
        )
        return replace(request, review=review)
    if case == "unauthenticated_approval":
        return replace(
            request,
            review=replace(request.review, authentication_verified=False),
        )
    if case == "review_request_identity_mismatch":
        review_request = request.review.request
        summary = exact_review_summary(
            review_request,
            request_id=uuid5(NAMESPACE_URL, "wrong-review-request"),
        )
        decision = exact_review_decision(review_request, summary)
        return replace(
            request,
            review=exact_review_evidence(
                request=review_request,
                summary=summary,
                decision=decision,
            ),
        )
    if case == "review_summary_identity_mismatch":
        return replace(
            request,
            review=replace(
                request.review,
                decision=replace(
                    request.review.decision,
                    summary_content_hash=digest("wrong-summary"),
                ),
            ),
        )
    if case == "review_decision_identity_mismatch":
        return replace(
            request,
            review=replace(
                request.review,
                decision=replace(
                    request.review.decision,
                    state=ReviewAdvisoryState.PENDING,
                ),
            ),
        )
    verification_fields = {
        "static_analysis_failed": "static_analysis_passed",
        "compile_failed": "compile_passed",
        "full_suite_failed": "full_suite_passed",
        "artifact_integrity_failed": "artifact_integrity_passed",
        "isolated_wheel_failed": "isolated_wheel_passed",
        "integration_rehearsal_failed": "integration_rehearsal_passed",
        "cross_python_identity_failed": "cross_python_semantic_identity_passed",
        "postgres_replay_failed": "postgres_replay_passed",
    }
    if case in verification_fields:
        return replace(
            request,
            verification=replace(
                request.verification,
                **{verification_fields[case]: False},
            ),
        )
    dependency_fields = {
        "equivalent_dependency_ref_included": ("equivalent_duplicate_refs_excluded"),
        "single_writer_policy_violation": "single_writer_reservation_active",
        "protected_branch_policy_violation": ("protected_branch_policy_satisfied"),
    }
    if case in dependency_fields:
        return replace(
            request,
            dependencies=replace(
                request.dependencies,
                **{dependency_fields[case]: False},
            ),
        )
    raise AssertionError(f"unknown block case: {case}")


@pytest.mark.parametrize(("case", "reason"), BLOCK_CASES)
def test_each_hard_block_condition_is_bounded(
    case: str,
    reason: MergeReadinessReason,
) -> None:
    record = ExactShaMergeReadinessGate().evaluate(
        request_with_block_case(case),
        exact_config(),
    )

    assert record.state is MergeReadinessState.BLOCKED
    assert reason in record.reasons
    assert MergeReadinessReason.ALL_GATES_PASSED not in record.reasons


HOLD_CASES = (
    ("review_pending", MergeReadinessReason.REVIEW_PENDING),
    ("insufficient_approvals", MergeReadinessReason.INSUFFICIENT_APPROVALS),
    (
        "missing_authenticated_envelope",
        MergeReadinessReason.MISSING_AUTHENTICATED_ENVELOPE,
    ),
    (
        "verification_evidence_stale",
        MergeReadinessReason.VERIFICATION_EVIDENCE_STALE,
    ),
    (
        "insufficient_full_suite_test_count",
        MergeReadinessReason.INSUFFICIENT_FULL_SUITE_TEST_COUNT,
    ),
    (
        "prerequisites_not_integrated",
        MergeReadinessReason.PREREQUISITES_NOT_INTEGRATED,
    ),
    (
        "insufficient_migration_passes",
        MergeReadinessReason.INSUFFICIENT_MIGRATION_PASSES,
    ),
    (
        "missing_verification_artifact",
        MergeReadinessReason.MISSING_VERIFICATION_ARTIFACT,
    ),
    (
        "missing_integration_checkpoint",
        MergeReadinessReason.MISSING_INTEGRATION_CHECKPOINT,
    ),
)


def request_with_hold_case(case: str) -> MergeReadinessRequest:
    request = exact_ready_request()
    if case in {"review_pending", "insufficient_approvals"}:
        review_request = request.review.request
        summary = exact_review_summary(review_request, approval_count=1)
        review = exact_review_evidence(
            request=review_request,
            summary=summary,
            decision=exact_review_decision(review_request, summary),
        )
        return replace(request, review=review)
    if case == "missing_authenticated_envelope":
        return replace(
            request,
            review=replace(
                request.review,
                authenticated_envelope_evidence_sha256=None,
            ),
        )
    if case == "verification_evidence_stale":
        return replace(
            request,
            verification=replace(
                request.verification,
                evidence_age_seconds=3600.0000001,
            ),
        )
    if case == "insufficient_full_suite_test_count":
        return replace(
            request,
            verification=replace(request.verification, full_suite_test_count=499),
        )
    if case == "prerequisites_not_integrated":
        return replace(
            request,
            dependencies=replace(
                request.dependencies,
                prerequisites_integrated_into_observed_base=False,
            ),
        )
    if case == "insufficient_migration_passes":
        return replace(
            request,
            verification=replace(request.verification, migration_pass_count=1),
        )
    if case == "missing_verification_artifact":
        return replace(
            request,
            verification=replace(
                request.verification,
                verification_artifact_sha256=None,
            ),
        )
    if case == "missing_integration_checkpoint":
        return replace(
            request,
            verification=replace(
                request.verification,
                integration_checkpoint_sha256=None,
            ),
        )
    raise AssertionError(f"unknown hold case: {case}")


@pytest.mark.parametrize(("case", "reason"), HOLD_CASES)
def test_each_hold_condition_is_bounded(
    case: str,
    reason: MergeReadinessReason,
) -> None:
    record = ExactShaMergeReadinessGate().evaluate(
        request_with_hold_case(case),
        exact_config(),
    )

    assert record.state is MergeReadinessState.HOLD
    assert reason in record.reasons
    assert MergeReadinessReason.ALL_GATES_PASSED not in record.reasons


def test_hard_blocks_suppress_all_simultaneous_hold_reasons() -> None:
    request = exact_ready_request()
    review_request = request.review.request
    summary = exact_review_summary(
        review_request,
        approval_count=0,
        changes_required_count=1,
    )
    blocked = replace(
        request,
        candidate=replace(
            request.candidate,
            observed_candidate_head_sha=OTHER_GIT_SHA,
            observed_diff_sha256=digest("drifted-diff"),
        ),
        review=exact_review_evidence(
            request=review_request,
            summary=summary,
            decision=exact_review_decision(review_request, summary),
            authenticated_envelope_evidence_sha256=None,
            authentication_verified=False,
        ),
        verification=replace(
            request.verification,
            static_analysis_passed=False,
            full_suite_passed=False,
            evidence_age_seconds=7200.0,
            verification_artifact_sha256=None,
            integration_checkpoint_sha256=None,
        ),
        dependencies=replace(
            request.dependencies,
            prerequisites_integrated_into_observed_base=False,
            single_writer_reservation_active=False,
            protected_branch_policy_satisfied=False,
        ),
    )

    record = ExactShaMergeReadinessGate().evaluate(blocked, exact_config())

    assert record.state is MergeReadinessState.BLOCKED
    assert MergeReadinessReason.CANDIDATE_SHA_DRIFT in record.reasons
    assert MergeReadinessReason.REVIEW_BLOCKED in record.reasons
    assert MergeReadinessReason.STATIC_ANALYSIS_FAILED in record.reasons
    assert MergeReadinessReason.SINGLE_WRITER_POLICY_VIOLATION in record.reasons
    assert not set(record.reasons).intersection(
        {
            MergeReadinessReason.REVIEW_PENDING,
            MergeReadinessReason.INSUFFICIENT_APPROVALS,
            MergeReadinessReason.MISSING_AUTHENTICATED_ENVELOPE,
            MergeReadinessReason.VERIFICATION_EVIDENCE_STALE,
            MergeReadinessReason.PREREQUISITES_NOT_INTEGRATED,
            MergeReadinessReason.MISSING_VERIFICATION_ARTIFACT,
            MergeReadinessReason.MISSING_INTEGRATION_CHECKPOINT,
        }
    )


def test_freshness_threshold_equality_passes_and_nonfinite_values_fail() -> None:
    request = exact_ready_request(verification=exact_verification(evidence_age_seconds=3600.0))

    record = ExactShaMergeReadinessGate().evaluate(request, exact_config())

    assert record.state is MergeReadinessState.READY
    for value in (math.nan, math.inf, -math.inf):
        with pytest.raises(MergeReadinessValidationError, match="evidence age"):
            exact_verification(evidence_age_seconds=value)


def test_postgres_result_is_ignored_only_when_replay_is_not_required() -> None:
    request = exact_ready_request(
        verification=exact_verification(
            postgres_replay_required=False,
            postgres_replay_passed=False,
        )
    )

    record = ExactShaMergeReadinessGate().evaluate(request, exact_config())

    assert record.state is MergeReadinessState.READY
    assert MergeReadinessReason.POSTGRES_REPLAY_FAILED not in record.reasons


@pytest.mark.parametrize(
    "factory",
    [
        lambda: exact_config(maximum_evidence_age_seconds=True),
        lambda: exact_config(maximum_evidence_age_seconds=0.0),
        lambda: exact_config(minimum_full_suite_test_count=True),
        lambda: exact_config(minimum_full_suite_test_count=0),
        lambda: exact_config(minimum_migration_pass_count=True),
        lambda: exact_config(minimum_migration_pass_count=-1),
        lambda: exact_config(gate_policy_version="other-policy"),
        lambda: exact_candidate(exact_dependencies(), repository="invalid"),
        lambda: exact_candidate(exact_dependencies(), pull_request_number=True),
        lambda: exact_candidate(
            exact_dependencies(),
            expected_candidate_sha="A" * 40,
        ),
        lambda: exact_verification(full_suite_test_count=True),
        lambda: exact_verification(evidence_age_seconds=-1.0),
        lambda: exact_verification(static_analysis_passed=1),
        lambda: MergeDependencyIdentity(
            ordinal=True,
            component_key="component",
            candidate_sha="5" * 40,
        ),
        lambda: MergeDependencyIdentity(
            ordinal=1,
            component_key="Component Key",
            candidate_sha="5" * 40,
        ),
        lambda: MergeDependencyReadiness(
            dependencies=[],
            observed_dependency_chain_sha256=digest("chain"),
            prerequisites_integrated_into_observed_base=True,
            equivalent_duplicate_refs_excluded=True,
            single_writer_reservation_active=True,
            protected_branch_policy_satisfied=True,
        ),
    ],
)
def test_malformed_values_fail_closed(factory: object) -> None:
    with pytest.raises(MergeReadinessValidationError):
        factory()  # type: ignore[operator]


def test_dependency_order_and_identity_must_be_exact() -> None:
    first = MergeDependencyIdentity(
        ordinal=1,
        component_key="first",
        candidate_sha="5" * 40,
    )
    second_gap = MergeDependencyIdentity(
        ordinal=3,
        component_key="second",
        candidate_sha="6" * 40,
    )
    duplicate_component = MergeDependencyIdentity(
        ordinal=2,
        component_key="first",
        candidate_sha="6" * 40,
    )
    duplicate_sha = MergeDependencyIdentity(
        ordinal=2,
        component_key="second",
        candidate_sha="5" * 40,
    )

    for values in (
        (first, second_gap),
        (first, duplicate_component),
        (first, duplicate_sha),
        (),
    ):
        with pytest.raises(MergeReadinessValidationError, match="dependencies"):
            exact_dependencies(dependencies=values)


class HostileStr(str):
    def __str__(self) -> str:
        raise AssertionError("HOSTILE_SECRET")

    def __repr__(self) -> str:
        raise AssertionError("HOSTILE_SECRET")


class HostileTuple(tuple):
    def __iter__(self):  # type: ignore[no-untyped-def]
        raise AssertionError("HOSTILE_SECRET")


def test_hostile_subclasses_fail_without_exposing_caller_text() -> None:
    factories = (
        lambda: exact_candidate(
            exact_dependencies(),
            repository=HostileStr("leon36000/NextGen-Memory"),
        ),
        lambda: MergeDependencyReadiness(
            dependencies=HostileTuple(exact_dependencies().dependencies),
            observed_dependency_chain_sha256=digest("chain"),
            prerequisites_integrated_into_observed_base=True,
            equivalent_duplicate_refs_excluded=True,
            single_writer_reservation_active=True,
            protected_branch_policy_satisfied=True,
        ),
    )
    for factory in factories:
        with pytest.raises(MergeReadinessValidationError) as captured:
            factory()
        assert "HOSTILE_SECRET" not in str(captured.value)
        assert captured.value.__cause__ is None
        assert captured.value.__context__ is None


def test_every_public_value_is_frozen_slotted_and_canonical() -> None:
    request = exact_ready_request()
    config = exact_config()
    record = ExactShaMergeReadinessGate().evaluate(request, config)
    values = (
        config,
        request.candidate,
        request.review,
        request.verification,
        request.dependencies.dependencies[0],
        request.dependencies,
        request,
        record,
    )

    for value in values:
        raw = value.render_json()
        assert raw == canonical_json(json.loads(raw))
        assert not hasattr(value, "__dict__")

    with pytest.raises((AttributeError, FrozenInstanceError)):
        record.content_hash = digest("changed")  # type: ignore[misc]


def test_material_changes_change_request_or_record_identity() -> None:
    request = exact_ready_request()
    gate = ExactShaMergeReadinessGate()
    config = exact_config()
    original = gate.evaluate(request, config)
    variants = (
        replace(
            request,
            candidate=replace(
                request.candidate,
                observed_base_head_sha=OTHER_GIT_SHA,
            ),
        ),
        replace(
            request,
            review=replace(
                request.review,
                authentication_verified=False,
            ),
        ),
        replace(
            request,
            verification=replace(
                request.verification,
                evidence_age_seconds=120.0,
            ),
        ),
        replace(
            request,
            dependencies=replace(
                request.dependencies,
                prerequisites_integrated_into_observed_base=False,
            ),
        ),
    )

    for variant in variants:
        assert variant.content_hash != request.content_hash
        assert variant.id != request.id
        changed = gate.evaluate(variant, config)
        assert changed.content_hash != original.content_hash
        assert changed.id != original.id


def test_serialized_values_and_errors_are_privacy_safe() -> None:
    record = ExactShaMergeReadinessGate().evaluate(
        exact_ready_request(),
        exact_config(),
    )
    lowered = record.render_json().lower()
    for forbidden in (
        "raw_query",
        "prompt",
        "answer",
        "memory_body",
        "command_output",
        "credential",
        "github_token",
        "reviewer_email",
        "reviewer_name",
        "filesystem_path",
    ):
        assert forbidden not in lowered
