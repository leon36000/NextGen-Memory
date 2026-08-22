# Memory-MoE Router v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a zero-dependency, typed Python kernel that applies hard scope masks before sparse deterministic memory-expert routing and records every routing decision.

**Architecture:** The domain layer defines stable request, scope, expert, candidate, and decision contracts. A pure eligibility evaluator rejects out-of-scope or insufficient-authority memories before any relevance scoring. A deterministic router selects a bounded expert set from explicit task features and evidence needs, allocates token budgets, emits an evidence-gap escalation order, and records the decision through a pluggable telemetry port.

**Tech Stack:** Python 3.12+, standard library dataclasses/enums/protocols, pytest, Ruff, Neon SQL migrations, GitHub Actions.

## Global Constraints

- The core package has no mandatory third-party runtime dependencies.
- Scope, permissions, sensitivity, validity, quarantine, and authority checks run before semantic retrieval.
- `feedback` is not injected into ordinary answer context.
- Selected experts are always a subset of eligible experts.
- Per-expert budgets never exceed their hard maximum and total allocated tokens never exceed the request budget.
- Every route decision is serializable and recordable.
- Migration files contain no secrets or environment-specific credentials.

---

### Task 1: Repository and migration contracts

**Files:**
- Create: `pyproject.toml`
- Create: `migrations/neon/0001_memory_moe_kernel.sql`
- Create: `migrations/neon/0002_core_idempotency.sql`
- Create: `migrations/mongodb/README.md`
- Test: `tests/test_migration_contract.py`

**Interfaces:**
- Consumes: verified live Neon schema 0.1.1 and Atlas collection contracts.
- Produces: reproducible, parser-safe schema artifacts matching the deployed bootstrap state.

- [ ] Write migration contract tests before adding migration files.
- [ ] Verify tests fail because migrations are absent.
- [ ] Add parser-safe SQL with composite scope constraints, immutable evidence triggers, twelve expert seeds, and core idempotency indexes.
- [ ] Run focused migration contract tests and confirm they pass.

### Task 2: Typed domain contracts

**Files:**
- Create: `src/nextgen_memory/__init__.py`
- Create: `src/nextgen_memory/domain.py`
- Test: `tests/test_domain.py`

**Interfaces:**
- Produces: `RoutingRequest`, `RoutingScope`, `RoutingDecision`, `MemoryCandidate`, enums for experts/tasks/phases/evidence needs, and validation invariants.

- [ ] Write failing tests for empty queries, invalid budgets, confidence ranges, subset rules, and serialization.
- [ ] Run tests and confirm failure due to missing domain module.
- [ ] Implement minimal frozen dataclasses and enums.
- [ ] Run focused tests and confirm success.

### Task 3: Hard eligibility evaluator

**Files:**
- Create: `src/nextgen_memory/eligibility.py`
- Test: `tests/test_eligibility.py`

**Interfaces:**
- Consumes: `RoutingRequest`, `MemoryCandidate`.
- Produces: `EligibilityResult` and `evaluate_candidate_eligibility(request, candidate, at=None)`.

- [ ] Write failing tests for scope, repository, branch, principal, permission, sensitivity, authority, validity, and quarantine rejection.
- [ ] Run tests and confirm failure because evaluator is absent.
- [ ] Implement deterministic fail-closed eligibility checks.
- [ ] Run focused tests and confirm success.

### Task 4: Deterministic sparse Memory-MoE router

**Files:**
- Create: `src/nextgen_memory/router.py`
- Create: `src/nextgen_memory/telemetry.py`
- Test: `tests/test_router.py`

**Interfaces:**
- Consumes: `RoutingRequest` plus static expert profiles.
- Produces: `DeterministicMemoryRouter.route(request, sink=None) -> RoutingDecision` and `RoutingDecisionSink.record(decision)`.

- [ ] Write failing tests for SWE diagnosis, risky edits, research, project continuity, exact historical recall, low token budgets, ineligible repository routing, and telemetry recording.
- [ ] Run tests and confirm failure because router is absent.
- [ ] Implement expert scoring, eligibility masking, sparse selection, bounded allocation, confidence, reasons, and escalation order.
- [ ] Run focused tests and confirm success.

### Task 5: Package documentation and CI

**Files:**
- Modify: `README.md`
- Create: `.github/workflows/ci.yml`
- Create: `docs/router-v0.md`

**Interfaces:**
- Produces: install/test instructions, routing contract documentation, and automated Python 3.12/3.13 checks.

- [ ] Document the exact route input/output and non-goals.
- [ ] Add CI for `ruff check` and `pytest`.
- [ ] Run `python -m pytest -q` and `ruff check .` locally.
- [ ] Review the complete diff for secrets and accidental scope expansion.
