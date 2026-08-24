from __future__ import annotations

import json
import math
from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from nextgen_memory.bounded_inherited_reranker import BoundedInheritedRerankerConfig
from nextgen_memory.causal_credit import OutcomeMeasurement
from nextgen_memory.inherited_rerank_telemetry import (
    build_inherited_rerank_telemetry,
    fingerprint_bounded_inherited_policy,
)
from nextgen_memory.paired_replay_experiment_registry import (
    BalancedPairedReplayPlanner,
    InMemoryPairedReplayExperimentRegistry,
    PairedReplayArmResult,
    PairedReplayExperimentSpec,
    PairedReplayFailureRecord,
    PairedReplayRegistryConflictError,
    PairedReplayRegistryStateError,
    PairedReplayRegistryValidationError,
    ReplayArm,
    ReplayArmOrder,
    ReplayFailureCode,
    ReplayPairStatus,
)

EXPERIMENT_ID = UUID("00000000-0000-5000-8000-000000000901")
SPACE_ID = UUID("00000000-0000-5000-8000-000000000902")
ROUTER_ID = UUID("00000000-0000-5000-8000-000000000903")
CONTINUATION_HASH = "c" * 64
SEED_HASH = "a" * 64
CONTEXTS = tuple(f"{index:064x}" for index in range(1, 5))


def policy_config(arm: ReplayArm):
    version = "control-v1" if arm is ReplayArm.CONTROL else "treatment-v1"
    return BoundedInheritedRerankerConfig(policy_version=version)


def make_spec(**overrides: object) -> PairedReplayExperimentSpec:
    control = policy_config(ReplayArm.CONTROL)
    treatment = policy_config(ReplayArm.TREATMENT)
    values: dict[str, object] = {
        "experiment_id": EXPERIMENT_ID,
        "space_id": SPACE_ID,
        "control_policy_version": control.policy_version,
        "control_policy_fingerprint": fingerprint_bounded_inherited_policy(control),
        "treatment_policy_version": treatment.policy_version,
        "treatment_policy_fingerprint": fingerprint_bounded_inherited_policy(treatment),
        "continuation_set_hash": CONTINUATION_HASH,
        "order_seed_hash": SEED_HASH,
        "maximum_pairs": 8,
        "maximum_tokens_per_arm": 100,
        "maximum_latency_ms_per_arm": 50.0,
        "maximum_total_tokens": 1_600,
        "maximum_total_latency_ms": 800.0,
        "registry_policy_version": "paired-replay-experiment-registry-v0",
    }
    values.update(overrides)
    return PairedReplayExperimentSpec(**values)  # type: ignore[arg-type]


def make_plan(*contexts: str, spec: PairedReplayExperimentSpec | None = None):
    return BalancedPairedReplayPlanner().plan(
        spec or make_spec(),
        contexts or CONTEXTS,
    )


def result_for_step(
    step,
    *,
    router_decision_id: UUID = ROUTER_ID,
    score: float | None = None,
    tokens: int = 10,
    latency_ms: float = 5.0,
):
    config = policy_config(step.arm)
    batch = build_inherited_rerank_telemetry(
        space_id=step.space_id,
        router_decision_id=router_decision_id,
        config=config,
        results=(),
    )
    outcome = OutcomeMeasurement(
        score=(0.4 if step.arm is ReplayArm.CONTROL else 0.5)
        if score is None
        else score,
        task_success=True,
        tokens=tokens,
        latency_ms=latency_ms,
    )
    return PairedReplayArmResult(
        step_id=step.id,
        pair_id=step.pair_id,
        experiment_id=step.experiment_id,
        arm=step.arm,
        telemetry_batch=batch,
        outcome=outcome,
    )


def failure_for_step(step, code: ReplayFailureCode):
    return PairedReplayFailureRecord(
        step_id=step.id,
        pair_id=step.pair_id,
        experiment_id=step.experiment_id,
        arm=step.arm,
        code=code,
    )


def test_plan_is_deterministic_balanced_and_input_order_invariant() -> None:
    first = make_plan(*CONTEXTS)
    second = make_plan(*reversed(CONTEXTS))

    assert first == second
    assert first.id == second.id
    assert first.content_hash == second.content_hash
    assert tuple(item.ordinal for item in first.assignments) == (1, 2, 3, 4)
    assert first.summary.pair_count == 4
    assert first.summary.control_first_count + first.summary.treatment_first_count == 4
    assert abs(
        first.summary.control_first_count - first.summary.treatment_first_count
    ) <= 1
    assert first.summary.worst_case_total_tokens == 800
    assert first.summary.worst_case_total_latency_ms == 400.0
    assert not hasattr(first, "__dict__")
    with pytest.raises((AttributeError, FrozenInstanceError)):
        first.content_hash = "0" * 64  # type: ignore[misc]


