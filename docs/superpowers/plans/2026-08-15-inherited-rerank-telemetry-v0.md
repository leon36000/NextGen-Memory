# Inherited Rerank Telemetry v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build deterministic, aggregate-only, privacy-safe telemetry for Bounded Inherited Reranker v0 without modifying scoring, protected reranker files, or any database.

**Architecture:** A standalone `inherited_rerank_telemetry.py` module maps exact inherited-aware reranker results plus policy context to immutable observations, one deterministic summary, and one deterministic batch. A sink protocol and idempotent in-memory sink provide a backend-neutral emission boundary. Public exports, canonical JSON, generated properties, and exact-head CI complete the feature.

**Tech Stack:** Python 3.12+ standard-library dataclasses, enums, hashlib, json, UUID5, protocols, mapping proxies, pytest, Ruff, GitHub Actions.

## Global Constraints

- Base branch is `feat/bounded-inherited-reranker-v0`.
- Do not modify `bounded_inherited_reranker.py`, `utility_reranker.py`, `neon_utility.py`, routing, eligibility, retrieval, context compilation, or migrations.
- Accept only aggregate typed values; no query, prompt, answer, memory body, command, output, relation path, edge path, secret, token, environment, or free-form metadata.
- Do not include direct reward or verdict aggregates in observation records.
- Use deterministic UUID5 identities and SHA-256 content hashes.
- Exact retries must rebuild byte-identical JSON and IDs.
- Changed results or policy must produce a different batch identity.
- Allow an explicit empty batch.
- Fail closed on invalid ranks, scores, cap, policy, score equation, duplicate candidates, or unsupported types.
- Provide no SQL, migration, database writer, timestamp, or automatic production activation.
- Keep the pull request draft and unmerged.

---

### Task 1: Observation, summary, and batch contracts

**Files:**
- Create: `tests/test_inherited_rerank_telemetry.py`
- Create after RED: `src/nextgen_memory/inherited_rerank_telemetry.py`

**Interfaces:**
- Consumes: `BoundedInheritedRerankerConfig`, `InheritedAwareRerankedMemory`, and `InheritedEvidenceDisposition`.
- Produces: `InheritedRerankTelemetryValidationError`, `InheritedRerankTelemetryConflictError`, `InheritedRerankObservation`, `InheritedRerankSummary`, and `InheritedRerankTelemetryBatch`.

- [ ] **Step 1: Write contract tests before the production module exists**

Tests instantiate frozen values and require validation for UUIDs, finite scores, positive ranks, bounded reliability values, normalized policy version, content hashes, summary partitions, and batch consistency.

```python
def test_observation_is_frozen_and_validates_score_fields() -> None:
    observation = valid_observation()
    assert observation.rank_delta == observation.base_rank - observation.final_rank
    with pytest.raises(FrozenInstanceError):
        observation.final_score = 0.0
```

- [ ] **Step 2: Run the focused contract suite and record RED**

Run:

```bash
python -m pytest tests/test_inherited_rerank_telemetry.py -q
```

Expected: collection fails only because `nextgen_memory.inherited_rerank_telemetry` does not exist.

- [ ] **Step 3: Implement minimum immutable contracts**

Required signatures:

