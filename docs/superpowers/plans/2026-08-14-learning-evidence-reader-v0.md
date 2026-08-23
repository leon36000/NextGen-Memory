# Learning Evidence Reader v0 Implementation Plan

> **For agentic workers:** use strict TDD and fresh evidence. Record an ordinary pull-request RED run before adding production code.

**Goal:** Read direct and inherited memory-learning evidence from Neon as separate immutable Python contracts without producing a combined score or changing existing direct-utility behavior.

**Architecture:** `learning_evidence.py` defines nested direct/inherited evidence values, one scoped node snapshot, a static SQL contract, and a driver-independent fail-closed reader. It reads the additive `ngm.node_learning_evidence` view created by migration `0006`. `NodeUtilityReader` and the utility reranker remain untouched.

**Tech stack:** Python 3.12+, standard-library dataclasses/protocols/mapping proxy/datetime/math, pytest, Ruff, Neon candidate branch.

## Global constraints

- Do not modify `NodeUtilityReader`.
- Do not modify utility-reranker scoring.
- Do not calculate or expose combined utility.
- Treat missing rows as conflicts, not neutral evidence.
- Keep direct and inherited values in distinct nested types.
- Use one static parameterized, scope-bound query.
- Return an immutable UUID-keyed mapping.
- Store and emit no raw query or memory content.
- Do not apply migration `0006` to Neon main.

### Task 1 — Immutable evidence contracts

**Files:**
- Create: `tests/test_learning_evidence.py`
- Create after RED: `src/nextgen_memory/learning_evidence.py`

- [ ] Write failing tests for `DirectUtilityEvidence`, `InheritedUtilityEvidence`, and `NodeLearningEvidence`.
- [ ] Cover neutral states, count consistency, finite numbers, confidence, absolute sums, timezone-aware timestamps, immutability, and absence of combined-score properties.
- [ ] Record RED because `nextgen_memory.learning_evidence` is absent.
- [ ] Implement the minimum frozen contracts.

### Task 2 — Scoped Neon reader

**Files:**
- Modify: `tests/test_learning_evidence.py`
- Modify: `src/nextgen_memory/learning_evidence.py`
- Create: `tests/test_learning_evidence_sql.py`

- [ ] Test exact SQL projection, `space_id` predicate, UUID array predicate, order, and absence of free-form columns.
- [ ] Test empty input without SQL.
- [ ] Test UUID deduplication and stable parameter ordering.
- [ ] Test mapping-only rows and native/string UUIDs.
- [ ] Test missing, unexpected, duplicate, malformed, and cross-space rows.
- [ ] Implement structural cursor protocol and exact immutable mapping readback.

### Task 3 — Generated invariants

**Files:**
- Create: `tests/test_learning_evidence_properties.py`

- [ ] Generate at least 5,000 deterministic valid snapshots.
- [ ] Verify row/request permutation invariance.
- [ ] Verify one-space and one-row-per-memory rules.
- [ ] Verify direct and inherited neutral/non-neutral invariants.
- [ ] Verify serialized rows/results contain no forbidden raw-payload fields.

### Task 4 — Public API and documentation

**Files:**
- Create: `tests/test_learning_evidence_public_api.py`
- Modify after RED: `src/nextgen_memory/__init__.py`
- Create: `docs/learning-evidence-reader-v0.md`

- [ ] Record RED for missing root exports.
- [ ] Export reader, contracts, errors, protocol, and SQL constant.
- [ ] Document evidence separation, failure behavior, privacy, and future reranker gate.

### Task 5 — Isolated Neon validation

- [ ] Execute the exact read SQL on `br-soft-cherry-a6pv1ag2` only.
- [ ] Read the inherited-credit smoke target and confirm direct count `0` with inherited count `1` and value `0.5`.
- [ ] Read a canonical node without inherited evidence and confirm explicit neutral inherited fields.
- [ ] Verify missing UUID returns no row, which the Python reader treats as a conflict.
- [ ] Confirm canonical parent branch remains unchanged.

### Task 6 — Final verification

- [ ] Open a stacked draft PR targeting `feat/inherited-credit-ledger-v0`.
- [ ] Require ordinary pull-request CI on Python 3.12 and 3.13.
- [ ] Run Ruff, full pytest, compileall, coverage, wheel build/install, exact diff, and high-signal secret scan.
- [ ] Persist a machine-readable verification marker and canonical project checkpoint.
- [ ] Do not merge or deploy.
