# NextGen Memory — Architecture and Stable Contracts

This file is the compact source of truth for stable repository boundaries and invariants. It deliberately excludes current task state, temporary branches/worktrees, one-off test counts, live service observations, and unmerged review findings; those belong in project checkpoint memory.

## 1. Authority order

Use this order when recovering or reviewing the project:

1. Source code and executable tests define current behavior.
2. `src/nextgen_memory/__init__.py` defines the supported package-root API.
3. `migrations/` defines durable storage contracts.
4. This document defines stable architectural boundaries and invariants.
5. Subsystem docs explain algorithms and detailed contracts.
6. `docs/superpowers/specs/` and `docs/superpowers/plans/` preserve dated design rationale and implementation intent; they are not proof of current completion.
7. Project checkpoint memory carries current development state and must be reconciled with Git.

## 2. System boundary

NextGen Memory is an experimental Memory-Mixture-of-Experts kernel for long-horizon LLM agents. Its core principle is to preserve exact evidence while selectively recalling only the memory experts and evidence required for the current task.

The architecture separates three planes:

- **Neon/Postgres:** canonical identity, structured ledger/state, provenance, routing/retrieval telemetry, aggregate utility, feedback, and project checkpoints.
- **MongoDB Atlas:** rich episodic/research/repository payloads and retrieval representations linked to canonical identities.
- **Python kernel:** typed contracts and deterministic routing, eligibility, retrieval, reranking, context compilation, and credit logic.

Durable workflow orchestration is a planned layer. Introducing or expanding it should be accompanied by explicit lifecycle, retry, persistence, privacy, and identity contracts plus verification appropriate to the change.

## 3. Stable subsystem map

### Routing and eligibility

Sources: `src/nextgen_memory/domain.py`, `src/nextgen_memory/eligibility.py`, `src/nextgen_memory/router.py`, `src/nextgen_memory/telemetry.py`.

Responsibilities: immutable routing/scope contracts, fail-closed candidate eligibility, deterministic sparse expert selection/allocation, and safe routing telemetry.

### Research retrieval

Sources: `src/nextgen_memory/retrieval.py`, `src/nextgen_memory/mongodb_retrieval.py`, `src/nextgen_memory/retrieval_telemetry.py`.

Responsibilities: immutable research query/hit contracts, scoped Atlas hybrid retrieval, dependency-injected retrieval, deterministic retrieval-event identities, and preservation of retrieval privacy boundaries.

### Utility-aware reranking

Sources: `src/nextgen_memory/neon_utility.py`, `src/nextgen_memory/utility_reranker.py`.

Responsibilities: scoped aggregate utility reads and deterministic evidence-shrunk reranking. Missing feedback remains neutral; backend failure is not a reason to silently weaken ranking semantics.

### Direct causal credit

Sources: `src/nextgen_memory/causal_credit.py`, `src/nextgen_memory/credit_targets.py`, `src/nextgen_memory/causal_feedback.py`.

Responsibilities: matched intervention/ablation attribution, uncertainty gates, abstention, selected-and-used targeting, deterministic feedback identity, and conflict verification.

### Interaction and dependency-aware credit

Sources: `src/nextgen_memory/interaction_credit.py`, `src/nextgen_memory/interaction_planner.py`, `src/nextgen_memory/pairwise_interactions.py`.

Responsibilities: dependency-closed coalitions, precedence-constrained allocation, deterministic bounded evaluation planning, and separate synergy/redundancy diagnostics. Allocated credit must close to measured bundle value.

### Provenance credit

Source: `src/nextgen_memory/provenance_credit.py`.

Propagation is conservative and policy-gated. The existence of implementation code does not imply unrestricted automatic propagation is production-approved.

### Integrated context compiler

Sources: `src/nextgen_memory/context_compiler_contracts.py`, `src/nextgen_memory/context_objective.py`, `src/nextgen_memory/context_exact_solver.py`, `src/nextgen_memory/context_heuristic_solver.py`, `src/nextgen_memory/context_compiler.py`.

