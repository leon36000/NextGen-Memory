from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from nextgen_memory.paired_rerank_policy_evaluation import PairedPolicyVerdict
from nextgen_memory.policy_promotion import (
    DeterministicPolicyPromotionGate,
    PolicyPromotionDisposition,
    PolicyPromotionEvidence,
    PolicyPromotionGateConfig,
    PolicyPromotionReason,
    PolicyVerificationSignal,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
SIGNALS = tuple(PolicyVerificationSignal)


def evidence_for(index: int, **overrides: object) -> PolicyPromotionEvidence:
    values: dict[str, object] = {
        "space_id": UUID("00000000-0000-5000-8000-000000000e01"),
        "candidate_policy_id": UUID(
            f"00000000-0000-5000-8000-{index + 1:012x}"
        ),
        "evaluated_policy_version": "treatment-v1",
        "current_policy_version": "treatment-v1",
        "evaluated_policy_fingerprint": f"{index + 1:064x}"[-64:],
        "current_policy_fingerprint": f"{index + 1:064x}"[-64:],
        "evaluation_id": UUID(
            f"00000000-0000-5001-8000-{index + 1:012x}"
        ),
        "evaluation_content_hash": f"{index + 10_001:064x}"[-64:],
        "context_collection_hash": f"{index + 20_001:064x}"[-64:],
        "continuation_set_hash": f"{index + 30_001:064x}"[-64:],
        "paired_trial_count": 32 + index % 4,
        "mean_effect": 0.05 + (index % 5) * 0.001,
        "confidence_lower": 0.02 + (index % 3) * 0.001,
        "confidence_upper": 0.08 + (index % 7) * 0.001,
        "standard_error": 0.01 + (index % 4) * 0.001,
        "mean_cost_delta": (index % 5) * 0.001,
        "harm_rate": 0.0,
        "evaluator_verdict": PairedPolicyVerdict.PROMISING,
        "evidence_at": NOW - timedelta(seconds=index % 1_000),
        "decision_at": NOW,
        "maximum_evidence_age_seconds": 86_400,
        "rollback_plan_id": UUID(
            f"00000000-0000-5002-8000-{index + 1:012x}"
        ),
        "rollback_plan_hash": f"{index + 40_001:064x}"[-64:],
        "rollback_ready": True,
        "required_signals": SIGNALS,
        "passed_signals": tuple(reversed(SIGNALS)),
        "reviewer_count": 2,
        "required_reviewer_count": 2,
        "evaluated_base_sha": f"{index + 1:040x}"[-40:],
        "current_base_sha": f"{index + 1:040x}"[-40:],
        "evaluated_candidate_sha": f"{index + 5_001:040x}"[-40:],
        "current_candidate_sha": f"{index + 5_001:040x}"[-40:],
        "hard_safety_violation": False,
    }
    values.update(overrides)
    return PolicyPromotionEvidence(**values)  # type: ignore[arg-type]


def test_five_thousand_generated_decisions_preserve_invariants() -> None:
    gate = DeterministicPolicyPromotionGate()

    for index in range(5_000):
        mode = index % 3
        if mode == 0:
            evidence = evidence_for(index)
            expected = PolicyPromotionDisposition.PROMOTE
        elif mode == 1:
            evidence = evidence_for(index, paired_trial_count=15)
            expected = PolicyPromotionDisposition.HOLD
        else:
            evidence = evidence_for(
                index,
                evaluator_verdict=PairedPolicyVerdict.HARMFUL,
            )
            expected = PolicyPromotionDisposition.REJECT

        first = gate.evaluate(evidence)
        second = gate.evaluate(evidence)

        assert first == second
        assert first.render_json() == second.render_json()
        assert first.disposition is expected
        assert first.reasons
        assert first.id.version == 5
        assert len(first.content_hash) == 64
        assert len(first.evidence_fingerprint) == 64
        assert len(first.config_fingerprint) == 64
        assert json.loads(first.render_json())["disposition"] == expected.value
        if expected is PolicyPromotionDisposition.PROMOTE:
            assert first.reasons == (
                PolicyPromotionReason.ALL_REQUIREMENTS_SATISFIED,
            )
        elif expected is PolicyPromotionDisposition.HOLD:
            assert PolicyPromotionReason.INSUFFICIENT_TRIALS in first.reasons
        else:
            assert PolicyPromotionReason.EVALUATOR_HARMFUL in first.reasons

        changed = gate.evaluate(replace(evidence, reviewer_count=3))
        assert changed.id != first.id
        assert changed.evidence_fingerprint != first.evidence_fingerprint


def test_signal_collection_permutations_are_identity_invariant() -> None:
    gate = DeterministicPolicyPromotionGate()

    for index in range(250):
        evidence = evidence_for(index)
        first = gate.evaluate(evidence)
        second = gate.evaluate(
            replace(
                evidence,
                required_signals=set(reversed(SIGNALS)),
                passed_signals=list(SIGNALS) + list(reversed(SIGNALS)),
            )
        )

        assert first == second
        assert first.render_json() == second.render_json()


def test_each_accepted_material_field_changes_evidence_identity() -> None:
    gate = DeterministicPolicyPromotionGate()
    evidence = evidence_for(900_000)
    baseline = gate.evaluate(evidence)
    mutations: dict[str, object] = {
        "space_id": UUID("00000000-0000-5000-8000-000000000e99"),
        "candidate_policy_id": UUID(
            "00000000-0000-5000-8000-000000000e98"
        ),
        "evaluated_policy_version": "treatment-v2",
        "current_policy_version": "treatment-v2",
        "evaluated_policy_fingerprint": "f" * 64,
        "current_policy_fingerprint": "f" * 64,
        "evaluation_id": UUID("00000000-0000-5000-8000-000000000e97"),
        "evaluation_content_hash": "e" * 64,
        "context_collection_hash": "d" * 64,
        "continuation_set_hash": "c" * 64,
        "paired_trial_count": 33,
        "mean_effect": 0.051,
        "confidence_lower": 0.021,
        "confidence_upper": 0.081,
        "standard_error": 0.011,
        "mean_cost_delta": 0.002,
        "harm_rate": 0.001,
        "evaluator_verdict": PairedPolicyVerdict.NEUTRAL,
        "evidence_at": NOW - timedelta(seconds=2),
        "decision_at": NOW + timedelta(seconds=1),
        "maximum_evidence_age_seconds": 86_401,
        "rollback_plan_id": UUID(
            "00000000-0000-5000-8000-000000000e96"
        ),
        "rollback_plan_hash": "b" * 64,
        "rollback_ready": False,
        "required_signals": SIGNALS[:-1],
        "passed_signals": SIGNALS[:-1],
        "reviewer_count": 3,
        "required_reviewer_count": 3,
        "evaluated_base_sha": "a" * 40,
        "current_base_sha": "a" * 40,
        "evaluated_candidate_sha": "b" * 40,
        "current_candidate_sha": "b" * 40,
        "hard_safety_violation": True,
    }

    for field, value in mutations.items():
        if field in {
            "evaluated_policy_version",
            "current_policy_version",
            "evaluated_policy_fingerprint",
            "current_policy_fingerprint",
            "evaluated_base_sha",
            "current_base_sha",
            "evaluated_candidate_sha",
            "current_candidate_sha",
        }:
            if field.startswith("evaluated_"):
                partner = field.replace("evaluated_", "current_", 1)
            else:
                partner = field.replace("current_", "evaluated_", 1)
            candidate = replace(evidence, **{field: value, partner: value})
        else:
            candidate = replace(evidence, **{field: value})
        decision = gate.evaluate(candidate)
        assert decision.id != baseline.id, field
        assert decision.evidence_fingerprint != baseline.evidence_fingerprint, field


def test_generated_malformed_strings_are_fingerprinted_not_echoed() -> None:
    gate = DeterministicPolicyPromotionGate()

    for index in range(250):
        sentinel = f"private-query-{index}"
        decision = gate.evaluate(
            evidence_for(index, evaluation_content_hash=sentinel)
        )
        rendered = decision.render_json()

        assert decision.disposition is PolicyPromotionDisposition.REJECT
        assert decision.reasons == (
            PolicyPromotionReason.MALFORMED_EVIDENCE,
        )
        assert sentinel not in rendered
        assert "private-query" not in rendered


def test_configuration_mutations_change_config_fingerprint() -> None:
    evidence = evidence_for(700_000)
    baseline = DeterministicPolicyPromotionGate(
        PolicyPromotionGateConfig()
    ).evaluate(evidence)
    configs = (
        PolicyPromotionGateConfig(minimum_paired_trials=17),
        PolicyPromotionGateConfig(minimum_confidence_lower_bound=0.001),
        PolicyPromotionGateConfig(maximum_standard_error=0.06),
        PolicyPromotionGateConfig(maximum_mean_cost_delta=0.06),
        PolicyPromotionGateConfig(maximum_harm_rate=0.02),
        PolicyPromotionGateConfig(
            established_negative_effect_tolerance=0.001
        ),
        PolicyPromotionGateConfig(policy_version="policy-promotion-gate-v0.1"),
    )

    for config in configs:
        decision = DeterministicPolicyPromotionGate(config).evaluate(evidence)
        assert decision.id != baseline.id
        assert decision.config_fingerprint != baseline.config_fingerprint


def test_process_hash_seed_does_not_change_decision_json() -> None:
    script = r'''
from datetime import UTC, datetime, timedelta
from uuid import UUID
from nextgen_memory.paired_rerank_policy_evaluation import PairedPolicyVerdict
from nextgen_memory.policy_promotion import DeterministicPolicyPromotionGate, PolicyPromotionEvidence, PolicyVerificationSignal
now = datetime(2026, 8, 24, 4, 0, tzinfo=UTC)
signals = set(PolicyVerificationSignal)
evidence = PolicyPromotionEvidence(
    space_id=UUID("00000000-0000-5000-8000-000000000f01"),
    candidate_policy_id=UUID("00000000-0000-5000-8000-000000000f02"),
    evaluated_policy_version="treatment-v1",
    current_policy_version="treatment-v1",
    evaluated_policy_fingerprint="a" * 64,
    current_policy_fingerprint="a" * 64,
    evaluation_id=UUID("00000000-0000-5000-8000-000000000f03"),
    evaluation_content_hash="b" * 64,
    context_collection_hash="c" * 64,
    continuation_set_hash="d" * 64,
    paired_trial_count=32,
    mean_effect=0.05,
    confidence_lower=0.02,
    confidence_upper=0.08,
    standard_error=0.01,
    mean_cost_delta=0.01,
    harm_rate=0.0,
    evaluator_verdict=PairedPolicyVerdict.PROMISING,
    evidence_at=now - timedelta(hours=1),
    decision_at=now,
    maximum_evidence_age_seconds=86400,
    rollback_plan_id=UUID("00000000-0000-5000-8000-000000000f04"),
    rollback_plan_hash="e" * 64,
    rollback_ready=True,
    required_signals=signals,
    passed_signals=signals,
    reviewer_count=2,
    required_reviewer_count=2,
    evaluated_base_sha="1" * 40,
    current_base_sha="1" * 40,
    evaluated_candidate_sha="2" * 40,
    current_candidate_sha="2" * 40,
    hard_safety_violation=False,
)
print(DeterministicPolicyPromotionGate().evaluate(evidence).render_json(), end="")
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
    assert json.loads(outputs[0])["disposition"] == "promote"
