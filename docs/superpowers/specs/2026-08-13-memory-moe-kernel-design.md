# NextGen Memory — Memory-MoE Kernel Design

**Date:** 2026-08-13
**Status:** Approved direction (user delegated architecture decisions)
**Primary objective:** Build a persistent memory substrate for long-horizon LLM agents, initially optimized for software-engineering agents and ChatGPT project continuity, that retains exact evidence while selectively routing only the most useful memory into working context.

## 1. Core thesis

NextGen Memory is not a larger RAG index. It is a **memory operating system with Mixture-of-Memory-Experts routing**.

A conventional RAG answers: *Which chunks are most similar to this query?*

NextGen Memory answers, in order:

1. **Should memory be consulted at all?**
2. **Which memory expert families are eligible for this task, phase, scope and authority level?**
3. **How deep should each expert search?**
4. **Does the task require current state, historical evidence, exact wording, causal history, a procedure, or a failure precedent?**
5. **Which retrieved memories are trustworthy, temporally valid and mutually consistent?**
6. **What is the smallest evidence set that closes the agent's evidence gap?**
7. **After execution, which retrieved memories actually helped or harmed the outcome?**

The system is *eidetic at storage, selective at consciousness*.

## 2. Non-negotiable invariants

### 2.1 Immutable evidence
Raw events, observations, tool outputs, test results, diffs, user instructions and source documents are append-only. No summarization or consolidation may destroy or overwrite the source artifact.

### 2.2 Derived memory never outranks its source automatically
Summaries, facts, hypotheses, rules and skills are separate descendants with explicit `derived_from` lineage. Their authority is capped by their provenance unless independently verified.

### 2.3 Bitemporal memory
Every durable memory can distinguish:
- **event time**: when the underlying event/fact occurred;
- **knowledge time**: when the memory system learned or recorded it.

Current truth is a projection, not an overwrite. Historical states remain recoverable.

### 2.4 Current-state adjudication
The system maintains explicit state slots for facts that have a current value (e.g. active database, current branch policy, present architecture decision). New evidence may supersede or invalidate old state, but old evidence remains historical.

### 2.5 Scope before semantic similarity
Eligibility filters run before vector/lexical similarity. Repository, branch, user, agent, task, permission, validity and authority constraints can make a memory ineligible even if it is semantically similar.

### 2.6 Utility is learned from downstream impact
Every retrieval can receive post-task feedback: helpful, neutral, harmful, stale, incorrect, decisive, redundant. The router learns from actual downstream outcomes rather than assuming similarity equals utility.

### 2.7 Memory can govern actions
High-confidence failure memories and deterministic execution state may intervene before an action is executed (warn, require revalidation, or block under explicit policy). This is separate from passive context injection.

### 2.8 Rollback and reconstruction
Mutable projections must be reconstructible from immutable history. A checkpoint can be rebuilt without trusting an LLM-authored summary as the sole source of truth.

## 3. Memory expert families

The initial expert registry contains twelve experts. They are logical experts; physical storage can evolve independently.

| Expert | Purpose | Default store | Typical trigger |
|---|---|---|---|
| `working` | bounded task-local state | Neon | every active task |
| `execution` | deterministic observations, modifications, commands, tests | Neon | software/tool execution |
| `episodic` | exact past episodes and trajectories | MongoDB | “what happened?”, exact chronology |
| `semantic` | stable facts and abstractions | Hybrid | factual/project knowledge |
| `temporal` | state evolution and time relations | Neon | current-vs-historical questions |
| `causal` | cause/effect and evidence chains | Neon | diagnosis, why/how |
| `procedural` | reusable workflows and skills | Hybrid | recurring tasks |
| `failure` | failed attempts, root causes, recoveries | Hybrid | before risky/repeated actions |
| `decision` | architecture/product/user decisions | Neon | constraint checking |
| `repository` | code entities, dependencies, commit history | Hybrid | software navigation |
| `research` | papers, external sources, research notes | MongoDB | research/design tasks |
| `feedback` | memory/router quality signals | Neon | learning and evaluation |

