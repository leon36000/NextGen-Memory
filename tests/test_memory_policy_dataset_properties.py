from __future__ import annotations

import hashlib
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest

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
MemoryPolicyDatasetValidationError = (
    _memory_policy_dataset.MemoryPolicyDatasetValidationError
)
MemoryPolicyDecisionTrace = _memory_policy_dataset.MemoryPolicyDecisionTrace
MemoryPolicyOutcomeLabel = _memory_policy_dataset.MemoryPolicyOutcomeLabel
MemoryPolicySplit = _memory_policy_dataset.MemoryPolicySplit

ROOT = Path(__file__).resolve().parents[1]
BASE_SHA = "1" * 40
POLICY_FP = "2" * 64


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def features(index: int, **overrides: object) -> MemoryPolicyCandidateFeatures:
    values: dict[str, object] = {
        "semantic_relevance": ((index * 17) % 101) / 100.0,
        "direct_utility_mean": (((index * 7) % 201) - 100) / 100.0,
        "direct_utility_confidence": ((index * 19) % 101) / 100.0,
        "inherited_utility_mean": (((index * 11) % 201) - 100) / 100.0,
        "inherited_utility_confidence": ((index * 23) % 101) / 100.0,
        "interaction_effect_mean": (((index * 13) % 201) - 100) / 100.0,
        "interaction_confidence": ((index * 29) % 101) / 100.0,
        "novelty": ((index * 31) % 101) / 100.0,
        "authority": ((index * 37) % 101) / 100.0,
        "freshness": ((index * 41) % 101) / 100.0,
        "token_cost": index % 10_000,
        "latency_ms": float(index % 5_000) / 10.0,
        "prior_retrieval_count": index % 1_000,
        "prior_use_count": index % max(1, (index % 1_000) + 1),
        "original_rank": index % 128,
    }
    values.update(overrides)
    return MemoryPolicyCandidateFeatures(**values)  # type: ignore[arg-type]


def observation(
    index: int,
    mode: int,
    *,
    original_rank: int = 0,
    **overrides: object,
) -> MemoryPolicyCandidateObservation:
    common: dict[str, object] = {
        "candidate_id": UUID(int=100_000 + index),
        "candidate_content_hash": digest(f"candidate-content:{index}"),
        "memory_identity_hash": digest(f"memory:{index}"),
        "expert_key_hash": digest(f"expert:{index % 17}"),
        "features": features(index, original_rank=original_rank),
        "selected_by_policy": True,
        "used_by_action": True,
        "credit_kind": MemoryPolicyCreditKind.DIRECT_CAUSAL,
        "credit_effect_mean": 0.08,
        "credit_confidence_lower_bound": 0.04,
        "credit_confidence_upper_bound": 0.12,
        "attribution_confidence": 0.9,
        "outcome_observed": True,
        "harm_observed": False,
        "credit_evidence_hash": digest(f"credit:{index}"),
        "interaction_bundle_hash": None,
    }
    if mode == 0:
        pass
    elif mode == 1:
        common.update(
            {
                "credit_effect_mean": 0.0,
                "credit_confidence_lower_bound": -0.01,
                "credit_confidence_upper_bound": 0.01,
            }
        )
    elif mode == 2:
        common.update(
            {
                "credit_effect_mean": -0.08,
                "credit_confidence_lower_bound": -0.12,
                "credit_confidence_upper_bound": -0.04,
            }
        )
    elif mode == 3:
        common.update(
            {
                "selected_by_policy": False,
                "used_by_action": False,
                "credit_kind": MemoryPolicyCreditKind.NONE,
                "credit_effect_mean": 0.0,
                "credit_confidence_lower_bound": 0.0,
                "credit_confidence_upper_bound": 0.0,
                "attribution_confidence": 0.0,
                "outcome_observed": False,
            }
        )
    elif mode == 4:
        common["credit_kind"] = MemoryPolicyCreditKind.OBSERVATIONAL
    elif mode == 5:
        common["attribution_confidence"] = 0.74
    elif mode == 6:
        common.update(
            {
                "selected_by_policy": False,
                "used_by_action": False,
                "credit_kind": MemoryPolicyCreditKind.MATCHED_REPLAY,
            }
        )
    elif mode == 7:
        common.update(
            {
                "credit_kind": MemoryPolicyCreditKind.INTERACTION_ALLOCATION,
                "interaction_bundle_hash": digest(f"bundle:{index}"),
            }
        )
    else:
        raise AssertionError(f"unsupported mode: {mode}")
    common.update(overrides)
    return MemoryPolicyCandidateObservation(**common)  # type: ignore[arg-type]


