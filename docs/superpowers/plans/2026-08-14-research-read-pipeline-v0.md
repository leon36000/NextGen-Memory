# Research Read Pipeline v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute a fail-closed end-to-end research memory read path from sparse routing through scoped retrieval, utility reranking, cross-store materialization, coverage-first context compilation, and immutable retrieval observations.

**Architecture:** A research-specific pipeline coordinates already verified components. New reader adapters validate canonical Neon metadata and exact Atlas payloads. A cross-store materializer joins them by UUID and backend reference, computes a materialized-view hash, injects a caller-owned token estimator, and produces `ContextEvidence`. The pipeline gates every side effect on routing and expert budget, then compiles and returns an explicit status.

**Tech Stack:** Python 3.12+ standard library dataclasses/enums/protocols/hashlib, pytest, Ruff, existing Mongo/Neon adapters, GitHub Actions.

## Global Constraints

- Research retrieval never runs unless the router selects `ExpertKey.RESEARCH`.
- Routing, retrieval, and compilation requests must share one exact `space_id` and normalized query text.
- Compiler usable evidence tokens may not exceed the research expert allocation.
- Neon owns identity, authority, confidence, expert membership, sensitivity, and validity.
- Atlas owns exact rich payload fields and must remain `status=active` in the same space.
- Missing, duplicate, unexpected, inactive, or stale cross-store data fails closed.
- Canonical Neon `content_hash` and materialized `rag_text` hash are distinct audit fields.
- The pipeline never guesses token count; a positive estimator result is required.
- No query text or evidence content appears in telemetry serialization.
- No database migration or write is introduced by this feature.

---

### Task 1: Pipeline and materialization contracts

**Files:**
- Create: `src/nextgen_memory/research_read_pipeline.py`
- Create: `tests/test_research_read_pipeline.py`

**Interfaces:**
- Produces: errors, status enum, metadata/document/materialized/result dataclasses, provider protocols, and `ResearchReadRequest`.

- [ ] **Step 1: Write failing contract tests**

Cover:

```python
ResearchReadRequest(
    routing_request=...,
    retrieval_query=...,
    compile_request=...,
    mandatory_memory_ids=(),
    coverage_aliases={},
)
```

Expected validation:

- exact shared space;
- normalized routing/retrieval query equality;
- research task/need intent;
- `memory:read` permission;
- unique mandatory IDs;
- non-empty aliases;
- immutable alias mapping.

Also test `ResearchMemoryMetadata`, `ResearchSourceDocument`, `MaterializedResearchEvidence`, and `ResearchReadResult` validation.

- [ ] **Step 2: Confirm RED**

Run: `python -m pytest tests/test_research_read_pipeline.py -q`  
Expected: missing module.

- [ ] **Step 3: Implement minimal frozen contracts**

Required names:

```python
ResearchReadValidationError
ResearchReadBudgetError
ResearchMaterializationError
ResearchReadStatus
ResearchReadRequest
ResearchMemoryMetadata
ResearchSourceDocument
MaterializedResearchEvidence
ResearchReadResult
ResearchMetadataProvider
ResearchDocumentProvider
TokenEstimator
```

- [ ] **Step 4: Run focused tests**

- [ ] **Step 5: Commit**

```bash
git add src/nextgen_memory/research_read_pipeline.py tests/test_research_read_pipeline.py
git commit -m "feat: add research read pipeline contracts"
```

### Task 2: Scoped Neon metadata reader

**Files:**
- Modify: `src/nextgen_memory/research_read_pipeline.py`
- Create: `tests/test_research_metadata_reader.py`

**Interfaces:**
- Produces `RESEARCH_METADATA_SELECT_SQL`, `ResearchMetadataCursor`, and `NeonResearchMetadataReader.fetch(...)`.

- [ ] **Step 1: Write failing tests**

Verify:

- query contains `WHERE space_id = %(space_id)s` and UUID array;
- empty input performs no query;
- rows must be mappings with all required columns;
- row space and UUID must be requested;
- duplicates and unexpected IDs fail;
- expert keys must contain `research`;
- malformed hashes/probabilities/sensitivity/timestamps fail;
- output order is irrelevant and mapping is immutable.

- [ ] **Step 2: Confirm RED**

- [ ] **Step 3: Implement the reader**

SQL columns:

```sql
SELECT
  id AS memory_id,
  space_id,
  subject_key,
  expert_keys,
  confidence,
  authority,
  content_hash,
  sensitivity,
  valid_from,
  valid_to
FROM ngm.memory_nodes
WHERE space_id = %(space_id)s
  AND id = ANY(%(memory_ids)s::uuid[])
ORDER BY id
```

Do not fabricate rows for absent IDs; materialization owns completeness validation.

- [ ] **Step 4: Run focused tests**

- [ ] **Step 5: Commit**

### Task 3: Scoped Atlas document reader

**Files:**
- Modify: `src/nextgen_memory/research_read_pipeline.py`
- Create: `tests/test_research_document_reader.py`

**Interfaces:**
- Produces `MongoFindCollection` protocol and `MongoResearchDocumentReader.fetch(...)`.

- [ ] **Step 1: Write failing tests**

Verify exact filter:

```python
{
    "_id": {"$in": sorted_backend_refs},
    "memory_id": {"$in": sorted_uuid_strings},
    "space_id": str(space_id),
    "status": active_status,
}
```

Projection must contain only `_id`, identity/scope/status, title/source fields, tags, `rag_text`, and provenance.

Reject:

- non-mapping documents;
- missing columns;
- cross-space/inactive/unrequested UUID;
- unexpected backend reference;
- duplicate memory UUID or backend reference;
- malformed tags/provenance/claims/rag text;
- requested memory/backend pairs that do not correspond.

