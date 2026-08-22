# Research Retrieval v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add native hybrid research retrieval and privacy-preserving Neon retrieval-event emission to the NextGen Memory kernel.

**Architecture:** A pure pipeline builder creates a MongoDB 8.0 `$rankFusion` aggregation over existing lexical and auto-embed indexes. A dependency-injected retriever maps results to immutable contracts, and a separate telemetry module emits deterministic rows compatible with `ngm.retrieval_events` without storing raw queries.

**Tech Stack:** Python 3.12+, dataclasses, typing protocols, PyMongo as an optional runtime dependency, MongoDB Atlas Search/Vector Search, PostgreSQL-compatible parameterized SQL, pytest, Ruff.

## Global Constraints

- Do not merge or mutate `main`.
- Preserve Neon as canonical authority for `memory_id`.
- Require `space_id` on every research query.
- Return only `status=active` records.
- Do not store raw query text in retrieval telemetry.
- Do not add a learned router, utility reranker, Temporal workflow, or schema change in this slice.
- Keep all unit tests network-free.

---

### Task 1: Typed retrieval contracts and native Atlas pipeline

**Files:**
- Create: `src/nextgen_memory/retrieval.py`
- Create: `src/nextgen_memory/mongodb_retrieval.py`
- Test: `tests/test_mongodb_retrieval.py`

**Interfaces:**
- Produces: `ResearchRetrievalQuery`, `ResearchRetrievalHit`, `MongoResearchIndexConfig`, `build_research_hybrid_pipeline`, `MongoResearchRetriever`.
- Consumes: Mongo documents containing `_id`, `memory_id`, `title`, `source_uri`, `tags`, and fusion score metadata.

- [ ] **Step 1: Write failing contract and pipeline tests**

Create tests asserting:

```python
query = ResearchRetrievalQuery(
    text="memory MoE utility router",
    space_id=UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e"),
    limit=5,
)
pipeline = build_research_hybrid_pipeline(query, MongoResearchIndexConfig())
assert "$rankFusion" in pipeline[0]
semantic = pipeline[0]["$rankFusion"]["input"]["pipelines"]["semantic"][0]
assert semantic["$vectorSearch"]["query"] == {"text": query.text}
assert semantic["$vectorSearch"]["filter"] == {
    "space_id": str(query.space_id),
    "status": "active",
}
```

Also assert empty text, non-positive limit, `num_candidates < limit`, non-finite weights, and zero total weight raise `ValueError`.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest tests/test_mongodb_retrieval.py -q`
Expected: collection failure because `nextgen_memory.retrieval` and `nextgen_memory.mongodb_retrieval` do not exist.

- [ ] **Step 3: Implement minimal immutable contracts and pure pipeline builder**

Implement the exact interfaces above. Use `$rankFusion` as the first stage, `$limit` as the second stage, and `$project` as the final stage. Keep `$project` outside fusion sub-pipelines.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_mongodb_retrieval.py -q`
Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add src/nextgen_memory/retrieval.py src/nextgen_memory/mongodb_retrieval.py tests/test_mongodb_retrieval.py
git commit -m "feat: add native hybrid research retrieval"
```

### Task 2: Dependency-injected Mongo adapter and result mapping

**Files:**
- Modify: `src/nextgen_memory/mongodb_retrieval.py`
- Modify: `tests/test_mongodb_retrieval.py`

**Interfaces:**
- Consumes: an object with `aggregate(pipeline)` returning iterable mappings.
- Produces: `MongoResearchRetriever.search(query) -> tuple[ResearchRetrievalHit, ...]` and `MongoResearchRetriever.from_uri(...)`.

- [ ] **Step 1: Add failing adapter tests**

Use a fake collection that captures the pipeline and returns two documents. Assert ranks are assigned in returned order, UUID strings become `UUID`, tags become tuples, and score details are preserved only when present. Add a malformed `memory_id` case that raises `ValueError`.

- [ ] **Step 2: Run focused tests and confirm RED**

Run: `python -m pytest tests/test_mongodb_retrieval.py -q`
Expected: failures because `MongoResearchRetriever.search` and mapping behavior are missing.

- [ ] **Step 3: Implement adapter and mapping**

Keep `pymongo` imported only inside `from_uri`. Store an owned client only for instances created by `from_uri`; `close()` must be a no-op for injected collections and close the owned client otherwise.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_mongodb_retrieval.py -q`
Expected: all retrieval tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add src/nextgen_memory/mongodb_retrieval.py tests/test_mongodb_retrieval.py
git commit -m "feat: add injectable Mongo research retriever"
```

### Task 3: Privacy-preserving Neon retrieval events

**Files:**
- Create: `src/nextgen_memory/retrieval_telemetry.py`
- Test: `tests/test_retrieval_telemetry.py`

**Interfaces:**
- Consumes: `space_id: UUID`, `router_decision_id: UUID`, `expert_key: str`, `ResearchRetrievalHit` values, and a set of selected memory IDs.
- Produces: `RetrievalEvent`, `build_retrieval_events`, `RetrievalEventWriter.write(cursor, events) -> int`.

- [ ] **Step 1: Write failing event tests**

Assert:

```python
events_a = build_retrieval_events(...)
events_b = build_retrieval_events(...)
assert events_a == events_b
assert events_a[0].id == events_b[0].id
assert events_a[0].selected_for_context is True
assert "query" not in events_a[0].to_db_params()
```

Use a fake cursor to assert `executemany` receives parameter dictionaries and the SQL contains `ON CONFLICT (id) DO NOTHING`.

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest tests/test_retrieval_telemetry.py -q`
Expected: collection failure because the telemetry module does not exist.