def trace(
    index: int,
    *,
    trajectory_id: UUID | None = None,
    event_ordinal: int | None = None,
    candidates: object | None = None,
    **overrides: object,
) -> MemoryPolicyDecisionTrace:
    values: dict[str, object] = {
        "trace_id": UUID(int=1_000_000 + index),
        "trajectory_id": trajectory_id or UUID(int=2_000_000 + index),
        "event_ordinal": (
            (5, 15, 25)[index % 3]
            if event_ordinal is None
            else event_ordinal
        ),
        "policy_version": "deterministic-v1",
        "policy_fingerprint": POLICY_FP,
        "source_sha": BASE_SHA,
        "task_feature_vector_hash": digest(f"task:{index}"),
        "query_embedding_hash": digest(f"query:{index}"),
        "outcome_content_hash": digest(f"outcome:{index}"),
        "provenance_content_hash": digest(f"provenance:{index}"),
        "decision_budget_tokens": 4_000,
        "decision_budget_latency_ms": 250.0,
        "candidates": (
            observation(index, index % 8, original_rank=0),
        )
        if candidates is None
        else candidates,
    }
    values.update(overrides)
    return MemoryPolicyDecisionTrace(**values)  # type: ignore[arg-type]


def config(**overrides: object) -> MemoryPolicyDatasetConfig:
    values: dict[str, object] = {
        "train_max_ordinal": 10,
        "validation_max_ordinal": 20,
        "minimum_attribution_confidence": 0.75,
        "beneficial_effect_threshold": 0.02,
        "harmful_effect_threshold": 0.02,
        "neutral_effect_band": 0.01,
    }
    values.update(overrides)
    return MemoryPolicyDatasetConfig(**values)  # type: ignore[arg-type]


def test_five_thousand_generated_traces_cover_labels_splits_and_retries() -> None:
    builder = InMemoryMemoryPolicyDatasetBuilder()

    for index in range(5_000):
        value = trace(index)
        assert builder.register_trace(value) is value
        assert builder.register_trace(value) is value

    snapshot = builder.build(config())
    repeated = builder.build(config())

    assert repeated is not snapshot
    assert repeated == snapshot
    assert repeated.render_json() == snapshot.render_json()
    assert repeated.render_jsonl() == snapshot.render_jsonl()
    assert len(snapshot.trace_ids) == 5_000
    assert len(snapshot.examples) == 5_000
    assert snapshot.trajectory_count == 5_000
    assert snapshot.trainable_example_count > 0
    assert snapshot.abstention_count > 0

    label_counts = dict(snapshot.label_counts)
    split_counts = dict(snapshot.split_counts)
    assert set(label_counts) == {
        label.value for label in MemoryPolicyOutcomeLabel
    }
    assert set(split_counts) == {split.value for split in MemoryPolicySplit}
    assert label_counts["beneficial"] > 0
    assert label_counts["neutral"] > 0
    assert label_counts["harmful"] > 0
    assert label_counts["abstain"] > 0
    assert split_counts["train"] > 0
    assert split_counts["validation"] > 0
    assert split_counts["test"] > 0
    assert sum(label_counts.values()) == 5_000
    assert sum(split_counts.values()) == 5_000

    trainable_ids = {
        example.id for example in snapshot.examples if example.trainable
    }
    split_ids = (
        set(snapshot.train_example_ids)
        | set(snapshot.validation_example_ids)
        | set(snapshot.test_example_ids)
    )
    assert split_ids == trainable_ids
    assert len(snapshot.render_jsonl().splitlines()) == 5_000
    assert len(snapshot.render_jsonl(trainable_only=True).splitlines()) == (
        snapshot.trainable_example_count
    )


def test_generated_trajectory_groups_never_cross_splits() -> None:
    builder = InMemoryMemoryPolicyDatasetBuilder()
    expected_split_by_trajectory: dict[UUID, MemoryPolicySplit] = {}

    for trajectory_index in range(300):
        trajectory_id = UUID(int=3_000_000 + trajectory_index)
        maximum = (8, 18, 28)[trajectory_index % 3]
        ordinals = (maximum - 2, maximum - 1, maximum)
        for offset, ordinal in enumerate(ordinals):
            trace_index = trajectory_index * 3 + offset
            builder.register_trace(
                trace(
                    trace_index,
                    trajectory_id=trajectory_id,
                    event_ordinal=ordinal,
                )
            )
        expected_split_by_trajectory[trajectory_id] = (
            MemoryPolicySplit.TRAIN
            if maximum <= 10
            else MemoryPolicySplit.VALIDATION
            if maximum <= 20
            else MemoryPolicySplit.TEST
        )

    snapshot = builder.build(config())
    observed: dict[UUID, set[MemoryPolicySplit]] = {}
    for example in snapshot.examples:
        observed.setdefault(example.trajectory_id, set()).add(example.split)

    assert set(observed) == set(expected_split_by_trajectory)
    for trajectory_id, splits in observed.items():
        assert splits == {expected_split_by_trajectory[trajectory_id]}

    split_trajectories = {
        split: {
            example.trajectory_id
            for example in snapshot.examples_for_split(split)
        }
        for split in MemoryPolicySplit
    }
    assert split_trajectories[MemoryPolicySplit.TRAIN].isdisjoint(
        split_trajectories[MemoryPolicySplit.VALIDATION]
    )
    assert split_trajectories[MemoryPolicySplit.TRAIN].isdisjoint(
        split_trajectories[MemoryPolicySplit.TEST]
    )
    assert split_trajectories[MemoryPolicySplit.VALIDATION].isdisjoint(
        split_trajectories[MemoryPolicySplit.TEST]
    )