## 4. Two-plane architecture

### 4.1 Evidence plane
Stores immutable source evidence and derived memory artifacts. It favors recall fidelity, provenance, version history and auditability.

### 4.2 Control plane
Makes decisions about admission, routing, adjudication, context budgets, consolidation, state resolution, quarantine and rollback. It logs every decision so routing policies can later be trained and evaluated.

The control plane must never silently alter the evidence plane.

## 5. Storage architecture

### 5.1 Neon/Postgres — canonical ledger
Neon is the authoritative transaction and metadata store for:
- memory namespaces/scopes;
- source identities and trust classes;
- immutable memory nodes;
- provenance/causal/temporal edges;
- current-state projections plus append-only resolution history;
- expert registry and routing policy configuration;
- router decisions and retrieval traces;
- utility feedback and verification results;
- project checkpoints;
- skill metadata and validation state.

Postgres is chosen for transactional consistency, constraints, relational provenance, temporal queries, auditability and later pgvector/full-text fallback.

### 5.2 MongoDB Atlas — rich payload and episodic store
MongoDB stores large or heterogeneous payloads that should not rigidify the canonical schema:
- raw agent/tool traces;
- long episodic transcripts;
- research documents;
- repository artifacts and extracted structures;
- alternate structured representations;
- multimodal metadata later.

Every MongoDB object carries the canonical Neon `memory_id` when one exists. Neon remains the source of identity and authority.

### 5.3 Temporal — durable memory lifecycle orchestration (phase 2)
Temporal will orchestrate asynchronous/durable flows such as:
- ingest → verify → classify → persist → index;
- episode closure → reflection candidates → verification → consolidation;
- skill promotion/demotion;
- stale-state adjudication;
- reindexing after embedding model changes;
- scheduled memory hygiene and benchmark replay.

Temporal history is workflow durability, not the authoritative semantic memory.

## 6. Memory object model

A canonical memory node is immutable and includes:
- stable UUID;
- namespace/scope;
- source identity;
- kind and layer;
- text and/or structured content;
- event time and knowledge time;
- optional validity interval;
- confidence and authority annotations;
- content hash;
- metadata;
- creation timestamp.

Relationships are separate immutable edges such as:
- `derived_from`
- `supports`
- `contradicts`
- `supersedes`
- `invalidates`
- `causes`
- `part_of`
- `references`
- `validated_by`
- `generalizes`
- `retracts`

Corrections create new nodes/edges; they do not mutate history.

## 7. Write path

1. **Capture** exact evidence.
2. **Classify** source and scope.
3. **Admission routing** decides whether a durable derived memory should be created; raw evidence required by policy is stored regardless.
4. **Verification** checks coverage, preservation, faithfulness and authority.
5. **Type routing** assigns one or more expert families.
6. **Conflict detection** searches potentially affected current-state slots and relevant prior memories.
7. **State adjudication** emits an append-only state-resolution event and updates the rebuildable current projection.
8. **Indexing** updates the appropriate lexical/vector/graph representation.
9. **Deferred consolidation** may produce semantic/procedural descendants only after sufficient evidence.

## 8. Read path: Memory-MoE routing

### Stage A — query/task features
Features include task type, current plan phase, repository/branch, user/agent, requested time horizon, uncertainty, permission scope, evidence gaps, token budget and latency budget.

### Stage B — eligibility mask
Hard constraints remove impossible or unsafe experts/memory shards before semantic scoring.

### Stage C — expert routing
A lightweight router emits a sparse expert distribution. Initial production policy is heuristic + logged features; later policy is learned from router/retrieval outcome data.

A conceptual objective is:

`utility(expert | q) = expected_task_gain - λ_token*token_cost - λ_latency*latency - λ_risk*risk`

### Stage D — expert-local retrieval
Each expert uses the retrieval method suited to its memory:
- deterministic key/state lookup;
- lexical search;
- vector similarity;
- temporal range queries;
- graph traversal;
- episode search;
- skill-trigger matching;
- failure precheck.

