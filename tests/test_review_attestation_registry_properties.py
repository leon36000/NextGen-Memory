from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nextgen_memory.review_attestation_registry import (
    ExactShaReviewAttestation,
    ExactShaReviewRequest,
    InMemoryExactShaReviewAttestationRegistry,
    ReviewAdvisoryState,
    ReviewAttestationConflictError,
    ReviewAttestationValidationError,
    ReviewAttestationVerdict,
    ReviewFindingCode,
    ReviewerIdentity,
    ReviewModel,
)

ROOT = Path(__file__).resolve().parents[1]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fingerprints(index: int) -> tuple[str, str, str, str]:
    values = tuple(digest(f"reviewer:{index}:{offset}") for offset in range(4))
    return values[0], values[1], values[2], values[3]


def request_for(index: int, **overrides: object) -> ExactShaReviewRequest:
    values: dict[str, object] = {
        "repository": "leon36000/NextGen-Memory",
        "pull_request_number": index + 1,
        "base_sha": f"{index + 1:040x}"[-40:],
        "candidate_sha": f"{index + 100_001:040x}"[-40:],
        "diff_sha256": digest(f"diff:{index}"),
        "review_packet_sha256": digest(f"packet:{index}"),
        "acceptance_criteria_sha256": digest(f"criteria:{index}"),
        "required_model": ReviewModel.GPT_5_6_SOL,
        "trusted_reviewer_fingerprints": fingerprints(index),
        "minimum_approvals": 2,
    }
    values.update(overrides)
    return ExactShaReviewRequest(**values)  # type: ignore[arg-type]


def attestation_for(
    review_request: ExactShaReviewRequest,
    fingerprint: str,
    label: str,
    *,
    verdict: ReviewAttestationVerdict = ReviewAttestationVerdict.APPROVE,
    findings: object = (),
    **overrides: object,
) -> ExactShaReviewAttestation:
    values: dict[str, object] = {
        "request_id": review_request.id,
        "request_content_hash": review_request.content_hash,
        "repository": review_request.repository,
        "pull_request_number": review_request.pull_request_number,
        "candidate_sha": review_request.candidate_sha,
        "reviewer": ReviewerIdentity(
            model=ReviewModel.GPT_5_6_SOL,
            reviewer_key_fingerprint=fingerprint,
        ),
        "verdict": verdict,
        "finding_codes": findings,
        "review_artifact_sha256": digest(f"review:{label}"),
        "evidence_artifact_sha256s": {
            digest(f"evidence:{label}:a"),
            digest(f"evidence:{label}:b"),
        },
        "authenticated_envelope_sha256": digest(f"envelope:{label}"),
    }
    values.update(overrides)
    return ExactShaReviewAttestation(**values)  # type: ignore[arg-type]


def values_for_mode(
    review_request: ExactShaReviewRequest,
    index: int,
    mode: int,
) -> tuple[ExactShaReviewAttestation, ...]:
    reviewer_a, reviewer_b, reviewer_c, reviewer_d = (
        review_request.trusted_reviewer_fingerprints
    )
    values = [attestation_for(review_request, reviewer_a, f"{index}:a")]
    if mode in {1, 2, 3}:
        values.append(attestation_for(review_request, reviewer_b, f"{index}:b"))
    if mode in {2, 3}:
        values.append(
            attestation_for(
                review_request,
                reviewer_c,
                f"{index}:c",
                verdict=ReviewAttestationVerdict.BLOCKED_BY_EVIDENCE,
                findings=(ReviewFindingCode.MISSING_ARTIFACT,),
            )
        )
    if mode == 3:
        values.append(
            attestation_for(
                review_request,
                reviewer_d,
                f"{index}:d",
                verdict=ReviewAttestationVerdict.CHANGES_REQUIRED,
                findings=(ReviewFindingCode.CONTRACT_VIOLATION,),
            )
        )
    return tuple(values)