```python
class InheritedRerankTelemetryValidationError(ValueError): ...
class InheritedRerankTelemetryConflictError(RuntimeError): ...

@dataclass(frozen=True, slots=True)
class InheritedRerankObservation:
    id: UUID
    batch_id: UUID
    space_id: UUID
    router_decision_id: UUID
    memory_id: UUID
    base_rank: int
    base_score: float
    final_rank: int
    final_score: float
    rank_delta: int
    applied_component: float
    uncapped_component: float
    disposition: InheritedEvidenceDisposition
    contribution_count: int
    value_sum: float | None
    absolute_value_sum: float | None
    standard_error_sum: float | None
    minimum_structural_confidence: float | None
    count_shrinkage: float
    path_coherence: float
    uncertainty_reliability: float
    confidence_reliability: float
    policy_version: str
    policy_fingerprint: str
    content_hash: str

@dataclass(frozen=True, slots=True)
class InheritedRerankSummary:
    candidate_count: int
    applied_count: int
    no_evidence_count: int
    below_minimum_count: int
    below_minimum_confidence: int
    promoted_count: int
    demoted_count: int
    unchanged_count: int
    top_changed: bool
    base_top_memory_id: UUID | None
    final_top_memory_id: UUID | None
    signed_adjustment_sum: float
    absolute_adjustment_sum: float
    maximum_absolute_adjustment_observed: float
    configured_hard_cap: float
    content_hash: str

@dataclass(frozen=True, slots=True)
class InheritedRerankTelemetryBatch:
    id: UUID
    space_id: UUID
    router_decision_id: UUID
    policy_version: str
    policy_fingerprint: str
    observations: tuple[InheritedRerankObservation, ...]
    summary: InheritedRerankSummary
    content_hash: str
```

- [ ] **Step 4: Run focused tests to GREEN**

```bash
python -m pytest tests/test_inherited_rerank_telemetry.py -q
```

- [ ] **Step 5: Commit the contract slice**

```bash
git add src/nextgen_memory/inherited_rerank_telemetry.py tests/test_inherited_rerank_telemetry.py
git commit -m "feat: add inherited rerank telemetry contracts"
```

### Task 2: Deterministic policy fingerprint and batch builder

**Files:**
- Modify: `src/nextgen_memory/inherited_rerank_telemetry.py`
- Modify: `tests/test_inherited_rerank_telemetry.py`

**Interfaces:**
- Produces: `fingerprint_bounded_inherited_policy(config)` and `build_inherited_rerank_telemetry(...)`.

- [ ] **Step 1: Write failing deterministic builder tests**

Cover exact retry stability, changed policy identity, changed score identity, empty batch, final-order observations, canonical JSON, summary counts, rank delta, top change, positive/negative adjustments, and aggregate-only fields.

```python
def test_exact_retry_rebuilds_identical_batch() -> None:
    first = build_inherited_rerank_telemetry(...)
    second = build_inherited_rerank_telemetry(...)
    assert first == second
    assert first.render_json() == second.render_json()
```

- [ ] **Step 2: Run focused tests and confirm the new symbols fail**

```bash
python -m pytest tests/test_inherited_rerank_telemetry.py -q
```

Expected: failures identify the absent fingerprint/builder behavior.

- [ ] **Step 3: Implement canonical hashes and identities**

Required signatures:

```python
def fingerprint_bounded_inherited_policy(
    config: BoundedInheritedRerankerConfig,
) -> str: ...

def build_inherited_rerank_telemetry(
    *,
    space_id: UUID,
    router_decision_id: UUID,
    config: BoundedInheritedRerankerConfig,
    results: Sequence[InheritedAwareRerankedMemory],
) -> InheritedRerankTelemetryBatch: ...
```

Implementation order:

1. validate UUIDs, config, result types, candidate IDs, base/final ranks, finite scores, policy version, cap, and score equation;
2. compute the policy fingerprint from all config fields;
3. build canonical observation payloads in memory UUID order;
4. compute observation content hashes;
5. derive a provisional summary and summary hash;
6. compute batch content hash and UUID5;
7. derive observation UUID5 values under the batch UUID;
8. store observations in final-rank order;
9. validate summary partitions and top-change semantics;
10. expose `to_dict()` and canonical `render_json()`.

- [ ] **Step 4: Verify focused and complete behavior**

```bash
ruff check src/nextgen_memory/inherited_rerank_telemetry.py tests/test_inherited_rerank_telemetry.py
python -m pytest tests/test_inherited_rerank_telemetry.py -q
python -m pytest -q
```

- [ ] **Step 5: Commit the deterministic builder**

