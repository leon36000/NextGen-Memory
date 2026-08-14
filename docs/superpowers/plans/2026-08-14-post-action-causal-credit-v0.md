# Post-Action Causal Credit v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attribute stable task-outcome changes to the specific memories that were selected and used, then persist deterministic append-only feedback without broadcasting terminal reward to correlated shadows.

**Architecture:** Consume scoped retrieval-use evidence and matched full/no-memory/leave-one-out outcomes. A pure assigner computes paired effects and abstains under missing, unstable, unused, or interaction-ambiguous evidence. A separate builder/writer produces idempotent `memory_feedback` rows protected by an additive Neon migration tested only on a temporary branch.

**Tech Stack:** Python 3.12+, immutable dataclasses, standard-library statistics/hash/UUID, DB-API-style cursor protocols, PostgreSQL/Neon, pytest, Ruff, GitHub Actions.

## Global Constraints

- Work only on `feat/post-action-causal-credit-v0`, stacked on `feat/utility-aware-reranker-v0`.
- Do not merge, retarget to `main`, or modify the production Neon schema.
- Do not write live `memory_feedback` rows on the production branch.
- Do not add a learned model, LLM evaluator, NumPy, PyTorch, or external ML dependency.
- Only memories with `selected_for_context=true` and `used_in_action=true` are eligible.
- Every comparison is paired by a fixed context hash and continuation hash.
- Missing ablations and provider failures must abstain or propagate; they must never become zero effects.
- No raw query, prompt, action, answer, command, output, note, secret, token, diff, patch, or environment payload may enter causal feedback.
- Record integrated RED evidence before each production slice.
- Final CI must pass Ruff and the complete pytest suite on Python 3.12 and 3.13.

---

### Task 1: Immutable counterfactual contracts and pure credit assignment

**Files:**
- Create: `tests/test_causal_credit.py`
- Create after RED: `src/nextgen_memory/causal_credit.py`

**Interfaces:**
- Produces:
  - `OutcomeMeasurement(score, task_success, tokens=0, latency_ms=0.0)`
  - `CounterfactualTrial(trial_key, context_hash, continuation_hash, full, no_memory, without_memory)`
  - `CreditTarget(memory_id, retrieval_event_id, router_decision_id, selected_for_context, used_in_action)`
  - `CausalCreditConfig(min_trials=2, helpful_threshold=0.05, decisive_threshold=0.20, harmful_threshold=-0.05, neutral_band=0.02, max_standard_error=0.10, reward_clip=1.0, record_neutral=False)`
  - `CreditAbstentionReason`
  - `AttributedMemoryCredit`
  - `CreditAssignmentResult`
  - `CausalCreditAssigner.assign(targets, trials) -> CreditAssignmentResult`

- [ ] **Step 1: Write focused failing tests**

Create tests covering:

```python
def test_stable_positive_effect_is_helpful(): ...
def test_large_effect_that_changes_success_is_decisive(): ...
def test_stable_negative_effect_is_harmful(): ...
def test_unused_or_unselected_memory_is_withheld(): ...
def test_missing_ablation_is_withheld(): ...
def test_one_trial_is_insufficient_by_default(): ...
def test_high_variance_effect_is_withheld(): ...
def test_duplicate_trial_key_fails_closed(): ...
def test_redundant_positive_bundle_is_interaction_ambiguous(): ...
def test_cost_delta_sign_is_full_minus_without_memory(): ...
```

Use two or more matched trials with fixed 64-character hashes. Assert exact means, sample standard error, verdict, reward, task-success majority, token delta, latency delta, and abstention reason.

- [ ] **Step 2: Push tests-only commit and record integrated RED**

Create the stacked draft PR after tests only. GitHub CI must pass Ruff and fail only because `nextgen_memory.causal_credit` does not exist.

- [ ] **Step 3: Implement validation and immutable contracts**

Required validation:

```python
- score in [-1.0, 1.0]
- tokens is a non-negative integer
- latency_ms is finite and non-negative
- trial_key is non-empty
- context_hash and continuation_hash match ^[0-9a-f]{64}$
- without_memory keys are UUIDs
- target IDs are UUIDs
- router_decision_id is identical for all targets in one assignment
- trial keys are unique
```

- [ ] **Step 4: Implement paired statistics and verdict mapping**

For each eligible target with at least `min_trials` leave-one-out observations:

```python
marginals = [trial.full.score - trial.without_memory[memory_id].score]
bundle_uplifts = [trial.full.score - trial.no_memory.score]
mean_effect = statistics.fmean(marginals)
standard_error = statistics.stdev(marginals) / sqrt(len(marginals))
```

For exactly one observation, standard error is `inf`; default `min_trials=2` therefore abstains before classification.

Classification:

```python
if standard_error > config.max_standard_error:
    abstain(HIGH_VARIANCE)
elif mean_effect >= decisive_threshold and full_success_rate > without_success_rate:
    DECISIVE
elif mean_effect >= helpful_threshold:
    HELPFUL
elif mean_effect <= harmful_threshold:
    HARMFUL
elif abs(mean_effect) <= neutral_band and record_neutral:
    NEUTRAL
else:
    abstain(BELOW_THRESHOLD)
```

Before per-node neutral classification, if mean bundle uplift exceeds `helpful_threshold` and every eligible mean effect lies inside the neutral band, abstain all with `INTERACTION_AMBIGUOUS`.

- [ ] **Step 5: Run focused GREEN and Ruff**

```bash
python -m pytest tests/test_causal_credit.py -q
python -m ruff check src/nextgen_memory/causal_credit.py tests/test_causal_credit.py
```

Expected: all focused tests pass with pristine output.

- [ ] **Step 6: Commit**

```bash
git add src/nextgen_memory/causal_credit.py tests/test_causal_credit.py
git commit -m "feat: add paired causal memory credit"
```

---

### Task 2: Scoped retrieval-use target reader

**Files:**
- Create: `tests/test_credit_targets.py`
- Create after RED: `src/nextgen_memory/credit_targets.py`

**Interfaces:**
- Produces:
  - `CREDIT_TARGETS_SELECT_SQL`
  - `CreditTargetReader.fetch(cursor, *, space_id, router_decision_id) -> tuple[CreditTarget, ...]`

- [ ] **Step 1: Write failing reader tests**

Assert the SQL contains:

```sql
FROM ngm.retrieval_events
WHERE space_id = %(space_id)s
  AND router_decision_id = %(router_decision_id)s
  AND node_id IS NOT NULL
  AND selected_for_context = true
ORDER BY rank, node_id
```

Use a fake mapping cursor. Verify exact parameters, deterministic order, UUID parsing, and propagation of `used_in_action`.

Reject:

- missing required columns;
- returned `space_id` or router decision mismatch;
- duplicate node IDs;
- rows with `selected_for_context=false`;
- invalid UUIDs.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_credit_targets.py -q
```

Expected: import failure for `nextgen_memory.credit_targets`.

- [ ] **Step 3: Implement minimal parameterized reader**

The reader returns selected targets even when `used_in_action=false`; the pure assigner owns the explicit `NOT_USED` abstention decision.

- [ ] **Step 4: Run focused GREEN and Ruff**

```bash
python -m pytest tests/test_credit_targets.py -q
python -m ruff check src/nextgen_memory/credit_targets.py tests/test_credit_targets.py
```

- [ ] **Step 5: Commit**

```bash
git add src/nextgen_memory/credit_targets.py tests/test_credit_targets.py
git commit -m "feat: read scoped memory credit targets"
```

---

### Task 3: Deterministic feedback builder and transactional writer

**Files:**
- Create: `tests/test_causal_feedback.py`
- Create after RED: `src/nextgen_memory/causal_feedback.py`

**Interfaces:**
- Produces:
  - `CAUSAL_FEEDBACK_INSERT_SQL`
  - `CAUSAL_FEEDBACK_SELECT_SQL`
  - `MemoryFeedbackRecord`
  - `build_memory_feedback_records(*, space_id, credit_evaluation_id, assignment) -> tuple[MemoryFeedbackRecord, ...]`
  - `MemoryFeedbackWriter.write(cursor, records) -> int`

- [ ] **Step 1: Write failing builder tests**

Assert:

```python
feedback_id == uuid5(
    credit_evaluation_id,
    f"paired_leave_one_out_v0:{memory_id}",
)
record.verdict in {"decisive", "helpful", "harmful", "neutral"}
record.reward == pytest.approx(attributed.mean_effect)
record.notes is None
len(record.content_hash) == 64
```

Metadata must contain only:

```text
credit_version
trial_count
mean_full_score
mean_no_memory_score
mean_without_memory_score
mean_bundle_uplift
mean_effect
standard_error
context_set_hash
continuation_set_hash
```

- [ ] **Step 2: Write failing writer tests**

Use a fake cursor that records calls and returns the stored row. Assert:

1. insertion is parameterized;
2. rows are selected back by deterministic ID;
3. identical stored payload returns success;
4. any changed immutable field raises `CausalFeedbackConflictError`;
5. empty record batches do no I/O.

- [ ] **Step 3: Run RED**

```bash
python -m pytest tests/test_causal_feedback.py -q
```

Expected: import failure for `nextgen_memory.causal_feedback`.

- [ ] **Step 4: Implement immutable records and canonical hashing**

Hash the canonical JSON representation of every immutable persisted field except `created_at`. Use `allow_nan=False`, sorted keys, compact separators, and UUID/date string normalization.

- [ ] **Step 5: Implement insert-then-verify writer**

`CAUSAL_FEEDBACK_INSERT_SQL` uses:

```sql
INSERT INTO ngm.memory_feedback (...)
VALUES (...)
ON CONFLICT (space_id, credit_evaluation_id, node_id)
WHERE credit_evaluation_id IS NOT NULL
DO NOTHING
```

After the insert batch, select every deterministic ID using `CAUSAL_FEEDBACK_SELECT_SQL` and compare exact immutable payloads. The surrounding transaction is owned by the caller.

- [ ] **Step 6: Run focused GREEN and Ruff**

```bash
python -m pytest tests/test_causal_feedback.py -q
python -m ruff check src/nextgen_memory/causal_feedback.py tests/test_causal_feedback.py
```

- [ ] **Step 7: Commit**

```bash
git add src/nextgen_memory/causal_feedback.py tests/test_causal_feedback.py
git commit -m "feat: persist idempotent causal memory feedback"
```

---

### Task 4: Additive Neon causal-feedback migration

**Files:**
- Create: `tests/test_causal_feedback_migration.py`
- Create after RED: `migrations/neon/0005_causal_credit_feedback.sql`
- Create: `docs/causal-credit-v0.md`

**Interfaces:**
- Adds nullable columns to `ngm.memory_feedback`:
  - `credit_evaluation_id uuid`
  - `evidence_key text`
  - `content_hash text`
- Adds partial unique index:
  - `(space_id, credit_evaluation_id, node_id)` where `credit_evaluation_id IS NOT NULL`
- Adds safe-metadata validation and immutability only for causal rows.

- [ ] **Step 1: Write failing migration contract test**

Assert the SQL contains:

```text
ADD COLUMN IF NOT EXISTS credit_evaluation_id
ADD COLUMN IF NOT EXISTS evidence_key
ADD COLUMN IF NOT EXISTS content_hash
paired_leave_one_out_v0
CREATE UNIQUE INDEX IF NOT EXISTS memory_feedback_causal_identity_uidx
credit_metadata_is_safe
assert_same_causal_feedback_payload
reject_causal_feedback_mutation
credit_evaluation_id IS NOT NULL
```

Also assert the migration never drops or recreates `memory_feedback`.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_causal_feedback_migration.py -q
```

Expected: missing migration file.

- [ ] **Step 3: Implement additive, idempotent SQL**

Use `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Add constraints through `DO` blocks scoped by both `conname` and `conrelid`. The causal-row completeness constraint is:

```sql
CHECK (
  credit_evaluation_id IS NULL
  OR (
    node_id IS NOT NULL
    AND router_decision_id IS NOT NULL
    AND evidence_key = 'paired_leave_one_out_v0'
    AND content_hash ~ '^[0-9a-f]{64}$'
    AND notes IS NULL
    AND jsonb_typeof(metadata) = 'object'
    AND ngm.credit_metadata_is_safe(metadata)
  )
)
```

Trigger behavior:

```text
legacy row (credit_evaluation_id NULL): unchanged behavior
causal row: UPDATE and DELETE rejected
```

- [ ] **Step 4: Verify on a temporary Neon branch**

Create a temporary branch from project `polished-unit-28052463`. Apply the migration twice. Insert one valid helpful feedback row and verify `ngm.node_utility` reflects it. Verify these failures in isolated exception blocks:

- conflicting causal identity;
- unsafe nested metadata;
- mutation of a causal row;
- deletion of a causal row;
- non-null notes on a causal row.

Confirm production remains unchanged, then delete the temporary branch.

- [ ] **Step 5: Run focused test and document evidence**

```bash
python -m pytest tests/test_causal_feedback_migration.py -q
```

Document exact branch name/ID, positive path, negative paths, reapplication result, deletion, and production non-mutation in `docs/causal-credit-v0.md`.

- [ ] **Step 6: Commit**

```bash
git add migrations/neon/0005_causal_credit_feedback.sql tests/test_causal_feedback_migration.py docs/causal-credit-v0.md
git commit -m "feat: add causal feedback persistence contract"
```

---

### Task 5: Deterministic causal-credit simulation

**Files:**
- Create: `tests/test_causal_credit_simulation.py`
- Create after RED: `scripts/simulate_causal_credit.py`

**Interfaces:**
- Produces:
  - `SimulationConfig(seed=20260814, task_count=5000, shadow_count=4, trial_count=3, noise_stddev=0.03)`
  - `simulate(config) -> SimulationResult`
  - deterministic CLI JSON.

- [ ] **Step 1: Write failing simulation tests**

Assert fixed-seed results satisfy:

```python
result.bundle_shadow_contamination_rate >= 0.80
result.loo_shadow_false_credit_rate <= 0.05
result.loo_causal_detection_rate >= 0.75
result.noisy_abstention_precision >= 0.90
```

Also assert two runs produce byte-identical JSON.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_causal_credit_simulation.py -q
```