def test_five_thousand_generated_traces_preserve_state_and_retry_invariants() -> None:
    expected = {
        0: ReviewAdvisoryState.PENDING,
        1: ReviewAdvisoryState.APPROVED,
        2: ReviewAdvisoryState.EVIDENCE_BLOCKED,
        3: ReviewAdvisoryState.BLOCKED,
    }
    state_counts = {state: 0 for state in ReviewAdvisoryState}

    for index in range(5_000):
        mode = index % 4
        registry = InMemoryExactShaReviewAttestationRegistry()
        review_request = request_for(index)
        assert registry.register_request(review_request) is review_request
        assert registry.register_request(review_request) is review_request

        values = values_for_mode(review_request, index, mode)
        for value in values:
            assert registry.record_attestation(value) is value
            assert registry.record_attestation(value) is value

        summary = registry.summary(review_request.id)
        decision = registry.decision(review_request.id)
        assert registry.summary(review_request.id) == summary
        assert registry.decision(review_request.id) == decision
        assert decision.state is expected[mode]
        assert summary.registered_attestation_count == len(values)
        assert summary.distinct_reviewer_count == len(values)
        assert (
            summary.approval_count
            + summary.changes_required_count
            + summary.evidence_blocked_count
            == len(values)
        )
        state_counts[decision.state] += 1

    assert all(state_counts[state] > 0 for state in ReviewAdvisoryState)


def test_request_attestation_and_insertion_permutations_are_invariant() -> None:
    for index in range(250):
        reviewer_values = fingerprints(index)
        first_request = request_for(
            index,
            trusted_reviewer_fingerprints=reviewer_values,
        )
        second_request = request_for(
            index,
            trusted_reviewer_fingerprints=set(reversed(reviewer_values)),
        )
        assert first_request == second_request

        findings = (
            ReviewFindingCode.CONTRACT_VIOLATION,
            ReviewFindingCode.TEST_FAILURE,
        )
        first = attestation_for(
            first_request,
            reviewer_values[0],
            f"permutation:{index}",
            verdict=ReviewAttestationVerdict.CHANGES_REQUIRED,
            findings=findings,
            evidence_artifact_sha256s=(
                digest(f"evidence:{index}:a"),
                digest(f"evidence:{index}:b"),
            ),
        )
        second = attestation_for(
            second_request,
            reviewer_values[0],
            f"permutation:{index}",
            verdict=ReviewAttestationVerdict.CHANGES_REQUIRED,
            findings=set(reversed(findings)),
            evidence_artifact_sha256s={
                digest(f"evidence:{index}:b"),
                digest(f"evidence:{index}:a"),
            },
        )
        assert first == second

        first_registry = InMemoryExactShaReviewAttestationRegistry()
        second_registry = InMemoryExactShaReviewAttestationRegistry()
        first_registry.register_request(first_request)
        second_registry.register_request(second_request)
        for value in values_for_mode(first_request, index, 3):
            first_registry.record_attestation(value)
        for value in reversed(values_for_mode(second_request, index, 3)):
            second_registry.record_attestation(value)
        assert first_registry.summary(first_request.id) == second_registry.summary(
            second_request.id
        )
        assert first_registry.decision(first_request.id) == second_registry.decision(
            second_request.id
        )


