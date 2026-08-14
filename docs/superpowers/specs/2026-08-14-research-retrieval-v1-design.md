# Research Retrieval v1 Design

## Status and authorization

The project owner explicitly asked the research/software-engineering work to continue. This design implements the next documented roadmap slice without merging or mutating `main`. Publication, if performed, must use an isolated feature branch and remain reviewable.

## Goal

Add a production-shaped, privacy-preserving research retrieval adapter that converts a scoped query into a ranked set of canonical memory records using MongoDB Atlas native hybrid search, then converts those results into Neon-compatible retrieval-event rows.

## Scope

Included:

- MongoDB Atlas lexical + auto-embedded vector retrieval over `nextgen_memory.research_sources`.
- Native MongoDB 8.0 `$rankFusion` using reciprocal-rank fusion.
- Mandatory `space_id` and `status=active` isolation.
- Typed query and result contracts.
- Dependency-injected collection access so unit tests require no network.
- Deterministic, idempotent retrieval-event IDs for `ngm.retrieval_events`.
- A writer that emits Neon-compatible rows without storing raw query text.
- Unit tests, documentation, a live Atlas smoke validation, and idempotent canonical Neon research identities.

Excluded:

- Utility reranking from `ngm.node_utility`.
- Context compilation and token packing.
- Learned routing or feedback updates.
- Temporal workflows.
- Schema changes; the only live data write is an idempotent append-only reconciliation of the ten Mongo research identities into existing `ngm.memory_nodes`.
- Merging the existing draft PR.

## Approaches considered

### A. Native `$rankFusion` — selected

One Atlas aggregation executes semantic and lexical sub-pipelines and fuses ranks server-side. It preserves the documented RRF formula, requires one round trip, exposes score details for diagnostics, and avoids client-side score-scale mistakes. The connected cluster is MongoDB 8.0.29, and a live query against the two existing indexes succeeded.

### B. Client-side reciprocal-rank fusion

This works on older MongoDB versions but requires two queries, duplicates fusion logic, and makes consistency and latency worse. It remains a fallback only if the deployment target loses MongoDB 8.0 support.

### C. `$scoreFusion`

This would support score normalization and custom formulas but requires MongoDB 8.2. The current cluster is 8.0.29, so this approach is intentionally deferred.

## Architecture

### `retrieval.py`

Defines immutable contracts:

- `ResearchRetrievalQuery`: query text, canonical space, result limit, candidate multiplier, semantic/lexical weights, and diagnostic-score flag.
- `ResearchRetrievalHit`: canonical memory UUID, Mongo backend reference, final rank, fused score, title, URI, tags, and optional score details.

Validation is fail-fast: empty queries, invalid limits, non-finite weights, zero total weight, and invalid ranks are rejected before database access.

### `mongodb_retrieval.py`

Defines:

- `MongoResearchIndexConfig`: database/collection/index names and indexed paths.
- `build_research_hybrid_pipeline`: a pure function returning the exact Atlas aggregation.
- `MongoResearchRetriever`: a collection-injected adapter that executes the pipeline and maps documents into typed hits.
- `from_uri`: the only path that imports and owns `pymongo.MongoClient`.

The semantic sub-pipeline uses the auto-embed query form:

```javascript
$vectorSearch: {
  index: "rag_autoembed_v1",
  path: "rag_text",
  query: { text: "..." },
  filter: { space_id: "...", status: "active" }
}
```

The lexical sub-pipeline uses `$search`, then `$match` for scope/status, then `$limit`. Both feed `$rankFusion`; projection occurs only after fusion.

### `migrations/neon/0003_research_sources_seed.sql`

Creates the ten canonical `ngm.memory_nodes` identities referenced by MongoDB `research_sources`. The seed is append-only and idempotent, uses only the registered `research` and `semantic` expert keys, and leaves rich payloads in MongoDB.

### `retrieval_telemetry.py`

Defines:

- `RetrievalEvent`: an immutable representation of one `ngm.retrieval_events` row.
- `build_retrieval_events`: deterministic UUIDv5 event construction from decision, node, backend reference, and rank.
- `RetrievalEventWriter`: parameterized `executemany` persistence with `ON CONFLICT (id) DO NOTHING`.

No telemetry object accepts or serializes query text. The query hash already belongs to the router-decision record; retrieval events reference `router_decision_id`.

## Data flow

```text
RoutingRequest + RoutingDecision
  -> selected research expert
  -> ResearchRetrievalQuery(space_id, query)
  -> build_research_hybrid_pipeline
  -> canonical Neon IDs already reconciled to Mongo backend references
  -> MongoDB Atlas $rankFusion
  -> ResearchRetrievalHit[]
  -> context compiler (future/current caller)
  -> build_retrieval_events(selected IDs)
  -> RetrievalEventWriter
  -> ngm.retrieval_events
```

## Failure handling

- Invalid requests fail before I/O with `ValueError`.
- Missing `pymongo` affects only `from_uri`, not pure contracts/tests.
- Atlas errors propagate with their original driver exception; the adapter does not silently degrade to lexical-only retrieval.
- Malformed Mongo documents fail closed instead of inventing canonical IDs.
- Event persistence is idempotent by deterministic primary key.
- The caller owns transaction commit/rollback.

## Security and privacy

- `space_id` is mandatory and is applied as a vector prefilter and lexical post-filter.
- Only `status=active` records can be returned.
- No raw query is placed in retrieval telemetry or Neon rows.
- SQL is parameterized.
- Mongo credentials come from caller configuration/environment and never enter source files.

## Testing

Unit tests cover:

- exact pipeline structure and native fusion placement;
- scope/status filters in both retrieval branches;
- query validation and weight validation;
- document-to-hit mapping and rank assignment;
- malformed canonical IDs;
- exact Neon/Mongo research-identity seed coverage and idempotence;
- deterministic retrieval-event IDs;
- selected-for-context flags;
- absence of raw query fields;
- parameterized Neon writer behavior and idempotent SQL.

A live Atlas aggregation is retained as external verification evidence, not as a required CI test.