def test_trace_candidate_and_registration_permutations_are_invariant() -> None:
    for index in range(250):
        candidates = tuple(
            observation(
                index * 10 + offset,
                (index + offset) % 8,
                original_rank=offset,
            )
            for offset in range(4)
        )
        first_trace = trace(index, candidates=candidates)
        second_trace = trace(index, candidates=set(reversed(candidates)))
        assert first_trace == second_trace
        assert first_trace.render_json() == second_trace.render_json()

    traces = tuple(trace(10_000 + index) for index in range(250))
    first_builder = InMemoryMemoryPolicyDatasetBuilder()
    second_builder = InMemoryMemoryPolicyDatasetBuilder()
    for value in traces:
        first_builder.register_trace(value)
    for value in reversed(traces):
        second_builder.register_trace(value)

    first = first_builder.build(config())
    second = second_builder.build(config())
    assert first == second
    assert first.render_json() == second.render_json()
    assert first.render_jsonl() == second.render_jsonl()


def test_material_fields_change_identity_or_conflict() -> None:
    base_features = features(1)
    feature_mutations = (
        {"semantic_relevance": 0.99},
        {"direct_utility_mean": -0.9},
        {"inherited_utility_confidence": 0.99},
        {"token_cost": 9_999},
        {"original_rank": 7},
    )
    for mutation in feature_mutations:
        changed = features(1, **mutation)
        assert changed.content_hash != base_features.content_hash

    base_observation = observation(1, 0)
    observation_mutations = (
        {"credit_effect_mean": 0.09},
        {"attribution_confidence": 0.95},
        {"credit_evidence_hash": digest("changed-credit")},
        {"harm_observed": True},
    )
    for mutation in observation_mutations:
        changed = observation(1, 0, **mutation)
        assert changed.id != base_observation.id
        assert changed.content_hash != base_observation.content_hash

    base_trace = trace(1)
    changed_trace = trace(
        1,
        task_feature_vector_hash=digest("changed-task"),
    )
    assert changed_trace.content_hash != base_trace.content_hash

    builder = InMemoryMemoryPolicyDatasetBuilder()
    builder.register_trace(base_trace)
    with pytest.raises(MemoryPolicyDatasetConflictError):
        builder.register_trace(changed_trace)
    assert builder.traces() == (base_trace,)

    base_config = config()
    changed_config = config(validation_max_ordinal=21)
    assert changed_config.content_hash != base_config.content_hash
    first_snapshot = builder.build(base_config)
    second_snapshot = builder.build(changed_config)
    assert first_snapshot.id != second_snapshot.id
    assert first_snapshot.content_hash != second_snapshot.content_hash


def test_threshold_and_split_boundary_neighborhoods() -> None:
    builder = InMemoryMemoryPolicyDatasetBuilder()
    values = (
        observation(
            0,
            0,
            credit_confidence_lower_bound=0.02,
            credit_effect_mean=0.03,
            credit_confidence_upper_bound=0.04,
        ),
        observation(
            1,
            0,
            credit_confidence_lower_bound=0.019999,
            credit_effect_mean=0.03,
            credit_confidence_upper_bound=0.04,
        ),
        observation(
            2,
            2,
            credit_confidence_lower_bound=-0.04,
            credit_effect_mean=-0.03,
            credit_confidence_upper_bound=-0.02,
        ),
        observation(
            3,
            2,
            credit_confidence_lower_bound=-0.04,
            credit_effect_mean=-0.03,
            credit_confidence_upper_bound=-0.019999,
        ),
        observation(
            4,
            1,
            credit_confidence_lower_bound=-0.01,
            credit_effect_mean=0.0,
            credit_confidence_upper_bound=0.01,
        ),
        observation(
            5,
            1,
            credit_confidence_lower_bound=-0.010001,
            credit_effect_mean=0.0,
            credit_confidence_upper_bound=0.01,
        ),
    )
    builder.register_trace(trace(0, event_ordinal=10, candidates=values[:2]))
    builder.register_trace(trace(1, event_ordinal=20, candidates=values[2:4]))
    builder.register_trace(trace(2, event_ordinal=21, candidates=values[4:]))

    snapshot = builder.build(config())
    by_candidate = {example.candidate_id: example for example in snapshot.examples}

    assert by_candidate[values[0].candidate_id].label is MemoryPolicyOutcomeLabel.BENEFICIAL
    assert by_candidate[values[1].candidate_id].label is MemoryPolicyOutcomeLabel.ABSTAIN
    assert by_candidate[values[2].candidate_id].label is MemoryPolicyOutcomeLabel.HARMFUL
    assert by_candidate[values[3].candidate_id].label is MemoryPolicyOutcomeLabel.ABSTAIN
    assert by_candidate[values[4].candidate_id].label is MemoryPolicyOutcomeLabel.NEUTRAL
    assert by_candidate[values[5].candidate_id].label is MemoryPolicyOutcomeLabel.ABSTAIN
    assert by_candidate[values[0].candidate_id].split is MemoryPolicySplit.TRAIN
    assert by_candidate[values[2].candidate_id].split is MemoryPolicySplit.VALIDATION
    assert by_candidate[values[4].candidate_id].split is MemoryPolicySplit.TEST


