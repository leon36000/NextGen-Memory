# Memory Policy Dataset v0 Design

**Date:** 2026-08-31  
**Status:** approved under the project owner's standing autonomous-development delegation  
**Milestone:** first deterministic training-data boundary for a learned memory reranker  
**Base:** verified post-merge `main` recorded by `evidence/m-head-main-postmerge-checkpoint-20260831`

## 1. Goal

Memory Policy Dataset v0 converts immutable memory-decision traces and bounded causal/replay credit into deterministic, privacy-safe pointwise training examples. It is the required bridge between the current deterministic learning-policy stack and the first learned memory reranker.

The component does **not** train, load, execute, evaluate, promote, deploy, or activate a model. It produces a versioned dataset snapshot whose examples can later be consumed by a separate training pipeline.

## 2. Position in the learning loop

```text
retrieval / routing decision
  → candidate features
  → selection and actual use
  → outcome observation
  → direct causal / replay / interaction credit
  → MemoryPolicyDecisionTrace
  → Memory Policy Dataset v0
  → immutable train / validation / test snapshot
  → later Learned Memory Reranker v0
```

The dataset builder never treats missing feedback as negative feedback. Unknown, observational, low-confidence, or structurally ambiguous evidence becomes `abstain` and remains auditable but non-trainable.

## 3. Design principles

1. **Evidence before labels.** A trainable label requires exact bounded credit evidence.
2. **No absent-feedback penalty.** No outcome or insufficient confidence yields `abstain`, never `harmful`.
3. **Trajectory-safe splitting.** Every trace and candidate from one trajectory belongs to one split.
4. **Conservative chronology.** A trajectory is assigned using its maximum registered event ordinal; a trajectory crossing a boundary moves wholly into the later split.
5. **No raw content.** Inputs contain hashes and numerical features only.
6. **Canonical identities.** Every immutable value has canonical JSON, SHA-256 content identity, and versioned UUID5 where an ID is derived.
7. **Exact retries.** Re-registering identical evidence returns the same object; changed immutable content conflicts.
8. **Bounded input.** Candidate collections and scalar ranges are hard bounded, including arbitrary iterators.
9. **Pure core.** Standard library only; no I/O, environment, clock, randomness, network, database, worker, scheduler, feedback, merge, deployment, or activation.
10. **Training remains separate.** A valid snapshot is evidence, not authorization to train or promote a model.

## 4. Public enums

### 4.1 `MemoryPolicyCreditKind`

```python
class MemoryPolicyCreditKind(StrEnum):
    NONE = "none"
    DIRECT_CAUSAL = "direct_causal"
    MATCHED_REPLAY = "matched_replay"
    INTERACTION_ALLOCATION = "interaction_allocation"
    OBSERVATIONAL = "observational"
```

V0 trusts `DIRECT_CAUSAL`, `MATCHED_REPLAY`, and `INTERACTION_ALLOCATION` when all structural and confidence gates pass. `NONE` and `OBSERVATIONAL` always produce `abstain`.

### 4.2 `MemoryPolicyOutcomeLabel`

```python
class MemoryPolicyOutcomeLabel(StrEnum):
    BENEFICIAL = "beneficial"
    NEUTRAL = "neutral"
    HARMFUL = "harmful"
    ABSTAIN = "abstain"
```

### 4.3 `MemoryPolicySplit`

```python
class MemoryPolicySplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
```

## 5. Errors

```python
MemoryPolicyDatasetValidationError(ValueError)
MemoryPolicyDatasetConflictError(RuntimeError)
MemoryPolicyDatasetStateError(RuntimeError)
```

Messages contain bounded field/reason categories only. They do not echo raw input values or arbitrary `repr` output.

## 6. `MemoryPolicyCandidateFeatures`

A frozen, slotted numerical feature vector:

