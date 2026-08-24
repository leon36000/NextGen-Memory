# Inherited Rerank Telemetry v0 Design

**Date:** 2026-08-15
**Status:** approved under the project owner's standing architecture delegation
**Base:** `feat/bounded-inherited-reranker-v0`

## 1. Goal

Inherited Rerank Telemetry v0 records the aggregate-only effect of Bounded Inherited Reranker v0 without persisting query text, memory content, path-level provenance, direct feedback, or database-specific state.

The component must answer:

- which canonical memories were evaluated;
- what their base and inherited-aware ranks and scores were;
- how much inherited adjustment was applied;
- why inherited evidence was applied or neutralized;
- how many candidates were promoted, demoted, unchanged, or gated;
- whether the top candidate changed;
- which exact bounded policy produced the observation;
- whether a retry produced the same deterministic telemetry batch.

It does not score candidates, query Neon, write a database, or alter retrieval behavior.

## 2. Considered approaches

### 2.1 Extend `ngm.retrieval_events`

Rejected for v0.

Retrieval events are written before or during retrieval/context compilation and are immutable. Updating them after inherited reranking would either violate append-only semantics or overload one row with observations from multiple stages.

### 2.2 Add a Neon telemetry table immediately

Deferred.

A storage schema would create deployment, retention, and migration commitments before aggregate fields and operational usefulness are proven. The project first needs a stable typed event contract and deterministic fixtures.

### 2.3 Deterministic telemetry batch plus injected sink — selected

The selected approach produces immutable aggregate records and a deterministic batch. A sink protocol allows local, file, event-bus, or future Neon adapters without coupling the kernel to one backend.

## 3. Inputs

`build_inherited_rerank_telemetry(...)` receives:

- canonical `space_id`;
- `router_decision_id` identifying the upstream routing decision;
- exact `BoundedInheritedRerankerConfig`;
- a sequence of `InheritedAwareRerankedMemory` results.

The builder never accepts a query string or free-form metadata.

## 4. Core contracts

### 4.1 `InheritedRerankObservation`

One immutable aggregate observation per canonical memory:

- deterministic observation UUID;
- deterministic batch UUID;
- space and router-decision UUIDs;
- memory UUID;
- base rank and score;
- final rank and score;
- rank delta;
- inherited applied and uncapped components;
- inherited evidence disposition;
- contribution count;
- signed and absolute inherited value sums;
- conservative standard-error sum;
- minimum structural confidence;
- count shrinkage;
- path coherence;
- uncertainty reliability;
- confidence reliability;
- policy version and policy fingerprint;
- deterministic content hash.

The observation intentionally excludes:

- direct reward and verdict aggregates;
- retrieval query text;
- memory content;
- backend payloads;
- relation or edge paths;
- feedback notes;
- timestamps generated during building.

### 4.2 `InheritedRerankSummary`

One immutable deterministic summary per batch:

- candidate count;
- applied count;
- no-evidence count;
- minimum-count-gated count;
- minimum-confidence-gated count;
- promoted, demoted, and unchanged counts;
- whether the top memory changed;
- original and final top-memory UUIDs when candidates exist;
- signed adjustment sum;
- absolute adjustment sum;
- maximum absolute adjustment observed;
- configured hard cap;
- deterministic content hash.

The summary contains no averaged direct utility and no combined utility score.

### 4.3 `InheritedRerankTelemetryBatch`

One immutable batch:

- deterministic batch UUID;
- space and router-decision UUIDs;
- policy version and policy fingerprint;
- observations in final-rank order;
- summary;
- deterministic batch content hash.

For an empty candidate list, the explicit configuration supplies policy identity and the summary contains zero counts and null top memories.

### 4.4 Sink contracts

`InheritedRerankTelemetrySink` exposes:

```python
record(batch: InheritedRerankTelemetryBatch) -> None
```

`InMemoryInheritedRerankTelemetrySink` stores batches by deterministic UUID:

- exact retries are idempotent;
- a reused UUID with different immutable content raises `InheritedRerankTelemetryConflictError`;
- iteration order is deterministic by batch UUID.

The sink owns no transaction and performs no serialization outside the typed contract.

## 5. Deterministic identities and hashes

### 5.1 Policy fingerprint

