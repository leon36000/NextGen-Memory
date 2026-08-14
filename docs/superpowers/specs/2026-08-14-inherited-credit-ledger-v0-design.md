# Inherited Credit Ledger v0 Design

**Date:** 2026-08-14
**Status:** approved for implementation
**Base:** `feat/provenance-credit-v0`

## 1. Goal

Inherited Credit Ledger v0 persists Provenance Credit results as an append-only evidence class that remains structurally and analytically separate from direct `memory_feedback`.

The ledger must make these statements distinguishable forever:

- this memory directly changed a matched outcome;
- this memory received an interaction allocation;
- this memory inherited bounded structural support through a reviewed provenance path.

Inherited credit is not direct causal feedback and must never be inserted into `ngm.memory_feedback` or silently included in `ngm.node_utility`.

## 2. Selected storage model

The durable contract uses four typed tables.

### 2.1 `ngm.provenance_credit_evaluations`

One immutable header per selected direct credit, graph snapshot, and policy snapshot:

- deterministic evaluation UUID;
- direct credit and evidence-group UUIDs;
- root memory UUID;
- direct source kind, value, standard error, and trial count;
- matched context and continuation hashes;
- graph and policy fingerprints;
- policy version;
- result status;
- deterministic result hash.

The evaluation identity includes direct-credit identity plus graph and policy fingerprints. The same direct evidence can therefore be replayed under a later reviewed policy without overwriting its earlier interpretation.

### 2.2 `ngm.inherited_credit_contributions`

One immutable row per retained provenance path:

- deterministic contribution UUID;
- evaluation and target memory UUIDs;
- signed propagated value and standard error;
- structural confidence and minimum edge confidence;
- depth;
- normalized relation path;
- exact edge UUID path;
- path fingerprint;
- deterministic content hash.

Path rows are primary evidence. Per-target totals remain derivable and are not persisted as an independent mutable truth.

### 2.3 `ngm.provenance_credit_observations`

One immutable row for each blocked edge or root abstention:

- deterministic observation UUID;
- evaluation UUID;
- kind: `blocked` or `abstention`;
- current, target, and edge UUIDs when applicable;
- normalized relation and reason;
- depth and path fingerprint when applicable;
- deterministic content hash.

This prevents an empty inherited result from being confused with a successful zero-value propagation.

### 2.4 `ngm.provenance_credit_accounting`

Exactly one immutable conservation row per evaluation:

- direct value;
- propagation budget;
- propagated, dropped, and unallocated values;
- conservation residual;
- deterministic content hash.

The row is required even when propagation abstains.

## 3. Analytic separation

The existing `ngm.node_utility` view continues to aggregate only direct rows from `ngm.memory_feedback`.

A new `ngm.node_inherited_credit` view exposes inherited evidence separately:

- contribution count;
- sum of inherited value;
- sum of absolute inherited value;
- sum of path standard errors;
- minimum structural confidence;
- last inherited-credit timestamp.

A new `ngm.node_learning_evidence` view joins direct and inherited aggregates side-by-side. It deliberately does not calculate one combined utility score.

Any future reranker that uses inherited evidence must declare an explicit bounded coefficient and must retain direct/inherited feature provenance in its score breakdown.

## 4. Python contracts

`provenance_credit_persistence.py` provides:

- `ProvenanceCreditEvaluationRecord`;
- `InheritedCreditContributionRecord`;
- `ProvenanceCreditObservationRecord`;
- `ProvenanceCreditAccountingRecord`;
- `ProvenanceCreditBatch`;
- `build_provenance_credit_batch`;
- `ProvenanceCreditPersistenceWriter`;
- static insert and verification SQL constants.

The builder consumes:

- the exact `TypedProvenanceGraph`;
- reviewed relation policies;
- `PropagationConfig`;
- one `ProvenanceCreditResult`.

It recomputes canonical graph and policy fingerprints, validates every result reference, groups evidence per direct credit, and derives deterministic UUID5 record identities and SHA-256 content hashes.

## 5. Fingerprints

