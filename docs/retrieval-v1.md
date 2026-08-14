# Research Retrieval v1

## Purpose

Research Retrieval v1 is the first executable read path for the NextGen Memory research expert. It retrieves canonical research memories from MongoDB Atlas while preserving Neon as the authority for identity, routing decisions, and retrieval feedback.

## Requirements

- MongoDB 8.0 or newer because the pipeline uses native `$rankFusion`.
- Database: `nextgen_memory`.
- Collection: `research_sources`.
- Vector Search index: `rag_autoembed_v1` with auto-embedding on `rag_text` and filter fields `space_id`, `source_type`, and `status`.
- Atlas Search index: `rag_lexical_v2` over `rag_text`, `title`, `claims_text`, and `tags`, with token mappings for `space_id`, `status`, and `source_type`.
- PyMongo is optional and loaded only by `MongoResearchRetriever.from_uri`.

`$scoreFusion` is deliberately not used because it requires MongoDB 8.2; the connected cluster currently runs MongoDB 8.0.29.

## Retrieval contract

Every query requires a canonical `space_id`. The semantic branch applies `space_id` and `status=active` as vector prefilters. The lexical branch applies the same restrictions inside the `$search.compound.filter` stage; global lexical retrieval followed by `$match` is forbidden. Results are fused using MongoDB's reciprocal-rank fusion implementation.

```python
from os import environ
from uuid import UUID

from nextgen_memory import MongoResearchRetriever, ResearchRetrievalQuery

retriever = MongoResearchRetriever.from_uri(environ["MONGODB_URI"])
try:
    hits = retriever.search(
        ResearchRetrievalQuery(
            text="utility-aware retrieval and co-evolving memory routing",
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

The connected Atlas cluster reports MongoDB 8.0.29. Both `rag_lexical_v2` and `rag_autoembed_v1` are READY and queryable.

For `utility-aware retrieval and co-evolving memory routing`, weighted native RRF returned:

1. CoEvo-Mem.
2. MemRL.
3. RoMeRL.
4. ElasticMem.
5. Dynamic Mixture of Latent Memories.

Score details showed each result's lexical and semantic rank. A lexical query using an unrelated `space_id` returned zero documents, verifying scope isolation inside Atlas Search.

One immediate second auto-embedding request hit the provider's rate limit. This is an external capacity condition rather than an index-definition failure; callers must retain retry/backoff behavior and must not silently fall back to unscoped retrieval.

## Deferred work

- utility-aware reranking from Neon;
- context token packing;
- attribution of used memories after the action;
- feedback and learned router updates;
- Temporal-managed consolidation.
