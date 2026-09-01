from __future__ import annotations

import hashlib
from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5

import pytest

from nextgen_memory import (
    ExactShaReviewRequest,
    ReviewAdvisoryState,
    ReviewAttestationDecision,
    ReviewAttestationRegistrySummary,
    ReviewModel,
)
from nextgen_memory.merge_readiness_gate import (
    ExactReviewReadinessEvidence,
    ExactShaMergeReadinessGate,
    MergeCandidateIdentity,
    MergeDependencyIdentity,
    MergeDependencyReadiness,
    MergeReadinessConfig,
    MergeReadinessReason,
    MergeReadinessRequest,
    MergeReadinessState,
    MergeReadinessValidationError,
    MergeVerificationEvidence,
)

BASE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
DIFF_SHA = "3" * 64
OTHER_GIT_SHA = "4" * 40
POLICY_VERSION = "exact-sha-merge-readiness-v0"


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def review_request() -> ExactShaReviewRequest:
    return ExactShaReviewRequest(
        repository="leon36000/NextGen-Memory",
        pull_request_number=185,
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        diff_sha256=DIFF_SHA,
        review_packet_sha256=digest("review-packet"),
        acceptance_criteria_sha256=digest("acceptance-criteria"),
        required_model=ReviewModel.GPT_5_6_SOL,
        trusted_reviewer_fingerprints=(digest("reviewer-a"), digest("reviewer-b")),
        minimum_approvals=2,
    )


def review_evidence(*, authentication_verified: bool = True) -> ExactReviewReadinessEvidence:
    req = review_request()
    ids = tuple(uuid5(NAMESPACE_URL, f"merge-readiness-test-attestation:{i}") for i in range(2))
    summary = ReviewAttestationRegistrySummary(
        request_id=req.id,
        request_content_hash=req.content_hash,
        attestation_ids=ids,
        registered_attestation_count=2,
        approval_count=2,
        changes_required_count=0,
        evidence_blocked_count=0,
        distinct_reviewer_count=2,
        missing_approval_count=0,
    )
    decision = ReviewAttestationDecision(
        request_id=req.id,
        request_content_hash=req.content_hash,
        state=ReviewAdvisoryState.APPROVED,
        summary_content_hash=summary.content_hash,
        advisory_only=True,
    )
    return ExactReviewReadinessEvidence(
        request=req,
        summary=summary,
        decision=decision,
        authenticated_envelope_evidence_sha256=digest("authenticated-envelope"),
        authentication_verified=authentication_verified,
    )


def dependencies(*, single_writer: bool = True) -> MergeDependencyReadiness:
    deps = (
        MergeDependencyIdentity(1, "policy-promotion-gate-v0", "5" * 40),
        MergeDependencyIdentity(2, "review-attestation-registry-v0", CANDIDATE_SHA),
    )
    temp = MergeDependencyReadiness(
        dependencies=deps,
        observed_dependency_chain_sha256=digest("temporary-chain"),
        prerequisites_integrated_into_observed_base=True,
        equivalent_duplicate_refs_excluded=True,
        single_writer_reservation_active=single_writer,
        protected_branch_policy_satisfied=True,
    )
    return replace(temp, observed_dependency_chain_sha256=temp.computed_dependency_chain_sha256)


def candidate(
    deps: MergeDependencyReadiness,
    *,
    observed_candidate_head_sha: str = CANDIDATE_SHA,
) -> MergeCandidateIdentity:
    return MergeCandidateIdentity(
        repository="leon36000/NextGen-Memory",
        pull_request_number=185,
        expected_base_sha=BASE_SHA,
        observed_base_head_sha=BASE_SHA,
        expected_candidate_sha=CANDIDATE_SHA,
        observed_candidate_head_sha=observed_candidate_head_sha,
        expected_diff_sha256=DIFF_SHA,
        observed_diff_sha256=DIFF_SHA,
        expected_dependency_chain_sha256=deps.computed_dependency_chain_sha256,
        merge_policy_version=POLICY_VERSION,
    )


