# Action-Memory Usage Events v0 Design

**Date:** 2026-08-22

**Status:** Approved autonomous implementation direction

**Base:** `93cce924debb9ae2ff46d71b2e8fa043f4cefa0b`

**Issues:** #40, #41, #42, #43, #44, #45

## Goal

Record exact positive evidence that a memory selected during retrieval was actually used by one action, without mutating the immutable retrieval event. This evidence closes the boundary required by paired causal credit: selected evidence is not assumed to be used, and use is not inferred from rendering, ranking, or retrieval alone.

## Chosen model

One immutable `ActionMemoryUsageEvent` links:

- schema version;
- canonical `space_id`;
- canonical external `action_id`;
- `router_decision_id`;
- `retrieval_event_id`;
- canonical `memory_id`;
- canonical privacy-safe `content_hash`.

Only positive use is persisted. A selected memory that was not used has no matching event for that action. The same retrieval event may be used by several distinct actions, but never more than once per action.

## Identity and privacy

The event content hash is SHA-256 of canonical sorted JSON containing only the version and UUID strings. Its UUID is UUID5 over the version plus this hash. No query, prompt, answer, content, title, source URI, backend payload, score, command, tool output, note, principal or secret is accepted.

## Builder boundary

`build_action_memory_usage_events` receives:

- one canonical `action_id`;
- immutable `RetrievalEvent` objects;
- the exact set of memory UUIDs used by the action.

It requires one space and one router decision, unique retrieval IDs, unique node-backed memory identities, and `selected_for_context=true` for every used memory. Unknown, backend-only, unselected, duplicate, mixed-scope or mixed-decision use fails before SQL. Output is sorted deterministically.

## Persistence boundary

Migration `0006_action_memory_usage_events.sql` creates an additive append-only table. A database trigger independently reads the referenced retrieval row and verifies matching scope, decision, memory identity, and selection. A separate immutable trigger rejects update/delete. Static indexes support action-specific and retrieval-specific reads.

The writer uses parameterized `INSERT ... ON CONFLICT DO NOTHING`, followed by an exact scope/action-bound readback. Missing, duplicate, unexpected, malformed, or conflicting rows fail closed through a bounded error that contains no payload.

## Causal reader

Historical `CreditTargetReader.fetch` remains unchanged. `fetch_for_action` uses an action-specific SQL query and derives `used_in_action` only from a matching usage event with the same action, scope, router decision, retrieval event and memory. An event for another action cannot contaminate the target.

## Rollout

1. Record test-only RED in ordinary CI.
2. Implement pure Python contracts and property oracle.
3. Implement migration and action-specific reader.
4. Run focused/full Python 3.12 and 3.13 checks.
5. Verify exact candidate SHA directly.
6. Replay migration and adversarial writes on a temporary Neon child branch; prove parent isolation and delete the child.
7. Submit a blind GPT-5.6 Sol packet.
8. Merge only on exact-SHA `APPROVE`. Production migration remains a later deployment decision.

## Non-goals

- mutating legacy `retrieval_events.used_in_action`;
- storing raw action payloads;
- assigning credit automatically;
- requiring the separate execution-ledger stack;
- durable orchestration or Temporal;
- treating absence of a usage event as evidence that retrieval itself failed.
