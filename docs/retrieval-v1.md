# Research Retrieval v1

## Purpose

Research Retrieval v1 is the first executable read path for the NextGen Memory research expert. It retrieves canonical research memories from MongoDB Atlas while preserving Neon as the authority for identity, routing decisions, and retrieval feedback.

## Requirements

- MongoDB 8.0 or newer because the pipeline uses native `$rankFusion`.
- Database: `nextgen_memory`.
- Collection: `research_sources`.
- Vector Search index: `rag_autoembed_v1` with auto-embedding on `rag_text` and filter fields `space_id`, `status`.
- Atlas Search index: `rag_lexical_v1` over `rag_text`, `title`, `claims_text`, and `tags`.
- PyMongo is optional and loaded only by `MongoResearchRetriever.from_uri`.

`$scoreFusion` is deliberately not used because it requires MongoDB 8.2; the connected cluster currently runs MongoDB 8.0.29.

## Retrieval contract

Every query requires a canonical `space_id`. The semantic branch applies `space_id` and `status=active` as vector prefilters. The lexical branch applies the same restrictions immediately after `$search`. Results are fused using MongoDB's reciprocal-rank fusion implementation.

```python
from os import environ
from uuid import UUID

from nextgen_memory import MongoResearchRetriever, ResearchRetrievalQuery

retriever = MongoResearchRetriever.from_uri(environ["MONGODB_URI"])
try:
    hits = retriever.search(
        ResearchRetrievalQuery(
            text="memory MoE router utility latent memory",
            space_id=UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e"),
            limit=5,
        )
    )
finally:
    retriever.close()
```

## Canonical identity reconciliation

The ten MongoDB research records have matching UUID rows in `ngm.memory_nodes`. The idempotent seed is stored at `migrations/neon/0003_research_sources_seed.sql`; Neon remains authoritative for identity while MongoDB remains the rich-payload and retrieval backend.

## Privacy boundary

The query is sent to Atlas because it is required for retrieval, but it is not copied into Neon retrieval telemetry. `ngm.router_decisions` owns the SHA-256 query hash and feature record. `ngm.retrieval_events` stores only decision ID, expert, canonical node/backend reference, rank, scores, and usage flags.

## Live validation — August 14, 2026

The native hybrid pipeline was executed against the connected Atlas collection. For the query `memory MoE router utility latent memory`, the top results were:

1. Dynamic Mixture of Latent Memories for Self-Evolving Agents.
2. CoEvo-Mem: Co-Evolving Retrieval Policy and Memory Bank for LLM Agents.
3. ElasticMem: Latent Memory as a Learnable Resource for LLM Agents.
4. Continual Self-Improvement with Lightweight Experiential Latent Memories.
5. RoMeRL: Balancing Feedback Coverage and the Memory-Reward Trap.

This smoke result verifies index readiness, auto-embed query syntax, scope/status filtering, weighted RRF, and score-detail projection. It is external evidence rather than a network-dependent CI test.

## Deferred work

- utility-aware reranking from Neon;
- context token packing;
- attribution of used memories after the action;
- feedback and learned router updates;
- Temporal-managed consolidation.
