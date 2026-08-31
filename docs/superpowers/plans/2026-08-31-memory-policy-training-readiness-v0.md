# Memory Policy Training Readiness Gate v0 Implementation Plan

> **Execution rule:** implement with immutable tests-only RED, exact source preservation, TDD, independent exact-SHA verification, and a separate merge authorization. This milestone never trains or executes a model.

**Goal:** Build a pure advisory gate that rejects unsafe or structurally invalid training data, holds insufficient real datasets, and marks a dataset `ready` only when every real-data, chronology, coverage, balance, freshness, integrity, and privacy gate passes.

**Architecture:** One standard-library-only module owns bounded enums, frozen/slotted split/evidence/config/request/record contracts, canonical SHA-256/UUID5 identity, exact count/chronology reconciliation, stable reason precedence, and a stateless evaluator. It imports only `MemoryPolicySplit` from the already integrated Memory Policy Dataset v0 contract.

**Spec:** `docs/superpowers/specs/2026-08-31-memory-policy-training-readiness-v0-design.md`

## Global constraints

- Exact base is current verified `main`, recorded by `evidence/memory-policy-dataset-v0-postmerge-checkpoint-20260831`.
- Final product surface is exactly the nine paths listed in the design.
- Runtime dependencies remain empty.
- `ready` means only offline-experiment eligibility; `model_training_authorized` is always false.
- No raw prompt/query/response/memory text, reviewer/account identity, credential, path, command output, or arbitrary metadata.
- No filesystem, environment, clock, randomness, network, database, worker, scheduler, model, tensor, optimizer, trainer, feedback, merge, activation, deployment, migration, or release behavior.
- No stub, `pass`, executable ellipsis, `NotImplementedError`, skip, xfail, opportunistic `noqa`, weakened assertion, or fake success.

---

## Task 1: Record the immutable tests-only module-absence RED

**Create:**

```text
docs/memory-policy-training-readiness-v0-red.md
tests/test_memory_policy_training_readiness.py
tests/test_memory_policy_training_readiness_properties.py
tests/test_memory_policy_training_readiness_public_api.py
```

### Focused fixtures

Build deterministic helpers for:

- one nonempty split statistics object;
- a three-split evidence record with exact count/source/credit partitions;
- a passing readiness config;
- an exact request binding the evidence snapshot, source SHA, and artifact hash.

The passing fixture should contain, at minimum:

```text
real operational trajectories         800
controlled replay trajectories        200
synthetic fixture trajectories         0
trainable examples                  8,000
real trainable examples             6,800
replay trainable examples           1,200
synthetic trainable examples            0
direct causal examples              6,400
matched replay examples             1,200
interaction examples                  400
observational examples               800
absent-credit examples              1,200
abstentions                         2,000
```

Split examples, labels, trajectories, ordinals, and total counts must reconcile exactly.

### Reject tests

Write one independent test for every hard reason:

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

Also write one combined case that violates every hold condition plus one hard rejection and requires only rejection reasons.

### Hold tests

Write one independent case for every hold reason:

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

Every isolated case must produce exactly one reason.

### Boundary and structural tests

Cover:

- equality accepted for every minimum and maximum gate;
- one-ULP below/above each relevant threshold;
- train max equal to validation min rejected;
- validation max equal to test min rejected;
- empty split ordinals must be `None`;
- nonempty split ordinals must be present and ordered;
- split input permutation identity;
- fourth split iterator element stops collection;
- duplicate/missing split rejection;
- bool-as-int rejection;
- NaN/Inf rejection;
- malformed UUID, SHA-256, Git SHA, enum, and schema version;
- exact split/internal count validation;
- cross-partition mismatches retained until gate evaluation;
- zero-denominator rates equal exactly `0.0`;
- canonical reasons are unique and declaration ordered;
- frozen/slotted values and canonical JSON;
- no raw-content markers in values or exceptions;
- exact retry equality and material-field identity sensitivity.

### Generated properties

`tests/test_memory_policy_training_readiness_properties.py` must execute at least 10,000 deterministic valid evidence/config evaluations spanning:

```text
ready
hold
reject
all reject reasons
all hold reasons
threshold equality
threshold one-ULP neighborhoods
```

For every generated case:

- repeated evaluation is byte-identical;
- reasons are unique and canonical;
- READY has exactly `all_gates_passed`;
- REJECT has no hold reason;
- HOLD has no reject reason;
- `model_training_authorized` is false;
- `advisory_only` is true;
- material request/config/evidence mutations change identity or fail validation.

A subprocess test constructs split statistics from sets under `PYTHONHASHSEED=1`, `37`, and `999` and requires byte-identical request and decision JSON.

### Public API RED

Require package-root object identity and exactly-once `__all__` membership for:

```text
AdvisoryMemoryPolicyTrainingReadinessGate
MemoryPolicyDataSourceKind
MemoryPolicyDatasetReadinessEvidence
MemoryPolicyDatasetSplitStatistics
MemoryPolicyTrainingReadinessConfig
MemoryPolicyTrainingReadinessReason
MemoryPolicyTrainingReadinessRecord
MemoryPolicyTrainingReadinessRequest
MemoryPolicyTrainingReadinessState
MemoryPolicyTrainingReadinessValidationError
```

