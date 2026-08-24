from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID

from nextgen_memory.policy_promotion_gate import (
    AdvisoryPolicyPromotionGate,
    PairedPolicyEvidence,
    PolicyIdentity,
    PolicyOperationalReadiness,
    PolicyPromotionDecision,
    PolicyPromotionGateConfig,
    PolicyPromotionRequest,
)

from nextgen_memory.paired_rerank_policy_evaluation import PairedPolicyVerdict

ROOT = Path(__file__).resolve().parents[1]
CURRENT_FP = "1" * 64
CANDIDATE_FP = "2" * 64
CURRENT_SHA = "3" * 40
CANDIDATE_SHA = "4" * 40


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def current_identity() -> PolicyIdentity:
    return PolicyIdentity(
        policy_version="control-v1",
        policy_fingerprint=CURRENT_FP,
        source_sha=CURRENT_SHA,
    )


def candidate_identity() -> PolicyIdentity:
    return PolicyIdentity(
        policy_version="treatment-v1",
        policy_fingerprint=CANDIDATE_FP,
        source_sha=CANDIDATE_SHA,
    )


def evidence_for(index: int) -> PairedPolicyEvidence:
    matched = 20 + (index % 17)
    mean = 0.03 + ((index % 11) * 0.002)
    lower = mean - 0.02
    upper = mean + 0.02
    return PairedPolicyEvidence(
        evaluation_id=UUID(f"00000000-0000-5000-8000-{index + 1:012x}"),
        evaluation_content_hash=digest(f"evaluation:{index}"),
        control_policy_version="control-v1",
        control_policy_fingerprint=CURRENT_FP,
        treatment_policy_version="treatment-v1",
        treatment_policy_fingerprint=CANDIDATE_FP,
        evaluated_base_sha=CURRENT_SHA,
        evaluated_candidate_sha=CANDIDATE_SHA,
        verdict=PairedPolicyVerdict.PROMISING,
        matched_pair_count=matched,
        mean_score_effect=mean,
        score_confidence_lower_bound=lower,
        score_confidence_upper_bound=upper,
        score_standard_error=0.01 + ((index % 5) * 0.003),
        mean_token_delta=float(index % 7),
        mean_latency_delta_ms=float(index % 13),
        harm_rate=(index % 4) * 0.005,
        registry_summary_content_hash=digest(f"registry:{index}"),
        registry_pair_count=matched,
        registry_completed_trial_count=matched,
        registry_failed_count=0,
        registry_cancelled_count=0,
        registry_active_count=0,
    )


def readiness_for(index: int) -> PolicyOperationalReadiness:
    return PolicyOperationalReadiness(
        tests_passed=True,
        integration_passed=True,
        artifact_integrity_passed=True,
        rollback_ready=True,
        safety_violation=False,
        reviewer_count=2 + (index % 3),
        evidence_age_seconds=float(index % 1_000),
    )


def gate_config() -> PolicyPromotionGateConfig:
    return PolicyPromotionGateConfig(
        minimum_matched_pairs=20,
        minimum_score_lower_bound=0.0,
        maximum_score_standard_error=0.05,
        maximum_mean_token_delta=10.0,
        maximum_mean_latency_delta_ms=20.0,
        maximum_harm_rate=0.05,
        maximum_evidence_age_seconds=3_600.0,
        minimum_reviewer_count=2,
        gate_policy_version="advisory-policy-promotion-gate-v0",
    )


def request_for(index: int) -> PolicyPromotionRequest:
    return PolicyPromotionRequest(
        current_policy=current_identity(),
        candidate_policy=candidate_identity(),
        evaluation=evidence_for(index),
        readiness=readiness_for(index),
    )