Responsibilities: immutable compile contracts, canonicalization/deduplication, prerequisite closure, exact or deterministic heuristic selection, omission classification, and deterministic packet identity/rendering. Retrieved evidence remains data; compilation does not silently rewrite accepted evidence.

### Corrective retrieval

`src/nextgen_memory/corrective_retrieval_contracts.py` is an internal module containing canonical identity and immutable/transient contracts for corrective retrieval work. Its presence does not make corrective retrieval a supported package-root API.

Detailed corrective design and implementation sequencing live in the dated documents under `docs/superpowers/`. Current readiness, active task status, and review findings must come from Git, executable tests, and project checkpoint evidence rather than from this stable architecture document.

## 4. Cross-cutting invariants

### Fail closed before usefulness

Invalid scope, permission, lifecycle, sensitivity, temporal validity, quarantine, identity, capability, or malformed safety-critical structure must be rejected before semantic usefulness can override it.

### Retrieval scope is structural

Scope, active status, and required source-type constraints belong inside the ranking/pre-filter boundary. A later filter may narrow an already safe result set but cannot repair an unsafe ranking stage.

### No implicit semantic fallback

A backend/capability/mode failure must not silently switch to an unplanned weaker retrieval mode, legacy index, or evidence-free behavior. Any supported fallback must be explicit in its contract and preserve the required safety boundaries.

### Deterministic identity

- Deterministic identities use explicit canonical payloads.
- Unsupported or ambiguous values fail closed instead of relying on arbitrary string conversion.
- Non-finite numbers are rejected at deterministic numeric boundaries.
- Execution-order sequences retain order; normalization is used only where a contract explicitly declares set semantics.
- Validation and hashing/execution must refer to the same effective value; mutable aliases must not allow one value to be validated and another to be used.
- Equal inputs require deterministic tie-breaking and ordering.

### Privacy and persistence boundaries

Privacy-safe audit, telemetry, and error objects are built from explicit allowlists. Runtime payloads remain transient unless a narrow storage contract explicitly allows them.

Neon is the canonical structured authority; MongoDB holds rich linked payloads. Read-only/preproduction components must not acquire durable write behavior accidentally; any new write path requires an explicit contract and verification gate.

### Evidence correction is non-destructive

History and provenance must remain explainable. Corrections, supersession, invalidation, adjudication, and feedback should preserve the evidence needed to reconstruct how current state was reached.

## 5. Public API and compatibility

The supported package-root API is the `__all__` surface in `src/nextgen_memory/__init__.py`. A module existing in the repository is not automatically a stable root API.

Unless a change explicitly revises a contract and provides regression/migration evidence, preserve:

- established package-root exports;
- research retrieval query/hit and Mongo retriever/builder behavior;
- retrieval telemetry semantics;
- deterministic router identities and ordering;
- canonical storage identity and append-only/idempotency guarantees;
- context packet identity and omission semantics;
- causal/interaction abstention and value-closure rules.

When an internal module becomes a supported package-root API, update `src/nextgen_memory/__init__.py`, regression coverage, and this document in the same reviewed change.

## 6. Verification model

The configured GitHub Actions workflow tests Python 3.12 and 3.13 and runs:

```bash
ruff check .
python -m pytest -q
```

The default test workflow does not invoke live storage/search probes. Package installation may still use network access in CI.

During development, run focused tests first and then repository-wide checks before integration. `git diff --check` is an additional local acceptance check. Live storage/search validation is separate, explicitly authorized, and must be treated as timestamped evidence rather than a permanent capability guarantee.

## 7. Documentation taxonomy

- `README.md`: mission, onboarding, broad architecture and repository map.
- `docs/architecture-and-contracts.md`: stable architectural source of truth.
- `AGENTS.md`: repository-local recovery/development rules.
- `docs/*-v*.md`: detailed subsystem contracts and research results.
- `docs/superpowers/specs/`: dated designs.
- `docs/superpowers/plans/`: dated task plans.
- Tests and migrations: executable/persistent contracts.
- Project checkpoint memory: active task, SHAs, review/test evidence, current risks and exact next action.

Update this file whenever a supported cross-subsystem boundary, public API, durable schema, or stable safety/privacy invariant changes. Do not turn it into a current-task log.