def test_process_hash_seed_does_not_change_snapshot_json_or_jsonl() -> None:
    script = r'''
import hashlib
import json
from uuid import UUID
from nextgen_memory.memory_policy_dataset import (
    InMemoryMemoryPolicyDatasetBuilder,
    MemoryPolicyCandidateFeatures,
    MemoryPolicyCandidateObservation,
    MemoryPolicyCreditKind,
    MemoryPolicyDatasetConfig,
    MemoryPolicyDecisionTrace,
)


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def feature(index, rank):
    return MemoryPolicyCandidateFeatures(
        semantic_relevance=0.8,
        direct_utility_mean=0.2,
        direct_utility_confidence=0.9,
        inherited_utility_mean=0.1,
        inherited_utility_confidence=0.7,
        interaction_effect_mean=0.0,
        interaction_confidence=0.0,
        novelty=0.5,
        authority=0.8,
        freshness=0.9,
        token_cost=100 + index,
        latency_ms=5.0 + index,
        prior_retrieval_count=10 + index,
        prior_use_count=4,
        original_rank=rank,
    )


def candidate(index, rank):
    return MemoryPolicyCandidateObservation(
        candidate_id=UUID(int=100 + index),
        candidate_content_hash=digest(f"candidate:{index}"),
        memory_identity_hash=digest(f"memory:{index}"),
        expert_key_hash=digest(f"expert:{index}"),
        features=feature(index, rank),
        selected_by_policy=True,
        used_by_action=True,
        credit_kind=MemoryPolicyCreditKind.DIRECT_CAUSAL,
        credit_effect_mean=0.08,
        credit_confidence_lower_bound=0.04,
        credit_confidence_upper_bound=0.12,
        attribution_confidence=0.9,
        outcome_observed=True,
        harm_observed=False,
        credit_evidence_hash=digest(f"credit:{index}"),
        interaction_bundle_hash=None,
    )


def trace(index, ordinal):
    candidates = {
        candidate(index * 2, 0),
        candidate(index * 2 + 1, 1),
    }
    return MemoryPolicyDecisionTrace(
        trace_id=UUID(int=1000 + index),
        trajectory_id=UUID(int=2000 + index // 2),
        event_ordinal=ordinal,
        policy_version="deterministic-v1",
        policy_fingerprint="2" * 64,
        source_sha="1" * 40,
        task_feature_vector_hash=digest(f"task:{index}"),
        query_embedding_hash=digest(f"query:{index}"),
        outcome_content_hash=digest(f"outcome:{index}"),
        provenance_content_hash=digest(f"provenance:{index}"),
        decision_budget_tokens=2000,
        decision_budget_latency_ms=100.0,
        candidates=candidates,
    )


traces = {
    trace(0, 5),
    trace(1, 25),
    trace(2, 15),
    trace(3, 16),
}
builder = InMemoryMemoryPolicyDatasetBuilder()
for value in traces:
    builder.register_trace(value)
config = MemoryPolicyDatasetConfig(
    train_max_ordinal=10,
    validation_max_ordinal=20,
    minimum_attribution_confidence=0.75,
    beneficial_effect_threshold=0.02,
    harmful_effect_threshold=0.02,
    neutral_effect_band=0.01,
)
snapshot = builder.build(config)
print(json.dumps({
    "json": snapshot.render_json(),
    "jsonl": snapshot.render_jsonl(),
}, sort_keys=True, separators=(",", ":")))
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
    assert payload["json"].endswith("\n")
    assert payload["jsonl"].endswith("\n")
