# Inherited Rerank Telemetry v0

## Purpose

Inherited Rerank Telemetry v0 records the aggregate effect of Bounded Inherited Reranker v0 without storing query text, memory content, direct feedback, path-level provenance, or database-specific payloads.

It observes an already-completed second-stage rerank:

```text
utility-aware base results
  → bounded inherited reranker
  → inherited-aware results
  → deterministic aggregate telemetry batch
  → injected sink
```

The component does not score candidates, query a database, update retrieval events, or activate inherited reranking in production.

## Why this is a separate telemetry contract

The existing retrieval-event contract is append-only and represents retrieval/context-stage observations. Mutating those rows after inherited reranking would weaken stage boundaries and immutable replay semantics.

Inherited Rerank Telemetry therefore emits a separate typed batch. The batch can later be sent to a file, event bus, observability service, or reviewed persistence adapter without coupling the memory kernel to one backend.

## Inputs

`build_inherited_rerank_telemetry()` requires:

- canonical `space_id`;
- upstream `router_decision_id`;
- exact `BoundedInheritedRerankerConfig`;
- the complete `InheritedAwareRerankedMemory` sequence.

There is no argument for query text, memory bodies, arbitrary metadata, timestamps, or direct feedback.

## Observation contract

`InheritedRerankObservation` contains one aggregate record per canonical memory:

- deterministic observation and batch UUIDs;
- space, router-decision, and memory UUIDs;
- base rank and score;
- inherited-aware final rank and score;
- rank delta;
- applied and uncapped inherited components;
- evidence disposition;
- contribution count;
- signed and absolute inherited value sums;
- conservative standard-error sum;
- minimum structural confidence;
- count shrinkage;
- path coherence;
- uncertainty reliability;
- confidence reliability;
- policy version and policy fingerprint;
- immutable content hash.

Rank delta is defined as:

```text
rank_delta = base_rank - final_rank
```

Therefore:

- positive delta means promotion;
- negative delta means demotion;
- zero means unchanged.

The observation contains no direct average reward, direct verdict counts, relation paths, edge paths, source text, or free-form note.

## Summary contract

`InheritedRerankSummary` records one deterministic batch summary:

- candidate count;
- applied count;
- no-evidence count;
- minimum-count-gated count;
- minimum-confidence-gated count;
- promoted, demoted, and unchanged counts;
- whether the top candidate changed;
- base and final top-memory UUIDs;
- signed adjustment sum;
- absolute adjustment sum;
- maximum observed absolute adjustment;
- configured hard cap;
- immutable content hash.

The two count partitions must both close exactly:

```text
applied
+ no_evidence
+ below_minimum_count
+ below_minimum_confidence
= candidate_count
```

```text
promoted
+ demoted
+ unchanged
= candidate_count
```

An empty batch is explicit: zero counts, null top-memory UUIDs, zero adjustment aggregates, and `top_changed = false`.

## Deterministic batch identity

### Policy fingerprint

`fingerprint_bounded_inherited_policy()` hashes every configuration field that can change behavior:

- inherited weight;
- hard adjustment cap;
- prior contribution count;
- minimum contribution count;
- minimum structural confidence;
- value scale;
- uncertainty floor;
- policy version.

### Observation hashes

Each observation content hash covers all immutable aggregate fields except observation and batch UUIDs.

### Batch hash and UUID

The batch content hash covers:

- space UUID;
- router-decision UUID;
- policy identity;
- observation hashes in canonical memory-UUID order;
- summary content hash.

The batch UUID is UUID5 over the schema identifier and batch content hash. Observation UUIDs are UUID5 under the batch UUID and canonical memory UUID.

Exact retries recreate identical objects, hashes, UUIDs, and JSON. A changed score, rank, disposition, aggregate, decision, or policy creates a different batch identity.

## Canonical serialization

`InheritedRerankTelemetryBatch.render_json()` produces compact canonical JSON:

- sorted keys;
- stable separators;
- observations stored in final-rank order;
- no runtime timestamp;
- no backend-generated identifier.

Input result order does not affect the batch.

## Fail-closed validation

The builder rejects:

- non-UUID space or decision identifiers;
- unsupported config or result types;
- duplicate candidate memory UUIDs;
- non-positive, duplicate, or non-contiguous base ranks;
- non-positive, duplicate, or non-contiguous final ranks;
- non-finite base or final scores;
- policy-version mismatch;
- applied adjustment above the configured cap;
- final score inconsistent with `base_score + applied_component`;
- malformed no-evidence or observed-evidence aggregates;
- gated evidence with a non-zero applied component;
- invalid summary partitions or top-change semantics.

There is no fallback that silently drops an invalid candidate or fabricates a neutral observation.

## Sink boundary

`InheritedRerankTelemetrySink` defines one method:

```python
record(batch: InheritedRerankTelemetryBatch) -> None
```

`InMemoryInheritedRerankTelemetrySink` is the reference adapter:

- exact retry is idempotent;
- batch iteration is lexical by batch UUID;
- same UUID with different immutable content raises `InheritedRerankTelemetryConflictError`;
- unsupported values raise `InheritedRerankTelemetryValidationError`.

The sink manages no transaction and performs no database write.

## Generated verification

`tests/test_inherited_rerank_telemetry_properties.py` generates 5,000 deterministic result sets containing zero to six candidates and all four evidence dispositions.

It verifies:

- byte-identical JSON under input permutation;
- deterministic batch and observation identities;
- unique memory and observation UUIDs;
- contiguous final-rank ordering;
- exact score equation;
- hard adjustment cap;
- exact disposition and rank-change partitions;
- correct top-memory semantics;
- explicit empty batches;
- policy and router-decision identity sensitivity;
- absence of forbidden raw-content and direct-feedback fields.

## Privacy boundary

The telemetry contains only:

- UUIDs;
- ranks and finite scores;
- aggregate inherited evidence;
- bounded reliability factors;
- dispositions;
- policy identity;
- hashes.

It excludes:

- query, prompt, or answer text;
- memory bodies or source text;
- commands, stdout, stderr, patches, or environment values;
- secrets, tokens, API keys, or connection strings;
- direct reward and direct verdict aggregates;
- relation paths, edge paths, or feedback notes;
- arbitrary metadata mappings.

Canonical JSON is suitable for a control-plane telemetry boundary, but it does not grant authorization or make a candidate eligible.

## Minimal example

```python
from nextgen_memory import (
    InMemoryInheritedRerankTelemetrySink,
    build_inherited_rerank_telemetry,
)

batch = build_inherited_rerank_telemetry(
    space_id=space_id,
    router_decision_id=decision_id,
    config=reranker.config,
    results=inherited_aware_results,
)

sink = InMemoryInheritedRerankTelemetrySink()
sink.record(batch)
sink.record(batch)  # exact retry is idempotent

assert sink.batches == (batch,)
```

## Future persistence gate

A future persistence adapter may store the exact aggregate contract only after a separate review of:

- retention and deletion policy;
- sampling and volume limits;
- same-space foreign keys;
- append-only conflict semantics;
- transaction ownership;
- operational dashboards;
- confirmation that no raw query or memory content enters the schema.

Inherited Rerank Telemetry v0 itself defines no SQL or migration.

## Non-goals

V0 does not:

- modify the bounded inherited reranker;
- alter direct-aware scoring;
- query or write Neon, MongoDB, or another backend;
- update retrieval events;
- add timestamps;
- store path-level provenance or direct feedback;
- define retention or sampling policy;
- attribute downstream task reward;
- learn coefficients;
- alter routing, eligibility, retrieval, or context compilation;
- merge or deploy a branch.
