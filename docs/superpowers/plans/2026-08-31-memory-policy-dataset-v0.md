# Memory Policy Dataset v0 Implementation Plan

> **Execution rule:** use the existing TDD and exact-SHA verification workflow. The immutable product candidate may contain only the nine paths named in the design. No model training or production action belongs in this milestone.

**Goal:** Convert exact memory-policy decision traces plus causal/replay credit into immutable, privacy-bounded, trajectory-safe train/validation/test examples for a later learned memory reranker.

**Architecture:** One standard-library-only module owns bounded enums, frozen slotted contracts, canonical SHA-256/UUID5 identity, trace registration, evidence-to-label derivation, conservative trajectory grouping, deterministic snapshot rendering, and audit-safe JSONL. Tests are split into focused contracts, generated properties/hash-seed determinism, and package-root API verification.

**Spec:** `docs/superpowers/specs/2026-08-31-memory-policy-dataset-v0-design.md`

## Global constraints

- Base is the exact verified `main` SHA referenced by `evidence/m-head-main-postmerge-checkpoint-20260831`.
- Product surface is exactly nine paths.
- Standard library only; runtime dependencies remain empty.
- No raw prompt/query/response/memory text, account identity, credential, path, command output, or arbitrary metadata.
- Missing, observational, low-confidence, or ambiguous evidence becomes `abstain`, never negative supervision.
- One trajectory may never cross train/validation/test.
- No trainer, model, optimizer, inference, environment, clock, randomness, filesystem, network, database, worker, feedback, merge, activation, deployment, migration, or release behavior.
- No `pass`, executable ellipsis, `NotImplementedError`, skip, xfail, opportunistic `noqa`, weakened assertion, or fake success.

---

## Task 1: Record an immutable tests-only module-absence RED

**Create:**

```text
docs/memory-policy-dataset-v0-red.md
tests/test_memory_policy_dataset.py
tests/test_memory_policy_dataset_properties.py
tests/test_memory_policy_dataset_public_api.py
```

### Focused test inventory

1. feature-vector finite/range/bool validation;
2. candidate structural invariants for every credit kind;
3. decision-trace uniqueness and 128-candidate iterator bound;
4. exact trace retry and trace/event-key conflicts;
5. no-partial-mutation guarantees;
6. all four labels and inclusive threshold boundaries;
7. no-outcome, observational, and low-confidence abstention;
8. direct/interaction use requirements and matched-replay unselected support;
9. conservative trajectory split by maximum ordinal;
10. zero trajectory overlap across splits;
11. trainable split IDs exclude abstentions;
12. deterministic example/snapshot identities under input permutation;
13. canonical JSON, JSONL, feature payload, target payload, and frozen slots;
14. malformed hashes, UUIDs, Git SHAs, policy versions, budgets, thresholds, and duplicate ranks/identities;
15. unknown trace fail-closed.

### Generated properties

`tests/test_memory_policy_dataset_properties.py` must generate at least 5,000 deterministic traces partitioned across:

```text
beneficial
neutral
harmful
abstain/no outcome
abstain/observational
abstain/low confidence
train
validation
test
```

For every generated dataset:

- exact trace retries return the same object;
- trace/candidate input permutations produce identical snapshots;
- label and split counts exactly partition examples;
- trainable IDs partition only non-abstain examples;
- trajectory sets are pairwise disjoint;
- exact snapshot retries are byte-identical;
- a material field mutation changes identity or fails validation.

A subprocess test must construct traces from sets under `PYTHONHASHSEED=1`, `37`, and `999` and require byte-identical snapshot JSON and JSONL.

### Public API RED

The package-root test imports and checks object identity for exactly these public names:

```text
InMemoryMemoryPolicyDatasetBuilder
MemoryPolicyCandidateFeatures
MemoryPolicyCandidateObservation
MemoryPolicyCreditKind
MemoryPolicyDatasetConfig
MemoryPolicyDatasetConflictError
MemoryPolicyDatasetSnapshot
MemoryPolicyDatasetStateError
MemoryPolicyDatasetValidationError
MemoryPolicyDecisionTrace
MemoryPolicyOutcomeLabel
MemoryPolicySplit
MemoryPolicyTrainingExample
```

### RED qualification

Before product code:

```bash
ruff check tests/test_memory_policy_dataset*.py
ruff format --check tests/test_memory_policy_dataset*.py
python -m py_compile tests/test_memory_policy_dataset*.py
```

Copy the tests into an isolated worktree at the exact base SHA. Each file must independently fail collection only because:

```text
nextgen_memory.memory_policy_dataset
```

Publish one immutable branch:

```text
tdd/memory-policy-dataset-v0-red-20260831
```

---

## Task 2: Implement enums, validation, and immutable feature/candidate contracts

**Create:** `src/nextgen_memory/memory_policy_dataset.py`

1. Add versioned schema/domain constants and hard limits:

```text
MAX_CANDIDATES_PER_TRACE = 128
MAX_REGISTERED_TRACES = 100_000
MAX_POLICY_VERSION_LENGTH = 128
MAX_TOKEN_COST = 1_000_000
MAX_LATENCY_MS = 1_000_000
MAX_COUNT = 1_000_000_000
MAX_EVENT_ORDINAL = 2^63 - 1
```