def test_five_thousand_generated_valid_requests_are_deterministic() -> None:
    gate = AdvisoryPolicyPromotionGate()
    configuration = gate_config()

    for index in range(5_000):
        promotion_request = request_for(index)
        first = gate.evaluate(promotion_request, configuration)
        second = gate.evaluate(promotion_request, configuration)

        assert first == second
        assert first.id == second.id
        assert first.content_hash == second.content_hash
        assert first.request_content_hash == promotion_request.content_hash
        assert first.decision is PolicyPromotionDecision.PROMOTE
        assert first.advisory_only is True
        assert len(first.content_hash) == 64
        assert first.id.version == 5
        assert json.loads(first.render_json())["decision"] == "promote"


def test_generated_reject_precedence_never_degrades_to_hold() -> None:
    gate = AdvisoryPolicyPromotionGate()
    configuration = gate_config()

    for index in range(1_000):
        base = evidence_for(index)
        hostile = replace(
            base,
            verdict=PairedPolicyVerdict.HARMFUL,
            matched_pair_count=1,
            mean_score_effect=-0.01,
            score_confidence_lower_bound=-0.02,
            score_confidence_upper_bound=0.0,
            score_standard_error=0.1,
            mean_token_delta=11.0,
            mean_latency_delta_ms=21.0,
            harm_rate=0.06,
            registry_pair_count=2,
            registry_completed_trial_count=1,
            registry_active_count=1,
        )
        operational = replace(
            readiness_for(index),
            tests_passed=False,
            integration_passed=False,
            artifact_integrity_passed=False,
            rollback_ready=False,
            safety_violation=index % 2 == 0,
            reviewer_count=0,
            evidence_age_seconds=10_000.0,
        )
        promotion_request = PolicyPromotionRequest(
            current_policy=current_identity(),
            candidate_policy=candidate_identity(),
            evaluation=hostile,
            readiness=operational,
        )

        record = gate.evaluate(promotion_request, configuration)

        assert record.decision is PolicyPromotionDecision.REJECT
        assert record.advisory_only is True


def test_material_inputs_change_record_identity() -> None:
    gate = AdvisoryPolicyPromotionGate()
    configuration = gate_config()
    original_request = request_for(77)
    original = gate.evaluate(original_request, configuration)

    mutations = (
        replace(
            original_request,
            current_policy=replace(
                original_request.current_policy,
                policy_version="control-v2",
            ),
        ),
        replace(
            original_request,
            candidate_policy=replace(
                original_request.candidate_policy,
                source_sha="5" * 40,
            ),
        ),
        replace(
            original_request,
            evaluation=replace(
                original_request.evaluation,
                evaluation_content_hash=digest("changed-evaluation"),
            ),
        ),
        replace(
            original_request,
            readiness=replace(
                original_request.readiness,
                evidence_age_seconds=61.0,
            ),
        ),
    )
    configuration_mutations = (
        replace(configuration, minimum_matched_pairs=21),
        replace(configuration, maximum_score_standard_error=0.049),
        replace(configuration, gate_policy_version="advisory-policy-promotion-gate-v0.1"),
    )

    identities: set[tuple[UUID, str]] = {(original.id, original.content_hash)}
    for mutated in mutations:
        record = gate.evaluate(mutated, configuration)
        assert record.request_content_hash != original.request_content_hash
        identities.add((record.id, record.content_hash))
    for mutated_config in configuration_mutations:
        record = gate.evaluate(original_request, mutated_config)
        assert record.config_content_hash != original.config_content_hash
        identities.add((record.id, record.content_hash))

    assert len(identities) == 1 + len(mutations) + len(configuration_mutations)