def test_seed_changes_plan_order_but_not_pair_identity() -> None:
    first = make_plan(spec=make_spec(order_seed_hash="1" * 64))
    second = make_plan(spec=make_spec(order_seed_hash="2" * 64))

    first_pairs = {item.context_set_hash: item.id for item in first.assignments}
    second_pairs = {item.context_set_hash: item.id for item in second.assignments}
    assert first_pairs == second_pairs
    assert first.id != second.id
    assert first.content_hash != second.content_hash
    assert tuple(item.arm_order for item in first.assignments) != tuple(
        item.arm_order for item in second.assignments
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"experiment_id": "not-a-uuid"},
        {"space_id": "not-a-uuid"},
        {"control_policy_version": " "},
        {"control_policy_fingerprint": "A" * 64},
        {"treatment_policy_fingerprint": "z" * 64},
        {"continuation_set_hash": "1" * 63},
        {"order_seed_hash": "2" * 65},
        {"maximum_pairs": True},
        {"maximum_pairs": 0},
        {"maximum_tokens_per_arm": -1},
        {"maximum_latency_ms_per_arm": math.inf},
        {"maximum_total_tokens": 0},
        {"maximum_total_latency_ms": math.nan},
        {"registry_policy_version": ""},
    ],
)
def test_spec_rejects_malformed_values(overrides: dict[str, object]) -> None:
    with pytest.raises(PairedReplayRegistryValidationError):
        make_spec(**overrides)


def test_spec_requires_distinct_policy_fingerprints() -> None:
    control = make_spec().control_policy_fingerprint

    with pytest.raises(PairedReplayRegistryValidationError, match="distinct"):
        make_spec(treatment_policy_fingerprint=control)


@pytest.mark.parametrize(
    ("contexts", "spec", "message"),
    [
        ((), make_spec(), "at least one"),
        ((CONTEXTS[0], CONTEXTS[0]), make_spec(), "duplicate"),
        (CONTEXTS, make_spec(maximum_pairs=3), "maximum_pairs"),
        (CONTEXTS, make_spec(maximum_total_tokens=799), "token budget"),
        (CONTEXTS, make_spec(maximum_total_latency_ms=399.0), "latency budget"),
        (("A" * 64,), make_spec(), "context_set_hash"),
    ],
)
def test_planner_rejects_invalid_context_or_budget_contract(
    contexts: tuple[str, ...],
    spec: PairedReplayExperimentSpec,
    message: str,
) -> None:
    with pytest.raises(PairedReplayRegistryValidationError, match=message):
        BalancedPairedReplayPlanner().plan(spec, contexts)


def test_assignment_and_step_identity_contract() -> None:
    plan = make_plan(*CONTEXTS[:2])
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)

    steps = registry.next_steps(EXPERIMENT_ID)

    assert len(steps) == 2
    assert tuple(step.pair_id for step in steps) == tuple(
        assignment.id for assignment in plan.assignments
    )
    for assignment, step in zip(plan.assignments, steps, strict=True):
        assert step.arm is assignment.arm_order.first_arm
        assert step.order_position == 1
        assert step.context_set_hash == assignment.context_set_hash
        assert step.continuation_set_hash == CONTINUATION_HASH
        assert step.maximum_tokens == plan.spec.maximum_tokens_per_arm
        assert step.maximum_latency_ms == plan.spec.maximum_latency_ms_per_arm
        assert len(step.content_hash) == 64


def test_register_plan_exact_retry_is_idempotent_and_conflict_fails() -> None:
    registry = InMemoryPairedReplayExperimentRegistry()
    plan = make_plan()
    registry.register_plan(plan)
    registry.register_plan(plan)

    conflicting = make_plan(spec=make_spec(order_seed_hash="3" * 64))
    with pytest.raises(PairedReplayRegistryConflictError, match="plan conflict"):
        registry.register_plan(conflicting)


def test_recording_first_arm_exposes_only_second_arm() -> None:
    plan = make_plan(CONTEXTS[0])
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)
    first_step = registry.next_steps(EXPERIMENT_ID)[0]

    registry.record_arm_result(result_for_step(first_step))

    snapshot = registry.pair_snapshots(EXPERIMENT_ID)[0]
    assert snapshot.status is ReplayPairStatus.FIRST_ARM_RECORDED
    assert snapshot.recorded_arms == (first_step.arm,)
    assert snapshot.next_step is not None
    assert snapshot.next_step.arm is plan.assignments[0].arm_order.second_arm
    assert snapshot.next_step.order_position == 2
    assert registry.completed_trials(EXPERIMENT_ID) == ()


