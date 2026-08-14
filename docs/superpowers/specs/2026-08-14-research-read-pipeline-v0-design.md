# Research Read Pipeline v0 Design

**Date:** 2026-08-14  
**Status:** Approved under the project owner's standing architecture delegation  
**Base:** `feat/context-compiler-v0`

## 1. Goal

Research Read Pipeline v0 executes the first complete, auditable NextGen Memory read path:

```text
RoutingRequest
  → Memory-MoE route
  → scoped Atlas hybrid retrieval
  → utility-aware reranking
  → cross-store evidence materialization
  → coverage-first Context Compiler
  → privacy-preserving result and retrieval observations
```

The pipeline must never bypass routing, widen scope after an empty search, invent missing metadata, or silently convert a coverage gap into a complete packet.

V0 is intentionally research-specific because research is the first expert with verified retrieval, utility, and rich-payload infrastructure. A generic multi-expert orchestrator should be extracted only after at least two expert pipelines share stable behavior.

## 2. Why a specialized pipeline first

### Generic expert orchestrator now

A generic registry of expert providers would look elegant, but only the research expert currently has a complete retrieval and materialization path. Such an abstraction would either:

- pretend unsupported experts are implemented;
- silently skip selected experts;
- encode speculative interfaces that later expert stores must imitate;
- obscure the exact cross-store checks required for research evidence.

### Concrete research pipeline — selected

The selected design integrates only verified components and exposes explicit ports at the real side-effect boundaries. Later expert pipelines can demonstrate which interfaces are truly common.

## 3. Existing verified components consumed

- `DeterministicMemoryRouter`
- `RoutingRequest` and `RoutingDecision`
- `ResearchRetrievalQuery` and `ResearchRetrievalHit`
- `UtilityAwareResearchRetriever` and `RerankedMemory`
- `ContextCompileRequest`, `ContextEvidence`, `ContextCompiler`, `ContextPacket`
- `RetrievalEvent` telemetry contract
- MongoDB `research_sources`
- Neon `ngm.memory_nodes`

The pipeline does not reimplement their algorithms.

## 4. Real storage contract

Live Atlas inspection confirmed active `research_sources` documents contain:

- `_id`
- `memory_id`
- `space_id`
- `source_uri`
- `source_type`
- `status`
- `title`
- `authors`
- `claims`
- `claims_text`
- `tags`
- `rag_text`
- `provenance`

`rag_lexical_v2` and `rag_autoembed_v1` both filter `space_id`, `status`, and `source_type` inside the retrieval channel.

Neon remains canonical for identity and authority. For requested research memory UUIDs, the metadata reader uses `ngm.memory_nodes` and returns:

- `id`
- `space_id`
- `subject_key`
- `expert_keys`
- `confidence`
- `authority`
- `content_hash`
- `sensitivity`
- validity interval
- creation/knowledge timestamps

No Atlas field is allowed to replace canonical Neon authority or confidence.

## 5. Pipeline contracts

### 5.1 `ResearchReadRequest`

One immutable request contains:

- `routing_request: RoutingRequest`
- `retrieval_query: ResearchRetrievalQuery`
- `compile_request: ContextCompileRequest`
- optional explicit `mandatory_memory_ids`
- optional `coverage_aliases`, mapping normalized Atlas tags to canonical coverage keys
- `active_status`, default `active`

Validation requires:

- all three scopes use the same `space_id`;
- routing and retrieval query text are identical after normalization;
- mandatory UUIDs are unique;
- coverage alias keys and values are non-empty normalized strings;
- the routing request is allowed to read memory;
- the request contains research intent through `TaskKind.RESEARCH` or `EvidenceNeed.RESEARCH`.

### 5.2 `ResearchMemoryMetadata`

One immutable canonical Neon row with:

- memory and space UUIDs;
- subject key;
- expert keys;
- confidence and authority;
- canonical Neon content hash;
- sensitivity;
- optional `valid_from` and `valid_to`.

It must contain expert `research`, match the requested space, use finite probabilities, and have a valid interval.

### 5.3 `MaterializedResearchEvidence`

One cross-store joined item with:

- original `RerankedMemory`;
- canonical `ResearchMemoryMetadata`;
- exact Atlas `rag_text` content;
- SHA-256 `materialized_content_hash` of that exact string;
- Atlas title, source URI, source type, tags, and provenance;
- positive token estimate;
- normalized coverage keys;
- mandatory flag.

