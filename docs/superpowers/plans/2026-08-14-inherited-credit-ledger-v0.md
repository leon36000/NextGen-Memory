# Inherited Credit Ledger v0 Implementation Plan

> **For agentic workers:** use strict TDD. Record an integrated RED state before every production slice and verify the final exact pull-request head independently.

**Goal:** Persist typed inherited provenance credit without contaminating direct memory feedback or its utility aggregates.

**Architecture:** A pure builder maps `ProvenanceCreditResult`, graph, policies, and configuration to deterministic evaluation, contribution, observation, and accounting records. A driver-independent writer uses static parameterized insert-then-readback SQL. An additive candidate migration creates separate append-only tables and separate analytical views.

**Tech stack:** Python 3.12+ standard library, pytest, Ruff, PostgreSQL/Neon candidate migration, GitHub Actions.

## Global constraints

- Never insert inherited credit into `ngm.memory_feedback`.
- Never modify the existing `ngm.node_utility` definition.
- Do not compute a combined direct-plus-inherited score.
- Use deterministic UUID5 identities and SHA-256 content hashes.
- Persist path contributions, blocked/abstention observations, and conservation accounting.
- Use static parameterized SQL and exact readback comparison.
- Store no raw query, prompt, answer, memory body, command, output, note, secret, or environment.
- Do not apply the migration to Neon main.

### Task 1 — Builder contracts and fingerprints

**Files:**
- Create: `tests/test_provenance_credit_persistence.py`
- Create after RED: `src/nextgen_memory/provenance_credit_persistence.py`

- [ ] Write failing tests for record contracts, graph/policy fingerprints, deterministic IDs, result completeness, and input-order invariance.
- [ ] Record RED because `nextgen_memory.provenance_credit_persistence` is absent.
- [ ] Implement frozen records, canonical fingerprints, hashes, and `build_provenance_credit_batch`.
- [ ] Verify exact retries and graph/policy changes.

### Task 2 — Insert/readback writer

**Files:**
- Modify: `src/nextgen_memory/provenance_credit_persistence.py`
- Modify: `tests/test_provenance_credit_persistence.py`
- Create: `tests/test_provenance_credit_persistence_sql.py`

- [ ] Write failing SQL and writer tests.
- [ ] Implement four static insert statements and four scoped select statements.
- [ ] Implement one-space validation, deterministic insertion order, exact immutable comparison, and conflict errors.
- [ ] Verify empty batches, duplicates, missing/unexpected rows, and mapping-only cursor results.

### Task 3 — Additive migration contract

**Files:**
- Create: `tests/test_inherited_credit_migration.py`
- Create after RED: `migrations/neon/0006_inherited_credit_ledger.sql`

- [ ] Write failing migration-contract tests.
- [ ] Add evaluation, contribution, observation, and accounting tables.
- [ ] Add same-space foreign keys, format/completeness constraints, indexes, and append-only triggers.
- [ ] Add `node_inherited_credit` and `node_learning_evidence` views.
- [ ] Assert the migration never replaces or redefines `ngm.node_utility`.
- [ ] Register `inherited_credit_ledger` schema metadata.

### Task 4 — Randomized identity and privacy verification

**Files:**
- Create: `tests/test_provenance_credit_persistence_properties.py`

- [ ] Generate at least 2,000 deterministic provenance results.
- [ ] Verify builder permutation invariance and unique child identities.
- [ ] Verify every child refers to a known evaluation and one space.
- [ ] Verify no forbidden raw-data key or value appears in serialized DB parameters.
- [ ] Verify exact accounting and result-hash completeness.

### Task 5 — Public API and documentation

**Files:**
- Modify: `src/nextgen_memory/__init__.py`
- Create: `tests/test_provenance_credit_persistence_public_api.py`
- Create: `docs/inherited-credit-ledger-v0.md`

- [ ] Record RED for missing root exports.
- [ ] Export stable records, builder, writer, errors, and SQL constants.
- [ ] Document direct/inherited separation, schema, replay, views, privacy, and deployment gate.

### Task 6 — Candidate Neon validation

- [ ] Create a temporary Neon branch from the canonical project database.
- [ ] Apply migration `0006` only to the temporary branch.
- [ ] Insert one evaluation with contributions, a blocked observation, an abstention case, and accounting.
- [ ] Replay exact rows and reject conflicting identities.
- [ ] Verify append-only triggers and separate direct/inherited views.
- [ ] Confirm production `memory_feedback` and schema remain unchanged.
- [ ] Delete or retain the candidate branch according to the project verification policy; never promote without explicit approval.

### Task 7 — Final verification

- [ ] Open a stacked draft PR targeting `feat/provenance-credit-v0`.
- [ ] Require ordinary pull-request CI on Python 3.12 and 3.13.
- [ ] Run Ruff, full pytest, compileall, coverage, wheel build/install, diff check, and high-signal secret scan.
- [ ] Compare the exact final diff to the base branch.
- [ ] Persist a machine-readable verification marker.
- [ ] Do not merge or deploy.