def test_second_arm_before_first_is_rejected_without_mutation() -> None:
    plan = make_plan(CONTEXTS[0])
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)
    first = registry.next_steps(EXPERIMENT_ID)[0]
    second = replace(
        first,
        arm=plan.assignments[0].arm_order.second_arm,
        order_position=2,
    )

    with pytest.raises(PairedReplayRegistryStateError, match="currently schedulable"):
        registry.record_arm_result(result_for_step(second))

    snapshot = registry.pair_snapshots(EXPERIMENT_ID)[0]
    assert snapshot.status is ReplayPairStatus.PLANNED
    assert snapshot.recorded_arms == ()


def test_wrong_policy_space_or_step_identity_is_rejected() -> None:
    plan = make_plan(CONTEXTS[0])
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)
    step = registry.next_steps(EXPERIMENT_ID)[0]
    valid = result_for_step(step)

    wrong_policy_batch = build_inherited_rerank_telemetry(
        space_id=step.space_id,
        router_decision_id=ROUTER_ID,
        config=BoundedInheritedRerankerConfig(policy_version="wrong-policy"),
        results=(),
    )
    wrong_policy = replace(valid, telemetry_batch=wrong_policy_batch)
    with pytest.raises(PairedReplayRegistryValidationError, match="policy"):
        registry.record_arm_result(wrong_policy)

    wrong_space_batch = build_inherited_rerank_telemetry(
        space_id=UUID("00000000-0000-5000-8000-000000000999"),
        router_decision_id=ROUTER_ID,
        config=policy_config(step.arm),
        results=(),
    )
    with pytest.raises(PairedReplayRegistryValidationError, match="space"):
        registry.record_arm_result(replace(valid, telemetry_batch=wrong_space_batch))

    with pytest.raises(PairedReplayRegistryStateError, match="currently schedulable"):
        registry.record_arm_result(
            replace(
                valid,
                step_id=UUID("00000000-0000-5000-8000-000000000998"),
            )
        )


def test_per_arm_budget_is_enforced_before_state_mutation() -> None:
    plan = make_plan(CONTEXTS[0])
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)
    step = registry.next_steps(EXPERIMENT_ID)[0]

    with pytest.raises(PairedReplayRegistryValidationError, match="token limit"):
        registry.record_arm_result(result_for_step(step, tokens=101))
    with pytest.raises(PairedReplayRegistryValidationError, match="latency limit"):
        registry.record_arm_result(result_for_step(step, latency_ms=50.1))

    assert registry.pair_snapshots(EXPERIMENT_ID)[0].status is ReplayPairStatus.PLANNED


def test_exact_result_retry_is_idempotent_and_conflicting_retry_fails() -> None:
    plan = make_plan(CONTEXTS[0])
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)
    step = registry.next_steps(EXPERIMENT_ID)[0]
    result = result_for_step(step)

    registry.record_arm_result(result)
    registry.record_arm_result(result)

    with pytest.raises(PairedReplayRegistryConflictError, match="result conflict"):
        registry.record_arm_result(replace(result, outcome=replace(result.outcome, score=0.2)))


def test_two_matched_arms_create_one_complete_trial() -> None:
    plan = make_plan(CONTEXTS[0])
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)
    first = registry.next_steps(EXPERIMENT_ID)[0]
    registry.record_arm_result(result_for_step(first))
    second = registry.next_steps(EXPERIMENT_ID)[0]
    registry.record_arm_result(result_for_step(second))

    snapshot = registry.pair_snapshots(EXPERIMENT_ID)[0]
    trials = registry.completed_trials(EXPERIMENT_ID)
    summary = registry.summary(EXPERIMENT_ID)

    assert snapshot.status is ReplayPairStatus.COMPLETE
    assert snapshot.recorded_arms == (ReplayArm.CONTROL, ReplayArm.TREATMENT)
    assert snapshot.next_step is None
    assert snapshot.completed_trial_id is not None
    assert len(trials) == 1
    assert trials[0].trial_id == snapshot.completed_trial_id
    assert trials[0].context_set_hash == CONTEXTS[0]
    assert trials[0].continuation_set_hash == CONTINUATION_HASH
    assert summary.complete_count == 1
    assert summary.recorded_arm_count == 2
    assert summary.completed_trial_count == 1
    assert summary.actual_tokens == 20
    assert summary.actual_latency_ms == 10.0


