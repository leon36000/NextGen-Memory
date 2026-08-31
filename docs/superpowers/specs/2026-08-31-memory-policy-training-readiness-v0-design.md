# Memory Policy Training Readiness Gate v0 Design

**Date:** 2026-08-31  
**Status:** approved under the project owner's standing autonomous-development delegation  
**Purpose:** fail-closed evidence gate before any Learned Memory Reranker v0 training experiment  
**Base:** verified `main` containing Memory Policy Dataset v0, recorded by `evidence/memory-policy-dataset-v0-postmerge-checkpoint-20260831`

## 1. Goal

Memory Policy Training Readiness Gate v0 determines whether one immutable Memory Policy Dataset snapshot contains enough trustworthy real operational evidence to justify creating a separately reviewed offline Learned Memory Reranker experiment.

The gate returns one advisory state:

```text
ready
hold
reject
```

It never trains, loads, executes, publishes, deploys, or activates a model. `ready` means only that the data satisfies the configured readiness contract. `model_training_authorized` is always `false` in v0.

## 2. Position in the learned-memory path

```text
real memory-policy traces
  → immutable Memory Policy Dataset snapshot
  → integrity / privacy / leakage / coverage evidence
  → Memory Policy Training Readiness Gate v0
  → ready | hold | reject
  → separately reviewed offline training experiment
  → chronological holdout + shadow mode + paired replay
  → later promotion gate
```

No later step is implied by a `ready` record.

## 3. Design principles

1. **Real evidence dominates.** Controlled replay may supplement but never replace real operational trajectories.
2. **Synthetic data is not training evidence.** Any synthetic trainable example is a hard rejection.
3. **No trajectory leakage.** Any trajectory overlap across train, validation, and test is a hard rejection.
4. **Chronology is structural.** Split event ranges must be strictly ordered and non-overlapping.
5. **Count partitions are exact.** Snapshot, split, source, label, and credit counts must reconcile exactly.
6. **Missing evidence is not failure.** Insufficient volume or coverage yields `hold`, not `reject`.
7. **Hard rejection wins.** If any reject condition exists, hold reasons are suppressed.
8. **No raw content.** Only UUIDs, hashes, bounded identifiers, booleans, ordinals, counts, rates, and finite metrics are accepted.
9. **Canonical decisions.** Inputs and records use compact canonical JSON, SHA-256 content identity, UUID5 domain separation, stable reason ordering, and exact retry determinism.
10. **Pure core.** Standard library plus the local Memory Policy Dataset contract only; no I/O, clock, randomness, environment, network, database, worker, model, optimizer, feedback, merge, deployment, migration, activation, or release surface.

## 4. Public enums

### 4.1 `MemoryPolicyDataSourceKind`

```python
class MemoryPolicyDataSourceKind(StrEnum):
    REAL_OPERATIONAL = "real_operational"
    CONTROLLED_REPLAY = "controlled_replay"
    SYNTHETIC_FIXTURE = "synthetic_fixture"
```

The enum is exported for exact bounded provenance categories. Aggregate source counts in readiness evidence use these categories.

### 4.2 `MemoryPolicyTrainingReadinessState`

```python
class MemoryPolicyTrainingReadinessState(StrEnum):
    READY = "ready"
    HOLD = "hold"
    REJECT = "reject"
```

### 4.3 `MemoryPolicyTrainingReadinessReason`

Canonical order is declaration order.

Hard rejection reasons:

```text
safety_violation
snapshot_identity_mismatch
source_sha_mismatch
artifact_hash_mismatch
schema_validation_failed
artifact_integrity_failed
privacy_audit_failed
raw_content_scan_failed
provenance_validation_failed
synthetic_trainable_data
trajectory_leakage
chronological_overlap
count_partition_mismatch
```

Hold reasons:

```text
insufficient_real_trajectories
insufficient_real_trainable_share
insufficient_trainable_examples
insufficient_train_trajectories
insufficient_validation_trajectories
insufficient_test_trajectories
insufficient_effective_sample_size
insufficient_chronological_span
insufficient_policy_diversity
insufficient_expert_diversity
insufficient_beneficial_coverage
insufficient_neutral_coverage
insufficient_harmful_coverage
insufficient_direct_causal_share
excessive_abstention_rate
excessive_dominant_label_share
excessive_replay_share
excessive_duplicate_feature_rate
stale_evidence
```

Success reason:

```text
all_gates_passed
```

## 5. Errors

```python
MemoryPolicyTrainingReadinessValidationError(ValueError)
```

Malformed immutable inputs fail construction. Exception messages contain bounded field and reason categories only and never echo raw values or arbitrary representations.

## 6. `MemoryPolicyDatasetSplitStatistics`

A frozen, slotted split summary:

```python
split: MemoryPolicySplit
trajectory_count: int
example_count: int
trainable_example_count: int
beneficial_count: int
neutral_count: int
harmful_count: int
abstain_count: int
minimum_event_ordinal: int | None
maximum_event_ordinal: int | None
content_hash: str
```

Validation:

- booleans are rejected as counts/ordinals;
- counts are in `[0, 2^63 - 1]`;
- `example_count == trainable_example_count + abstain_count`;
- `trainable_example_count == beneficial_count + neutral_count + harmful_count`;
- when `trajectory_count == 0`, every example/label count is zero and both ordinals are `None`;
- when `trajectory_count > 0`, `example_count > 0`, both ordinals are present, and `minimum_event_ordinal <= maximum_event_ordinal`.

The object exposes canonical `to_dict()` and `render_json()`.

## 7. `MemoryPolicyDatasetReadinessEvidence`

A frozen, slotted aggregate evidence record:

```python
snapshot_id: UUID
snapshot_content_hash: str                  # SHA-256
dataset_artifact_sha256: str                # SHA-256
dataset_source_sha: str                     # lowercase 40-char Git SHA
dataset_schema_version: str                 # bounded ASCII identifier
snapshot_trajectory_count: int
snapshot_example_count: int
snapshot_trainable_example_count: int
snapshot_abstention_count: int
split_statistics: object                    # exactly train/validation/test
real_operational_trajectory_count: int
controlled_replay_trajectory_count: int
synthetic_fixture_trajectory_count: int
real_operational_trainable_example_count: int
controlled_replay_trainable_example_count: int
synthetic_fixture_trainable_example_count: int
direct_causal_example_count: int
matched_replay_example_count: int
interaction_allocation_example_count: int
observational_example_count: int
absent_credit_example_count: int
effective_sample_size: float
duplicate_feature_vector_count: int
distinct_policy_version_count: int
distinct_expert_key_count: int
train_validation_trajectory_overlap_count: int
train_test_trajectory_overlap_count: int
validation_test_trajectory_overlap_count: int
evidence_age_seconds: float
schema_validation_passed: bool
artifact_integrity_passed: bool
privacy_audit_passed: bool
raw_content_scan_passed: bool
provenance_validation_passed: bool
safety_violation: bool
content_hash: str
```

`split_statistics` is consumed through four elements, rejects strings/mappings, requires actual `MemoryPolicyDatasetSplitStatistics` instances, and normalizes to train/validation/test order. Exactly one object per split is required.

Scalar validation is strict and finite. Cross-partition inconsistencies are intentionally retained for gate evaluation and become the hard reason `count_partition_mismatch`, rather than being silently normalized.

Derived properties include:

```text
total_label_counts
chronological_span_ordinals
abstention_rate
real_operational_trainable_share
controlled_replay_trainable_share
direct_causal_trainable_share
dominant_trainable_label_share
duplicate_feature_rate
```

All zero-denominator rates are deterministically `0.0`; corresponding insufficiency gates still prevent readiness.

## 8. `MemoryPolicyTrainingReadinessConfig`

A frozen, slotted gate policy:

```python
minimum_real_operational_trajectories: int
minimum_real_operational_trainable_share: float
minimum_trainable_examples: int
minimum_train_trajectories: int
minimum_validation_trajectories: int
minimum_test_trajectories: int
minimum_effective_sample_size: float
minimum_chronological_span_ordinals: int
minimum_distinct_policy_versions: int
minimum_distinct_expert_keys: int
minimum_beneficial_examples: int
minimum_neutral_examples: int
minimum_harmful_examples: int
minimum_direct_causal_trainable_share: float
maximum_abstention_rate: float
maximum_dominant_label_share: float
maximum_controlled_replay_trainable_share: float
maximum_duplicate_feature_rate: float
maximum_evidence_age_seconds: float
gate_policy_version: str = "memory-policy-training-readiness-v0"
content_hash: str
```

Validation:

- integer minima are nonnegative and bounded; booleans are rejected;
- required trajectory/example/policy/expert minima are positive except chronological span, which may be zero;
- rates are finite and within `[0, 1]`;
- minimum shares may be zero but `minimum_real_operational_trainable_share + maximum_controlled_replay_trainable_share` need not equal one because synthetic trainable data is separately rejected;
- maximum evidence age is finite and nonnegative;
- gate policy version is a bounded ASCII identifier.

## 9. `MemoryPolicyTrainingReadinessRequest`

A frozen exact binding:

```python
snapshot_id: UUID
snapshot_content_hash: str
dataset_source_sha: str
dataset_artifact_sha256: str
evidence: MemoryPolicyDatasetReadinessEvidence
id: UUID
content_hash: str
```

The request intentionally duplicates the four external snapshot identities so the gate can reject identity drift between the expected training input and the evidence record.

Identity domain:

```text
nextgen-memory:memory-policy-training-readiness-request-v0:<content_hash>
```

## 10. Count and chronology reconciliation

The gate computes the following hard invariants.

### 10.1 Snapshot/split counts

```text
sum split trajectory_count == snapshot_trajectory_count
sum split example_count == snapshot_example_count
sum split trainable_example_count == snapshot_trainable_example_count
sum split abstain_count == snapshot_abstention_count
sum split beneficial/neutral/harmful counts == snapshot_trainable_example_count
```

### 10.2 Source counts

```text
real + replay + synthetic trajectory counts == snapshot_trajectory_count
real + replay + synthetic trainable example counts == snapshot_trainable_example_count
```

### 10.3 Credit counts

```text
direct causal
+ matched replay
+ interaction allocation
+ observational
+ absent credit
== snapshot_example_count
```

### 10.4 Chronology

When all three splits are nonempty:

```text
train.maximum_event_ordinal < validation.minimum_event_ordinal
validation.maximum_event_ordinal < test.minimum_event_ordinal
```

For any two nonempty adjacent splits, equality or overlap is `chronological_overlap`.

### 10.5 Leakage

Any nonzero pairwise trajectory-overlap count is `trajectory_leakage`.

## 11. `AdvisoryMemoryPolicyTrainingReadinessGate`

```python
evaluate(
    request: MemoryPolicyTrainingReadinessRequest,
    config: MemoryPolicyTrainingReadinessConfig,
) -> MemoryPolicyTrainingReadinessRecord
```

The gate is stateless and pure.

### 11.1 Reject precedence

Evaluate all reject conditions in canonical reason order:

1. safety violation;
2. request/evidence snapshot UUID or content-hash mismatch;
3. source Git SHA mismatch;
4. dataset artifact SHA mismatch;
5. schema validation failure;
6. artifact integrity failure;
7. privacy audit failure;
8. raw-content scan failure;
9. provenance validation failure;
10. synthetic trainable examples greater than zero;
11. any pairwise trajectory overlap;
12. chronological overlap;
13. any count partition mismatch.

If any rejection exists, return `REJECT` with only reject reasons. Hold reasons are suppressed.

### 11.2 Hold gates

When no rejection exists, add every violated sufficiency reason in canonical order:

- real operational trajectories below minimum;
- real operational trainable share below minimum;
- trainable examples below minimum;
- train/validation/test trajectories below configured minima;
- effective sample size below minimum;
- chronological span below minimum;
- distinct policy/expert counts below minima;
- beneficial/neutral/harmful counts below minima;
- direct-causal trainable share below minimum;
- abstention rate above maximum;
- dominant trainable-label share above maximum;
- controlled replay trainable share above maximum;
- duplicate-feature rate above maximum;
- evidence age above maximum.

