from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

import nextgen_memory.paired_replay_experiment_registry as registry_module
from nextgen_memory.bounded_inherited_reranker import BoundedInheritedRerankerConfig
from nextgen_memory.inherited_rerank_telemetry import fingerprint_bounded_inherited_policy
from nextgen_memory.paired_replay_experiment_registry import (
    BalancedPairedReplayPlanner,
    InMemoryPairedReplayExperimentRegistry,
    PairedReplayExperimentSpec,
    PairedReplayPairSnapshot,
    PairedReplayPlan,
    PairedReplayRegistryValidationError,
    ReplayArm,
    ReplayFailureCode,
    ReplayPairStatus,
)


def make_plan():
    control = BoundedInheritedRerankerConfig(policy_version="control-v1")
    treatment = BoundedInheritedRerankerConfig(policy_version="treatment-v1")
    spec = PairedReplayExperimentSpec(
        experiment_id=UUID("00000000-0000-5000-8000-000000000e01"),
        space_id=UUID("00000000-0000-5000-8000-000000000e02"),
        control_policy_version=control.policy_version,
        control_policy_fingerprint=fingerprint_bounded_inherited_policy(control),
        treatment_policy_version=treatment.policy_version,
        treatment_policy_fingerprint=fingerprint_bounded_inherited_policy(treatment),
        continuation_set_hash="c" * 64,
        order_seed_hash="a" * 64,
        maximum_pairs=4,
        maximum_tokens_per_arm=100,
        maximum_latency_ms_per_arm=50.0,
        maximum_total_tokens=800,
        maximum_total_latency_ms=400.0,
    )
    return BalancedPairedReplayPlanner().plan(
        spec,
        ("1" * 64, "2" * 64),
    )


def rebuild_plan(plan, *, assignments=None, summary=None):
    assignments = tuple(assignments or plan.assignments)
    summary = summary or plan.summary
    payload = {
        "schema": registry_module._SCHEMA,
        "spec": plan.spec.to_dict(),
        "spec_content_hash": plan.spec.content_hash,
        "assignments": [item.to_dict() for item in assignments],
        "assignment_content_hashes": [item.content_hash for item in assignments],
        "summary": summary.to_dict(),
        "summary_content_hash": summary.content_hash,
    }
    content_hash = registry_module._hash_payload(payload)
    return PairedReplayPlan(
        id=registry_module._stable_uuid("plan", content_hash),
        spec=plan.spec,
        assignments=assignments,
        summary=summary,
        content_hash=content_hash,
    )


def test_public_plan_rejects_forged_pair_identity_even_with_rehashed_content() -> None:
    plan = make_plan()
    forged = replace(
        plan.assignments[0],
        id=UUID("00000000-0000-5000-8000-000000000eff"),
    )

    with pytest.raises(PairedReplayRegistryValidationError, match="pair id"):
        rebuild_plan(plan, assignments=(forged, plan.assignments[1]))


def test_public_plan_rejects_noncanonical_assignment_order() -> None:
    plan = make_plan()
    reversed_assignments = tuple(
        replace(item, ordinal=index)
        for index, item in enumerate(reversed(plan.assignments), start=1)
    )

    with pytest.raises(PairedReplayRegistryValidationError, match="canonical"):
        rebuild_plan(plan, assignments=reversed_assignments)


def test_public_plan_rejects_forged_reservation_summary() -> None:
    plan = make_plan()
    forged_summary = replace(
        plan.summary,
        worst_case_total_tokens=plan.summary.worst_case_total_tokens + 1,
    )

    with pytest.raises(PairedReplayRegistryValidationError, match="summary"):
        rebuild_plan(plan, summary=forged_summary)


@pytest.mark.parametrize(
    "changes",
    [
        {
            "status": ReplayPairStatus.PLANNED,
            "recorded_arms": (),
            "next_step": None,
            "failure_code": None,
            "completed_trial_id": None,
        },
        {
            "status": ReplayPairStatus.COMPLETE,
            "recorded_arms": (ReplayArm.CONTROL,),
            "next_step": None,
            "failure_code": None,
            "completed_trial_id": UUID(
                "00000000-0000-5000-8000-000000000e10"
            ),
        },
        {
            "status": ReplayPairStatus.CANCELLED,
            "recorded_arms": (),
            "next_step": None,
            "failure_code": ReplayFailureCode.EXECUTION_FAILED,
            "completed_trial_id": None,
        },
    ],
)
def test_public_snapshot_rejects_status_field_contradictions(
    changes: dict[str, object],
) -> None:
    plan = make_plan()
    registry = InMemoryPairedReplayExperimentRegistry()
    registry.register_plan(plan)
    valid = registry.pair_snapshots(plan.spec.experiment_id)[0]

    with pytest.raises(PairedReplayRegistryValidationError, match="status"):
        PairedReplayPairSnapshot(
            pair_id=valid.pair_id,
            experiment_id=valid.experiment_id,
            ordinal=valid.ordinal,
            arm_order=valid.arm_order,
            **changes,
        )
