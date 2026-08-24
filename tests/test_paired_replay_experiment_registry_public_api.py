from __future__ import annotations

import nextgen_memory
from nextgen_memory.paired_replay_experiment_registry import (
    BalancedPairedReplayPlanner,
    InMemoryPairedReplayExperimentRegistry,
    PairedReplayArmResult,
    PairedReplayAssignment,
    PairedReplayExperimentSpec,
    PairedReplayExperimentSummary,
    PairedReplayFailureRecord,
    PairedReplayPairSnapshot,
    PairedReplayPlan,
    PairedReplayPlanSummary,
    PairedReplayRegistryConflictError,
    PairedReplayRegistryStateError,
    PairedReplayRegistryValidationError,
    PairedReplayStep,
    ReplayArm,
    ReplayArmOrder,
    ReplayFailureCode,
    ReplayPairStatus,
)


def test_paired_replay_registry_contract_is_exported_from_package_root() -> None:
    expected = {
        "BalancedPairedReplayPlanner": BalancedPairedReplayPlanner,
        "InMemoryPairedReplayExperimentRegistry": InMemoryPairedReplayExperimentRegistry,
        "PairedReplayArmResult": PairedReplayArmResult,
        "PairedReplayAssignment": PairedReplayAssignment,
        "PairedReplayExperimentSpec": PairedReplayExperimentSpec,
        "PairedReplayExperimentSummary": PairedReplayExperimentSummary,
        "PairedReplayFailureRecord": PairedReplayFailureRecord,
        "PairedReplayPairSnapshot": PairedReplayPairSnapshot,
        "PairedReplayPlan": PairedReplayPlan,
        "PairedReplayPlanSummary": PairedReplayPlanSummary,
        "PairedReplayRegistryConflictError": PairedReplayRegistryConflictError,
        "PairedReplayRegistryStateError": PairedReplayRegistryStateError,
        "PairedReplayRegistryValidationError": PairedReplayRegistryValidationError,
        "PairedReplayStep": PairedReplayStep,
        "ReplayArm": ReplayArm,
        "ReplayArmOrder": ReplayArmOrder,
        "ReplayFailureCode": ReplayFailureCode,
        "ReplayPairStatus": ReplayPairStatus,
    }

    for name, value in expected.items():
        assert getattr(nextgen_memory, name) is value
        assert name in nextgen_memory.__all__