The canonical Neon hash and materialized view hash are deliberately distinct fields. PostgreSQL's `memory_nodes.content_hash` describes the canonical memory node; the materialized hash describes the exact evidence string given to the compiler.

`to_context_evidence()` uses the materialized hash because that is the immutable content inside the context packet, while the result retains the canonical hash for audit.

### 5.4 `ResearchReadStatus`

- `complete`
- `incomplete`
- `no_results`
- `not_routed`

`not_routed` is returned without calling retrieval. The pipeline never bypasses a sparse route merely because it is research-capable.

### 5.5 `ResearchReadResult`

The immutable result contains:

- route decision;
- status;
- reranked candidates;
- materialized evidence;
- optional context packet;
- deterministic retrieval events;
- missing materialization IDs or uncovered coverage keys;
- policy version.

No raw query text is emitted by `to_telemetry_dict()`.

## 6. Ports

### 6.1 `ResearchMetadataProvider`

```python
class ResearchMetadataProvider(Protocol):
    def fetch(
        self,
        *,
        space_id: UUID,
        memory_ids: Sequence[UUID],
    ) -> Mapping[UUID, ResearchMemoryMetadata]: ...
```

A DB-API adapter `NeonResearchMetadataReader` executes one parameterized scoped query.

### 6.2 `ResearchDocumentProvider`

```python
class ResearchDocumentProvider(Protocol):
    def fetch(
        self,
        *,
        space_id: UUID,
        backend_refs: Sequence[str],
        memory_ids: Sequence[UUID],
        active_status: str,
    ) -> Mapping[UUID, ResearchSourceDocument]: ...
```

`MongoResearchDocumentReader` executes one `find` using all of:

```javascript
{
  _id: { $in: backendRefs },
  memory_id: { $in: memoryIds },
  space_id: exactSpace,
  status: activeStatus
}
```

The reader projects only materialization fields and rejects duplicate, missing, unexpected, inactive, malformed, or cross-space documents.

### 6.3 `TokenEstimator`

```python
class TokenEstimator(Protocol):
    def estimate(self, content: str) -> int: ...
```

The pipeline does not guess model tokens. A positive deterministic estimate must be injected by the caller. Tests use a fixed estimator.

## 7. Cross-store materialization invariants

For every reranked candidate chosen for materialization:

1. the hit's `memory_id` must exist exactly once in Neon metadata;
2. the hit's `backend_ref` must identify exactly one Atlas document;
3. both stores must match the request's `space_id`;
4. Atlas `status` must equal the configured active status;
5. Neon expert keys must contain `research`;
6. Atlas `_id`, `memory_id`, `title`, `source_uri`, and tags must match the retrieval hit snapshot;
7. `rag_text` must be non-empty;
8. authority and confidence come only from Neon;
9. the token estimator must return a positive integer;
10. no unexpected row or document may be ignored.

A mismatch raises `ResearchMaterializationError`. It is treated as time-of-check/time-of-use drift or data corruption, not as an empty search.

## 8. Routing and budget governance

### 8.1 Route first

The router executes before retrieval.

If `ExpertKey.RESEARCH` is not selected:

- retrieval, utility, metadata, document, and token ports are not called;
- result status is `not_routed`;
- packet is `None`;
- selected and materialized evidence are empty.

The presence of research in `escalation_experts` does not authorize automatic retrieval in v0. A later evidence-gap controller may issue a new explicit routing decision.

### 8.2 Expert allocation

When research is selected, `RoutingDecision.expert_budgets[ExpertKey.RESEARCH]` is authoritative.

The request is invalid if:

```text
compile_request.usable_evidence_tokens > research expert token allocation
```

The pipeline fails closed with `ResearchReadBudgetError`; it does not silently enlarge the expert allocation or shrink the caller's packet contract.

### 8.3 Retrieval oversampling

`UtilityAwareResearchRetriever` retains ownership of oversampling. The pipeline passes the validated retrieval query unchanged.

## 9. Execution sequence

1. Validate `ResearchReadRequest`.
2. Route with optional routing telemetry sink.
3. Return `not_routed` when research is not selected.
4. Validate compiler evidence budget against the research allocation.
5. Execute utility-aware research search.
6. If no reranked result exists, compile no packet and return `no_results` with all required coverage keys missing.
7. Fetch canonical Neon metadata for exactly the reranked memory UUIDs.
8. Fetch exact Atlas documents for exactly the reranked backend references and UUIDs.
9. Join and validate cross-store identities.
10. Estimate tokens.
11. Derive coverage keys from normalized Atlas tags plus configured aliases.
12. Convert all materialized records to `ContextEvidence`.
13. Compile the packet.
14. Build deterministic retrieval events with:
    - raw Atlas score;
    - utility-reranked final score;
    - materialized token estimate;
    - packet selection flag.
