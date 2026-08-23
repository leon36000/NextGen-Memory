# Neon Execution Ledger Adapter v0 — Design

**Date:** 2026-08-14
**Status:** implementation candidate
**Depends on:** Router v0, State Replay v0, Execution Ledger v0

## Objective

Connect the pure Python execution-ledger contracts to the durable Neon schema without making the Python package depend on psycopg at runtime and without weakening append-only or idempotency invariants.

## Boundary

The adapter accepts already validated `ExecutionRun`, `ExecutionEvent`, and `ExecutionArtifact` values. It does not execute commands, capture raw stdout/stderr, decide what evidence is trustworthy, or promote database migrations.

It writes only static parameterized SQL. Rich command/output payloads stay outside Neon and are represented by hashes and `backend_ref` values.

## Required guarantees

1. **One transaction per bundle.** A run, its ordered events, and its artifacts commit together or roll back together.
2. **Exact idempotency.** Conflicts use the database helper `ngm.assert_same_execution_payload`; the same logical write is replayed and conflicting immutable content fails closed.
3. **Canonical identity preservation.** Neon must return the same `content_hash` supplied by Python.
4. **Cross-layer chain agreement.** Neon must return the exact Python `event_hash` for every event.
5. **Storage integrity separation.** `storage_content_hash` is read from Neon and never substituted for the canonical Python hash.
6. **Static SQL only.** No identifier or value is interpolated into SQL text.
7. **Driver independence.** The core module uses structural protocols and JSON strings; psycopg remains an optional integration dependency.
8. **Scope isolation.** Every read and write includes `space_id`; event and artifact rows must belong to the supplied run before SQL is executed.
9. **Local sequence verification.** Bundle events are contiguous, ordered, linked to the previous event, and terminal only at the end.
10. **Independent drift read.** Verification reads `ngm.execution_chain_drift` and `ngm.execution_run_heads`, rather than trusting an in-memory success flag.

## API

`NeonExecutionLedgerAdapter(connection)` exposes:

- `persist_run(run)`;
- `persist_event(event)`;
- `persist_artifact(artifact)`;
- `persist_bundle(run, events, artifacts)`;
- `verify_run(space_id, run_id)`.

Write calls return immutable receipts containing the record ID, canonical hash, whether the row was inserted or replayed, and event storage/chain hashes when applicable.

## Transaction semantics

`persist_bundle` validates the complete graph before opening a transaction. It then writes:

1. run;
2. events in sequence order;
3. artifacts in `(event sequence, ordinal)` order;
4. a final drift/head verification query.

Any returned canonical-hash mismatch, event-hash mismatch, missing head, or drift row raises `NeonExecutionLedgerInvariantError`, causing rollback.

## Row adaptation

Metadata is thawed from immutable Python mappings/tuples and encoded with deterministic JSON (`sort_keys=True`, compact separators, `allow_nan=False`). SQL casts the string to `jsonb`; no driver-specific JSON wrapper is required.

Rows may be mapping-like or positional. The adapter accepts both so tests can use lightweight fakes while psycopg can use tuple or dict row factories.

## Non-goals

- applying migration `0004` to Neon main;
- retry loops or network backoff;
- connection-pool management;
- Temporal orchestration;
- raw trace storage;
- learned routing.

Those layers are added only after this persistence contract is independently verified.