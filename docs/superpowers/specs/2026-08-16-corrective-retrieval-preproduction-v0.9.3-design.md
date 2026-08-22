# Corrective Retrieval Preproduction Harness v0.9.3 Design

**Date:** 2026-08-16  
**Status:** Approved direction; written specification pending owner review  
**Base:** `feat/context-compiler-integrated-v0` at `d68fa8f884bc1d88a24b2e1785f9d61e1f276fcf`  
**Branch:** `feat/corrective-retrieval-preproduction-v0.9.3`

## 1. Goal

Corrective Retrieval Preproduction Harness v0.9.3 validates the real retrieval boundary that will later serve gap-aware corrective retrieval. It must prove, before durable orchestration or production writes, that a planned micro-retrieval can be executed against the live Atlas topology without scope leakage, unsafe fallback, unbounded embedding retries, score-scale confusion, or evidence-identity drift.

The harness is deliberately narrower than a production controller. It is a read-only, auditable execution substrate for:

- capability discovery;
- search/vector index contract verification;
- static pipeline scope auditing;
- opt-in live `explain()` probes;
- retrieval failure classification;
- rate-budget-aware retry directives;
- exact evidence materialization by canonical backend reference;
- privacy-safe execution evidence;
- deterministic fake-backend stress tests.

It does **not** persist packets, hits, raw queries, vectors, search payloads, or execution traces.

## 2. Verified starting point

The base Context Compiler has been reverified after removing a duplicate implementation stack and a Python module/package collision. The final base CI is green on Python 3.12 and 3.13 with 296 tests and Ruff.

The live Atlas research collection currently exposes:

- one canonical project scope;
- active research documents;
- `rag_lexical_v2` as the scope-filter-ready lexical index;
- `rag_autoembed_v1` as the automated-embedding vector index using `voyage-4-lite`;
- filterable `space_id`, `status`, and `source_type` metadata on the active retrieval indexes;
- `_id_` as the exact materialization index.

A live read-only hybrid `explain()` using `$rankFusion`, `$vectorSearch`, and `$search` succeeded with `space_id` and `status` inside each ranking branch. A subsequent embedding-bearing query hit the automated-embedding provider rate limit. Exact materialization by `_id` used the `_id_` index with one key and one document examined in the observed sample.

These observations are **audit evidence**, not assumptions that the same capabilities exist on another cluster.

## 3. Research and platform constraints

Current MongoDB documentation establishes several important boundaries:

- `$rankFusion` is a MongoDB 8.x feature, but support details vary by minor version and deployment state;
- `$scoreFusion` requires a newer server than the current live 8.0.x cluster;
- native `$rerank` requires MongoDB 8.3+ and is disabled by default;
- automated embedding produces embeddings at query time for `$vectorSearch` text queries;
- the free automated-embedding query allowance for `voyage-4-lite` is rate-limited by both requests per minute and tokens per minute;
- exceeding the embedding provider budget is an explicit failure, not a signal to silently weaken retrieval semantics.

Because version documentation and managed-feature availability can differ at feature boundaries, v0.9.3 uses **probe-first capabilities**: version checks establish conservative bounds, while a specific pipeline shape is enabled only when the configured capability evidence says it is supported or an opt-in read-only probe succeeds.

## 4. Approaches considered

### 4.1 Generic multi-provider execution framework first

A provider-neutral executor would make later migration easier, but it would expand scope before the Atlas retrieval contract is proven. It would also obscure real Atlas failure modes behind an abstraction too early.

**Rejected for v0.9.3.**

### 4.2 Atlas-first preproduction harness — selected

Build a small backend protocol but model the first concrete capability profile around the live Atlas research path. Keep execution injectable so tests need no MongoDB runtime dependency.

Advantages:

- exercises the real current indexes and pipeline semantics;
- keeps CI deterministic and offline;
- isolates Atlas-specific capabilities from the compiler and gap controller;
- produces supervision-quality failure evidence before production orchestration.

### 4.3 Temporal orchestration now

Durable retries and schedules are useful later, but they would turn an uncalibrated retrieval boundary into durable behavior before rate limits, capability gates, materialization, and privacy contracts are stable.

**Deferred.**

## 5. Architecture

```text
CorrectiveQuerySpec / retrieval intent
    ↓
RetrievalCapabilityProfile
    ↓
RetrievalPipelinePreflight
    ↓
RetrievalExecutionPlan
    ↓
backend adapter (fake in CI / Atlas in opt-in audit)
    ↓
RetrievalAttemptResult
    ↓
FailureClassifier + RetryDirective
    ↓
CanonicalHitGate
    ↓
ExactResearchMaterializer
    ↓
verified evidence candidate
    ↓
Integrated Context Compiler / corrective controller
```

The compiler remains unaware of Atlas versions, rate limits, search stages, and provider errors.

## 6. `RetrievalCapabilityProfile`

Immutable fields:

```text
profile_id
server_version
cluster_fingerprint
lexical_index_name
vector_index_name
lexical_index_fingerprint
vector_index_fingerprint
lexical_ready
vector_ready
rank_fusion_supported
score_fusion_supported
native_rerank_supported
native_rerank_enabled
auto_embedding_enabled
embedding_model
embedding_query_rpm
embedding_query_tpm
capability_evidence_hash
```

Rules:

- no capability is inferred from a name alone;
- index readiness is required before plan admission;
- `score_fusion_supported=False` on the current 8.0.x live profile;
- `native_rerank_supported=False` on the current profile;
- a successful live probe may authorize a pipeline shape that the profile explicitly records, but the authorization is bound to the cluster/index fingerprints;
- capability evidence never contains credentials, hostnames, connection strings, raw queries, or raw index payloads.

## 7. `RetrievalPipelinePreflight`

The preflight is a pure static auditor over a JSON-like pipeline.

### 7.1 Lexical branch

For every `$search` branch used for corrective retrieval, verify before execution:

```text
index == configured lexical corrective index
compound.filter contains exact space_id equality
compound.filter contains status == active
source_type filter matches policy when required
per-branch result limit is bounded
```

### 7.2 Vector branch

For every `$vectorSearch` branch:

```text
index == configured vector corrective index
path == configured vector path
filter contains exact space_id equality
filter contains status == active
source_type filter matches policy when required
numCandidates is positive and bounded
limit is positive and bounded
```

### 7.3 Fusion

- all input branches must pass their own scope audit before fusion;
- every branch must be explicitly bounded;
- `$rankFusion` is permitted only when the capability profile authorizes the exact pipeline family;
- `$scoreFusion` is rejected when unsupported;
- `$rerank` is rejected when unsupported or disabled;
- `rag_lexical_v1` is never an implicit fallback for corrective retrieval;
- unknown ranking stages fail closed.

A pipeline that applies `space_id` only **after** `$search`, `$vectorSearch`, or fusion fails preflight.

## 8. Retrieval modes and score calibration

V0.9.3 does not define one global numerical score threshold.

Reason: lexical search scores, reciprocal-rank-fusion scores, score-fusion outputs, and future reranking scores occupy different scales and semantics.

Admission therefore uses mode-aware evidence:

### Lexical

- bounded rank;
- positive finite provider score when available;
- gap-closure compatibility;
- authority/confidence/lifecycle gates downstream.

### Hybrid rank fusion

- bounded fused rank;
- finite fusion score if supplied;
- branch participation metadata reduced to privacy-safe booleans/counts;
- no lexical-score threshold copied onto RRF.

### Future score fusion / rerank

Disabled until an explicitly calibrated capability profile and evaluation tranche approves them.

Raw provider score details are not persisted by the harness.

## 9. Embedding rate-budget guard

Automated embedding is treated as a scarce external capability.

`EmbeddingBudgetGuard` receives an immutable policy snapshot:

```text
model
rpm_limit
tpm_limit
window_seconds
known_attempt_timestamps
known_token_estimates
```

It produces only:

```text
allowed
reason
remaining_request_budget
remaining_token_budget
not_before_time / retry_after_seconds
```

Rules:

- no immediate retry loop after provider rate limiting;
- no sleep inside the pure controller;
- rate-limit failure produces a structured retry directive for a caller to schedule later;
- lexical-only fallback after a failed hybrid/vector plan is forbidden unless the original plan explicitly declared lexical-only semantics;
- an embedding-bearing live `explain()` is conservatively accounted as a query-embedding attempt by the preproduction harness because the observed live path can consume provider capacity;
- local tests use a deterministic virtual clock, never wall-clock sleeps.

## 10. Failure taxonomy

```text
success
rate_limited
unsupported_capability
index_unavailable
scope_violation
invalid_pipeline
invalid_query
provider_transient
provider_permanent
materialization_missing
materialization_identity_mismatch
materialization_scope_mismatch
materialization_inactive
materialization_source_type_mismatch
```

Retry policy:

- `rate_limited` → no immediate retry; return not-before directive;
- `provider_transient` → caller may retry only within configured bounded attempt count;
- all capability, scope, pipeline, identity, inactive, and permanent failures → terminal;
- terminal failures never trigger a different retrieval mode implicitly.

## 11. `RetrievalExecutionPlan`

Privacy-safe immutable contract:

```text
plan_id
space_id
mode
query_fingerprint
semantic_fingerprint
pipeline_hash
capability_profile_id
index_fingerprints
max_results
max_attempts
embedding_token_estimate
created_for_gap_key
```

The executable raw query text and vector are transient adapter inputs and are deliberately excluded from `repr`, audit JSON, plan identity, database telemetry, and error records.

`plan_id` is a deterministic UUID5 bound to the full privacy-safe executable policy, including capability and pipeline hashes.

## 12. `RetrievalAttemptResult` and privacy-safe telemetry

Allowed fields:

```text
plan_id
attempt_number
mode
outcome
failure_class
query_fingerprint
pipeline_hash
capability_profile_id
index_fingerprints
returned_count
admitted_count
duration_bucket
retry_after_seconds
provider_status_class
```

