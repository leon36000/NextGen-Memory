# State Adjudication Replay v0

The state subsystem makes `ngm.state_resolutions` the immutable source of truth and treats
`ngm.state_slots` as a fast projection that must always be reproducible.

## Why explicit slot versions exist

Timestamps are evidence, not a safe concurrency primitive. Clocks can drift, retries can arrive late,
and two events can share the same timestamp. Every new `StateResolutionEvent` therefore carries:

- a positive `slot_version`, contiguous from `1` within `(space_id, slot_key)`;
- a non-empty `idempotency_key`, unique within a memory space;
- a globally unique `resolution_id`;
- a timezone-aware `created_at` retained for audit rather than ordering.

Replay orders by `slot_version`. A gap or duplicate version fails closed. Exact repeated delivery is
idempotent. When multiple transport deliveries represent the same logical write, replay keeps the
earliest `created_at` identity (then the smallest UUID as a deterministic tie-breaker). Reusing a
resolution ID or idempotency key with different logical content is corruption and raises
`StateReplayError`. Evidence UUID order is canonicalized before fingerprinting.

## Verdict semantics

`StateResolutionEvent` represents one immutable adjudication:

- `KEEP`: establish the candidate when no value exists, or preserve the explicitly named current
  value when a new candidate is rejected;
- `SUPERSEDE`: replace the explicitly named current node with a different candidate;
- `INVALIDATE`: retire the current node and mark the slot `stale`;
- `UNKNOWN`: remove the current assumption because the available evidence cannot settle it;
- `QUARANTINE`: exclude a candidate while preserving an unrelated current value.

When a slot has a current node, every subsequent event must name it through `previous_node_id`.
This optimistic contract rejects stale writers rather than silently overwriting state.

A quarantined candidate cannot become current in v0. A future release verdict requires a separate
authorization and audit design.

## Pure Python replay

```python
from nextgen_memory import replay_state, replay_state_slots

projection = replay_state(resolution_events_for_one_slot)
all_projections = replay_state_slots(resolution_events_across_slots)
```

The functions do not mutate events and require no database connection. `StateProjection` contains:

- current node and status;
- applied slot version;
- last resolution ID, idempotency key, and timestamp;
- the accumulated quarantined-node set.

## Neon migration contract

`migrations/neon/0003_state_resolution_replay.sql` advances the schema to `0.2.0`:

1. adds explicit slot versions and idempotency keys to future resolution events;
2. adds quarantine and last-idempotency metadata to the mutable projection;
3. preserves all legacy immutable rows without rewriting them;
4. exposes `ngm.state_replay_events`, which synthesizes deterministic metadata for legacy rows;
5. serializes writes per state slot with an advisory transaction lock;
6. validates version, previous-state, verdict, and quarantine invariants;
7. canonicalizes `slot_key`, `idempotency_key`, and `resolver` before uniqueness checks;
8. verifies that the stored projection points to the authoritative prior head, not only the same
   version number;
9. blocks ordinary direct mutation of `state_slots` and opens the projection write path only inside
   the resolution trigger;
10. updates `state_slots` atomically after each accepted event;
11. exposes `ngm.state_projection_drift` for lightweight version/identity drift detection.

The SQL projection is an optimization, not an alternative history. Python replay remains an
independent verification path. The projection-write session flag is a correctness tripwire, not a
complete authorization boundary; production roles must also deny application principals direct DML
on `state_slots`.

## Projection verification

An adapter reads ordered resolution rows and the corresponding mutable slot, then calls:

```python
verification = verify_state_projection(events, stored_slot)
```

Verification compares current node, status, version, last resolution identity, last idempotency key,
and quarantined candidates. Exact mismatch names support repair tooling and audit records.

## Adapter rules

A Neon adapter should:

1. read from `ngm.state_replay_events`, using `replay_slot_version` and
   `replay_idempotency_key` so legacy and new events share one contract;
2. parse UUIDs, verdicts, arrays, and timestamps without normalization that changes meaning;
3. insert new resolution events with the caller's stable idempotency key and canonical textual
   identifiers; the database trims defensive whitespace before indexing;
4. treat a uniqueness conflict as an idempotent lookup, never as permission to change the payload;
5. replay independently and compare against `state_slots` after writes or during audits;
6. repair only the mutable projection, never `state_resolutions`.

Replay proves structural consistency. It does not prove that an adjudicator's semantic judgment was
correct; provenance, authority, and write verification remain separate controls.

## Isolated Neon validation

Migration `0003` was applied and replayed on an isolated Neon child branch, never on `main`. The
live checks covered:

- `KEEP`, `SUPERSEDE`, `INVALIDATE`, `UNKNOWN`, and `QUARANTINE`;
- positive contiguous versions, stable idempotency, and stale-writer rejection;
- direct `state_slots` mutation rejection;
- canonical trimming of slot, idempotency, and resolver identities;
- deliberate projection-head drift, detection through `state_projection_drift`, and rejection of the
  next event until repair;
- a second idempotent application preserving all accepted events;
- zero drift after restoration.

The canonical Neon `main` branch remains on schema `0.1.1`; promotion of `0.2.0` is a separate
owner-controlled operation.