2. Add the three errors and three `StrEnum` types.
3. Implement canonical JSON, hashing, UUID5, UUID/hash/Git-SHA/policy-version/numeric validators, and bounded unique iterator normalization.
4. Implement `MemoryPolicyCandidateFeatures` exactly as specified.
5. Implement `MemoryPolicyCandidateObservation` and all credit-kind invariants.
6. Add `to_dict()`, `render_json()`, and inference-safe `feature_payload()` where specified.
7. Run constructor, privacy, canonicalization, frozen-slot, and identity-sensitivity tests.

Commit only after those tests pass.

---

## Task 3: Implement immutable decision traces and exact registration

1. Implement `MemoryPolicyDecisionTrace`.
2. Normalize candidate input through `islice(limit + 1)`.
3. Reject duplicate candidate IDs, content hashes, memory identities, and original ranks.
4. Require every used candidate to be selected.
5. Implement `InMemoryMemoryPolicyDatasetBuilder` with:

```python
_traces_by_id
_trace_ids_by_event_key
```

6. `register_trace` validates before mutation and supports exact idempotent retry.
7. Reusing a trace ID or `(trajectory_id, event_ordinal)` with changed content raises `MemoryPolicyDatasetConflictError`.
8. `get_trace` and `traces` fail closed and expose no mutable state.
9. Prove the 100,000-trace hard capacity without allocating unbounded caller iterables.

---

## Task 4: Implement config, labels, trajectory grouping, examples, and snapshot

1. Implement `MemoryPolicyDatasetConfig` and strict threshold ordering.
2. Implement the label precedence exactly from the design.
3. Compute each trajectory's maximum registered event ordinal before assigning any example.
4. Produce one example per candidate with the same split for every member of a trajectory.
5. Implement `MemoryPolicyTrainingExample`, including:

```text
feature_payload()
target_payload()
render_json()
```

6. Implement `MemoryPolicyDatasetSnapshot` with exact counts, trainable IDs, ordering, split methods, JSON, and JSONL.
7. Require no trajectory overlap and complete label/split partitions.
8. Ensure `build(config)` is pure and byte-identical across exact retries.
9. Run all focused tests.

---

## Task 5: Complete generated properties and process determinism

1. Execute 5,000 deterministic traces spanning all labels and splits.
2. Add permutation checks for traces, candidates, set inputs, and registration order.
3. Add material-field mutation tables for features, observations, traces, config, examples, and snapshot identities.
4. Add boundary cases at every threshold and split ordinal.
5. Add hash-seed subprocess comparison for JSON and JSONL.
6. Run generated properties separately and with the complete focused suite.

---

## Task 6: Export the API and document dataset use

**Modify:** `src/nextgen_memory/__init__.py`  
**Create:** `docs/memory-policy-dataset-v0.md`

The stable documentation must state:

- what becomes a trainable example;
- why abstention is not a negative label;
- how maximum-ordinal grouping prevents trajectory leakage;
- exact feature versus target/audit boundaries;
- privacy constraints;
- snapshot identity and JSONL ordering;
- the absence of model training or activation;
- the later Learned Memory Reranker v0 gate.

Export each public name exactly once and prove isolated wheel import.

---

## Task 7: Qualify one immutable nine-path product candidate

Run:

```bash
ruff check .
ruff format --check .
python -m compileall -q src scripts
python -m pytest -q tests/test_memory_policy_dataset.py \
  tests/test_memory_policy_dataset_properties.py \
  tests/test_memory_policy_dataset_public_api.py
python -m pytest -q
```

Then run a strict AST/text audit rejecting:

```text
non-standard-library runtime dependencies
filesystem/environment/network/database/time/random/subprocess APIs
model/trainer/optimizer execution
raw prompt/query/response/memory fields
pass, executable ellipsis, NotImplementedError
skip, xfail, noqa
merge, feedback, activation, deployment, migration, release behavior
```

Prove the exact nine-path diff against the immutable base and publish:

```text
candidate/memory-policy-dataset-v0-20260831
```

The candidate remains unmerged and review-pending.

---

## Task 8: Independent exact-SHA matrix, review, and canonical checkpoint

Python 3.12 and 3.13 independently verify:

- exact base/candidate SHA and nine paths;
- Ruff, formatting, compileall;
- focused and complete suites;
- 5,000 traces;
- trajectory split disjointness;
- hash-seed invariance;
- byte-identical semantic snapshot JSON/JSONL;
- strict audit;
- isolated wheel import and `pip check`.

Publish immutable per-Python artifacts, cross-Python evidence, a canonical draft PR, and an independent GPT-5.6 Pro technical review bound to the unchanged candidate SHA. Persist and read back the canonical checkpoint through Neon and MongoDB Atlas.

Merging this component still authorizes no model training. A separate Learned Memory Reranker v0 milestone must demonstrate enough real trajectories, chronological holdout performance, shadow-mode safety, paired replay superiority over the deterministic baseline, and an explicit promotion decision.