### RED qualification

Run Ruff 0.16.4, format check, and `py_compile`, then copy the exact tests into an isolated worktree at the exact base. Each test file must independently fail collection only because:

```text
nextgen_memory.memory_policy_training_readiness
```

Publish:

```text
tdd/memory-policy-training-readiness-v0-red-20260831
```

---

## Task 2: Implement enums, helpers, split statistics, and evidence

**Create:** `src/nextgen_memory/memory_policy_training_readiness.py`

1. Add schema/domain constants and hard bounds.
2. Add the validation error and three `StrEnum` types.
3. Define immutable frozen sets for reject and hold reasons.
4. Implement canonical JSON, SHA-256, UUID5, UUID/hash/Git-SHA/ASCII/numeric/bool validators, and bounded split-statistics normalization.
5. Implement `MemoryPolicyDatasetSplitStatistics` with exact internal partitions.
6. Implement `MemoryPolicyDatasetReadinessEvidence`, normalized split order, derived counts/rates/span, canonical identity, and no I/O.
7. Run constructor, iterator-bound, rate, canonicalization, privacy, and frozen-slot tests.

---

## Task 3: Implement config and exact request identity

1. Implement `MemoryPolicyTrainingReadinessConfig` with all minimum/maximum thresholds and finite/bool-safe validation.
2. Implement `MemoryPolicyTrainingReadinessRequest` binding exact snapshot UUID/hash, source SHA, artifact hash, and evidence.
3. Add `to_dict()` and `render_json()` for both.
4. Prove exact retry equality, permutation identity, and material-field sensitivity.

---

## Task 4: Implement record invariants and the stateless gate

1. Implement count-partition reconciliation helpers.
2. Implement chronological-overlap and trajectory-leakage checks.
3. Implement reject reasons in exact canonical order.
4. Suppress every hold reason when any rejection exists.
5. Implement all hold thresholds in exact canonical order.
6. Implement `MemoryPolicyTrainingReadinessRecord` invariants, canonical JSON, content hash, and UUID5 identity.
7. Enforce:

```text
READY  → all_gates_passed only, offline_experiment_eligible=true
HOLD   → hold reasons only, offline_experiment_eligible=false
REJECT → reject reasons only, offline_experiment_eligible=false
```

8. `model_training_authorized=false` and `advisory_only=true` for every record.
9. Run every focused reject/hold/ready case.

---

## Task 5: Complete generated properties and process determinism

1. Execute 10,000 deterministic evaluations.
2. Cover every reason and state.
3. Exercise threshold equality and one-ULP neighborhoods.
4. Prove reason-order determinism under input permutation.
5. Prove subprocess hash-seed identity.
6. Add material-field mutation tables.
7. Run property tests separately and with the focused suite.

---

## Task 6: Export the API and document operational meaning

**Modify:** `src/nextgen_memory/__init__.py`  
**Create:** `docs/memory-policy-training-readiness-v0.md`

The stable documentation must explain:

- reject versus hold versus ready;
- why synthetic trainable data and trajectory leakage are hard rejects;
- why insufficient real data is a hold;
- exact count/source/credit reconciliation;
- chronology and maximum-ordinal dataset split assumptions;
- rate denominators and zero behavior;
- the privacy boundary;
- that `ready` permits only proposing a separately reviewed offline experiment;
- that model training, shadow execution, promotion, activation, and release remain separate gates.

Export every public name exactly once and prove isolated wheel import.

---

## Task 7: Qualify one immutable nine-path product candidate

Run:

```bash
ruff check .
ruff format --check .
python -m compileall -q src scripts
python -m pytest -q \
  tests/test_memory_policy_training_readiness.py \
  tests/test_memory_policy_training_readiness_properties.py \
  tests/test_memory_policy_training_readiness_public_api.py
python -m pytest -q
```

Run a strict AST/text audit rejecting:

```text
non-standard-library runtime dependencies except the local dataset split enum
filesystem/environment/network/database/time/random/subprocess APIs
trainer/model/optimizer/tensor/checkpoint execution
raw prompt/query/response/memory/account/credential fields
pass, executable ellipsis, NotImplementedError
skip, xfail, noqa
merge, feedback, activation, deployment, migration, release behavior
```

Prove the exact nine-path diff and publish:

```text
candidate/memory-policy-training-readiness-v0-20260831
```

The candidate remains draft, unmerged, and exact-SHA review-pending.

---

## Task 8: Independent matrix, review, merge, and post-merge verification

Python 3.12 and 3.13 independently verify:

- exact base/candidate SHA and nine paths;
- exact RED source preservation;
- Ruff, format, compileall;
- focused/full suites and 10,000 generated evaluations;
- every reject/hold reason and READY state;
- hash-seed invariance and byte-identical semantic decisions;
- strict audit;
- isolated wheel import and `pip check`.

Publish immutable evidence/checkpoints and a GPT-5.6 Pro technical review. A separate exact-SHA authorization may merge the unchanged candidate. A fresh post-merge matrix is mandatory.

Even after merge, the next status may remain `hold` because no claim is made that sufficient real operational trajectories already exist. Training stays unauthorized until a separate offline experiment milestone consumes a real immutable dataset snapshot and a READY record.
