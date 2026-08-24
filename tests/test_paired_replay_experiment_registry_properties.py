from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

from nextgen_memory.paired_replay_experiment_registry import (
    BalancedPairedReplayPlanner,
    InMemoryPairedReplayExperimentRegistry,
    PairedReplayArmResult,
    PairedReplayExperimentSpec,
    PairedReplayFailureRecord,
    ReplayArm,
    ReplayFailureCode,
    ReplayPairStatus,
)

from nextgen_memory.bounded_inherited_reranker import BoundedInheritedRerankerConfig
from nextgen_memory.causal_credit import OutcomeMeasurement
from nextgen_memory.inherited_rerank_telemetry import (
    build_inherited_rerank_telemetry,
    fingerprint_bounded_inherited_policy,
)

ROOT = Path(__file__).resolve().parents[1]
SPACE_ID = UUID("00000000-0000-5000-8000-000000000a01")
ROUTER_ID = UUID("00000000-0000-5000-8000-000000000a02")
CONTINUATION_HASH = "d" * 64


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def config_for(arm: ReplayArm):
    return BoundedInheritedRerankerConfig(
        policy_version="control-v1" if arm is ReplayArm.CONTROL else "treatment-v1"
    )


def spec_for(index: int, *, pair_limit: int = 8) -> PairedReplayExperimentSpec:
    control = config_for(ReplayArm.CONTROL)
    treatment = config_for(ReplayArm.TREATMENT)
    return PairedReplayExperimentSpec(
        experiment_id=UUID(f"00000000-0000-5000-8000-{index + 1:012x}"),
        space_id=SPACE_ID,
        control_policy_version=control.policy_version,
        control_policy_fingerprint=fingerprint_bounded_inherited_policy(control),
        treatment_policy_version=treatment.policy_version,
        treatment_policy_fingerprint=fingerprint_bounded_inherited_policy(treatment),
        continuation_set_hash=CONTINUATION_HASH,
        order_seed_hash=digest(f"seed:{index}"),
        maximum_pairs=pair_limit,
        maximum_tokens_per_arm=50,
        maximum_latency_ms_per_arm=25.0,
        maximum_total_tokens=pair_limit * 2 * 50,
        maximum_total_latency_ms=pair_limit * 2 * 25.0,
    )


def result_for(step, *, router_id: UUID = ROUTER_ID):
    batch = build_inherited_rerank_telemetry(
        space_id=step.space_id,
        router_decision_id=router_id,
        config=config_for(step.arm),
        results=(),
    )
    return PairedReplayArmResult(
        step_id=step.id,
        pair_id=step.pair_id,
        experiment_id=step.experiment_id,
        arm=step.arm,
        telemetry_batch=batch,
        outcome=OutcomeMeasurement(
            score=0.4 if step.arm is ReplayArm.CONTROL else 0.5,
            task_success=True,
            tokens=7,
            latency_ms=3.0,
        ),
    )


def test_five_thousand_generated_plans_and_traces_preserve_invariants() -> None:
    planner = BalancedPairedReplayPlanner()

    for index in range(5_000):
        pair_count = (index % 8) + 1
        contexts = tuple(digest(f"context:{index}:{ordinal}") for ordinal in range(pair_count))
        spec = spec_for(index)
        first = planner.plan(spec, contexts)
        second = planner.plan(spec, tuple(reversed(contexts)))

        assert first == second
        assert first.id == second.id
        assert first.summary.pair_count == pair_count
        assert first.summary.control_first_count + first.summary.treatment_first_count == pair_count
        assert abs(first.summary.control_first_count - first.summary.treatment_first_count) <= 1
        assert first.summary.worst_case_total_tokens == pair_count * 100
        assert first.summary.worst_case_total_latency_ms == pair_count * 50.0
        assert len({assignment.id for assignment in first.assignments}) == pair_count
        assert len({assignment.content_hash for assignment in first.assignments}) == pair_count

        registry = InMemoryPairedReplayExperimentRegistry()
        registry.register_plan(first)
        registry.register_plan(first)
        steps = registry.next_steps(spec.experiment_id)
        assert len(steps) == pair_count
        assert len({step.pair_id for step in steps}) == pair_count

        if index % 10 == 0:
            step = steps[0]
            registry.record_arm_result(result_for(step))
            registry.record_arm_result(result_for(step))
            second_step = next(
                value
                for value in registry.next_steps(spec.experiment_id)
                if value.pair_id == step.pair_id
            )
            registry.record_arm_result(result_for(second_step))
            snapshot = registry.pair_snapshots(spec.experiment_id)[0]
            assert snapshot.status is ReplayPairStatus.COMPLETE
            assert len(registry.completed_trials(spec.experiment_id)) == 1
        elif index % 10 == 1:
            step = steps[0]
            failure = PairedReplayFailureRecord(
                step_id=step.id,
                pair_id=step.pair_id,
                experiment_id=step.experiment_id,
                arm=step.arm,
                code=ReplayFailureCode.EXECUTION_FAILED,
            )
            registry.record_failure(failure)
            registry.record_failure(failure)
            assert registry.pair_snapshots(spec.experiment_id)[0].status is ReplayPairStatus.FAILED

        summary = registry.summary(spec.experiment_id)
        assert (
            summary.planned_count
            + summary.first_arm_recorded_count
            + summary.complete_count
            + summary.failed_count
            + summary.cancelled_count
            == pair_count
        )
        assert summary.recorded_arm_count in {0, 2}
        assert summary.completed_trial_count in {0, 1}
        assert len(summary.content_hash) == 64