def test_material_request_and_attestation_fields_change_identity() -> None:
    base_request = request_for(600_000)
    request_mutations: tuple[dict[str, object], ...] = (
        {"repository": "other/Repository"},
        {"pull_request_number": base_request.pull_request_number + 1},
        {"base_sha": "a" * 40},
        {"candidate_sha": "b" * 40},
        {"diff_sha256": "c" * 64},
        {"review_packet_sha256": "d" * 64},
        {"acceptance_criteria_sha256": "e" * 64},
        {
            "trusted_reviewer_fingerprints": (
                *fingerprints(600_000),
                digest("extra-reviewer"),
            )
        },
        {"minimum_approvals": 3},
    )
    for mutation in request_mutations:
        changed = request_for(600_000, **mutation)
        assert changed.id != base_request.id
        assert changed.content_hash != base_request.content_hash

    fingerprint = base_request.trusted_reviewer_fingerprints[0]
    base_attestation = attestation_for(base_request, fingerprint, "material")
    attestation_mutations: tuple[dict[str, object], ...] = (
        {"request_content_hash": "a" * 64},
        {"repository": "other/Repository"},
        {"pull_request_number": base_request.pull_request_number + 1},
        {"candidate_sha": "b" * 40},
        {"review_artifact_sha256": "c" * 64},
        {"evidence_artifact_sha256s": ("d" * 64,)},
        {"authenticated_envelope_sha256": "e" * 64},
    )
    for mutation in attestation_mutations:
        changed = attestation_for(
            base_request,
            fingerprint,
            "material",
            **mutation,
        )
        assert changed.id != base_attestation.id
        assert changed.content_hash != base_attestation.content_hash

    changed_verdict = attestation_for(
        base_request,
        fingerprint,
        "material",
        verdict=ReviewAttestationVerdict.CHANGES_REQUIRED,
        findings=(ReviewFindingCode.CONTRACT_VIOLATION,),
    )
    assert changed_verdict.id != base_attestation.id
    with pytest.raises(ReviewAttestationValidationError):
        request_for(600_000, required_model="gpt-5.6-sol")


def test_changed_reviewer_retry_conflicts_without_partial_mutation() -> None:
    review_request = request_for(700_000)
    fingerprint = review_request.trusted_reviewer_fingerprints[0]
    registry = InMemoryExactShaReviewAttestationRegistry()
    registry.register_request(review_request)
    first = registry.record_attestation(
        attestation_for(review_request, fingerprint, "first")
    )
    before = registry.summary(review_request.id)

    with pytest.raises(ReviewAttestationConflictError):
        registry.record_attestation(
            attestation_for(review_request, fingerprint, "changed")
        )

    assert registry.summary(review_request.id) == before
    assert registry.attestations(review_request.id) == (first,)


def test_process_hash_seed_does_not_change_summary_or_decision_json() -> None:
    script = r'''
import hashlib
import json
from nextgen_memory.review_attestation_registry import (
    ExactShaReviewAttestation,
    ExactShaReviewRequest,
    InMemoryExactShaReviewAttestationRegistry,
    ReviewAttestationVerdict,
    ReviewerIdentity,
    ReviewModel,
)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


reviewers = {digest("reviewer-a"), digest("reviewer-b"), digest("reviewer-c")}
request = ExactShaReviewRequest(
    repository="leon36000/NextGen-Memory",
    pull_request_number=172,
    base_sha="1" * 40,
    candidate_sha="2" * 40,
    diff_sha256="3" * 64,
    review_packet_sha256="4" * 64,
    acceptance_criteria_sha256="5" * 64,
    required_model=ReviewModel.GPT_5_6_SOL,
    trusted_reviewer_fingerprints=reviewers,
    minimum_approvals=2,
)
registry = InMemoryExactShaReviewAttestationRegistry()
registry.register_request(request)
for index, fingerprint in enumerate(sorted(reviewers)[:2]):
    registry.record_attestation(
        ExactShaReviewAttestation(
            request_id=request.id,
            request_content_hash=request.content_hash,
            repository=request.repository,
            pull_request_number=request.pull_request_number,
            candidate_sha=request.candidate_sha,
            reviewer=ReviewerIdentity(
                model=ReviewModel.GPT_5_6_SOL,
                reviewer_key_fingerprint=fingerprint,
            ),
            verdict=ReviewAttestationVerdict.APPROVE,
            finding_codes=set(),
            review_artifact_sha256=digest(f"review:{index}"),
            evidence_artifact_sha256s={
                digest(f"evidence:{index}:a"),
                digest(f"evidence:{index}:b"),
            },
            authenticated_envelope_sha256=digest(f"envelope:{index}"),
        )
    )
payload = {
    "summary": json.loads(registry.summary(request.id).render_json()),
    "decision": json.loads(registry.decision(request.id).render_json()),
}
print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
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
    payload = json.loads(outputs[0])
    assert payload["decision"]["state"] == "approved"
    assert payload["summary"]["approval_count"] == 2
