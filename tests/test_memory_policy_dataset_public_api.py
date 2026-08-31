from __future__ import annotations

import importlib

_memory_policy_dataset = importlib.import_module(
    "nextgen_memory.memory_policy_dataset"
)
InMemoryMemoryPolicyDatasetBuilder = (
    _memory_policy_dataset.InMemoryMemoryPolicyDatasetBuilder
)
MemoryPolicyCandidateFeatures = (
    _memory_policy_dataset.MemoryPolicyCandidateFeatures
)
MemoryPolicyCandidateObservation = (
    _memory_policy_dataset.MemoryPolicyCandidateObservation
)
MemoryPolicyCreditKind = _memory_policy_dataset.MemoryPolicyCreditKind
MemoryPolicyDatasetConfig = _memory_policy_dataset.MemoryPolicyDatasetConfig
MemoryPolicyDatasetConflictError = (
    _memory_policy_dataset.MemoryPolicyDatasetConflictError
)
MemoryPolicyDatasetSnapshot = (
    _memory_policy_dataset.MemoryPolicyDatasetSnapshot
)
MemoryPolicyDatasetStateError = (
    _memory_policy_dataset.MemoryPolicyDatasetStateError
)
MemoryPolicyDatasetValidationError = (
    _memory_policy_dataset.MemoryPolicyDatasetValidationError
)
MemoryPolicyDecisionTrace = _memory_policy_dataset.MemoryPolicyDecisionTrace
MemoryPolicyOutcomeLabel = _memory_policy_dataset.MemoryPolicyOutcomeLabel
MemoryPolicySplit = _memory_policy_dataset.MemoryPolicySplit
MemoryPolicyTrainingExample = (
    _memory_policy_dataset.MemoryPolicyTrainingExample
)


def test_memory_policy_dataset_contract_is_exported_from_package_root() -> None:
    nextgen_memory = importlib.import_module("nextgen_memory")
    expected = {
        "InMemoryMemoryPolicyDatasetBuilder": (
            InMemoryMemoryPolicyDatasetBuilder
        ),
        "MemoryPolicyCandidateFeatures": MemoryPolicyCandidateFeatures,
        "MemoryPolicyCandidateObservation": MemoryPolicyCandidateObservation,
        "MemoryPolicyCreditKind": MemoryPolicyCreditKind,
        "MemoryPolicyDatasetConfig": MemoryPolicyDatasetConfig,
        "MemoryPolicyDatasetConflictError": MemoryPolicyDatasetConflictError,
        "MemoryPolicyDatasetSnapshot": MemoryPolicyDatasetSnapshot,
        "MemoryPolicyDatasetStateError": MemoryPolicyDatasetStateError,
        "MemoryPolicyDatasetValidationError": MemoryPolicyDatasetValidationError,
        "MemoryPolicyDecisionTrace": MemoryPolicyDecisionTrace,
        "MemoryPolicyOutcomeLabel": MemoryPolicyOutcomeLabel,
        "MemoryPolicySplit": MemoryPolicySplit,
        "MemoryPolicyTrainingExample": MemoryPolicyTrainingExample,
    }

    for name, value in expected.items():
        assert getattr(nextgen_memory, name) is value
        assert nextgen_memory.__all__.count(name) == 1
