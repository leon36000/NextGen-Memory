# Neon Execution Ledger Adapter v0 Implementation Plan

> **For agentic workers:** use test-driven development and fresh verification for every claim.

**Goal:** Persist a validated Python execution-ledger bundle to Neon atomically, preserve canonical identities across layers, and verify the resulting database chain.

**Architecture:** A zero-mandatory-dependency adapter talks to a structural connection protocol using static parameterized SQL. Python validates the bundle graph before opening a transaction. PostgreSQL remains responsible for serialization and append-only constraints. Returned hashes and drift/head views provide cross-layer verification.

**Tech stack:** Python 3.12+, standard library protocols/dataclasses/JSON, pytest, Ruff, optional psycopg 3, Neon/PostgreSQL.

## Constraints

- no raw command/output content;
- no dynamic SQL identifiers;
- no migration promotion;
- one bundle transaction;
- exact idempotency, not last-write-wins;
- returned canonical/event hashes must match Python;
- all rows are scope-bound;
- verification is a database read, not an assumption.

### Task 1 — SQL and connection contracts

**Files:**
- Create: `src/nextgen_memory/neon_execution_ledger.py`
- Test: `tests/test_neon_execution_ledger.py`
- Test: `tests/test_neon_execution_ledger_sql_contract.py`

- [ ] Write failing tests for static SQL, conflict guards, JSON casts, and protocol-based execution.
- [ ] Implement connection/cursor protocols and immutable receipt types.
- [ ] Verify no mandatory psycopg import exists.

### Task 2 — Atomic writes

- [ ] Test run, event, and artifact inserts plus exact replay receipts.
- [ ] Test canonical hash and event-chain mismatch rollback.
- [ ] Implement `persist_run`, `persist_event`, and `persist_artifact`.
- [ ] Keep SQL parameterized and compare all returned identities.

### Task 3 — Bundle graph validation

- [ ] Test cross-space/run artifacts, event gaps, bad predecessor links, and events after terminal state.
- [ ] Implement pre-transaction graph validation.
- [ ] Implement deterministic write ordering inside one transaction.

### Task 4 — Database verification

- [ ] Test zero drift, drift rows, missing head, and head hash mismatch.
- [ ] Implement `verify_run` from `execution_chain_drift` and `execution_run_heads`.
- [ ] Require bundle verification before returning success.

### Task 5 — Documentation and broad verification

**Files:**
- Create: `docs/neon-execution-ledger-adapter-v0.md`
- Modify: `README.md` only if the stacked base remains stable.

- [ ] Run focused tests during implementation.
- [ ] Run full pytest and Ruff on Python 3.12 and 3.13 through GitHub Actions.
- [ ] Run compileall, coverage, wheel build/install, diff check, and secret scan.
- [ ] Open a stacked draft PR targeting `feat/execution-ledger-v0`.
- [ ] Do not merge or apply migration `0004` to Neon main.