### Stage E — evidence arbitration
Candidates are reranked by relevance, temporal validity, provenance, authority, contradiction status, utility history, diversity and marginal information gain.

### Stage F — evidence-gap loop
The controller may choose among `retrieve`, `reflect/reframe`, `escalate`, `verify`, or `answer`. Retrieval ends when evidence coverage is sufficient or the hard budget is exhausted.

### Stage G — context compiler
The LLM receives a compact evidence packet containing only the necessary-and-sufficient context, with memory types and provenance clearly separated from user instructions.

## 9. Learning from success and failure

The system treats task completion as supervision for memory.

For each retrieved memory we record:
- whether it entered final context;
- whether the agent explicitly used it;
- task success/failure;
- reward/utility delta when measurable;
- token and latency cost;
- stale/incorrect/harmful verdicts;
- whether it prevented repeated work or enabled recovery.

Repeated validated experiences can be promoted into procedural skills. A single failure does not become a universal prohibition. Skills must encode trigger conditions, preconditions, procedure, counterexamples and executable validation criteria.

## 10. Software-engineering specialization

NextGen Memory must maintain explicit execution state rather than expecting the LLM to infer current repository state from a transcript.

Software memory will eventually represent:
- file and line observations with staleness after edits;
- file modification state;
- command/test attempts and validity conditions;
- branch/commit identity;
- AST/code entities;
- call/dependency relationships;
- issue/PR/commit history;
- repository decisions and conventions;
- failed fix patterns and verified recoveries.

Plan phase conditions memory retrieval, and memory-derived evidence can trigger replanning.

## 11. Security and governance

- Source provenance is recorded at write time.
- Derived memories preserve ancestry; summarization cannot launder trust.
- External/untrusted memory is distinguishable from user/system-authorized memory.
- Sensitive actions can require trusted evidence independent of retrieved natural-language instructions.
- Memory poisoning and contamination are benchmarked separately from ordinary recall.
- Quarantine is additive: suspect memory remains auditable but is excluded from default retrieval.
- Deletion/retention policies must preserve required audit semantics while respecting user-requested deletion and privacy requirements.

## 12. ChatGPT/mobile continuity profile

For this project, the highest-value immediate feature is a canonical `PROJECT_STATE` checkpoint containing:
- project mission;
- approved architecture;
- infrastructure IDs (non-secret);
- decisions and rejected alternatives;
- current research frontier;
- open hypotheses;
- next actions;
- current schema/version.

A future session should be able to retrieve this compact checkpoint first, then descend to evidence only when necessary.

## 13. Evaluation

NextGen Memory is not successful merely because retrieval recall is high. Evaluation must include:
- task success / SWE-bench style resolution;
- forward transfer across chronological tasks;
- catastrophic/functional forgetting;
- stale-memory usage;
- harmful retrieval rate;
- repeated failed-action rate;
- state reconstruction accuracy;
- provenance/rollback correctness;
- selective forgetting;
- retrieval precision and evidence coverage;
- context tokens per successful task;
- p50/p95 memory latency;
- memory utility calibration;
- memory poisoning persistence/adoption/repair.

## 14. Initial implementation boundary

Phase 1 intentionally does **not** train a neural router or fine-tune an LLM. It establishes the auditable substrate required to collect trustworthy supervision:

1. canonical Neon schema;
2. MongoDB rich-memory collections;
3. initial heuristic Memory-MoE routing policy;
4. project checkpoint capability;
5. routing/retrieval/feedback telemetry;
6. benchmark harness contract.

Once enough interaction data exists, the router can be learned from real `query → expert → evidence → outcome` trajectories.

## 15. Key architectural bet

The differentiator is not any one database or embedding model. It is the closed loop:

**eidetic evidence → sparse memory routing → provenance-aware arbitration → compact context → verified outcome → utility feedback → better routing/consolidation.**

This loop makes memory selection itself a learnable agent capability.
