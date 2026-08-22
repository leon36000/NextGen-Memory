# Provenance Credit v0 Implementation Plan

> **For agentic workers:** use test-driven development. Every production slice must follow an observed RED failure, minimal GREEN implementation, and fresh broad verification.

**Goal:** Propagate a bounded fraction of intervention-grounded direct memory credit through explicitly typed provenance relations without creating mass, leaking blame, or confusing inherited structural support with direct causal evidence.

**Architecture:** A standalone `provenance_credit.py` module defines immutable graph, policy, direct-evidence, result, and propagation contracts. A selector resolves interaction-vs-causal direct evidence. A conservative propagator validates the policy-oriented DAG for each sign, applies hard node gates, splits one fixed budget by typed edge weights, retains mass at reached nodes, and reports blocked/dropped/unallocated mass. No persistence is introduced.

**Tech stack:** Python 3.12+ standard library dataclasses/enums/hashlib/json/protocol-free pure functions, pytest, Ruff, GitHub Actions.

## Global constraints

- Unknown or blocked relations never propagate.
- Positive propagation is allowed only by explicit policy.
- Negative propagation is disabled by default and requires local attribution evidence when enabled.
- Direct and inherited credit remain separate.
- Interaction credit wins over causal credit within the same evidence group; values are never summed.
- Branches redistribute a fixed budget and cannot create mass.
- Unauthorized, invalid, cross-space, cyclic, or malformed graphs fail closed.
- No raw content or database write is introduced.

---

### Task 1 — Immutable contracts and canonical graph

**Files:**
- Create: `tests/test_provenance_credit.py`
- Create after RED: `src/nextgen_memory/provenance_credit.py`

- [ ] Write failing tests for node, edge, policy, direct evidence, configuration, and graph validation.
- [ ] Run focused tests and record RED because `nextgen_memory.provenance_credit` is absent.
- [ ] Implement enums, errors, frozen dataclasses, canonical ordering, same-space checks, and immutable collections.
- [ ] Verify focused GREEN.

### Task 2 — Direct evidence selection

- [ ] Write failing tests for interaction-over-causal precedence, exact duplicate deduplication, same-priority conflict rejection, and stable ordering.
- [ ] Implement `select_preferred_direct_credits`.
- [ ] Verify direct evidence is never added or averaged across sources.

### Task 3 — Typed positive propagation

- [ ] Write failing tests for `supported_by`, blocked relations, leaf retention, depth retention, and exact path evidence.
- [ ] Implement oriented adjacency from explicit policies.
- [ ] Implement weighted budget splitting and path-level retained contributions.
- [ ] Verify no direct root receives inherited credit.

### Task 4 — Mass conservation and convergence

- [ ] Write failing tests for branches, unequal edge weights, converging paths, floor dropping, root unallocation, and conservation residual.
- [ ] Implement per-direct `PropagationMassLedger` and result invariants.
- [ ] Keep converging paths separate; add conservative target summaries without assuming path independence.

### Task 5 — Hard gates, cycles, and negative credit

- [ ] Write failing tests for unauthorized/invalid targets, cross-space edges, oriented cycles, disabled negative credit, and negative local-attribution requirements.
- [ ] Implement blocked records, cycle detection, sign-specific policy checks, and negative path gates.
- [ ] Ensure blocked edges are excluded from normalized admissible weights.

### Task 6 — Determinism, JSON, property tests, and simulation

**Files:**
- Create: `tests/test_provenance_credit_properties.py`
- Create: `scripts/simulate_provenance_credit.py`
- Create: `tests/test_provenance_credit_simulation.py`

- [ ] Add canonical JSON and deterministic path fingerprints.
- [ ] Generate at least 5,000 deterministic DAG cases covering conservation, scope, uniqueness, and permutation invariance.
- [ ] Compare naive branch-multiplying BFS with mass-conserving propagation.
- [ ] Verify simulation output twice and record SHA-256.

### Task 7 — Public API and documentation

**Files:**
- Modify: `src/nextgen_memory/__init__.py`
- Create: `docs/provenance-credit-v0.md`
- Modify: `README.md` only if conflict-free on the stacked base.

- [ ] Write failing root-export tests.
- [ ] Export only stable v0 contracts.
- [ ] Document policies, mass equations, negative-credit gate, uncertainty, privacy, and non-goals.

### Task 8 — Final verification

- [ ] Run Ruff and full pytest on Python 3.12 and 3.13 through ordinary pull-request CI.
- [ ] Run compileall, coverage, wheel build/install, diff check, and targeted secret/raw-content scan.
- [ ] Compare the branch only against `feat/interaction-credit-v0` and confirm scoped files.
- [ ] Open or update a stacked draft PR.
- [ ] Record the exact head SHA, workflow ID, test count, simulation hash, and property-case count.
- [ ] Do not merge or modify any production database.
