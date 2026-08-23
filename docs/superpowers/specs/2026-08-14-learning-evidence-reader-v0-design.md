# Learning Evidence Reader v0 Design

**Date:** 2026-08-14
**Status:** approved under the project owner's standing architecture delegation
**Base:** `feat/inherited-credit-ledger-v0`

## 1. Goal

Learning Evidence Reader v0 reads direct and inherited memory-learning evidence from Neon while preserving their causal distinction in the Python type system.

It answers:

- how much direct task feedback exists for one canonical memory;
- how much inherited provenance evidence exists;
- what uncertainty and structural confidence accompany inherited evidence;
- when each evidence class was last updated;
- whether a requested memory is missing, duplicated, malformed, or outside scope.

It does **not** calculate a combined utility score and does not change retrieval order.

## 2. Position in the learning path

```text
memory_feedback
  → ngm.node_utility
  → DirectUtilityEvidence

inherited_credit_contributions
  → ngm.node_inherited_credit
  → InheritedUtilityEvidence

both views
  → ngm.node_learning_evidence
  → LearningEvidenceReader v0
  → future explicitly bounded scoring policy
```

The reader is the last neutral boundary before any model or reranker is permitted to use inherited evidence.

## 3. Why a separate reader is required

The existing `NodeUtilityReader` reads `ngm.node_utility`, which represents direct feedback only. Replacing that reader or extending its return type in place would create several risks:

- older callers might silently start consuming inherited evidence;
- a structural estimate could be mistaken for direct causal evidence;
- a single aggregate could hide whether reward came from direct trials or provenance paths;
- feature attribution in the reranker would become ambiguous;
- rollback would be harder because direct-only behavior would no longer have a stable contract.

Learning Evidence Reader v0 is therefore additive. `NodeUtilityReader` remains unchanged.

## 4. Core contracts

### 4.1 `DirectUtilityEvidence`

Immutable direct evidence for one memory:

- `feedback_count`;
- optional `average_reward`;
- `positive_count`;
- `negative_count`;
- optional `last_feedback_at`.

Invariants:

- counts are non-negative integers;
- positive and negative counts cannot exceed total feedback count;
- zero feedback requires a null average and timestamp;
- positive feedback count requires a finite average and timezone-aware timestamp.

A neutral direct record is represented explicitly rather than by a fabricated reward of zero.

### 4.2 `InheritedUtilityEvidence`

Immutable inherited evidence for one memory:

- `contribution_count`;
- optional signed `value_sum`;
- optional `absolute_value_sum`;
- optional conservative `standard_error_sum`;
- optional `minimum_structural_confidence`;
- optional `last_credit_at`.

Invariants:

- contribution count is non-negative;
- zero contributions require every aggregate and timestamp to be null;
- positive contribution count requires every aggregate and timestamp;
- all numeric values are finite;
- absolute sum is non-negative and at least `abs(value_sum)`;
- standard-error sum is non-negative;
- structural confidence is in `[0, 1]`;
- timestamp is timezone-aware.

No derived score is stored in this contract.

### 4.3 `NodeLearningEvidence`

One immutable scoped snapshot:

- canonical `space_id` and `memory_id`;
- `direct: DirectUtilityEvidence`;
- `inherited: InheritedUtilityEvidence`.

Convenience properties expose only evidence presence:

```python
has_direct_evidence
has_inherited_evidence
```

There is deliberately no `utility`, `score`, `combined_reward`, or implicit fallback property.

## 5. Reader contract

`NeonLearningEvidenceReader(cursor)` uses one static parameterized query:

```sql
SELECT
  space_id,
  node_id,
  direct_feedback_count,
  direct_avg_reward,
  direct_positive_count,
  direct_negative_count,
  last_direct_feedback_at,
  inherited_contribution_count,
  inherited_value_sum,
  inherited_absolute_value_sum,
  inherited_standard_error_sum,
  minimum_structural_confidence,
  last_inherited_credit_at
FROM ngm.node_learning_evidence
WHERE space_id = %(space_id)s
  AND node_id = ANY(%(memory_ids)s::uuid[])
ORDER BY node_id
```

The reader:

1. normalizes and deduplicates requested UUIDs;
2. performs no SQL for an empty request;
3. accepts mapping rows only;
4. requires every requested UUID exactly once;
5. rejects unexpected, duplicate, malformed, or cross-space rows;
6. returns an immutable mapping keyed by memory UUID;
7. never fabricates a missing memory as neutral.

Missing rows are a scope or schema-integrity failure, not a no-feedback state. A real memory with no evidence is returned by the view with explicit zero counts and null aggregates.

## 6. Driver boundary

The core package keeps no mandatory psycopg dependency. It defines a structural cursor protocol with:

```python
execute(sql, params)
fetchall()
```

Rows may contain native UUID/datetime/numeric objects or strings/numbers convertible under the strict contract.

## 7. Privacy boundary

The query and result contain only:

- memory and space UUIDs;
- counts;
- bounded aggregate values;
- timestamps;
- structural confidence.

They contain no query text, prompt, answer, memory body, command, stdout, stderr, patch, environment, token, secret, path fingerprint, relation path, or feedback note.

The reader accepts no free-form metadata.

## 8. Error model

- `LearningEvidenceValidationError`: malformed request or row contract;
- `LearningEvidenceReadConflictError`: missing, duplicate, unexpected, or cross-space rows.

Backend execution errors propagate. There is no fallback to direct-only or invented neutral evidence after a query failure.

## 9. Determinism

For the same logical requested UUID set and same stored rows:

- SQL parameters are sorted UUIDs;
- output mapping iteration order is UUID lexical order;
- input request order and database row order do not affect equality;
- neutral records remain explicit and stable.

## 10. Testing strategy

The suite must cover:

1. direct and inherited contracts independently;
2. neutral direct and inherited records;
3. finite-value, count, timestamp, absolute-sum, and confidence validation;
4. static scoped SQL and absence of raw query fields;
5. empty input without SQL;
6. request deduplication and stable parameter order;
7. mapping-only rows;
8. missing, unexpected, duplicate, and cross-space rows;
9. row-order and request-order invariance;
10. immutable result mappings;
11. stable public exports;
12. at least 5,000 deterministic generated snapshots preserving all invariants;
13. exact query smoke test against the isolated `0006` Neon candidate branch.

## 11. Non-goals

V0 does not:

- modify `NodeUtilityReader`;
- compute a direct-plus-inherited utility;
- alter the utility reranker;
- write feedback or inherited credit;
- apply migration `0006`;
- read path-level contribution details;
- learn coefficients;
- hide missing rows as neutral evidence.

## 12. Success criteria

The feature is complete when direct and inherited evidence can be read together but cannot be accidentally conflated, all malformed or incomplete reads fail closed, the full suite passes on Python 3.12 and 3.13, and no database or default-branch mutation occurs.
