# Utility-Aware Reranker v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, explainable utility-aware reranker that combines scoped Atlas relevance with aggregate Neon utility evidence, bounded cost penalties, and a reproducible reward-trap simulation.

**Architecture:** Add a pure scoring module with immutable contracts, a dependency-injected reader over the existing `ngm.node_utility` view, and a decorator that oversamples the current scope-safe retriever before returning the original result limit. No schema migration or feedback write is introduced.

**Tech Stack:** Python 3.12+, dataclasses, standard-library math/hash/types, DB-API-style cursor protocols, pytest, Ruff, existing MongoDB Atlas retrieval contracts, existing Neon `ngm.node_utility` view.

## Global Constraints

- Work only on `feat/utility-aware-reranker-v0`, stacked on `feat/retrieval-scope-safe-v2`.
- Do not merge, retarget to `main`, or mutate the default branch.
- Do not add a learned model, external ML dependency, LLM reranker, or schema migration.
- Missing utility evidence is neutral; provider failures propagate.
- Every utility lookup must include canonical `space_id` and canonical memory UUIDs.
- No raw query, prompt, command, output, note, secret, or source payload enters the utility contracts.
- Use strict TDD: record an integrated RED CI state before production implementation.
- Final CI must pass Ruff and the full pytest suite on Python 3.12 and 3.13.

---

### Task 1: Pure utility evidence and reranking contracts

**Files:**
- Create: `tests/test_utility_reranker.py`
- Create after RED: `src/nextgen_memory/utility_reranker.py`

**Interfaces:**
- Consumes: `ResearchRetrievalHit` from `nextgen_memory.retrieval`.
- Produces:
  - `UtilityEvidence(memory_id, feedback_count=0, avg_reward=None, positive_count=0, negative_count=0, last_feedback_at=None)`
  - `UtilityRerankCandidate(hit, utility, estimated_tokens=0, estimated_latency_ms=0.0)`
  - `UtilityRerankerConfig(...)`
  - `UtilityScoreBreakdown(...)`
  - `RerankedMemory(hit, original_rank, final_rank, final_score, breakdown)`
  - `UtilityAwareReranker.rerank(candidates, limit=None) -> tuple[RerankedMemory, ...]`

- [ ] **Step 1: Write failing contract and behavior tests**

Cover:

```python
def test_no_feedback_preserves_relevance_order(): ...
def test_one_positive_event_does_not_overpower_clear_relevance_gap(): ...
def test_repeated_helpful_evidence_can_promote_near_tied_candidate(): ...
def test_harmful_evidence_demotes_high_relevance_candidate(): ...
def test_cost_penalties_are_bounded_and_exposed(): ...
def test_ties_are_deterministic_by_original_rank_then_uuid(): ...
def test_invalid_counts_costs_and_weights_fail_closed(): ...
```

Use fixed UUIDs and `ResearchRetrievalHit` scores. Assert the breakdown components and that their weighted sum equals `final_score` within `pytest.approx`.

- [ ] **Step 2: Push tests and record integrated RED**

Create a draft stacked PR after committing tests only. GitHub CI must pass Ruff and fail because `nextgen_memory.utility_reranker` does not exist.

- [ ] **Step 3: Implement immutable contracts and scoring**

Implement:

```python
class UtilityAwareReranker:
    def rerank(
        self,
        candidates: Sequence[UtilityRerankCandidate],
        *,
        limit: int | None = None,
    ) -> tuple[RerankedMemory, ...]: ...
```

Scoring must follow the approved design exactly:

```python
confidence = count / (count + prior_strength)
reward_signal = clamp(avg_reward, -1.0, 1.0) * confidence
verdict_confidence = verdict_count / (verdict_count + prior_strength)
verdict_signal = ((positive - negative) / verdict_count) * verdict_confidence
harm_risk = (negative / verdict_count) * verdict_confidence
```

Use positive-score normalization by the maximum positive retrieval score; use reciprocal rank only when all scores are non-positive. Reject non-finite intermediate/final values.

- [ ] **Step 4: Run focused tests**

Run:

```bash
python -m pytest tests/test_utility_reranker.py -q
python -m ruff check src/nextgen_memory/utility_reranker.py tests/test_utility_reranker.py
```

Expected: all focused tests and Ruff pass.

- [ ] **Step 5: Commit**

```bash
git add src/nextgen_memory/utility_reranker.py tests/test_utility_reranker.py
git commit -m "feat: add deterministic utility-aware reranker"
```

---

### Task 2: Scoped Neon utility reader

**Files:**
- Create: `tests/test_neon_utility.py`
- Create after RED: `src/nextgen_memory/neon_utility.py`

**Interfaces:**
- Consumes: a cursor implementing `execute(sql, params)` and `fetchall()` returning mapping rows.
- Produces:
  - `NODE_UTILITY_SELECT_SQL`
  - `NodeUtilityReader.fetch(cursor, *, space_id, memory_ids) -> Mapping[UUID, UtilityEvidence]`
  - `UtilitySnapshotProvider` protocol with `get_many(space_id, memory_ids)`.

- [ ] **Step 1: Write failing SQL-reader tests**

Assert:

```python
assert "FROM ngm.node_utility" in NODE_UTILITY_SELECT_SQL
assert "space_id = %(space_id)s" in NODE_UTILITY_SELECT_SQL
assert "node_id = ANY(%(memory_ids)s::uuid[])" in NODE_UTILITY_SELECT_SQL
```

Use a fake cursor to verify exact parameters, mapping to immutable evidence, empty input without SQL, neutral defaults for missing rows through the helper, and rejection of duplicate, out-of-scope, or unexpected memory IDs.

- [ ] **Step 2: Run and record RED**

Run:

```bash
python -m pytest tests/test_neon_utility.py -q
```

Expected: import failure for `nextgen_memory.neon_utility`.

- [ ] **Step 3: Implement the parameterized reader**

Use only aggregate fields:

```sql
SELECT node_id, feedback_count, avg_reward,
       positive_count, negative_count, last_feedback_at
FROM ngm.node_utility
WHERE space_id = %(space_id)s
  AND node_id = ANY(%(memory_ids)s::uuid[])
ORDER BY node_id
```

Return a mapping keyed by UUID. Do not accept notes, raw feedback rows, or query text.

- [ ] **Step 4: Run focused tests and Ruff**

```bash
python -m pytest tests/test_neon_utility.py -q
python -m ruff check src/nextgen_memory/neon_utility.py tests/test_neon_utility.py
```

- [ ] **Step 5: Commit**

```bash
git add src/nextgen_memory/neon_utility.py tests/test_neon_utility.py
git commit -m "feat: add scoped Neon utility reader"
```

---

### Task 3: Oversampled utility-aware retrieval decorator

**Files:**
- Modify: `src/nextgen_memory/utility_reranker.py`
- Modify: `tests/test_utility_reranker.py`

**Interfaces:**
- Consumes:
  - base retriever with `search(ResearchRetrievalQuery) -> tuple[ResearchRetrievalHit, ...]`;
  - `UtilitySnapshotProvider.get_many(space_id, memory_ids)`;
  - `UtilityAwareReranker`.
- Produces:
  - `UtilityAwareResearchRetriever.search(query) -> tuple[RerankedMemory, ...]`.

- [ ] **Step 1: Write failing decorator tests**

Assert an input `limit=5` with oversample factor `4` calls the base retriever with `limit=20`, raises `num_candidates` to at least `200`, requests utility for exactly the returned memory IDs and canonical space, and returns at most five reranked results.

Also assert:

- oversampling is capped at 100;
- utility-provider errors propagate;
- no implicit neutral fallback occurs on provider failure;
- missing utility rows are filled with `UtilityEvidence.neutral(memory_id)`.

- [ ] **Step 2: Run focused RED**

```bash
python -m pytest tests/test_utility_reranker.py -q
```

Expected: missing `UtilityAwareResearchRetriever` behavior.

- [ ] **Step 3: Implement minimal decorator**

Use `dataclasses.replace` to create the expanded query while preserving text, space, weights, and score-detail settings. Keep the original query object immutable.

- [ ] **Step 4: Run focused tests and Ruff**

