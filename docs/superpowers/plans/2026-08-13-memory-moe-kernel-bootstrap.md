# Memory-MoE Kernel Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bootstrap the persistent, auditable data substrate for NextGen Memory and make project-state memory retrievable before implementing a learned router.

**Architecture:** Neon/Postgres is the canonical immutable ledger and control-plane store. MongoDB Atlas stores rich episodic/research payloads keyed by canonical memory IDs. Routing starts as a deterministic/heuristic policy whose decisions and outcomes are logged so a learned sparse Memory-MoE router can later replace it without changing memory semantics.

**Tech Stack:** Neon Postgres, MongoDB Atlas, Atlas Search/Vector Search (after data exists), Temporal (phase 2), Python/TypeScript adapter layer (when a repository is mounted), MCP/connectors.

## Global Constraints

- Raw source evidence is append-only and never overwritten by summaries.
- Derived memory must preserve provenance to source evidence.
- Event time and knowledge time must be separately representable.
- Scope and authorization filters run before similarity retrieval.
- Current state is a rebuildable projection, not the authoritative history.
- Every routing/retrieval decision must be observable for later policy learning.
- No learned router is introduced until a trustworthy outcome dataset exists.
- No secret connection strings, passwords, tokens or credentials are written into memory content or user-facing artifacts.

---

### Task 1: Canonical Neon memory ledger

**Interfaces:**
- Consumes: fresh Neon project `NextGen Memory`.
- Produces: schemas/tables/views for namespaces, sources, immutable nodes, immutable edges, state resolutions, expert registry, router decisions, retrieval events, feedback, verifications, skills and checkpoints.

- [ ] **Step 1:** Verify PostgreSQL version and required extensions (`pgcrypto`, optional `vector`) are available.
- [ ] **Step 2:** Prepare the schema migration on a temporary Neon branch.
- [ ] **Step 3:** Verify all required relations, triggers and seed expert rows on the temporary branch.
- [ ] **Step 4:** Confirm immutable-node/edge triggers reject mutation while projection tables remain mutable.
- [ ] **Step 5:** Apply the verified migration to the main branch only through Neon's migration completion flow.
- [ ] **Step 6:** Re-query schema metadata and expert registry to establish fresh evidence of success.

### Task 2: MongoDB episodic payload substrate

**Interfaces:**
- Consumes: Atlas project `NextGen Memory` and canonical memory UUIDs from Neon.
- Produces: collections for rich memory payloads and later expert-specific search indexes.

- [ ] **Step 1:** Wait for/verify the free Atlas cluster is ready and obtain an MCP connection.
- [ ] **Step 2:** Create database `nextgen_memory` with initial collections `memory_objects`, `raw_traces`, `research_sources`, and `repository_artifacts`.
- [ ] **Step 3:** Insert one non-sensitive bootstrap document describing collection contracts and canonical-Neon-ID linkage.
- [ ] **Step 4:** Inspect collection schemas/data before proposing search indexes.
- [ ] **Step 5:** Create lexical/vector indexes only after index design is reviewed against actual payload fields and embedding strategy.

### Task 3: Project continuity checkpoint

**Interfaces:**
- Consumes: canonical Neon ledger.
- Produces: a durable `PROJECT_STATE` memory/checkpoint for NextGen Memory.

- [ ] **Step 1:** Create a project namespace and source principals for user, assistant, verified-runtime, external-research and derived-memory origins.
- [ ] **Step 2:** Store immutable memories for the project mission, approved Memory-MoE architecture, database provisioning decisions and current research findings.
- [ ] **Step 3:** Create provenance edges from derived architecture conclusions to their underlying research/decision nodes.
- [ ] **Step 4:** Store a compact project checkpoint with open hypotheses and next actions.
- [ ] **Step 5:** Query the latest checkpoint plus its provenance to prove that a future session can reconstruct state without relying on chat transcript alone.

### Task 4: Initial Memory-MoE routing contract

**Interfaces:**
- Consumes: expert registry and project checkpoint.
- Produces: stable router input/output schema suitable for heuristic routing today and learned routing later.