15. Return `complete` or `incomplete` according to the packet.

## 10. Materialization scope and candidate count

V0 materializes every reranked result returned by `UtilityAwareResearchRetriever`, bounded by its configured result limit. This preserves reranker ordering and allows the compiler to explain budget/cap omissions.

A future optimization may materialize progressively, but only after telemetry shows that cross-store reads dominate cost. Progressive materialization must preserve the ability to close coverage gaps and cannot assume top score alone is sufficient.

## 11. Coverage keys

Default coverage keys are normalized Atlas tags:

```text
lowercase
trim whitespace
replace internal whitespace and underscores with hyphens
collapse repeated hyphens
```

`coverage_aliases` may map a source tag to one or more canonical keys. The original normalized tag remains present unless explicitly mapped to an empty set, which is forbidden in v0.

Examples:

```text
credit-assignment → causal-credit
hybrid-retrieval → retrieval
success-failure → outcome-learning
```

The pipeline never uses an LLM to infer coverage.

## 12. Retrieval telemetry

The current retrieval event contract is extended backward-compatibly to accept optional maps:

- final score by memory UUID;
- token estimate by memory UUID;
- selected memory IDs.

Existing callers without these maps preserve prior behavior.

The event identity remains tied to the retrieval hit identity. The pipeline is the single writer after reranking and compilation; it must not first write a raw-only row and then attempt to update immutable telemetry.

Telemetry includes no query text or evidence content.

## 13. Error model

- `ResearchReadValidationError`: mismatched scopes/text/intent/contracts.
- `ResearchReadBudgetError`: compiler evidence budget exceeds router allocation.
- `ResearchMaterializationError`: missing, duplicate, unexpected, inactive, malformed, stale, or cross-store-inconsistent data.
- Backend retrieval/utility exceptions propagate. There is no unscoped or relevance-only fallback.
- Context mandatory overflow propagates `ContextBudgetError`.
- Incomplete coverage is a normal result status, not an exception.

## 14. Testing strategy

### Contract tests

- mismatched scopes;
- mismatched query text;
- missing research intent;
- invalid aliases and duplicate mandatory IDs;
- invalid metadata probabilities, hashes, validity interval, and expert keys.

### Routing tests

- research selected → retrieval called;
- research not selected → every downstream port remains untouched;
- compiler budget exceeding allocation fails before retrieval.

### Cross-store tests

- exact positive join;
- missing Neon metadata;
- missing Atlas document;
- unexpected or duplicate rows;
- backend reference, title, URI, tag, memory, scope, and status drift;
- non-research canonical metadata;
- non-positive token estimate;
- distinct canonical and materialized hashes retained.

### Pipeline tests

- complete packet;
- incomplete coverage;
- no results;
- mandatory evidence;
- utility order retained before compiler selection;
- final retrieval telemetry scores/tokens/selection;
- no query or content in telemetry serialization;
- backend exception propagation.

### Property tests

At least 2,000 deterministic generated cross-store cases verify:

- no downstream call when not routed;
- every materialized UUID was reranked and requested;
- selected packet IDs are a subset of materialized IDs;
- packet budget and scope invariants;
- retrieval event ranks and selection flags;
- deterministic output under mapping/document order permutation.

## 15. Non-goals

V0 does not:

- retrieve non-research experts;
- automatically escalate to another expert;
- write context packet telemetry to Neon;
- infer semantic coverage with an LLM;
- tokenize without an injected estimator;
- summarize evidence;
- repair Atlas/Neon inconsistencies;
- promote or mutate any database schema;
- execute the resulting context packet.

## 16. Success criteria

The pipeline is complete when:

- all contracts are typed and immutable;
- route and budget gates execute before side effects;
- exact live Atlas fields are represented;
- cross-store mismatch always fails closed;
- complete, incomplete, no-results, and not-routed states are explicit;
- utility final scores and compiler selection are represented in immutable retrieval telemetry;
- output is deterministic under backend row order permutation;
- the full suite and property tests pass on Python 3.12 and 3.13;
- no database or default-branch mutation occurs.