Forbidden fields:

```text
raw query text
embedding vector
prompt or answer
memory content
title
source URI
provider error body
scoreDetails payload
credentials
hostnames
connection strings
```

Provider errors are mapped to a bounded enum plus status class before leaving the adapter boundary.

## 13. Canonical hit gate

Before materialization, each hit must satisfy:

- exact plan ID/query fingerprint association;
- `space_id` equality;
- `status=active`;
- allowed source type;
- unique canonical `memory_id`;
- unique `backend_ref`;
- bounded rank;
- finite mode-appropriate score when score exists;
- no already-selected memory/content/source exclusion violation;
- declared compatibility with the target gap.

A result batch with impossible duplicate rank/identity accounting fails closed rather than silently deduplicating evidence from different canonical identities.

## 14. Exact research materialization

The preferred live materialization key is the canonical `backend_ref` mapped to MongoDB `_id`.

Materialization procedure:

```text
find exact _id
→ require one document
→ verify memory_id
→ verify space_id
→ verify status == active
→ verify source_type
→ verify immutable retrieval metadata
→ materialize exact text only after all gates pass
```

The live `_id_` index is sufficient for this path; v0.9.3 does not add a `memory_id` production index.

If the returned document disagrees with the hit metadata, the evidence is rejected even when the text itself looks useful.

## 15. Opt-in live Atlas audit

CI never contacts Atlas.

A separate read-only script may be run manually/through a trusted connector:

```text
1. read server and index capability metadata
2. fingerprint capability profile
3. static-audit one canonical lexical pipeline
4. run read-only explain
5. if embedding budget permits, static-audit one canonical hybrid pipeline
6. run one read-only explain
7. materialize one known backend_ref through _id
8. emit canonical privacy-safe JSON evidence
```

The script must stop rather than exceed configured embedding request/token budget.

It performs no insert, update, index mutation, schema change, or telemetry persistence.

## 16. Testing

### 16.1 Capability matrix

Test profiles representing:

- current Atlas 8.0.x profile;
- future profile with score fusion;
- future profile with native rerank supported but disabled;
- future profile with rerank enabled;
- missing/changed index fingerprints.

### 16.2 Static pipeline mutation tests

Starting from one valid pipeline, systematically mutate:

- remove `space_id` from one branch;
- move scope filter after ranking;
- remove active status;
- use legacy lexical index;
- remove branch limit;
- use unsupported fusion/rerank stage;
- change vector path/index;
- insert unknown branch stage.

Every unsafe mutant must be rejected.

### 16.3 Failure-state stress

At least 10,000 deterministic fake-backend sequences spanning:

```text
success
rate limit
transient provider failure
permanent provider failure
index unavailable
scope mismatch
materialization mismatch
```

Verify:

- no unbounded attempt loop;
- no mode fallback unless planned;
- deterministic retry directive;
- zero scope leaks;
- zero terminal-error retries;
- identical canonical audit JSON under repeated runs.

### 16.4 Materialization tests

Verify exact `_id` lookup contract and every identity/scope/lifecycle mismatch independently.

### 16.5 Privacy tests

Inject raw queries, vectors, titles, URIs, command-like text, connection-string-looking values, and provider error bodies at adapter inputs. None may appear in audit JSON or exception strings.

## 17. Acceptance criteria

V0.9.3 is complete when:

1. the base Context Compiler remains green and unchanged semantically;
2. all corrective retrieval pipelines are statically scope-audited before execution;
3. unsupported capabilities fail before backend execution;
4. rate-limited embedding attempts cannot create immediate retry loops;
5. no implicit lexical fallback exists after hybrid/vector failure;
6. exact materialization verifies `_id`, memory identity, scope, active status, and source type;
7. no single global score threshold is shared across lexical and fusion modes;
8. audit contracts contain no raw query/vector/content/provider payload;
9. 10,000 fake-backend failure sequences pass deterministically;
10. opt-in live Atlas `explain()` evidence passes for the current capability profile without writes;
11. Ruff and the complete repository suite pass on Python 3.12 and 3.13;
12. no merge, schema mutation, index mutation, feedback write, packet persistence, or durable orchestration occurs.

## 18. Non-goals

V0.9.3 does not:

- implement the full gap detector from the isolated v0.9.1 prototype;
- persist corrective telemetry;
- execute Temporal workflows;
- auto-upgrade MongoDB;
- enable `$scoreFusion` or `$rerank` on the current live cluster;
- learn score thresholds;
- sleep/retry in background;
- call an LLM to rewrite micro-queries;
- create or alter Atlas indexes;
- expose provider error payloads to downstream agents.

## 19. Next tranche after verification

After this harness is green, the project may safely implement the production-facing corrective controller adapter:

```text
Context packet
→ gap detector
→ corrective plan
→ preproduction-proven retrieval boundary
→ exact materialization
→ recompilation under original budget
→ strict accept/reject
```

Durable Temporal orchestration comes only after that controller has deterministic retry and privacy telemetry contracts.