def test_one_ulp_threshold_neighborhoods_are_stable() -> None:
    gate = AdvisoryPolicyPromotionGate()
    configuration = gate_config()
    base_request = request_for(88)

    at_cost = replace(
        base_request,
        evaluation=replace(
            base_request.evaluation,
            mean_token_delta=configuration.maximum_mean_token_delta,
        ),
    )
    above_cost = replace(
        base_request,
        evaluation=replace(
            base_request.evaluation,
            mean_token_delta=math.nextafter(
                configuration.maximum_mean_token_delta,
                math.inf,
            ),
        ),
    )
    at_age = replace(
        base_request,
        readiness=replace(
            base_request.readiness,
            evidence_age_seconds=configuration.maximum_evidence_age_seconds,
        ),
    )
    above_age = replace(
        base_request,
        readiness=replace(
            base_request.readiness,
            evidence_age_seconds=math.nextafter(
                configuration.maximum_evidence_age_seconds,
                math.inf,
            ),
        ),
    )

    assert gate.evaluate(at_cost, configuration).decision is PolicyPromotionDecision.PROMOTE
    assert gate.evaluate(above_cost, configuration).decision is PolicyPromotionDecision.REJECT
    assert gate.evaluate(at_age, configuration).decision is PolicyPromotionDecision.PROMOTE
    assert gate.evaluate(above_age, configuration).decision is PolicyPromotionDecision.HOLD


def test_process_hash_seed_does_not_change_record_json() -> None:
    script = r"""
from uuid import UUID

from nextgen_memory.paired_rerank_policy_evaluation import PairedPolicyVerdict
from nextgen_memory.policy_promotion_gate import (
    AdvisoryPolicyPromotionGate,
    PairedPolicyEvidence,
    PolicyIdentity,
    PolicyOperationalReadiness,
    PolicyPromotionGateConfig,
    PolicyPromotionRequest,
)

current = PolicyIdentity(
    policy_version="control-v1", policy_fingerprint="1" * 64, source_sha="3" * 40
)
candidate = PolicyIdentity(
    policy_version="treatment-v1", policy_fingerprint="2" * 64, source_sha="4" * 40
)
evidence = PairedPolicyEvidence(
    evaluation_id=UUID("00000000-0000-5000-8000-000000001111"),
    evaluation_content_hash="5" * 64,
    control_policy_version=current.policy_version,
    control_policy_fingerprint=current.policy_fingerprint,
    treatment_policy_version=candidate.policy_version,
    treatment_policy_fingerprint=candidate.policy_fingerprint,
    evaluated_base_sha=current.source_sha,
    evaluated_candidate_sha=candidate.source_sha,
    verdict=PairedPolicyVerdict.PROMISING,
    matched_pair_count=24,
    mean_score_effect=0.08,
    score_confidence_lower_bound=0.04,
    score_confidence_upper_bound=0.12,
    score_standard_error=0.02,
    mean_token_delta=4.0,
    mean_latency_delta_ms=8.0,
    harm_rate=0.01,
    registry_summary_content_hash="6" * 64,
    registry_pair_count=24,
    registry_completed_trial_count=24,
    registry_failed_count=0,
    registry_cancelled_count=0,
    registry_active_count=0,
)
ready = PolicyOperationalReadiness(
    tests_passed=True,
    integration_passed=True,
    artifact_integrity_passed=True,
    rollback_ready=True,
    safety_violation=False,
    reviewer_count=2,
    evidence_age_seconds=60.0,
)
config = PolicyPromotionGateConfig(
    minimum_matched_pairs=20,
    minimum_score_lower_bound=0.0,
    maximum_score_standard_error=0.05,
    maximum_mean_token_delta=10.0,
    maximum_mean_latency_delta_ms=20.0,
    maximum_harm_rate=0.05,
    maximum_evidence_age_seconds=3600.0,
    minimum_reviewer_count=2,
    gate_policy_version="advisory-policy-promotion-gate-v0",
)
request = PolicyPromotionRequest(
    current_policy=current, candidate_policy=candidate, evaluation=evidence, readiness=ready
)
print(AdvisoryPolicyPromotionGate().evaluate(request, config).render_json(), end="")
"""
    outputs: list[str] = []
    for seed in ("1", "2", "37", "999"):
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
    decoded = json.loads(outputs[0])
    assert decoded["decision"] == "promote"
    assert decoded["advisory_only"] is True
