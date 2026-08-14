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
4. Scope filters are applied before lexical or vector relevance.
5. No passwords, connection strings, tokens, or private keys are stored in collection
   contract documents or checked-in fixtures.

## Planned search strategy

- Atlas Search for exact identifiers, paths, symbols, error strings, and citations.
- Vector Search for semantic episode/research matching.
- Rank fusion only after MongoDB version and workload fields are verified.
- Entity/temporal/causal traversal remains governed by canonical Neon metadata.