### Graph fingerprint

The canonical graph fingerprint includes only control-plane evidence:

- node UUID, space UUID, authorization, and validity;
- edge UUID, endpoints, relation, confidence, local attribution, and evidence UUID.

It contains no memory body, query, prompt, answer, command, output, note, or secret.

### Policy fingerprint

The policy fingerprint includes sorted relation policies and all propagation configuration values that change allocation.

### Result hash

Each evaluation result hash covers its evaluation payload plus the ordered content hashes of contributions, observations, and accounting. It proves completeness of the persisted batch without storing raw content.

## 6. Deterministic identities

For one direct credit:

```text
evaluation_id = UUID5(
    direct_credit_id,
    "inherited-credit-evaluation-v0:" + graph_fingerprint + ":" + policy_fingerprint
)
```

Child records use UUID5 under the evaluation UUID and their stable evidence identity:

- contribution: path fingerprint;
- blocked observation: path fingerprint plus reason;
- abstention: reason;
- accounting: fixed key `mass-ledger`.

Exact retries produce identical records. Reusing an identity with different immutable content fails after insert-then-readback verification.

## 7. Writer behavior

The writer receives a structural cursor protocol and one complete batch.

1. Validate one space and unique record identities before SQL.
2. Insert the evaluation rows.
3. Insert contribution rows.
4. Insert observation rows.
5. Insert accounting rows.
6. Read every inserted identity back with scoped queries.
7. Compare every immutable field exactly.
8. Return the number of verified rows.

The caller owns the transaction. A future orchestration adapter may wrap the writer in one transaction with direct-credit persistence, but this module does not create hidden commits.

## 8. Migration invariants

`0006_inherited_credit_ledger.sql` is additive and idempotent.

It enforces:

- same-space foreign keys;
- append-only update/delete rejection;
- SHA-256 formats;
- finite numeric values;
- probability bounds;
- positive depths and trial counts;
- path cardinality equals depth;
- typed observation completeness;
- exactly one accounting row per evaluation;
- deterministic unique identities;
- no free-form notes or generic metadata payload.

The migration registers schema metadata but is not applied to Neon main by this PR.

## 9. Privacy boundary

The persisted schema contains only:

- UUID identities;
- relation and reason enums;
- bounded numeric evidence;
- typed paths;
- SHA-256 fingerprints;
- policy version and timestamps.

It contains no raw query, prompt, answer, memory body, command, stdout, stderr, patch, environment, token, secret, or feedback note.

## 10. Failure model

- malformed builder input raises `ProvenanceCreditPersistenceValidationError` before SQL;
- stored payload mismatch raises `ProvenanceCreditPersistenceConflictError`;
- missing or unexpected readback rows fail closed;
- contribution, observation, and accounting evidence must refer to a known direct evaluation;
- a result whose mass ledger does not match its direct credit cannot be persisted;
- no partial batch is reported as success.

## 11. Testing strategy

The test suite must cover:

1. deterministic graph, policy, evaluation, child-record, and result hashes;
2. input-order invariance;
3. exact retry equality;
4. distinct policy or graph snapshots create distinct evaluations;
5. contributions, blocks, abstentions, and mass accounting map exactly;
6. direct and inherited storage contracts never target `memory_feedback`;
7. static parameterized SQL;
8. insert-then-readback verification;
9. missing, duplicate, unexpected, or conflicting stored rows;
10. same-space and referential failures;
11. migration table, constraint, trigger, index, and view contracts;
12. `node_utility` remains unchanged and separate;
13. at least 2,000 deterministic generated results preserve identities and privacy.

## 12. Non-goals

V0 does not:

- apply the migration to production;
- update direct utility aggregates;
- learn a combined utility score;
- persist raw graph or memory content;
- schedule counterfactual trials;
- manage transactions or connection pools;
- re-run propagation;
- modify existing direct feedback.

## 13. Success criteria

The feature is complete when inherited evidence can be deterministically built, persisted, replayed, and audited without entering direct feedback, without altering `node_utility`, and without any production database mutation.
