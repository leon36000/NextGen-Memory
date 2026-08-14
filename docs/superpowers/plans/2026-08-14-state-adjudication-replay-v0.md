# State Adjudication Replay v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconstruct current state deterministically from append-only resolution events, project accepted events atomically in Neon, and verify the mutable projection without trusting it as history.

**Architecture:** A frozen `StateResolutionEvent` mirrors the canonical Neon resolution contract with explicit per-slot versions and idempotency keys. Pure functions apply `KEEP`, `SUPERSEDE`, `INVALIDATE`, `UNKNOWN`, and `QUARANTINE`, deduplicate exact retries, reject conflicting identities or sequence gaps, and emit a frozen `StateProjection`. Migration `0003` preserves legacy events, validates and serializes future writes, atomically refreshes `state_slots`, and exposes drift diagnostics.

**Tech Stack:** Python 3.12+ standard-library dataclasses/enums/hashing, pytest, Ruff, PostgreSQL 18/Neon migration SQL.

## Global Constraints

- Resolution events are immutable inputs; replay never mutates them.
- Event timestamps are timezone-aware audit evidence, not ordering authority.
- Every new event has a positive `slot_version` and non-empty idempotency key.
- Histories may arrive out of order, but replay output is deterministic by slot version.
- Exact at-least-once retries are idempotent; conflicting resolution or idempotency identities fail closed.
- Versions are contiguous from 1 within each `(space_id, slot_key)`.
- Events from different spaces or slots are never folded together.
- Any transition against a current value names it in `previous_node_id`.
- `KEEP` records rejection without replacing an active value; replacement requires `SUPERSEDE`.
- Quarantining a non-current candidate preserves active state; quarantining current state removes it.
- Stored projections are verification targets, not sources of truth.
- Existing immutable rows are never rewritten by the migration.

---

### Task 1: Resolution and projection contracts

**Files:**
- Create: `src/nextgen_memory/state.py`
- Modify: `src/nextgen_memory/__init__.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces: `StateVerdict`, `StateStatus`, `StateResolutionEvent`, `StateProjection`, `StoredStateSlot`, `StateProjectionVerification`, `StateReplayError`.

- [x] Write failing validation, serialization, and public-export tests.
- [x] Confirm failure before the state module/export existed.
- [x] Implement frozen contracts with timezone, version, idempotency, status, and quarantine invariants.
- [x] Rerun focused tests.

### Task 2: Pure transition and deterministic replay

**Files:**
- Modify: `src/nextgen_memory/state.py`
- Test: `tests/test_state.py`
- Test: `tests/test_state_sequence_contract.py`

**Interfaces:**
- Produces: `apply_state_resolution`, `replay_state`, and `replay_state_slots`.

- [x] Test initial keep, rejected-candidate keep, supersede, invalidate, unknown, quarantine, and stale previous pointers.
- [x] Test explicit-version ordering, gaps, duplicate versions, exact retry, conflicting identities, and multi-slot replay.
- [x] Implement logical fingerprints, idempotent canonicalization, contiguous-version validation, and pure folds.
- [x] Rerun state and sequence tests.

### Task 3: Projection verification

**Files:**
- Modify: `src/nextgen_memory/state.py`
- Test: `tests/test_state.py`
- Create: `docs/state-replay-v0.md`
- Modify: `README.md`

**Interfaces:**
- Produces: `verify_state_projection(events, stored_slot) -> StateProjectionVerification`.

- [x] Test current node, status, version, resolution identity, idempotency identity, and quarantine-set mismatches.
- [x] Permit structurally readable but semantically corrupt stored shapes so replay verification can diagnose them.
- [x] Document replay ordering, retry semantics, and adapter expectations.

### Task 4: Additive Neon state migration

**Files:**
- Create: `migrations/neon/0003_state_resolution_replay.sql`
- Test: `tests/test_state_migration_contract.py`

**Interfaces:**
- Consumes: canonical schema `0.1.1`.
- Produces: schema `0.2.0`, explicit state-event sequencing, idempotency, atomic projection, legacy replay view, and drift diagnostics.

- [x] Write failing migration contract tests.
- [x] Add columns and partial unique indexes without rewriting immutable history.
- [x] Add parser-safe insert/projection functions and per-slot serialization.
- [x] Add ordered replay and projection-drift views.
- [x] Validate migration twice against isolated Neon branch `state-replay-v0-verify`; exercise accepted transitions, direct-mutation rejection, authoritative-head drift rejection, canonical text identities, and zero drift after repair.

### Task 5: Broad verification and publication

**Files:**
- No additional product files unless verification finds a defect.

**Interfaces:**
- Consumes: completed state feature based on Router v0.
- Produces: one intentional commit and a stacked draft PR targeting `feat/memory-moe-kernel-v0`.

- [x] Run the complete test suite.
- [ ] Run Ruff, compileall, coverage, randomized replay properties, diff checks, and secret scan.
  Local results: 63 tests, 92% coverage, 5,000 randomized histories / 70,638 transitions,
  compileall, wheel build, diff check, and secret scan are green. Ruff awaits GitHub Actions.
- [ ] Commit the reviewed change in the isolated worktree.
- [ ] Publish branch `feat/state-adjudication-replay-v0` when GitHub write actions are available.
- [ ] Require GitHub Actions success on Python 3.12 and 3.13 before merge.