def test_order_seed_changes_plan_but_not_context_pair_ids_for_generated_cases() -> None:
    planner = BalancedPairedReplayPlanner()

    for index in range(250):
        contexts = tuple(digest(f"seed-context:{index}:{value}") for value in range(7))
        base = spec_for(index + 10_000)
        changed = PairedReplayExperimentSpec(
            experiment_id=base.experiment_id,
            space_id=base.space_id,
            control_policy_version=base.control_policy_version,
            control_policy_fingerprint=base.control_policy_fingerprint,
            treatment_policy_version=base.treatment_policy_version,
            treatment_policy_fingerprint=base.treatment_policy_fingerprint,
            continuation_set_hash=base.continuation_set_hash,
            order_seed_hash=digest(f"alternate-seed:{index}"),
            maximum_pairs=base.maximum_pairs,
            maximum_tokens_per_arm=base.maximum_tokens_per_arm,
            maximum_latency_ms_per_arm=base.maximum_latency_ms_per_arm,
            maximum_total_tokens=base.maximum_total_tokens,
            maximum_total_latency_ms=base.maximum_total_latency_ms,
            registry_policy_version=base.registry_policy_version,
        )
        first = planner.plan(base, contexts)
        second = planner.plan(changed, contexts)

        assert {assignment.context_set_hash: assignment.id for assignment in first.assignments} == {
            assignment.context_set_hash: assignment.id for assignment in second.assignments
        }
        assert first.id != second.id
        assert first.content_hash != second.content_hash


def test_process_hash_seed_does_not_change_plan_json() -> None:
    script = r"""
import hashlib
from uuid import UUID
from nextgen_memory.bounded_inherited_reranker import BoundedInheritedRerankerConfig
from nextgen_memory.inherited_rerank_telemetry import fingerprint_bounded_inherited_policy
from nextgen_memory.paired_replay_experiment_registry import (
    BalancedPairedReplayPlanner,
    PairedReplayExperimentSpec,
)
control = BoundedInheritedRerankerConfig(policy_version="control-v1")
treatment = BoundedInheritedRerankerConfig(policy_version="treatment-v1")
spec = PairedReplayExperimentSpec(
    experiment_id=UUID("00000000-0000-5000-8000-000000000b01"),
    space_id=UUID("00000000-0000-5000-8000-000000000b02"),
    control_policy_version=control.policy_version,
    control_policy_fingerprint=fingerprint_bounded_inherited_policy(control),
    treatment_policy_version=treatment.policy_version,
    treatment_policy_fingerprint=fingerprint_bounded_inherited_policy(treatment),
    continuation_set_hash="d" * 64,
    order_seed_hash="e" * 64,
    maximum_pairs=8,
    maximum_tokens_per_arm=50,
    maximum_latency_ms_per_arm=25.0,
    maximum_total_tokens=800,
    maximum_total_latency_ms=400.0,
)
contexts = tuple(hashlib.sha256(f"context:{value}".encode()).hexdigest() for value in range(8))
print(BalancedPairedReplayPlanner().plan(spec, set(contexts)).render_json(), end="")
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
    assert decoded["summary"]["pair_count"] == 8
    assert len(decoded["assignments"]) == 8


def test_safe_generated_serialization_never_contains_private_payload() -> None:
    plan = BalancedPairedReplayPlanner().plan(
        spec_for(20_000),
        tuple(digest(f"privacy-context:{value}") for value in range(3)),
    )
    encoded = plan.render_json().lower()

    for forbidden in (
        "private prompt",
        "query_text",
        "memory_body",
        "stdout",
        "stderr",
        "postgresql://",
        "mongodb://",
        "credential",
        "worker_identity",
        "lease_timestamp",
    ):
        assert forbidden not in encoded