- [ ] **Step 3: Implement deterministic events and writer**

Use UUIDv5 with a stable namespace and a key containing `space_id`, `router_decision_id`, `expert_key`, `node_id`, `backend_ref`, and rank. Do not accept query text as an argument.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest tests/test_retrieval_telemetry.py -q`
Expected: all telemetry tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add src/nextgen_memory/retrieval_telemetry.py tests/test_retrieval_telemetry.py
git commit -m "feat: add privacy-preserving retrieval telemetry"
```

### Task 4: Public API, documentation, and package verification

**Files:**
- Create or modify: `src/nextgen_memory/__init__.py`
- Modify: `pyproject.toml`
- Create: `docs/retrieval-v1.md`
- Modify: `README.md`
- Remove from target patch: obsolete standalone `src/ngm_rag/` prototype files.
- Test: `tests/test_public_api.py`

**Interfaces:**
- Produces public imports for all new retrieval contracts and adapters.

- [ ] **Step 1: Write failing public API test**

Assert the new types can be imported from `nextgen_memory` and that importing the package does not import `pymongo`.

- [ ] **Step 2: Run test and confirm RED**

Run: `python -m pytest tests/test_public_api.py -q`
Expected: failure because exports are absent.

- [ ] **Step 3: Add exports, optional dependency metadata, and docs**

Add `mongodb = ["pymongo>=4.10,<5"]` to optional dependencies when applying to the target repository. Document the verified Atlas 8.0 requirement, index names, privacy boundary, and live smoke query.

- [ ] **Step 4: Run full verification**

Run:

```bash
python -m pytest -q
python -m ruff check src tests
python -m compileall -q src
python -m build --no-isolation
```

Expected: all commands exit 0.

- [ ] **Step 5: Inspect diff and scan for secrets/raw queries**

Run:

```bash
git diff --check
grep -RInE 'mongodb\+srv://|postgres(ql)?://|MONGODB_URI=' src tests docs README.md || true
grep -RIn 'query_text' src/nextgen_memory tests || true
```

Expected: no connection strings and no retrieval telemetry field named `query_text`.

- [ ] **Step 6: Commit Task 4**

```bash
git add src/nextgen_memory/__init__.py pyproject.toml docs/retrieval-v1.md README.md tests/test_public_api.py
git commit -m "docs: expose and document research retrieval v1"
```

### Task 5: Canonical Neon research identity reconciliation

**Files:**
- Create: `migrations/neon/0003_research_sources_seed.sql`
- Test: `tests/test_research_seed_contract.py`

**Interfaces:**
- Consumes: the ten canonical UUIDs already stored in MongoDB `research_sources`.
- Produces: idempotent `ngm.memory_nodes` identities pointing to Mongo backend references.

- [x] **Step 1: Detect the integrity gap**

A read-only Neon query returned zero matching canonical nodes for the ten Mongo UUIDs.

- [x] **Step 2: Add an idempotent append-only seed**

Use existing schema and source principal; set `expert_keys` to `research` and `semantic`; keep rich payloads in MongoDB.

- [x] **Step 3: Add contract tests**

Assert exact UUID coverage, valid expert keys, 64-character hashes, Mongo collection metadata, and `ON CONFLICT DO NOTHING`.

- [x] **Step 4: Verify live reconciliation**

The live insert returned ten rows. A follow-up query confirmed ten canonical nodes, ten research-routed nodes, ten Mongo links, and ten distinct backend references.
