# MongoDB Atlas collection contracts

Database: `nextgen_memory`

MongoDB stores rich payloads. Neon/Postgres remains the source of identity, authority,
provenance, state, and routing telemetry. Every durable document uses the canonical
`ngm.memory_nodes.id` UUID string in its `memory_id` field.

## Collections

- `memory_objects`: rich episodic, semantic, and procedural payloads.
- `raw_traces`: exact append-only agent and tool traces.
- `research_sources`: external source metadata, claims, and citation provenance.
- `repository_artifacts`: files, symbols, AST facts, dependencies, commits, and tests.

## Required operational rules

1. Corrections append a new document and link through `supersedes` or `invalidates`;
   they never silently replace source evidence.
2. `space_id` is mandatory on durable project/user memories.
3. Search indexes are created only after representative payloads exist and are inspected.
4. Scope filters are applied inside Atlas Search or as Vector Search prefilters before relevance.
5. No passwords, connection strings, tokens, or private keys are stored in collection
   contract documents or checked-in fixtures.
6. An embedding-provider rate limit must trigger bounded retry/backoff or an explicit failure;
   it must never trigger unscoped retrieval.

## Verified research search strategy

- `rag_lexical_v2` performs exact/token-aware lexical search and indexes `space_id`, `status`,
  and `source_type` so policy filters execute inside `$search`.
- `rag_autoembed_v1` performs semantic candidate generation over `rag_text` and prefilters the
  same scope/lifecycle fields.
- MongoDB 8.0 native `$rankFusion` combines the channels and can expose per-channel rank details.
- The versioned lexical definition is stored in `rag_lexical_v2.json`.
- Entity/temporal/causal traversal remains governed by canonical Neon metadata.