```bash
git add src/nextgen_memory/inherited_rerank_telemetry.py tests/test_inherited_rerank_telemetry.py
git commit -m "feat: build deterministic inherited rerank telemetry"
```

### Task 3: Sink protocol and idempotent in-memory adapter

**Files:**
- Modify: `src/nextgen_memory/inherited_rerank_telemetry.py`
- Modify: `tests/test_inherited_rerank_telemetry.py`

**Interfaces:**
- Produces: `InheritedRerankTelemetrySink` and `InMemoryInheritedRerankTelemetrySink`.

- [ ] **Step 1: Write failing sink tests**

```python
def test_in_memory_sink_deduplicates_exact_retry() -> None:
    sink = InMemoryInheritedRerankTelemetrySink()
    sink.record(batch)
    sink.record(batch)
    assert sink.batches == (batch,)
```

Also require conflict detection for a manually corrupted same-ID batch, deterministic lexical batch ordering, and rejection of unsupported values.

- [ ] **Step 2: Run focused tests and confirm RED**

```bash
python -m pytest tests/test_inherited_rerank_telemetry.py -q
```

- [ ] **Step 3: Implement protocol and sink**

```python
class InheritedRerankTelemetrySink(Protocol):
    def record(self, batch: InheritedRerankTelemetryBatch) -> None: ...

class InMemoryInheritedRerankTelemetrySink:
    def record(self, batch: InheritedRerankTelemetryBatch) -> None: ...

    @property
    def batches(self) -> tuple[InheritedRerankTelemetryBatch, ...]: ...
```

Store batches in a private UUID-keyed mapping. Exact same batch is idempotent; same ID with different content raises `InheritedRerankTelemetryConflictError`.

- [ ] **Step 4: Verify focused and complete GREEN**

```bash
ruff check .
python -m pytest tests/test_inherited_rerank_telemetry.py -q
python -m pytest -q
python -m compileall -q src
```

- [ ] **Step 5: Commit the sink boundary**

```bash
git add src/nextgen_memory/inherited_rerank_telemetry.py tests/test_inherited_rerank_telemetry.py
git commit -m "feat: add inherited rerank telemetry sink"
```

### Task 4: Five-thousand-case generated verification

**Files:**
- Create: `tests/test_inherited_rerank_telemetry_properties.py`

**Interfaces:**
- Consumes: `build_inherited_rerank_telemetry` and valid bounded-reranker result fixtures.
- Produces: deterministic property evidence only.

- [ ] **Step 1: Generate 5,000 deterministic result sets**

For each seed, generate zero to six valid inherited-aware results with contiguous base/final ranks, all dispositions, signed bounded adjustments, finite scores, and one stable config.

- [ ] **Step 2: Assert hard invariants**

Each generated case must verify:

```python
assert first == second_under_input_permutation
assert first.render_json() == second.render_json()
assert len(first.observations) == first.summary.candidate_count
assert first.summary.applied_count + first.summary.no_evidence_count + first.summary.below_minimum_count + first.summary.below_minimum_confidence == first.summary.candidate_count
assert first.summary.promoted_count + first.summary.demoted_count + first.summary.unchanged_count == first.summary.candidate_count
```

Also verify cap, score equation, UUID uniqueness, final-order observations, empty-batch semantics, changed-policy identity, and forbidden-field absence.

- [ ] **Step 3: Run properties twice**

```bash
python -m pytest tests/test_inherited_rerank_telemetry_properties.py -q
python -m pytest tests/test_inherited_rerank_telemetry_properties.py -q
```

Expected: both runs pass with identical deterministic assertions.

- [ ] **Step 4: Commit generated verification**

```bash
git add tests/test_inherited_rerank_telemetry_properties.py
git commit -m "test: verify inherited rerank telemetry properties"
```

### Task 5: Public API and operating documentation

