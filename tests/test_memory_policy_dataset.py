from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import FrozenInstanceError, replace
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

BASE_SHA = "1" * 40
POLICY_FP = "2" * 64
TASK_HASH = "3" * 64
QUERY_HASH = "4" * 64
OUTCOME_HASH = "5" * 64
PROVENANCE_HASH = "6" * 64


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def features(**overrides: object) -> MemoryPolicyCandidateFeatures:
    values: dict[str, object] = {
        "semantic_relevance": 0.8,
        "direct_utility_mean": 0.2,
        "direct_utility_confidence": 0.9,
        "inherited_utility_mean": 0.1,
        "inherited_utility_confidence": 0.7,
        "interaction_effect_mean": 0.0,
        "interaction_confidence": 0.0,
        "novelty": 0.5,
        "authority": 0.8,
        "freshness": 0.9,
        "token_cost": 120,
        "latency_ms": 8.5,
        "prior_retrieval_count": 10,
        "prior_use_count": 4,
        "original_rank": 0,
    }
    values.update(overrides)
    return MemoryPolicyCandidateFeatures(**values)  # type: ignore[arg-type]


def observation(
    index: int = 0,
    *,
    credit_kind: MemoryPolicyCreditKind = MemoryPolicyCreditKind.DIRECT_CAUSAL,
    **overrides: object,
) -> MemoryPolicyCandidateObservation:
    values: dict[str, object] = {
        "candidate_id": UUID(int=index + 1),
        "candidate_content_hash": digest(f"candidate-content:{index}"),
        "memory_identity_hash": digest(f"memory-identity:{index}"),
        "expert_key_hash": digest(f"expert:{index}"),
        "features": features(original_rank=index),
        "selected_by_policy": True,
        "used_by_action": True,
        "credit_kind": credit_kind,
        "credit_effect_mean": 0.08,
        "credit_confidence_lower_bound": 0.04,
        "credit_confidence_upper_bound": 0.12,
        "attribution_confidence": 0.9,
        "outcome_observed": True,
        "harm_observed": False,
        "credit_evidence_hash": digest(f"credit-evidence:{index}"),
        "interaction_bundle_hash": None,
    }
    if credit_kind is MemoryPolicyCreditKind.NONE:
        values.update(
            {
                "selected_by_policy": False,
                "used_by_action": False,
                "credit_effect_mean": 0.0,
                "credit_confidence_lower_bound": 0.0,
                "credit_confidence_upper_bound": 0.0,
                "attribution_confidence": 0.0,
                "outcome_observed": False,
                "harm_observed": False,
            }
        )
    elif credit_kind is MemoryPolicyCreditKind.MATCHED_REPLAY:
        values.update(
            {
                "selected_by_policy": False,
                "used_by_action": False,
            }
        )
    elif credit_kind is MemoryPolicyCreditKind.INTERACTION_ALLOCATION:
        values["interaction_bundle_hash"] = digest(f"interaction:{index}")
    elif credit_kind is MemoryPolicyCreditKind.OBSERVATIONAL:
        values.update(
            {
                "selected_by_policy": True,
                "used_by_action": True,
            }
        )
    values.update(overrides)
    return MemoryPolicyCandidateObservation(**values)  # type: ignore[arg-type]