Any hold reason yields `HOLD`.

### 11.3 Ready

No reject or hold reason yields:

```text
state = ready
reasons = (all_gates_passed,)
offline_experiment_eligible = true
model_training_authorized = false
advisory_only = true
```

## 12. `MemoryPolicyTrainingReadinessRecord`

A frozen, slotted decision:

```python
id: UUID
request_id: UUID
request_content_hash: str
config_content_hash: str
evidence_content_hash: str
state: MemoryPolicyTrainingReadinessState
reasons: tuple[MemoryPolicyTrainingReadinessReason, ...]
offline_experiment_eligible: bool
model_training_authorized: bool
advisory_only: bool
content_hash: str
```

Invariants:

- reasons are nonempty, unique, and in enum declaration order;
- `REJECT` contains only reject reasons;
- `HOLD` contains only hold reasons;
- `READY` contains exactly `ALL_GATES_PASSED`;
- `offline_experiment_eligible` is true only for `READY`;
- `model_training_authorized` is always false;
- `advisory_only` is always true.

Record identity domain:

```text
nextgen-memory:memory-policy-training-readiness-record-v0:<content_hash>
```

## 13. Privacy and side-effect boundary

Allowed runtime imports are standard-library modules and the local `memory_policy_dataset` contract for `MemoryPolicySplit`.

The module contains no:

```text
filesystem or environment access
clock or randomness
network or database client
subprocess, thread, task, worker, lease, scheduler
trainer, model, optimizer, tensor, checkpoint loader
feedback writer, policy activation, merge, deployment, migration, release
```

Canonical JSON contains only bounded identifiers, UUIDs, hashes, Git SHA, enums, booleans, ordinals, counts, finite metrics, rates, reasons, and readiness state.

## 14. TDD requirements

The immutable tests-only RED must cover:

- all public constructors and exports;
- every reject reason independently;
- every hold reason independently;
- hard-reject suppression of all simultaneous holds;
- all-gates-passed READY;
- equality and one-ULP neighborhoods for every threshold/rate;
- count-partition mismatches one dimension at a time;
- empty split and chronological overlap edge cases;
- zero-denominator rate determinism;
- split-statistics iterator bound and permutation invariance;
- exact retry identity and material-field sensitivity;
- canonical JSON, frozen slots, privacy markers, exception privacy;
- at least 10,000 generated valid evidence/config evaluations spanning READY/HOLD/REJECT;
- subprocess hash-seed invariance under seeds 1, 37, and 999;
- package-root exports and isolated wheel import.

## 15. Exact product surface

```text
docs/memory-policy-training-readiness-v0-red.md
docs/memory-policy-training-readiness-v0.md
docs/superpowers/specs/2026-08-31-memory-policy-training-readiness-v0-design.md
docs/superpowers/plans/2026-08-31-memory-policy-training-readiness-v0.md
src/nextgen_memory/__init__.py
src/nextgen_memory/memory_policy_training_readiness.py
tests/test_memory_policy_training_readiness.py
tests/test_memory_policy_training_readiness_properties.py
tests/test_memory_policy_training_readiness_public_api.py
```

No workflow, migration, dependency, trainer, model artifact, persistence adapter, feedback writer, activation path, deployment path, or release path belongs in the immutable product candidate.

## 16. Verification and next stage

Before merge:

- exact tests-only module-absence RED from current main;
- Ruff 0.16.4, format, compileall;
- focused and complete tests;
- 10,000 generated evaluations;
- process hash-seed invariance;
- strict dependency/privacy/side-effect/stub audit;
- isolated wheel import;
- independent Python 3.12/3.13 exact-SHA matrix;
- immutable evidence/checkpoint and GPT-5.6 Pro technical review.

After merge, the gate may remain `hold` until real operational data exists. Only a separate Learned Memory Reranker offline experiment specification may consume a `ready` record. Model training, shadow execution, promotion, activation, and release each remain separate reviewed milestones.