**Files:**
- Create: `tests/test_inherited_rerank_telemetry_public_api.py`
- Modify after RED: `src/nextgen_memory/__init__.py`
- Create: `docs/inherited-rerank-telemetry-v0.md`
- Create: `docs/inherited-rerank-telemetry-v0-verification.md`

**Interfaces:**
- Produces stable package exports for errors, contracts, builder, fingerprint, protocol, and in-memory sink.

- [ ] **Step 1: Write the root export test**

Require these names in `nextgen_memory` and `__all__`:

```text
InheritedRerankTelemetryValidationError
InheritedRerankTelemetryConflictError
InheritedRerankObservation
InheritedRerankSummary
InheritedRerankTelemetryBatch
InheritedRerankTelemetrySink
InMemoryInheritedRerankTelemetrySink
fingerprint_bounded_inherited_policy
build_inherited_rerank_telemetry
```

- [ ] **Step 2: Record one-failure API RED**

Run the full suite before exports. Expected: all internal tests pass and exactly one public API test fails on absent root exports.

- [ ] **Step 3: Add stable exports only**

Modify `src/nextgen_memory/__init__.py` without changing any protected module.

- [ ] **Step 4: Publish documentation**

Document contracts, fields, identity derivation, summary semantics, fail-closed rules, privacy boundary, sink behavior, generated verification, and the future persistence gate.

- [ ] **Step 5: Verify API, docs, and complete suite**

```bash
ruff check .
python -m pytest -q
python -m compileall -q src
```

- [ ] **Step 6: Commit exports and docs**

```bash
git add \
  src/nextgen_memory/__init__.py \
  tests/test_inherited_rerank_telemetry_public_api.py \
  docs/inherited-rerank-telemetry-v0.md \
  docs/inherited-rerank-telemetry-v0-verification.md
git commit -m "docs: publish inherited rerank telemetry v0"
```

### Task 6: Final independent verification

**Files:**
- No feature-code changes after the exact final user-authored head.
- Persist verification evidence only on a bootstrap verification branch.

**Interfaces:**
- Produces: draft PR body evidence and a machine-readable marker.

- [ ] **Step 1: Open a stacked draft PR**

Base: `feat/bounded-inherited-reranker-v0`.

- [ ] **Step 2: Require ordinary PR CI**

Require Ruff and the complete suite on Python 3.12 and Python 3.13 for the exact final head.

- [ ] **Step 3: Reproduce verification independently**

```bash
ruff check .
python -m pytest -q
python -m pytest --cov=nextgen_memory --cov-report=json -q
python -m compileall -q src
python -m pip wheel . --no-deps -w /tmp/wheel
python -m pip install --force-reinstall /tmp/wheel/*.whl
git diff --check BASE...HEAD
```

Run canonical batch JSON twice and require byte identity. Scan the exact diff for high-signal secrets and forbidden raw-payload fields.

- [ ] **Step 4: Verify exact scope**

Allowed feature files:

```text
docs/inherited-rerank-telemetry-v0.md
docs/inherited-rerank-telemetry-v0-verification.md
docs/superpowers/plans/2026-08-15-inherited-rerank-telemetry-v0.md
docs/superpowers/specs/2026-08-15-inherited-rerank-telemetry-v0-design.md
src/nextgen_memory/__init__.py
src/nextgen_memory/inherited_rerank_telemetry.py
tests/test_inherited_rerank_telemetry.py
tests/test_inherited_rerank_telemetry_properties.py
tests/test_inherited_rerank_telemetry_public_api.py
```

Protected reranker and database files must remain unchanged.

- [ ] **Step 5: Persist exact evidence**

Record head/base SHA, CI run, test count, coverage, property cases, changed files, wheel SHA, canonical JSON SHA, protected-file status, database status, and merge status.

- [ ] **Step 6: Advance the canonical project checkpoint only after verification**

Record project status and provenance in the existing canonical memory ledger. Do not write feedback, score telemetry, or schema changes.