```bash
python -m pytest tests/test_utility_reranker.py -q
python -m ruff check src/nextgen_memory/utility_reranker.py tests/test_utility_reranker.py
```

- [ ] **Step 5: Commit**

```bash
git add src/nextgen_memory/utility_reranker.py tests/test_utility_reranker.py
git commit -m "feat: compose utility-aware research retrieval"
```

---

### Task 4: Reproducible memory-reward-trap simulation

**Files:**
- Create: `scripts/simulate_memory_reward_trap.py`
- Create: `tests/test_memory_reward_trap_simulation.py`

**Interfaces:**
- Produces:
  - `SimulationConfig(seed=20260814, task_count=5000, shadow_count=4, success_probability=0.85)`
  - `simulate(config) -> SimulationResult`
  - CLI JSON output.

- [ ] **Step 1: Write failing simulation test**

With the fixed default seed, assert:

```python
result.naive_shadow_contamination_rate >= 0.80
result.counterfactual_shadow_contamination_rate <= 0.05
result.counterfactual_causal_rank_rate > result.naive_causal_rank_rate
```

The simulation must model one causal memory plus four correlated shadow memories per successful task. Naive bundle reward updates all retrieved memories; counterfactual updates only the memory whose removal changes the outcome.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_memory_reward_trap_simulation.py -q
```

- [ ] **Step 3: Implement fixed-seed standard-library simulation**

Use `random.Random(config.seed)`. Return immutable results and support:

```bash
python scripts/simulate_memory_reward_trap.py
```

The command must emit deterministic, sorted JSON and no network calls.

- [ ] **Step 4: Run tests and command twice**

```bash
python -m pytest tests/test_memory_reward_trap_simulation.py -q
python scripts/simulate_memory_reward_trap.py > /tmp/reward-trap-a.json
python scripts/simulate_memory_reward_trap.py > /tmp/reward-trap-b.json
cmp /tmp/reward-trap-a.json /tmp/reward-trap-b.json
```

- [ ] **Step 5: Commit**

```bash
git add scripts/simulate_memory_reward_trap.py tests/test_memory_reward_trap_simulation.py
git commit -m "test: simulate memory reward contamination"
```

---

### Task 5: Public API, documentation, and integrated verification

**Files:**
- Modify: `src/nextgen_memory/__init__.py`
- Create: `docs/utility-reranker-v0.md`
- Modify: `README.md`
- Create or modify: `tests/test_utility_reranker_public_api.py`

**Interfaces:**
- Produces public imports for all approved reranker and utility-reader contracts.

- [ ] **Step 1: Write failing public-API test**

Import from `nextgen_memory`:

```python
UtilityEvidence
UtilityRerankCandidate
UtilityRerankerConfig
UtilityScoreBreakdown
RerankedMemory
UtilityAwareReranker
UtilityAwareResearchRetriever
NodeUtilityReader
NODE_UTILITY_SELECT_SQL
```

Assert importing the package does not import `psycopg`, `pymongo`, NumPy, PyTorch, or any ML framework.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_utility_reranker_public_api.py -q
```

- [ ] **Step 3: Export and document**

Document:

- exact scoring equations and defaults;
- strong-prior behavior;
- scope and privacy boundaries;
- provider-failure behavior;
- current absence of feedback data;
- reward-trap simulation results;
- future replacement criteria for a learned reranker.

- [ ] **Step 4: Run full verification**

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
grep -RInE 'query_text|stdout|stderr|prompt|secret|token' src/nextgen_memory/utility_reranker.py src/nextgen_memory/neon_utility.py || true
```

Expected: all commands succeed; no secret or raw-payload field is introduced.

- [ ] **Step 5: Update draft PR with evidence**

Record:

- exact RED workflow run and failure reason;
- exact GREEN workflow run;
- Python 3.12 and 3.13 lint/test results;
- simulation output;
- confirmation that Neon schema and production feedback data were not modified.

- [ ] **Step 6: Commit**

```bash
git add src/nextgen_memory/__init__.py docs/utility-reranker-v0.md README.md tests/test_utility_reranker_public_api.py
git commit -m "docs: expose and verify utility-aware reranking"
```