def verification(
    *,
    static_analysis_passed: bool = True,
    evidence_age_seconds: float = 60.0,
) -> MergeVerificationEvidence:
    return MergeVerificationEvidence(
        base_sha=BASE_SHA,
        candidate_sha=CANDIDATE_SHA,
        diff_sha256=DIFF_SHA,
        static_analysis_passed=static_analysis_passed,
        compile_passed=True,
        full_suite_passed=True,
        full_suite_test_count=587,
        artifact_integrity_passed=True,
        isolated_wheel_passed=True,
        integration_rehearsal_passed=True,
        cross_python_semantic_identity_passed=True,
        postgres_replay_required=True,
        postgres_replay_passed=True,
        migration_pass_count=2,
        verification_artifact_sha256=digest("verification-artifact"),
        integration_checkpoint_sha256=digest("integration-checkpoint"),
        evidence_age_seconds=evidence_age_seconds,
    )


def config(*, max_age: float = 3600.0) -> MergeReadinessConfig:
    return MergeReadinessConfig(
        maximum_evidence_age_seconds=max_age,
        minimum_full_suite_test_count=500,
        minimum_migration_pass_count=2,
        gate_policy_version=POLICY_VERSION,
    )


def ready_request(
    *,
    review: ExactReviewReadinessEvidence | None = None,
    verify: MergeVerificationEvidence | None = None,
    deps: MergeDependencyReadiness | None = None,
    cand: MergeCandidateIdentity | None = None,
) -> MergeReadinessRequest:
    d = dependencies() if deps is None else deps
    return MergeReadinessRequest(
        candidate=candidate(d) if cand is None else cand,
        review=review_evidence() if review is None else review,
        verification=verification() if verify is None else verify,
        dependencies=d,
    )


def assert_ready(req: MergeReadinessRequest, cfg: MergeReadinessConfig | None = None) -> None:
    record = ExactShaMergeReadinessGate().evaluate(req, config() if cfg is None else cfg)
    assert record.state is MergeReadinessState.READY


def test_probe_verification_mutation_fails_closed() -> None:
    req = ready_request(verify=verification(static_analysis_passed=False))
    gate = ExactShaMergeReadinessGate()
    assert gate.evaluate(req, config()).state is MergeReadinessState.BLOCKED
    object.__setattr__(req.verification, "static_analysis_passed", True)
    with pytest.raises(MergeReadinessValidationError):
        gate.evaluate(req, config())


def test_probe_review_authentication_mutation_fails_closed() -> None:
    req = ready_request(review=review_evidence(authentication_verified=False))
    gate = ExactShaMergeReadinessGate()
    assert gate.evaluate(req, config()).state is MergeReadinessState.BLOCKED
    object.__setattr__(req.review, "authentication_verified", True)
    with pytest.raises(MergeReadinessValidationError):
        gate.evaluate(req, config())


def test_probe_single_writer_mutation_fails_closed() -> None:
    d = dependencies(single_writer=False)
    req = ready_request(deps=d, cand=candidate(d))
    gate = ExactShaMergeReadinessGate()
    assert gate.evaluate(req, config()).state is MergeReadinessState.BLOCKED
    object.__setattr__(req.dependencies, "single_writer_reservation_active", True)
    with pytest.raises(MergeReadinessValidationError):
        gate.evaluate(req, config())


def test_probe_candidate_head_mutation_fails_closed() -> None:
    d = dependencies()
    req = ready_request(deps=d, cand=candidate(d, observed_candidate_head_sha=OTHER_GIT_SHA))
    gate = ExactShaMergeReadinessGate()
    assert gate.evaluate(req, config()).state is MergeReadinessState.BLOCKED
    object.__setattr__(req.candidate, "observed_candidate_head_sha", CANDIDATE_SHA)
    with pytest.raises(MergeReadinessValidationError):
        gate.evaluate(req, config())