- [ ] **Step 3: Implement standard-library simulation**

Use `random.Random(seed)`. Model:

- one causal memory with true effect `+0.25`;
- `shadow_count` zero-effect correlated memories;
- a separate high-noise zero-effect candidate;
- three matched trials by default;
- naive bundle reward to every retrieved memory;
- leave-one-out mean and standard-error gate matching `CausalCreditConfig`.

- [ ] **Step 4: Verify determinism**

```bash
python scripts/simulate_causal_credit.py > /tmp/causal-credit-a.json
python scripts/simulate_causal_credit.py > /tmp/causal-credit-b.json
cmp /tmp/causal-credit-a.json /tmp/causal-credit-b.json
sha256sum /tmp/causal-credit-a.json
```

- [ ] **Step 5: Commit**

```bash
git add scripts/simulate_causal_credit.py tests/test_causal_credit_simulation.py
git commit -m "test: simulate post-action causal credit"
```

---

### Task 6: Public API and integrated verification

**Files:**
- Modify: `src/nextgen_memory/__init__.py`
- Create: `tests/test_causal_credit_public_api.py`
- Modify: `README.md`
- Modify: `docs/causal-credit-v0.md`

**Interfaces:**
- Exports all approved causal-credit, target-reader, and feedback-writer contracts without importing database drivers or ML frameworks.

- [ ] **Step 1: Write failing public-API test**

Import from `nextgen_memory`:

```python
OutcomeMeasurement
CounterfactualTrial
CreditTarget
CausalCreditConfig
CreditAbstentionReason
AttributedMemoryCredit
CreditAssignmentResult
CausalCreditAssigner
CREDIT_TARGETS_SELECT_SQL
CreditTargetReader
MemoryFeedbackRecord
CausalFeedbackWriter
build_memory_feedback_records
```

Assert package import does not load `psycopg`, `pymongo`, `numpy`, `torch`, or `tensorflow`.

- [ ] **Step 2: Run RED, then add exports and documentation**

```bash
python -m pytest tests/test_causal_credit_public_api.py -q
```

After the expected failure, update package exports and README architecture/status sections.

- [ ] **Step 3: Run full verification**

```bash
python -m pytest -q
python -m ruff check src tests scripts
python -m compileall -q src scripts
python -m build --no-isolation
```

Inspect:

```bash
git diff --check
grep -RInE 'postgres(ql)?://|mongodb\+srv://|api[_-]?key\s*=' src tests scripts docs README.md || true
grep -RInE 'query_text|stdout|stderr|prompt|secret|token|patch_text' src/nextgen_memory/causal_credit.py src/nextgen_memory/causal_feedback.py src/nextgen_memory/credit_targets.py || true
```

- [ ] **Step 4: Update draft PR with exact evidence**

Record:

- each RED workflow ID and expected failure;
- final GREEN workflow ID;
- Python 3.12/3.13 test counts;
- simulation output and SHA-256;
- temporary Neon branch verification and deletion;
- production row/schema counts before and after;
- no merge or default-branch mutation.

- [ ] **Step 5: Commit**

```bash
git add src/nextgen_memory/__init__.py tests/test_causal_credit_public_api.py README.md docs/causal-credit-v0.md
git commit -m "docs: expose and verify post-action causal credit"
```