def test_mismatched_router_decision_rejects_second_arm_without_mutation() -> None:
    plan = make_plan(CONTEXTS[0])
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)
    first = registry.next_steps(EXPERIMENT_ID)[0]
    registry.record_arm_result(result_for_step(first, router_decision_id=ROUTER_ID))
    second = registry.next_steps(EXPERIMENT_ID)[0]

    with pytest.raises(PairedReplayRegistryValidationError, match="router decision"):
        registry.record_arm_result(
            result_for_step(
                second,
                router_decision_id=UUID(
                    "00000000-0000-5000-8000-000000000904"
                ),
            )
        )

    snapshot = registry.pair_snapshots(EXPERIMENT_ID)[0]
    assert snapshot.status is ReplayPairStatus.FIRST_ARM_RECORDED
    assert snapshot.recorded_arms == (first.arm,)
    assert registry.completed_trials(EXPERIMENT_ID) == ()


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (ReplayFailureCode.EXECUTION_FAILED, ReplayPairStatus.FAILED),
        (ReplayFailureCode.BUDGET_EXCEEDED, ReplayPairStatus.FAILED),
        (ReplayFailureCode.CANCELLED, ReplayPairStatus.CANCELLED),
    ],
)
def test_failure_and_cancellation_are_terminal(
    code: ReplayFailureCode,
    status: ReplayPairStatus,
) -> None:
    plan = make_plan(CONTEXTS[0])
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)
    step = registry.next_steps(EXPERIMENT_ID)[0]
    failure = failure_for_step(step, code)

    registry.record_failure(failure)
    registry.record_failure(failure)

    snapshot = registry.pair_snapshots(EXPERIMENT_ID)[0]
    assert snapshot.status is status
    assert snapshot.failure_code is code
    assert snapshot.next_step is None
    assert registry.next_steps(EXPERIMENT_ID) == ()
    assert registry.completed_trials(EXPERIMENT_ID) == ()
    with pytest.raises(PairedReplayRegistryStateError, match="terminal"):
        registry.record_arm_result(result_for_step(step))
    with pytest.raises(PairedReplayRegistryConflictError, match="failure conflict"):
        registry.record_failure(
            replace(failure, code=ReplayFailureCode.CANCELLED)
        )


def test_summary_counts_partition_pairs_and_account_resources() -> None:
    plan = make_plan(*CONTEXTS[:4])
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)
    initial = registry.next_steps(EXPERIMENT_ID)

    registry.record_arm_result(result_for_step(initial[0], tokens=11, latency_ms=1.5))
    registry.record_failure(
        failure_for_step(initial[1], ReplayFailureCode.EXECUTION_FAILED)
    )
    registry.record_failure(failure_for_step(initial[2], ReplayFailureCode.CANCELLED))
    first_of_complete = initial[3]
    registry.record_arm_result(
        result_for_step(first_of_complete, tokens=13, latency_ms=2.5)
    )
    second_of_complete = next(
        step
        for step in registry.next_steps(EXPERIMENT_ID)
        if step.pair_id == first_of_complete.pair_id
    )
    registry.record_arm_result(
        result_for_step(second_of_complete, tokens=17, latency_ms=3.5)
    )

    summary = registry.summary(EXPERIMENT_ID)

    assert (
        summary.planned_count
        + summary.first_arm_recorded_count
        + summary.complete_count
        + summary.failed_count
        + summary.cancelled_count
        == summary.pair_count
        == 4
    )
    assert summary.first_arm_recorded_count == 1
    assert summary.complete_count == 1
    assert summary.failed_count == 1
    assert summary.cancelled_count == 1
    assert summary.recorded_arm_count == 3
    assert summary.completed_trial_count == 1
    assert summary.actual_tokens == 41
    assert summary.actual_latency_ms == 7.5
    assert len(summary.content_hash) == 64


def test_safe_serialization_contains_only_bounded_fields() -> None:
    plan = make_plan(CONTEXTS[0])
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)
    snapshot = registry.pair_snapshots(EXPERIMENT_ID)[0]
    summary = registry.summary(EXPERIMENT_ID)

    encoded = json.dumps(
        {
            "plan": plan.to_dict(),
            "snapshot": snapshot.to_dict(),
            "summary": summary.to_dict(),
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )

    for forbidden in (
        "query",
        "prompt",
        "answer",
        "memory_body",
        "stdout",
        "stderr",
        "credential",
        "connection_url",
        "worker_identity",
        "lease_timestamp",
        "error_message",
    ):
        assert forbidden not in encoded.lower()
