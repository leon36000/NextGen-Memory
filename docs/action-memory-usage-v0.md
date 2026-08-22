# Action-Memory Usage Events v0

## Purpose

A retrieval event records that a memory was selected for context. It does not prove that the resulting action actually used that memory. Action-memory usage events add this missing positive evidence without mutating the immutable retrieval row.

Only positive use is recorded. Absence of a usage event means that use has not been proven for that action; it does not mean retrieval failed or that the memory was harmful.

## Immutable contract

`ActionMemoryUsageEvent` contains only:

- deterministic event UUID;
- canonical `space_id`;
- external canonical `action_id`;
- router decision UUID;
- retrieval event UUID;
- canonical memory UUID;
- canonical SHA-256 payload hash.

The hash is computed from sorted JSON containing the version and those UUID strings. The UUID is UUID5 over the version and payload hash. Raw query text, prompt, answer, memory content, title, URI, backend reference, score, command, output, note, principal and secret values are excluded.

## Builder

`build_action_memory_usage_events` accepts one action, the immutable retrieval events visible to the action, and the exact set of memory UUIDs used. It fails before persistence when:

- the action or used identities are not UUIDs;
- retrieval rows span spaces or router decisions;
- retrieval event or memory identities are duplicated;
- a used identity is unknown, backend-only or was not selected for context.

The result contains only the used subset and is deterministic under permutation.

## Persistence

Migration `0006_action_memory_usage_events.sql` adds `ngm.action_memory_usage_events`. It never updates `ngm.retrieval_events`.

The application writer performs parameterized insert followed by exact action/scope-bound readback. Missing, duplicate, unexpected, malformed or conflicting rows fail closed with bounded errors.

A PostgreSQL trigger independently verifies that the referenced retrieval row has the same space, router decision and memory identity and was selected for context. The shared immutable trigger rejects update and delete.

## Causal reader

`CreditTargetReader.fetch_for_action` derives `used_in_action` from an exact `EXISTS` join on action, space, decision, retrieval event and memory. Usage evidence for another action cannot contaminate the requested action.

The historical `CreditTargetReader.fetch` contract remains available for callers that explicitly need the legacy retrieval field.

## Rollout boundary

The migration is a candidate until it passes temporary-branch replay, positive and adversarial write tests, parent isolation, exact-SHA CI and independent review. Production deployment is a separate decision from merging the Python contract.
