# Execution Ledger v0

## Purpose

Execution Ledger v0 records repository and agent work as immutable evidence. It answers:

- which scoped execution began;
- which observations, commands, file changes, tests, builds, and checkpoints occurred;
- which artifacts were consumed or produced;
- whether the run completed, failed, or was cancelled;
- whether the stored sequence and hash chain still agree.

The Python implementation is an in-memory reference model. The durable contract is the additive Neon migration `migrations/neon/0004_execution_ledger.sql`.

## Data model

### `ngm.execution_runs`

One immutable execution identity with canonical `space_id`, source principal, repository, branch, base revision, task/session keys, start time, request hash, content hash, and safe metadata.

### `ngm.execution_events`

An ordered append-only stream. Every event has:

- a contiguous sequence number;
- the preceding event UUID;
- an immutable content hash;
- an event hash computed from `previous_event_hash + content_hash`;
- a typed kind and outcome;
- optional hashes or backend references, never raw command/output payloads.

A retry with the same idempotency key and same immutable content returns the existing event. Reuse with different content fails closed. After `run_completed`, `run_failed`, or `run_cancelled`, no new event may be appended.

### `ngm.execution_artifacts`

Artifacts link an event to a canonical memory UUID or a rich-payload backend reference. Artifact ordinals are immutable and idempotent. Optional digests are validated.

## Privacy boundary

Neon stores hashes, typed facts, references, ranks, status, and bounded metadata. The recursive metadata validator rejects keys including:

- `command`, `argv`, `prompt`, `query_text`;
- `stdout`, `stderr`, `raw`, `raw_payload`;
- `secret`, `token`, `password`, `api_key`;
- `diff`, `patch`, and environment payloads.

Exact traces belong in append-only rich payload storage such as MongoDB `raw_traces`, referenced by `backend_ref` and protected by the same scope and authorization rules.

## Integrity controls

- `UPDATE` and `DELETE` are rejected by triggers on all three ledger tables.
- The run row is locked while an event head is validated, serializing concurrent appends per run.
- The first event must be `run_started` and its `input_hash` must equal the run's `request_hash`.
- Sequence, previous-event linkage, monotonic event time, terminal outcome, and terminal closure are enforced.
- `ngm.execution_chain_drift` recomputes the chain and exposes any sequence, linkage, or hash discrepancy.
- `ngm.execution_run_heads` exposes current status without mutating historical rows.

## Verification evidence — August 14, 2026

The migration was tested twice on a temporary Neon branch cloned from the project database, then the branch was deleted.

Positive path:

- one completed execution;
- three ordered events;
- one linked test-report artifact;
- zero rows in `ngm.execution_chain_drift`;
- stable head hash and terminal status.

Negative path:

- identical retry accepted after terminal closure;
- conflicting idempotency content rejected;
- append after terminal rejected;
- mutable update rejected;
- unsafe nested `stdout` metadata rejected;
- wrong `run_started.input_hash` rejected;
- correct request-hash binding accepted.

The full migration was reapplied successfully without duplicate schema objects or drift. No execution-ledger schema change has been applied to the primary Neon branch.

## Deployment gate

Production deployment requires a separate explicit approval. Before applying the migration:

1. review the SQL diff and backup/rollback procedure;
2. apply it to a fresh Neon branch;
3. run the positive and negative smoke suite;
4. confirm `execution_chain_drift = 0`;
5. apply to production during a controlled window;
6. retain the previous application version until both writers and readers are verified.
