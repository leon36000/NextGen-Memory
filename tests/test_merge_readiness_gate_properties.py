from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

from test_merge_readiness_gate import (
    CANDIDATE_SHA,
    OTHER_GIT_SHA,
    ExactShaMergeReadinessGate,
    MergeReadinessReason,
    MergeReadinessState,
    exact_config,
    exact_ready_request,
)

ROOT = Path(__file__).resolve().parents[1]


def test_five_thousand_generated_readiness_cases_preserve_precedence() -> None:
    gate = ExactShaMergeReadinessGate()
    config = exact_config()
    counts = {state: 0 for state in MergeReadinessState}

    for index in range(5_000):
        mode = index % 5
        request = exact_ready_request()
        if mode == 0:
            expected = MergeReadinessState.READY
        elif mode == 1:
            request = replace(
                request,
                verification=replace(
                    request.verification,
                    evidence_age_seconds=3600.0 + (index + 1) / 1_000_000,
                ),
            )
            expected = MergeReadinessState.HOLD
        elif mode == 2:
            request = replace(
                request,
                candidate=replace(
                    request.candidate,
                    observed_candidate_head_sha=OTHER_GIT_SHA,
                ),
            )
            expected = MergeReadinessState.BLOCKED
        elif mode == 3:
            request = replace(
                request,
                candidate=replace(
                    request.candidate,
                    observed_diff_sha256=f"{index + 1:064x}"[-64:],
                ),
                verification=replace(
                    request.verification,
                    evidence_age_seconds=7200.0,
                    verification_artifact_sha256=None,
                ),
                dependencies=replace(
                    request.dependencies,
                    prerequisites_integrated_into_observed_base=False,
                ),
            )
            expected = MergeReadinessState.BLOCKED
        else:
            above = index % 10 == 4
            request = replace(
                request,
                verification=replace(
                    request.verification,
                    evidence_age_seconds=(
                        3600.0000001 if above else 3600.0
                    ),
                ),
            )
            expected = (
                MergeReadinessState.HOLD
                if above
                else MergeReadinessState.READY
            )

        first = gate.evaluate(request, config)
        second = gate.evaluate(request, config)
        assert first == second
        assert first.render_json() == second.render_json()
        assert first.state is expected
        assert len(first.reasons) == len(set(first.reasons))
        counts[first.state] += 1

        if first.state is MergeReadinessState.READY:
            assert first.reasons == (MergeReadinessReason.ALL_GATES_PASSED,)
        elif first.state is MergeReadinessState.HOLD:
            assert MergeReadinessReason.ALL_GATES_PASSED not in first.reasons
            assert MergeReadinessReason.CANDIDATE_SHA_DRIFT not in first.reasons
        else:
            assert MergeReadinessReason.ALL_GATES_PASSED not in first.reasons
            assert not set(first.reasons).intersection(
                {
                    MergeReadinessReason.VERIFICATION_EVIDENCE_STALE,
                    MergeReadinessReason.PREREQUISITES_NOT_INTEGRATED,
                    MergeReadinessReason.MISSING_VERIFICATION_ARTIFACT,
                }
            )

    assert all(counts[state] > 0 for state in MergeReadinessState)


def test_one_thousand_exact_retries_are_byte_identical() -> None:
    gate = ExactShaMergeReadinessGate()
    request = exact_ready_request()
    config = exact_config()

    values = {
        (
            str(record.id),
            record.content_hash,
            record.render_json(),
        )
        for record in (gate.evaluate(request, config) for _ in range(1_000))
    }

    assert len(values) == 1


