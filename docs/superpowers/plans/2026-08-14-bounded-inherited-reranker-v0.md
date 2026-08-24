# Bounded Inherited Reranker v0 Implementation Plan

> **For agentic workers:** use strict TDD and fresh verification. Record an ordinary pull-request RED before adding production code.

**Goal:** Add a conservative second-stage inherited-evidence adjustment to existing `RerankedMemory` values while preserving direct-feedback scoring, eligibility, and evidence provenance.

**Architecture:** `bounded_inherited_reranker.py` defines immutable config, disposition, score breakdown, wrapped result, and a deterministic fail-closed reranker. It consumes `NodeLearningEvidence` snapshots but scores only the inherited nested contract. The existing Utility-Aware Reranker remains unchanged.

**Tech stack:** Python 3.12+, standard library dataclasses/enums/math/mapping, pytest, Ruff, deterministic simulation, GitHub Actions.

## Global constraints

- Do not modify `utility_reranker.py` or `NodeUtilityReader`.
- Do not query or write a database.
- Do not score direct evidence twice.
- Require exact candidate/evidence UUID-set equality.
- Preserve the complete base result unchanged.
- Return a complete inherited-only breakdown.
- Apply hard minimum count/confidence gates.
- Bound every adjustment by `maximum_absolute_adjustment`.
- Keep ranking deterministic under input and mapping permutations.
- Emit no query or memory content telemetry.

### Task 1 — Config and score contracts

**Files:**
- Create: `tests/test_bounded_inherited_reranker.py`
- Create after RED: `src/nextgen_memory/bounded_inherited_reranker.py`

- [ ] Write failing tests for `InheritedEvidenceDisposition`, `BoundedInheritedRerankerConfig`, `InheritedScoreBreakdown`, and `InheritedAwareRerankedMemory`.
- [ ] Cover finite values, bounds, positive scales, hard-cap relationship, immutability, and nested base preservation.
- [ ] Record RED because the production module is absent.
- [ ] Implement minimum contracts.

### Task 2 — Conservative component equation

- [ ] Write failing examples for no evidence, count gate, confidence gate, positive/negative signal, cancellation coherence, count shrinkage, uncertainty penalty, confidence monotonicity, saturation, and cap.
- [ ] Implement the exact formula from the design.
- [ ] Verify direct evidence fields do not change the inherited component.

### Task 3 — Fail-closed deterministic reranking

- [ ] Test exact evidence-set equality.
- [ ] Test mixed space, key/row mismatch, duplicate candidate UUID, non-contiguous or duplicate base rank, and non-finite base score.
- [ ] Test stable tie-breaking and contiguous final ranks.
- [ ] Test input-order and evidence-mapping-order invariance.
- [ ] Implement `BoundedInheritedReranker.rerank(...)`.

### Task 4 — 10,000 generated cases and naive-baseline simulation

**Files:**
- Create: `tests/test_bounded_inherited_reranker_properties.py`
- Create: `scripts/simulate_bounded_inherited_reranker_v0.py`
- Create: `tests/test_bounded_inherited_reranker_simulation.py`

- [ ] Generate 10,000 deterministic valid ranking cases.
- [ ] Verify cap, finite output, neutrality, scope, uniqueness, contiguous ranks, evidence-set equality, and permutation invariance.
- [ ] Verify monotonic reliability properties for paired generated evidence.
- [ ] Simulate naive `base + inherited mean` versus the bounded policy under:
  - one high-value low-confidence path;
  - sparse evidence;
  - conflicting paths;
  - high uncertainty;
  - many consistent high-confidence paths.
- [ ] Require the bounded policy to eliminate false promotion in weak-evidence scenarios while still permitting bounded promotion for strong evidence.

### Task 5 — Public API and documentation

**Files:**
- Create: `tests/test_bounded_inherited_reranker_public_api.py`
- Modify after RED: `src/nextgen_memory/__init__.py`
- Create: `docs/bounded-inherited-reranker-v0.md`

- [ ] Record one-failure RED for absent root exports.
- [ ] Export config, disposition, breakdown, wrapped result, reranker, and validation error.
- [ ] Document the equation, neutrality gates, failure behavior, simulation, privacy, and non-goals.

### Task 6 — Final verification

- [ ] Open a stacked draft PR targeting `feat/learning-evidence-reader-v0`.
- [ ] Require ordinary PR CI on Python 3.12 and 3.13.
- [ ] Run Ruff, full pytest, compileall, coverage, wheel build/install, exact diff, and high-signal secret scan.
- [ ] Persist a machine-readable verification marker and canonical project checkpoint.
- [ ] Do not merge, deploy, or alter any database.