```python
semantic_relevance: float                 # [0, 1]
direct_utility_mean: float                # [-1, 1]
direct_utility_confidence: float          # [0, 1]
inherited_utility_mean: float             # [-1, 1]
inherited_utility_confidence: float       # [0, 1]
interaction_effect_mean: float            # [-1, 1]
interaction_confidence: float             # [0, 1]
novelty: float                            # [0, 1]
authority: float                          # [0, 1]
freshness: float                          # [0, 1]
token_cost: int                           # [0, 1_000_000]
latency_ms: float                         # [0, 1_000_000]
prior_retrieval_count: int                # [0, 1_000_000_000]
prior_use_count: int                      # [0, prior_retrieval_count]
original_rank: int                        # [0, 1_000_000]
content_hash: str                         # derived lowercase SHA-256
```

All floats must be finite. Booleans are rejected as numbers. The vector intentionally excludes selected/used flags and labels from the model-input payload.

## 7. `MemoryPolicyCandidateObservation`

A frozen candidate observation:

```python
candidate_id: UUID
candidate_content_hash: str               # SHA-256
memory_identity_hash: str                 # SHA-256
expert_key_hash: str                      # SHA-256
features: MemoryPolicyCandidateFeatures
selected_by_policy: bool
used_by_action: bool
credit_kind: MemoryPolicyCreditKind
credit_effect_mean: float                 # [-1, 1]
credit_confidence_lower_bound: float       # [-1, 1]
credit_confidence_upper_bound: float       # [-1, 1]
attribution_confidence: float              # [0, 1]
outcome_observed: bool
harm_observed: bool
credit_evidence_hash: str                 # SHA-256
interaction_bundle_hash: str | None       # SHA-256 when present
id: UUID                                  # derived UUID5
content_hash: str                         # derived SHA-256
```

Structural invariants:

- `lower_bound <= mean <= upper_bound`;
- `used_by_action` implies `selected_by_policy`;
- `DIRECT_CAUSAL` and `INTERACTION_ALLOCATION` require selected, used, and observed outcome;
- `MATCHED_REPLAY` requires an observed outcome but may represent an unselected candidate;
- `NONE` requires no observed outcome, zero effect/bounds/confidence, no harm, and no interaction bundle;
- `OBSERVATIONAL` may carry an outcome but is never trainable in v0;
- `harm_observed` requires an observed outcome and a trusted non-`NONE` credit kind;
- interaction credit requires `interaction_bundle_hash`; non-interaction credit forbids it.

`selected_by_policy` and `used_by_action` are audit metadata and never part of `feature_payload()`.

## 8. `MemoryPolicyDecisionTrace`

A frozen trace groups all candidates considered by one memory-policy decision:

```python
trace_id: UUID
trajectory_id: UUID
event_ordinal: int                        # [0, 2^63 - 1]
policy_version: str                       # bounded ASCII identifier
policy_fingerprint: str                   # SHA-256
source_sha: str                           # lowercase 40-char Git SHA
task_feature_vector_hash: str             # SHA-256
query_embedding_hash: str                 # SHA-256
outcome_content_hash: str                 # SHA-256
provenance_content_hash: str              # SHA-256
decision_budget_tokens: int               # [0, 1_000_000]
decision_budget_latency_ms: float          # [0, 1_000_000]
candidates: object                        # normalized tuple, 1..128
content_hash: str                         # derived SHA-256
```

Candidate IDs, content hashes, memory identities, and original ranks must be unique within the trace. Candidate input is consumed through 129 elements and then stopped. A decision may select no candidate, but every used candidate must be selected.

No prompt, query, response, memory text, path, command, account, reviewer name, email, credential, or arbitrary metadata field exists.

## 9. `MemoryPolicyDatasetConfig`

```python
train_max_ordinal: int
validation_max_ordinal: int
minimum_attribution_confidence: float      # [0, 1]
beneficial_effect_threshold: float         # (0, 1]
harmful_effect_threshold: float            # (0, 1]
neutral_effect_band: float                 # [0, 1)
content_hash: str
```