- [ ] **Step 1:** Define router input features: scope, task kind, plan phase, temporal intent, exactness need, authority requirement, uncertainty, token budget and latency budget.
- [ ] **Step 2:** Define sparse router output: eligible experts, selected experts, per-expert budgets, escalation policy, justification and confidence.
- [ ] **Step 3:** Define hard eligibility masks independent of semantic relevance.
- [ ] **Step 4:** Define deterministic initial rules for software-engineering and research tasks.
- [ ] **Step 5:** Persist every routing decision and retrieval result in Neon so supervised labels can be reconstructed from outcomes.

### Task 5: Utility and state-adjudication feedback loop

**Interfaces:**
- Consumes: router decisions, retrieval events, task outcomes and new memory writes.
- Produces: calibrated memory utility and explicit current-state resolutions.

- [ ] **Step 1:** Record per-memory post-task feedback (helpful/neutral/harmful/stale/incorrect plus reward/cost signals).
- [ ] **Step 2:** Implement current-state slots as a mutable cache backed by append-only resolution events.
- [ ] **Step 3:** Define conflict outcomes `KEEP`, `SUPERSEDE`, `INVALIDATE`, `UNKNOWN`, `QUARANTINE` without mutating old evidence.
- [ ] **Step 4:** Add aggregate views for memory utility and router/expert performance.
- [ ] **Step 5:** Test reconstruction of current state after replaying resolution events.

### Task 6: Durable lifecycle orchestration (phase 2)

**Interfaces:**
- Consumes: stable write/read contracts from Tasks 1–5.
- Produces: Temporal workflows for ingestion, verification, consolidation, stale-state checks and reindexing.

- [ ] **Step 1:** Define deterministic workflow boundaries and side-effecting activities.
- [ ] **Step 2:** Implement ingest → verify → persist → index workflow with idempotency keys.
- [ ] **Step 3:** Implement deferred consolidation workflow that creates descendants rather than overwriting sources.
- [ ] **Step 4:** Implement retry/compensation behavior for partial Neon/Mongo failures.
- [ ] **Step 5:** Verify replay determinism and crash recovery.

### Task 7: Learned router research phase

**Interfaces:**
- Consumes: accumulated `query → routing → retrieval → outcome` telemetry.
- Produces: offline router dataset and first cost-sensitive sparse routing model.

- [ ] **Step 1:** Define gold expert labels from evidence actually used in successful outcomes.
- [ ] **Step 2:** Add negative labels from harmful/noisy retrievals and ineligible-scope examples.
- [ ] **Step 3:** Train a lightweight classifier/router before considering an autoregressive LLM router.
- [ ] **Step 4:** Optimize a cost-sensitive objective balancing task gain, token cost, latency and risk.
- [ ] **Step 5:** Evaluate against uniform retrieval, top-k RAG, fixed routing and oracle routing.
- [ ] **Step 6:** Deploy only if it improves quality without violating scope/authority invariants.

### Task 8: SWE specialization and memory-as-governance

**Interfaces:**
- Consumes: agent execution/tool traces and repository state.
- Produces: deterministic execution ledger and pre-action failure checks.

- [ ] **Step 1:** Track observed file spans, edits, commands and tests with validity/staleness conditions.
- [ ] **Step 2:** Add repository memory from AST/dependency/commit structures.
- [ ] **Step 3:** Retrieve memory conditioned on plan phase/subtask rather than issue text alone.
- [ ] **Step 4:** Add a conservative pre-action gate for repeated verified failures and stale observations.
- [ ] **Step 5:** Benchmark repeated-action rate, context exhaustion, resolution rate and cost.

## Self-review

- Spec coverage: all core invariants, storage roles, routing telemetry, project continuity, utility feedback, Temporal lifecycle, learned routing and SWE specialization are represented.
- Placeholder scan: no unresolved placeholder markers remain.
- Dependency order: canonical ledger precedes payload storage and checkpoints; telemetry precedes learned routing; stable contracts precede Temporal orchestration and SWE governance.
- Current limitation: no application repository is mounted in this ChatGPT environment, so code-file-specific tasks and commits cannot be specified yet. Database and connector bootstrap can proceed independently; adapter implementation will require a repository/workspace later.