- [ ] **Step 2: Confirm RED**

- [ ] **Step 3: Implement fail-closed reader**

Return immutable mapping keyed by memory UUID. Do not silently return an unexpected subset as complete.

- [ ] **Step 4: Run focused tests**

- [ ] **Step 5: Commit**

### Task 4: Cross-store evidence materializer

**Files:**
- Modify: `src/nextgen_memory/research_read_pipeline.py`
- Create: `tests/test_research_materializer.py`

**Interfaces:**
- Produces `CrossStoreResearchMaterializer.materialize(...)`.

- [ ] **Step 1: Write failing tests**

Positive join validates:

- exact requested ID sets;
- retrieval hit and Atlas `_id`, title, URI, tags match;
- metadata has research expert;
- token estimate is positive integer;
- aliases expand normalized tags;
- mandatory IDs propagate;
- materialized hash equals SHA-256 of exact `rag_text`;
- canonical Neon hash remains separately visible;
- `to_context_evidence()` uses materialized hash and Neon authority/confidence/subject.

Negative tests:

- missing/extra Neon row;
- missing/extra Atlas document;
- title/URI/tag/backend mismatch;
- invalid validity interval at supplied evaluation time;
- non-positive token result;
- duplicate reranked UUID or backend ref.

- [ ] **Step 2: Confirm RED**

- [ ] **Step 3: Implement deterministic join**

The materializer receives already reranked candidates and returns them in reranker rank order regardless of provider mapping order.

- [ ] **Step 4: Run focused tests**

- [ ] **Step 5: Commit**

### Task 5: Route and budget-gated pipeline execution

**Files:**
- Modify: `src/nextgen_memory/research_read_pipeline.py`
- Modify: `tests/test_research_read_pipeline.py`

**Interfaces:**
- Produces `ResearchReadPipeline.execute(request, *, routing_sink=None)`.

Constructor dependencies:

```python
ResearchReadPipeline(
    router: DeterministicMemoryRouter,
    retriever: UtilityAwareResearchRetriever,
    materializer: CrossStoreResearchMaterializer,
    compiler: ContextCompiler,
)
```

- [ ] **Step 1: Write failing tests**

Verify:

- `not_routed` leaves retriever/materializer/compiler untouched;
- selected research budget is required;
- compile usable tokens above allocation fails before retrieval;
- no hits returns `no_results`, no packet, explicit required gaps;
- complete materialization returns `complete`;
- uncovered keys return `incomplete`;
- backend exceptions propagate;
- final result collections are immutable;
- raw query/content absent from telemetry dict.

- [ ] **Step 2: Confirm RED**

- [ ] **Step 3: Implement sequence**

Use exact route allocation:

```python
allocation = decision.expert_budgets.get(ExpertKey.RESEARCH)
```

No implicit escalation.

- [ ] **Step 4: Run focused tests**

- [ ] **Step 5: Commit**

### Task 6: Final-score and token-aware retrieval events

**Files:**
- Modify: `src/nextgen_memory/retrieval_telemetry.py`
- Modify: `tests/test_retrieval_telemetry.py`
- Modify: `src/nextgen_memory/research_read_pipeline.py`
- Modify: `tests/test_research_read_pipeline.py`

**Interfaces:**
- Backward-compatible extension of `build_retrieval_events`.

New optional parameters:

```python
final_scores: Mapping[UUID, float] = MappingProxyType({})
estimated_tokens: Mapping[UUID, int] = MappingProxyType({})
```

- [ ] **Step 1: Write failing compatibility and enrichment tests**

Existing calls must remain byte-for-byte equivalent. Enriched events must use raw hit score, reranked final score, token estimate, and packet selection flag.

Reject unexpected map UUIDs or non-finite/non-positive values.

- [ ] **Step 2: Confirm RED**

- [ ] **Step 3: Implement extension and pipeline wiring**

The pipeline builds retrieval observations only after compilation.

- [ ] **Step 4: Run focused tests**

- [ ] **Step 5: Commit**

### Task 7: Property tests, exports, and documentation

**Files:**
- Create: `tests/test_research_read_pipeline_properties.py`
- Modify: `src/nextgen_memory/__init__.py`
- Create: `docs/research-read-pipeline-v0.md`
- Modify: `README.md`

**Interfaces:**
- Publicly exports the pipeline contracts and adapters.

- [ ] **Step 1: Write 2,000-case deterministic property test**

Check:

- no downstream calls when not routed;
- every materialized UUID was reranked;
- selected packet IDs are a subset of materialized IDs;
- total tokens remain bounded;
- retrieval observations match reranked ordering and packet selection;
- outputs are invariant under provider row order permutation;
- missing/extra cross-store data always fails.

- [ ] **Step 2: Add public exports and usage docs**

- [ ] **Step 3: Run fresh verification**

```bash
ruff check .
python -m pytest -q
python -m compileall -q src
python -m build --wheel --no-isolation
git diff --check
```

- [ ] **Step 4: Open stacked draft PR**

Base: `feat/context-compiler-v0`

- [ ] **Step 5: Require user-triggered GitHub Actions matrix success**

Python 3.12 and 3.13, Ruff, full suite, and property tests.

## Final Review Gate

- [ ] Diff contains only pipeline/materialization/telemetry-compatible files and docs.
- [ ] No raw query or evidence content is emitted by telemetry methods.
- [ ] No database schema or default branch changes.
- [ ] No hidden relevance-only or unscoped fallback.
- [ ] PR remains draft and unmerged until explicit owner approval.