Validation:

- `train_max_ordinal < validation_max_ordinal`;
- thresholds are finite and booleans are rejected;
- both beneficial and harmful thresholds are strictly greater than the neutral band.

A trajectory group uses its maximum registered `event_ordinal`:

```text
max ordinal <= train_max_ordinal       → train
max ordinal <= validation_max_ordinal  → validation
otherwise                              → test
```

This makes trajectory membership disjoint across splits.

## 10. Label derivation

For each candidate, derive the label in this strict order:

1. `NONE` or `OBSERVATIONAL` → `ABSTAIN`;
2. missing outcome → `ABSTAIN`;
3. attribution confidence below the configured minimum → `ABSTAIN`;
4. `harm_observed` → `HARMFUL`;
5. lower confidence bound greater than or equal to `beneficial_effect_threshold` → `BENEFICIAL`;
6. upper confidence bound less than or equal to negative `harmful_effect_threshold` → `HARMFUL`;
7. the complete confidence interval lies inside `[-neutral_effect_band, +neutral_effect_band]` → `NEUTRAL`;
8. otherwise → `ABSTAIN`.

`BENEFICIAL`, `NEUTRAL`, and `HARMFUL` are trainable. `ABSTAIN` is retained for audit but has `trainable=False` and `sample_weight=0.0`. Trainable examples use `sample_weight=attribution_confidence`.

Threshold equality is deliberately inclusive.

## 11. `MemoryPolicyTrainingExample`

Each candidate produces one immutable pointwise example:

```python
id: UUID
trace_id: UUID
trajectory_id: UUID
event_ordinal: int
split: MemoryPolicySplit
policy_fingerprint: str
source_sha: str
task_feature_vector_hash: str
query_embedding_hash: str
candidate_id: UUID
candidate_content_hash: str
memory_identity_hash: str
expert_key_hash: str
features: MemoryPolicyCandidateFeatures
label: MemoryPolicyOutcomeLabel
trainable: bool
sample_weight: float
target_effect_mean: float
target_effect_lower_bound: float
target_effect_upper_bound: float
credit_kind: MemoryPolicyCreditKind
selected_by_policy: bool                 # audit metadata only
used_by_action: bool                     # audit metadata only
credit_evidence_hash: str
interaction_bundle_hash: str | None
content_hash: str
```

The derived ID is UUID5 over the canonical content hash under the domain:

```text
nextgen-memory:memory-policy-training-example-v0:<content_hash>
```

`feature_payload()` returns only inference-safe feature inputs and immutable candidate/task identities. `target_payload()` returns label/effect/weight. Behavioral audit fields are excluded from `feature_payload()`.

## 12. `InMemoryMemoryPolicyDatasetBuilder`

Internal state:

```python
_traces_by_id: dict[UUID, MemoryPolicyDecisionTrace]
_trace_ids_by_event_key: dict[tuple[UUID, int], UUID]
```

Hard maximum: 100,000 registered traces.

Methods:

```python
register_trace(trace) -> MemoryPolicyDecisionTrace
get_trace(trace_id) -> MemoryPolicyDecisionTrace
traces() -> tuple[MemoryPolicyDecisionTrace, ...]
build(config) -> MemoryPolicyDatasetSnapshot
```

Registration order:

1. exact trace type;
2. existing trace ID exact retry or conflict;
3. existing `(trajectory_id, event_ordinal)` exact retry or conflict;
4. trace-count capacity;
5. mutate both maps only after every check passes.

No partial mutation is permitted.

## 13. `MemoryPolicyDatasetSnapshot`

A frozen snapshot contains:

```python
id: UUID
config_content_hash: str
trace_ids: tuple[UUID, ...]
examples: tuple[MemoryPolicyTrainingExample, ...]
train_example_ids: tuple[UUID, ...]       # trainable only
validation_example_ids: tuple[UUID, ...]  # trainable only
test_example_ids: tuple[UUID, ...]        # trainable only
trajectory_count: int
trainable_example_count: int
abstention_count: int
label_counts: tuple[tuple[str, int], ...]
split_counts: tuple[tuple[str, int], ...]
content_hash: str
```

Canonical ordering:

```text
trajectory UUID
→ event ordinal
→ original rank
→ candidate UUID
```

The snapshot validates:

- all referenced trace/example IDs are unique;
- every trainable example appears in exactly one split list;
- abstentions appear in no trainable split list;
- no trajectory ID appears in more than one split;
- label and split counts exactly partition all examples;
- all examples bind the snapshot config and source trace identities.

Methods:

```python
render_json() -> str
render_jsonl(*, trainable_only: bool = False) -> str
examples_for_split(
    split: MemoryPolicySplit,
    *,
    trainable_only: bool = False,
) -> tuple[MemoryPolicyTrainingExample, ...]
```

No method writes a file.

## 14. Canonicalization and privacy

Private helpers provide:

- canonical compact JSON with sorted keys, `allow_nan=False`, and one trailing newline;
- lowercase SHA-256 and Git-SHA validation;
- exact UUID and enum validation;
- bounded ASCII policy-version validation;
- finite integer/float validation with bool rejection;
- bounded unique iterable normalization using `itertools.islice(limit + 1)`;
- SHA-256 content hashing;
- versioned UUID5 domain separation.

Canonical JSON and JSONL may contain only UUIDs, hashes, bounded policy identifiers, enums, booleans, numerical features, counts, and labels. Exception messages never echo untrusted input.

## 15. Determinism and leakage tests

The tests-only RED must prove:

- exact request registration retry and immutable conflicts;
- no partial mutation;
- all four labels and inclusive threshold boundaries;
- no-outcome and observational abstention;
- direct-credit use requirements and matched-replay counterfactual support;
- candidate and trace collection bounds;
- duplicate candidate/rank/event rejection;
- maximum-event-ordinal trajectory split assignment;
- zero trajectory overlap across train/validation/test;
- trace/candidate/permutation invariance;
- canonical JSON/JSONL;
- frozen objects and material-field identity sensitivity;
- at least 5,000 deterministic generated traces spanning all labels and splits;
- subprocess `PYTHONHASHSEED=1`, `37`, and `999` byte identity;
- public package exports and isolated wheel import.

## 16. Exact product surface

```text
docs/memory-policy-dataset-v0-red.md
docs/memory-policy-dataset-v0.md
docs/superpowers/specs/2026-08-31-memory-policy-dataset-v0-design.md
docs/superpowers/plans/2026-08-31-memory-policy-dataset-v0.md
src/nextgen_memory/__init__.py
src/nextgen_memory/memory_policy_dataset.py
tests/test_memory_policy_dataset.py
tests/test_memory_policy_dataset_properties.py
tests/test_memory_policy_dataset_public_api.py
```

No workflow, migration, dependency, package metadata, database adapter, trainer, model artifact, feedback writer, activation path, deployment path, or release path belongs in the product candidate.

## 17. Verification and next milestone

Before merge:

- precise immutable tests-only module-absence RED from exact current main;
- Ruff 0.16.4, format, compileall;
- focused and complete suites;
- 5,000 generated traces;
- process hash-seed invariance;
- strict dependency/privacy/side-effect/stub audit;
- isolated wheel installation;
- independent Python 3.12/3.13 exact-SHA matrix;
- immutable evidence/checkpoint and GPT-5.6 Pro technical review.

Merging this component authorizes no training. The subsequent **Learned Memory Reranker v0** milestone may consume only an immutable dataset snapshot with enough real trajectories, a chronological holdout, a deterministic baseline, shadow-mode evaluation, paired replay, and a separate promotion gate.