def test_process_hash_seed_does_not_change_ready_record_json() -> None:
    script = r'''
from dataclasses import replace
from uuid import NAMESPACE_URL, uuid5
import hashlib

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
    MergeReadinessRequest,
    MergeVerificationEvidence,
)


def digest(label):
    return hashlib.sha256(label.encode("utf-8")).hexdigest()

base_sha = "1" * 40
candidate_sha = "2" * 40
diff_sha = "3" * 64
reviewers = {digest("reviewer-a"), digest("reviewer-b")}
review_request = ExactShaReviewRequest(
    repository="leon36000/NextGen-Memory",
    pull_request_number=185,
    base_sha=base_sha,
    candidate_sha=candidate_sha,
    diff_sha256=diff_sha,
    review_packet_sha256=digest("packet"),
    acceptance_criteria_sha256=digest("criteria"),
    required_model=ReviewModel.GPT_5_6_SOL,
    trusted_reviewer_fingerprints=reviewers,
    minimum_approvals=2,
)
attestation_ids = tuple(
    uuid5(NAMESPACE_URL, f"seed-review:{index}")
    for index in range(2)
)
summary = ReviewAttestationRegistrySummary(
    request_id=review_request.id,
    request_content_hash=review_request.content_hash,
    attestation_ids=attestation_ids,
    registered_attestation_count=2,
    approval_count=2,
    changes_required_count=0,
    evidence_blocked_count=0,
    distinct_reviewer_count=2,
    missing_approval_count=0,
)
decision = ReviewAttestationDecision(
    request_id=review_request.id,
    request_content_hash=review_request.content_hash,
    state=ReviewAdvisoryState.APPROVED,
    summary_content_hash=summary.content_hash,
    advisory_only=True,
)
review = ExactReviewReadinessEvidence(
    request=review_request,
    summary=summary,
    decision=decision,
    authenticated_envelope_evidence_sha256=digest("envelope"),
    authentication_verified=True,
)
dependency_values = (
    MergeDependencyIdentity(
        ordinal=1,
        component_key="policy-promotion-gate-v0",
        candidate_sha="5" * 40,
    ),
    MergeDependencyIdentity(
        ordinal=2,
        component_key="review-attestation-registry-v0",
        candidate_sha=candidate_sha,
    ),
)
dependencies = MergeDependencyReadiness(
    dependencies=dependency_values,
    observed_dependency_chain_sha256=digest("temporary"),
    prerequisites_integrated_into_observed_base=True,
    equivalent_duplicate_refs_excluded=True,
    single_writer_reservation_active=True,
    protected_branch_policy_satisfied=True,
)
dependencies = replace(
    dependencies,
    observed_dependency_chain_sha256=dependencies.computed_dependency_chain_sha256,
)
candidate = MergeCandidateIdentity(
    repository="leon36000/NextGen-Memory",
    pull_request_number=185,
    expected_base_sha=base_sha,
    observed_base_head_sha=base_sha,
    expected_candidate_sha=candidate_sha,
    observed_candidate_head_sha=candidate_sha,
    expected_diff_sha256=diff_sha,
    observed_diff_sha256=diff_sha,
    expected_dependency_chain_sha256=dependencies.computed_dependency_chain_sha256,
    merge_policy_version="exact-sha-merge-readiness-v0",
)
verification = MergeVerificationEvidence(
    base_sha=base_sha,
    candidate_sha=candidate_sha,
    diff_sha256=diff_sha,
    static_analysis_passed=True,
    compile_passed=True,
    full_suite_passed=True,
    full_suite_test_count=521,
    artifact_integrity_passed=True,
    isolated_wheel_passed=True,
    integration_rehearsal_passed=True,
    cross_python_semantic_identity_passed=True,
    postgres_replay_required=True,
    postgres_replay_passed=True,
    migration_pass_count=2,
    verification_artifact_sha256=digest("artifact"),
    integration_checkpoint_sha256=digest("checkpoint"),
    evidence_age_seconds=60.0,
)
request = MergeReadinessRequest(
    candidate=candidate,
    review=review,
    verification=verification,
    dependencies=dependencies,
)
config = MergeReadinessConfig(
    maximum_evidence_age_seconds=3600.0,
    minimum_full_suite_test_count=500,
    minimum_migration_pass_count=2,
    gate_policy_version="exact-sha-merge-readiness-v0",
)
print(ExactShaMergeReadinessGate().evaluate(request, config).render_json(), end="")
'''
    outputs: list[str] = []
    for seed in ("1", "37", "999"):
        environment = dict(os.environ)
        environment["PYTHONHASHSEED"] = seed
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        outputs.append(completed.stdout)

    assert len(set(outputs)) == 1
    assert json.loads(outputs[0])["state"] == "READY"
    assert CANDIDATE_SHA not in outputs[0]