def trace(
    trace_index: int = 0,
    *,
    trajectory_id: UUID | None = None,
    event_ordinal: int = 5,
    candidates: object | None = None,
    **overrides: object,
) -> MemoryPolicyDecisionTrace:
    values: dict[str, object] = {
        "trace_id": UUID(int=10_000 + trace_index),
        "trajectory_id": trajectory_id or UUID(int=20_000 + trace_index),
        "event_ordinal": event_ordinal,
        "policy_version": "deterministic-v1",
        "policy_fingerprint": POLICY_FP,
        "source_sha": BASE_SHA,
        "task_feature_vector_hash": TASK_HASH,
        "query_embedding_hash": QUERY_HASH,
        "outcome_content_hash": OUTCOME_HASH,
        "provenance_content_hash": PROVENANCE_HASH,
        "decision_budget_tokens": 2_000,
        "decision_budget_latency_ms": 100.0,
        "candidates": candidates
        if candidates is not None
        else (observation(trace_index),),
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


def example_by_candidate(
    snapshot: MemoryPolicyDatasetSnapshot,
) -> dict[UUID, MemoryPolicyTrainingExample]:
    return {example.candidate_id: example for example in snapshot.examples}


def test_label_precedence_and_inclusive_boundaries() -> None:
    beneficial = observation(
        0,
        credit_effect_mean=0.04,
        credit_confidence_lower_bound=0.02,
        credit_confidence_upper_bound=0.06,
    )
    neutral = observation(
        1,
        credit_effect_mean=0.0,
        credit_confidence_lower_bound=-0.01,
        credit_confidence_upper_bound=0.01,
    )
    harmful = observation(
        2,
        credit_effect_mean=-0.04,
        credit_confidence_lower_bound=-0.06,
        credit_confidence_upper_bound=-0.02,
    )
    ambiguous = observation(
        3,
        credit_effect_mean=0.0,
        credit_confidence_lower_bound=-0.02,
        credit_confidence_upper_bound=0.02,
    )
    hard_harm = observation(
        4,
        credit_effect_mean=0.08,
        credit_confidence_lower_bound=0.04,
        credit_confidence_upper_bound=0.12,
        harm_observed=True,
    )
    builder = InMemoryMemoryPolicyDatasetBuilder()
    review_trace = builder.register_trace(
        trace(
            candidates=(beneficial, neutral, harmful, ambiguous, hard_harm),
        )
    )

    snapshot = builder.build(config())
    examples = example_by_candidate(snapshot)

    assert examples[beneficial.candidate_id].label is MemoryPolicyOutcomeLabel.BENEFICIAL
    assert examples[neutral.candidate_id].label is MemoryPolicyOutcomeLabel.NEUTRAL
    assert examples[harmful.candidate_id].label is MemoryPolicyOutcomeLabel.HARMFUL
    assert examples[ambiguous.candidate_id].label is MemoryPolicyOutcomeLabel.ABSTAIN
    assert examples[hard_harm.candidate_id].label is MemoryPolicyOutcomeLabel.HARMFUL
    assert examples[beneficial.candidate_id].trainable is True
    assert examples[ambiguous.candidate_id].trainable is False
    assert examples[ambiguous.candidate_id].sample_weight == 0.0
    assert examples[beneficial.candidate_id].sample_weight == 0.9
    assert snapshot.trace_ids == (review_trace.trace_id,)


def test_absent_observational_and_low_confidence_evidence_abstain() -> None:
    none_value = observation(0, credit_kind=MemoryPolicyCreditKind.NONE)
    observational = observation(
        1,
        credit_kind=MemoryPolicyCreditKind.OBSERVATIONAL,
    )
    low_confidence = observation(2, attribution_confidence=0.74)
    missing_outcome = observation(
        3,
        credit_kind=MemoryPolicyCreditKind.OBSERVATIONAL,
        outcome_observed=False,
        credit_effect_mean=0.0,
        credit_confidence_lower_bound=0.0,
        credit_confidence_upper_bound=0.0,
        attribution_confidence=0.0,
    )
    builder = InMemoryMemoryPolicyDatasetBuilder()
    builder.register_trace(
        trace(candidates=(none_value, observational, low_confidence, missing_outcome))
    )

    snapshot = builder.build(config())

    assert all(
        example.label is MemoryPolicyOutcomeLabel.ABSTAIN
        for example in snapshot.examples
    )
    assert snapshot.trainable_example_count == 0
    assert snapshot.abstention_count == 4
    assert snapshot.train_example_ids == ()
    assert snapshot.validation_example_ids == ()
    assert snapshot.test_example_ids == ()


def test_direct_interaction_and_matched_replay_structural_rules() -> None:
    matched = observation(
        0,
        credit_kind=MemoryPolicyCreditKind.MATCHED_REPLAY,
    )
    assert matched.selected_by_policy is False
    assert matched.used_by_action is False
    assert matched.outcome_observed is True

    interaction = observation(
        1,
        credit_kind=MemoryPolicyCreditKind.INTERACTION_ALLOCATION,
    )
    assert interaction.interaction_bundle_hash == digest("interaction:1")

    with pytest.raises(MemoryPolicyDatasetValidationError, match="direct causal"):
        observation(
            2,
            selected_by_policy=True,
            used_by_action=False,
        )
    with pytest.raises(MemoryPolicyDatasetValidationError, match="interaction"):
        observation(
            3,
            credit_kind=MemoryPolicyCreditKind.INTERACTION_ALLOCATION,
            interaction_bundle_hash=None,
        )
    with pytest.raises(MemoryPolicyDatasetValidationError, match="matched replay"):
        observation(
            4,
            credit_kind=MemoryPolicyCreditKind.MATCHED_REPLAY,
            outcome_observed=False,
        )
    with pytest.raises(MemoryPolicyDatasetValidationError, match="used candidate"):
        observation(
            5,
            credit_kind=MemoryPolicyCreditKind.OBSERVATIONAL,
            selected_by_policy=False,
            used_by_action=True,
        )
    with pytest.raises(MemoryPolicyDatasetValidationError, match="none credit"):
        observation(
            6,
            credit_kind=MemoryPolicyCreditKind.NONE,
            outcome_observed=True,
        )
    with pytest.raises(MemoryPolicyDatasetValidationError, match="harm"):
        observation(
            7,
            credit_kind=MemoryPolicyCreditKind.OBSERVATIONAL,
            harm_observed=True,
        )


def test_exact_trace_retry_and_conflicts_do_not_partially_mutate() -> None:
    builder = InMemoryMemoryPolicyDatasetBuilder()
    first_trace = trace()

    first = builder.register_trace(first_trace)
    second = builder.register_trace(first_trace)

    assert first is first_trace
    assert second is first_trace
    assert builder.get_trace(first_trace.trace_id) is first_trace
    assert builder.traces() == (first_trace,)

    changed_same_id = trace(task_feature_vector_hash=digest("changed-task"))
    with pytest.raises(MemoryPolicyDatasetConflictError, match="trace id conflict"):
        builder.register_trace(changed_same_id)
    assert builder.traces() == (first_trace,)

    changed_event_key = trace(
        1,
        trajectory_id=first_trace.trajectory_id,
        event_ordinal=first_trace.event_ordinal,
    )
    with pytest.raises(MemoryPolicyDatasetConflictError, match="event key conflict"):
        builder.register_trace(changed_event_key)
    assert builder.traces() == (first_trace,)


def test_unknown_trace_reads_fail_closed() -> None:
    builder = InMemoryMemoryPolicyDatasetBuilder()
    unknown = UUID(int=999_999)

    with pytest.raises(MemoryPolicyDatasetStateError, match="not registered"):
        builder.get_trace(unknown)
    with pytest.raises(MemoryPolicyDatasetStateError, match="no traces"):
        builder.build(config())


def test_trajectory_uses_maximum_event_ordinal_for_one_split() -> None:
    shared = UUID(int=77_777)
    builder = InMemoryMemoryPolicyDatasetBuilder()
    early = builder.register_trace(
        trace(0, trajectory_id=shared, event_ordinal=5, candidates=(observation(0),))
    )
    late = builder.register_trace(
        trace(1, trajectory_id=shared, event_ordinal=25, candidates=(observation(1),))
    )
    train_trace = builder.register_trace(
        trace(2, event_ordinal=10, candidates=(observation(2),))
    )
    validation_trace = builder.register_trace(
        trace(3, event_ordinal=20, candidates=(observation(3),))
    )

    snapshot = builder.build(config())
    by_trace = {example.trace_id: example for example in snapshot.examples}

    assert by_trace[early.trace_id].split is MemoryPolicySplit.TEST
    assert by_trace[late.trace_id].split is MemoryPolicySplit.TEST
    assert by_trace[train_trace.trace_id].split is MemoryPolicySplit.TRAIN
    assert by_trace[validation_trace.trace_id].split is MemoryPolicySplit.VALIDATION

    trajectory_splits: dict[UUID, set[MemoryPolicySplit]] = {}
    for example in snapshot.examples:
        trajectory_splits.setdefault(example.trajectory_id, set()).add(example.split)
    assert all(len(splits) == 1 for splits in trajectory_splits.values())

    train_trajectories = {
        example.trajectory_id
        for example in snapshot.examples_for_split(MemoryPolicySplit.TRAIN)
    }
    validation_trajectories = {
        example.trajectory_id
        for example in snapshot.examples_for_split(MemoryPolicySplit.VALIDATION)
    }
    test_trajectories = {
        example.trajectory_id
        for example in snapshot.examples_for_split(MemoryPolicySplit.TEST)
    }
    assert train_trajectories.isdisjoint(validation_trajectories)
    assert train_trajectories.isdisjoint(test_trajectories)
    assert validation_trajectories.isdisjoint(test_trajectories)


def test_trainable_split_ids_partition_only_non_abstain_examples() -> None:
    beneficial = observation(0)
    abstain = observation(1, credit_kind=MemoryPolicyCreditKind.NONE)
    harmful = observation(
        2,
        credit_effect_mean=-0.08,
        credit_confidence_lower_bound=-0.12,
        credit_confidence_upper_bound=-0.04,
    )
    builder = InMemoryMemoryPolicyDatasetBuilder()
    builder.register_trace(trace(0, event_ordinal=5, candidates=(beneficial, abstain)))
    builder.register_trace(trace(1, event_ordinal=15, candidates=(harmful,)))

    snapshot = builder.build(config())
    trainable_ids = {
        example.id for example in snapshot.examples if example.trainable
    }
    partition_ids = (
        set(snapshot.train_example_ids)
        | set(snapshot.validation_example_ids)
        | set(snapshot.test_example_ids)
    )

    assert partition_ids == trainable_ids
    assert set(snapshot.train_example_ids).isdisjoint(
        snapshot.validation_example_ids
    )
    assert set(snapshot.train_example_ids).isdisjoint(snapshot.test_example_ids)
    assert set(snapshot.validation_example_ids).isdisjoint(
        snapshot.test_example_ids
    )
    assert snapshot.trainable_example_count == 2
    assert snapshot.abstention_count == 1
    assert dict(snapshot.label_counts) == {
        "abstain": 1,
        "beneficial": 1,
        "harmful": 1,
        "neutral": 0,
    }
    assert dict(snapshot.split_counts) == {
        "test": 0,
        "train": 2,
        "validation": 1,
    }


def test_candidate_and_trace_permutations_preserve_identity() -> None:
    first_candidate = observation(0)
    second_candidate = observation(1)
    first_trace = trace(candidates=(second_candidate, first_candidate))
    second_trace = trace(candidates={first_candidate, second_candidate})

    assert first_trace == second_trace
    assert first_trace.render_json() == second_trace.render_json()

    first_builder = InMemoryMemoryPolicyDatasetBuilder()
    second_builder = InMemoryMemoryPolicyDatasetBuilder()
    trace_a = trace(1, event_ordinal=5, candidates=(observation(2),))
    trace_b = trace(2, event_ordinal=15, candidates=(observation(3),))
    first_builder.register_trace(trace_a)
    first_builder.register_trace(trace_b)
    second_builder.register_trace(trace_b)
    second_builder.register_trace(trace_a)

    first_snapshot = first_builder.build(config())
    second_snapshot = second_builder.build(config())

    assert first_snapshot == second_snapshot
    assert first_snapshot.render_json() == second_snapshot.render_json()
    assert first_snapshot.render_jsonl() == second_snapshot.render_jsonl()


class GuardedCandidates:
    def __init__(self) -> None:
        self.pulls = 0

    def __iter__(self) -> GuardedCandidates:
        return self

    def __next__(self) -> MemoryPolicyCandidateObservation:
        self.pulls += 1
        if self.pulls <= 129:
            index = self.pulls + 1_000
            return observation(index)
        raise AssertionError("candidate iterator consumed beyond limit plus one")


def test_candidate_iterators_are_hard_bounded() -> None:
    guarded = GuardedCandidates()

    with pytest.raises(MemoryPolicyDatasetValidationError, match="candidates"):
        trace(candidates=guarded)

    assert guarded.pulls == 129


def test_trace_rejects_duplicate_candidate_id_memory_identity_and_rank() -> None:
    first = observation(0)
    duplicate_id = replace(
        observation(1),
        candidate_id=first.candidate_id,
    )
    duplicate_memory = replace(
        observation(2),
        memory_identity_hash=first.memory_identity_hash,
    )
    duplicate_rank = replace(
        observation(3),
        features=features(original_rank=first.features.original_rank),
    )

    for invalid_candidates in (
        (first, duplicate_id),
        (first, duplicate_memory),
        (first, duplicate_rank),
    ):
        with pytest.raises(MemoryPolicyDatasetValidationError, match="duplicate"):
            trace(candidates=invalid_candidates)


def test_feature_and_target_payloads_separate_inference_from_audit_fields() -> None:
    builder = InMemoryMemoryPolicyDatasetBuilder()
    value = observation(0)
    builder.register_trace(trace(candidates=(value,)))
    example = builder.build(config()).examples[0]

    feature_payload = example.feature_payload()
    target_payload = example.target_payload()

    assert feature_payload["memory_identity_hash"] == value.memory_identity_hash
    assert feature_payload["expert_key_hash"] == value.expert_key_hash
    assert feature_payload["features"] == value.features.feature_payload()
    for forbidden in (
        "selected_by_policy",
        "used_by_action",
        "credit_kind",
        "credit_evidence_hash",
        "label",
        "sample_weight",
        "outcome_observed",
    ):
        assert forbidden not in feature_payload
    assert target_payload == {
        "label": "beneficial",
        "sample_weight": 0.9,
        "target_effect_lower_bound": 0.04,
        "target_effect_mean": 0.08,
        "target_effect_upper_bound": 0.12,
        "trainable": True,
    }


def test_canonical_json_jsonl_privacy_and_frozen_slots() -> None:
    builder = InMemoryMemoryPolicyDatasetBuilder()
    registered = builder.register_trace(trace())
    snapshot = builder.build(config())
    example = snapshot.examples[0]

    for value in (
        features(),
        observation(),
        registered,
        config(),
        example,
        snapshot,
    ):
        raw = value.render_json()
        assert raw == (
            json.dumps(
                json.loads(raw),
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        assert not hasattr(value, "__dict__")

    jsonl = snapshot.render_jsonl()
    lines = jsonl.splitlines()
    assert len(lines) == len(snapshot.examples)
    assert all(json.loads(line)["schema"] for line in lines)
    assert snapshot.render_jsonl(trainable_only=True) == jsonl

    lowered = (snapshot.render_json() + jsonl).lower()
    for forbidden in (
        "raw_prompt",
        "raw_query",
        "response_text",
        "memory_body",
        "credential",
        "password",
        "reviewer_email",
        "reviewer_name",
    ):
        assert forbidden not in lowered

    with pytest.raises((AttributeError, FrozenInstanceError)):
        example.content_hash = "0" * 64  # type: ignore[misc]
    assert replace(features(), novelty=0.9).content_hash != features().content_hash
    assert replace(config(), validation_max_ordinal=21).content_hash != config().content_hash


@pytest.mark.parametrize(
    "overrides",
    [
        {"semantic_relevance": -0.01},
        {"semantic_relevance": 1.01},
        {"direct_utility_mean": float("nan")},
        {"token_cost": True},
        {"token_cost": 1_000_001},
        {"latency_ms": float("inf")},
        {"prior_retrieval_count": -1},
        {"prior_use_count": 11},
        {"original_rank": True},
    ],
)
def test_features_reject_malformed_values(overrides: dict[str, object]) -> None:
    with pytest.raises(MemoryPolicyDatasetValidationError):
        features(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"candidate_id": "not-a-uuid"},
        {"candidate_content_hash": "A" * 64},
        {"memory_identity_hash": "f" * 63},
        {"expert_key_hash": "g" * 64},
        {"features": object()},
        {"selected_by_policy": 1},
        {"used_by_action": 0},
        {"credit_kind": "direct_causal"},
        {"credit_effect_mean": 1.1},
        {"credit_confidence_lower_bound": 0.09},
        {"credit_confidence_upper_bound": 0.07},
        {"attribution_confidence": True},
        {"credit_evidence_hash": "A" * 64},
        {"interaction_bundle_hash": "b" * 63},
    ],
)
def test_candidate_rejects_malformed_values(overrides: dict[str, object]) -> None:
    with pytest.raises(MemoryPolicyDatasetValidationError):
        observation(0, **overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"trace_id": "not-a-uuid"},
        {"trajectory_id": "not-a-uuid"},
        {"event_ordinal": True},
        {"event_ordinal": -1},
        {"policy_version": ""},
        {"policy_version": "invalid policy"},
        {"policy_fingerprint": "A" * 64},
        {"source_sha": "A" * 40},
        {"task_feature_vector_hash": "3" * 63},
        {"query_embedding_hash": "z" * 64},
        {"decision_budget_tokens": True},
        {"decision_budget_latency_ms": float("nan")},
        {"candidates": ()},
        {"candidates": "not-a-candidate-collection"},
    ],
)
def test_trace_rejects_malformed_values(overrides: dict[str, object]) -> None:
    with pytest.raises(MemoryPolicyDatasetValidationError):
        trace(**overrides)


@pytest.mark.parametrize(
    "overrides",
    [
        {"train_max_ordinal": True},
        {"train_max_ordinal": -1},
        {"validation_max_ordinal": 10},
        {"minimum_attribution_confidence": float("nan")},
        {"minimum_attribution_confidence": 1.1},
        {"beneficial_effect_threshold": 0.0},
        {"harmful_effect_threshold": 0.0},
        {"neutral_effect_band": -0.01},
        {"neutral_effect_band": 1.0},
        {"beneficial_effect_threshold": 0.01},
        {"harmful_effect_threshold": 0.01},
    ],
)
def test_config_rejects_malformed_values(overrides: dict[str, object]) -> None:
    with pytest.raises(MemoryPolicyDatasetValidationError):
        config(**overrides)


def test_examples_for_split_rejects_non_enum_split() -> None:
    builder = InMemoryMemoryPolicyDatasetBuilder()
    builder.register_trace(trace())
    snapshot = builder.build(config())

    with pytest.raises(MemoryPolicyDatasetValidationError, match="split"):
        snapshot.examples_for_split("train")  # type: ignore[arg-type]