def test_probe_config_mutation_fails_closed() -> None:
    req = ready_request(verify=verification(evidence_age_seconds=60.0))
    cfg = config(max_age=1.0)
    gate = ExactShaMergeReadinessGate()
    assert gate.evaluate(req, cfg).state is MergeReadinessState.HOLD
    object.__setattr__(cfg, "maximum_evidence_age_seconds", 3600.0)
    with pytest.raises(MergeReadinessValidationError):
        gate.evaluate(req, cfg)


def test_nested_dependency_identity_mutation_breaks_parent_integrity() -> None:
    req = ready_request()
    object.__setattr__(
        req.dependencies.dependencies[0],
        "component_key",
        "policy-promotion-gate-v1",
    )
    with pytest.raises(MergeReadinessValidationError):
        req.dependencies.to_dict()
    with pytest.raises(MergeReadinessValidationError):
        ExactShaMergeReadinessGate().evaluate(req, config())


def test_request_reference_swap_and_identity_tampering_fail_closed() -> None:
    req = ready_request()
    d2 = dependencies()
    different_candidate = replace(candidate(d2), pull_request_number=186)
    object.__setattr__(req, "candidate", different_candidate)
    with pytest.raises(MergeReadinessValidationError):
        ExactShaMergeReadinessGate().evaluate(req, config())

    req2 = ready_request()
    object.__setattr__(req2, "content_hash", digest("forged-request"))
    with pytest.raises(MergeReadinessValidationError):
        req2.to_dict()

    req3 = ready_request()
    object.__setattr__(req3, "id", uuid5(NAMESPACE_URL, "forged-request-id"))
    with pytest.raises(MergeReadinessValidationError):
        req3.to_dict()


def test_record_mutation_cannot_be_serialized_as_ready() -> None:
    req = ready_request(verify=verification(static_analysis_passed=False))
    record = ExactShaMergeReadinessGate().evaluate(req, config())
    assert record.state is MergeReadinessState.BLOCKED
    object.__setattr__(record, "state", MergeReadinessState.READY)
    object.__setattr__(record, "reasons", (MergeReadinessReason.ALL_GATES_PASSED,))
    with pytest.raises(MergeReadinessValidationError):
        record.to_dict()
    with pytest.raises(MergeReadinessValidationError):
        record.render_json()


def test_record_hash_id_and_advisory_tampering_fail_closed() -> None:
    record = ExactShaMergeReadinessGate().evaluate(ready_request(), config())
    object.__setattr__(record, "advisory_only", False)
    with pytest.raises(MergeReadinessValidationError):
        record.to_dict()

    record2 = ExactShaMergeReadinessGate().evaluate(ready_request(), config())
    object.__setattr__(record2, "content_hash", digest("forged-record"))
    with pytest.raises(MergeReadinessValidationError):
        record2.to_dict()

    record3 = ExactShaMergeReadinessGate().evaluate(ready_request(), config())
    object.__setattr__(record3, "id", uuid5(NAMESPACE_URL, "forged-record-id"))
    with pytest.raises(MergeReadinessValidationError):
        record3.to_dict()


def test_component_serializers_revalidate_current_payloads() -> None:
    cfg = config()
    object.__setattr__(cfg, "minimum_full_suite_test_count", 1)
    with pytest.raises(MergeReadinessValidationError):
        cfg.to_dict()

    d = dependencies()
    cand = candidate(d)
    object.__setattr__(cand, "observed_diff_sha256", digest("forged-diff"))
    with pytest.raises(MergeReadinessValidationError):
        cand.to_dict()

    rev = review_evidence()
    object.__setattr__(rev, "authenticated_envelope_evidence_sha256", None)
    with pytest.raises(MergeReadinessValidationError):
        rev.to_dict()

    ver = verification()
    object.__setattr__(ver, "full_suite_test_count", 0)
    with pytest.raises(MergeReadinessValidationError):
        ver.to_dict()

    dep = MergeDependencyIdentity(1, "policy-promotion-gate-v0", "5" * 40)
    object.__setattr__(dep, "candidate_sha", "6" * 40)
    with pytest.raises(MergeReadinessValidationError):
        dep.to_dict()