The fingerprint covers every `BoundedInheritedRerankerConfig` field that changes behavior:

- inherited weight;
- hard adjustment cap;
- prior contribution count;
- minimum contribution count;
- minimum structural confidence;
- value scale;
- uncertainty floor;
- policy version.

### 5.2 Observation content hash

The observation content hash covers every immutable observation field except its UUID and batch UUID.

### 5.3 Batch identity

The builder first computes observation content hashes in canonical memory-UUID order, then computes:

```text
batch_content_hash = SHA256(
  space_id
  + router_decision_id
  + policy_fingerprint
  + ordered observation hashes
  + summary content hash
)
```

The batch UUID is UUID5 over the batch content hash. Observation UUIDs are UUID5 under the batch UUID and memory UUID.

Exact retries therefore recreate byte-identical JSON and UUIDs. Any changed score, rank, disposition, evidence aggregate, or policy creates a different batch identity.

## 6. Builder validation

The builder fails closed when:

1. `space_id` or `router_decision_id` is not a UUID;
2. config is not `BoundedInheritedRerankerConfig`;
3. results contain unsupported values;
4. candidate memory UUIDs are duplicated;
5. base ranks are not positive, unique, and contiguous;
6. final ranks are not positive, unique, and contiguous;
7. base or final scores are non-finite;
8. a result's policy version differs from the supplied config;
9. applied component exceeds the configured cap;
10. `final_score != base.final_score + applied_component` within a fixed numerical tolerance;
11. rank delta is inconsistent;
12. disposition and inherited aggregate fields are structurally inconsistent;
13. summary counts do not partition all candidates.

The original reranker output remains unchanged.

## 7. Canonical ordering

Input order does not affect telemetry.

- observations are stored in final-rank order;
- ties cannot exist because final ranks must be unique;
- hashes use canonical UUID order to avoid circular dependency on final ordering;
- in-memory sink iteration uses lexical batch UUID order;
- JSON keys are sorted and separators are compact.

## 8. Privacy boundary

The event contracts contain only:

- UUIDs;
- ranks and numeric scores;
- aggregate inherited evidence;
- bounded reliability factors;
- dispositions;
- policy identity;
- hashes.

Forbidden fields and values include:

- raw query, prompt, answer, or memory body;
- command, stdout, stderr, patch, or environment;
- secret, token, API key, or connection string;
- relation paths, edge paths, source text, or feedback notes;
- arbitrary metadata mappings.

`render_json()` is safe for control-plane telemetry but is not an authorization mechanism.

## 9. Summary semantics

Rank delta is defined as:

```text
rank_delta = base_rank - final_rank
```

Therefore:

- positive delta = promoted;
- negative delta = demoted;
- zero delta = unchanged.

`top_changed` is true only when both candidate lists are non-empty and the memory at base rank one differs from the memory at final rank one.

The summary adjustment aggregates are calculated from applied components, never uncapped components.

## 10. Testing strategy

The suite must cover:

1. immutable observation, summary, and batch contracts;
2. deterministic policy fingerprint;
3. exact UUID/hash retry stability;
4. changed policy/result creates a new batch identity;
5. empty batch behavior;
6. exact summary partition and top-change semantics;
7. applied, no-evidence, count-gated, and confidence-gated observations;
8. positive, negative, and zero rank deltas;
9. finite score, cap, score-equation, rank, duplicate, policy, and type failures;
10. input-order invariance and canonical JSON;
11. in-memory sink idempotence and conflict detection;
12. absence of direct evidence and raw-content fields;
13. at least 5,000 deterministic generated result sets preserving identity, partition, cap, score, rank, ordering, and privacy invariants;
14. stable root-package exports.

## 11. Non-goals

V0 does not:

- modify Bounded Inherited Reranker v0;
- query or write Neon;
- define retention or sampling policy;
- add timestamps;
- store path-level provenance;
- store direct feedback;
- calculate downstream reward attribution;
- train coefficients;
- alter routing, eligibility, retrieval, or context compilation;
- merge or deploy any branch.

## 12. Success criteria

The feature is complete when exact inherited-reranking outcomes can be represented, summarized, retried, serialized, and emitted without raw content or direct-feedback double counting; 5,000 generated cases preserve all invariants; the full repository passes Python 3.12 and 3.13; and no database or protected reranker file changes.
