# Inherited Credit Ledger v0

## Purpose

Inherited Credit Ledger v0 persists the output of Provenance Credit v0 without converting inherited structural evidence into direct causal feedback.

It permanently distinguishes:

```text
direct causal feedback
interaction allocation
inherited provenance contribution
```

Inherited rows are never written to `ngm.memory_feedback`, and the existing `ngm.node_utility` view remains unchanged.

## Storage model

The additive candidate migration `migrations/neon/0006_inherited_credit_ledger.sql` creates four append-only tables.

### `ngm.provenance_credit_evaluations`

One evaluation records the exact interpretation of one selected direct credit under one graph snapshot and one propagation-policy snapshot.

Its deterministic identity includes:

- direct credit UUID;
- graph fingerprint;
- policy fingerprint.

The row also contains the root memory UUID, direct source kind/value/uncertainty, trial count, matched-set hashes, result status, result hash, and the UUID of its exact accounting row.

### `ngm.inherited_credit_contributions`

One row represents one retained provenance path. It contains:

- target memory UUID;
- propagated value and standard error;
- structural and minimum edge confidence;
- exact depth;
- normalized relation path;
- exact edge UUID path;
- path fingerprint;
- immutable content hash.

Converging paths remain separate evidence rows. Target totals are derived rather than persisted as a second mutable truth.

### `ngm.provenance_credit_observations`

Observations distinguish:

- `blocked`: one typed edge excluded by policy or hard gate;
- `abstention`: one direct credit produced no inherited contribution.

Blocked rows require current/target node IDs, edge ID, relation, depth, and path fingerprint. Abstentions require all path fields to be null.

### `ngm.provenance_credit_accounting`

Exactly one accounting row is required per evaluation. It records:

```text
direct value
propagation budget
propagated value
dropped value
unallocated value
conservation residual
```

A circular composite foreign key is deferrable and initially deferred:

```text
evaluation.accounting_id → accounting.id
accounting.evaluation_id → evaluation.id
```

The transaction cannot commit unless both directions refer to the same evaluation/accounting pair.

## Python builder

`build_provenance_credit_batch()` consumes:

- `TypedProvenanceGraph`;
- reviewed `ProvenanceRelationPolicy` values;
- `PropagationConfig`;
- one `ProvenanceCreditResult`.

It validates all graph/result references and creates deterministic records.

### Graph fingerprint

The graph fingerprint includes only control-plane fields:

- node UUID, space, authorization, validity;
- edge UUID, endpoints, relation, confidence, local attribution, evidence UUID.

It excludes every memory body and free-form payload.

### Policy fingerprint

The policy fingerprint covers all reviewed relation policies plus every configuration value that changes allocation.

### Deterministic child IDs

```text
evaluation = UUID5(direct_credit_id, graph + policy fingerprint)
contribution = UUID5(evaluation_id, path fingerprint)
blocked observation = UUID5(evaluation_id, path + reason)
abstention = UUID5(evaluation_id, reason)
accounting = UUID5(evaluation_id, "mass-ledger")
```

Exact retries therefore rebuild identical rows.

### Result hash

The evaluation result hash covers:

- the evaluation payload;
- every ordered contribution hash;
- every ordered observation hash;
- the accounting hash.

It proves the persisted child set is complete without storing raw evidence.

## Writer and transaction boundary

`ProvenanceCreditPersistenceWriter` uses static parameterized SQL and a structural cursor protocol.

It performs four insert phases followed by four scoped readback phases:

1. evaluations;
2. contributions;
3. observations;
4. accounting;
5. exact readback and immutable comparison for every table.

The caller owns the transaction. Because evaluation/accounting foreign keys are deferred, all four write phases must execute in one transaction.

A missing, unexpected, duplicate, malformed, or conflicting readback row raises `ProvenanceCreditPersistenceConflictError`. No partial batch is reported as success.

## Analytical separation

### `ngm.node_inherited_credit`

This view exposes inherited evidence only:

- contribution count;
- signed value sum;
- absolute value sum;
- conservative standard-error sum;
- minimum structural confidence;
- latest inherited-credit timestamp.

### `ngm.node_learning_evidence`

This view joins direct and inherited aggregates side-by-side:

```text
direct feedback fields | inherited evidence fields
```

It deliberately does not create `combined_utility` or another blended score.

Any future reranker that consumes inherited evidence must declare a separate bounded coefficient and retain direct/inherited provenance in its score breakdown.

## Privacy boundary

The contracts and schema contain only:

- UUID identities;
- typed relation/reason values;
- bounded numeric evidence;
- exact UUID/relation paths;
- SHA-256 fingerprints;
- policy version and timestamps.

They contain no raw query, prompt, answer, memory content, command, stdout, stderr, patch, environment, token, secret, or feedback note.

## Candidate Neon validation

Migration `0006` was validated only on the temporary Neon branch:

```text
br-soft-cherry-a6pv1ag2
```

Verified positive path:

- four tables, four append-only triggers, two analytical views;
- two evaluations;
- one inherited contribution;
- one blocked observation and one abstention;
- two exact accounting rows;
- evaluation/accounting links valid in both directions;
- exact replay without duplicate rows;
- target inherited aggregate `0.5` while direct feedback remains `0`;
- `ngm.node_utility` definition unchanged.

Verified negative path:

- updates/deletes rejected on all four tables;
- evaluation without accounting rejected at deferred-constraint check;
- accounting without evaluation rejected;
- malformed blocked/abstention shape rejected;
- contribution path/depth mismatch rejected;
- conflicting immutable replay remains detectable by readback;
- no failed negative-test row survived.

No migration was applied to Neon main.

## Deployment gate

Production deployment remains a separate explicit decision.

Before promotion:

1. review the final migration diff;
2. create a fresh Neon branch from production;
3. apply migrations in stack order;
4. run exact replay, conflict, trigger, view, and privacy checks;
5. confirm `memory_feedback` and `node_utility` remain unchanged;
6. approve deployment explicitly;
7. retain rollback and prior application compatibility until readers and writers are verified.

## Non-goals

V0 does not:

- combine direct and inherited utility;
- write ordinary memory feedback;
- learn relation weights;
- schedule counterfactual experiments;
- store raw graph or memory content;
- manage transactions or connection pools;
- apply the migration automatically.
