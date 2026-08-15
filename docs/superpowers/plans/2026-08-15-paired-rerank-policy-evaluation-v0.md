# Paired Rerank Policy Evaluation v0 Implementation Plan

> **For agentic workers:** use strict test-driven development. Record an ordinary pull-request RED before each production slice and verify the final exact head independently.

**Goal:** Evaluate treatment versus control inherited-reranking policies from strictly matched replays without leaking task reward to individual memories or relying on unlogged propensity assumptions.

**Architecture:** `paired_rerank_policy_evaluation.py` defines immutable trial, config, verdict, abstention, and evaluation contracts. It validates matched telemetry batches and outcomes, computes paired treatment-minus-control statistics, applies uncertainty/harm/resource gates, and returns one deterministic policy-level evaluation. A generated property suite and deterministic simulation verify variance, verdict ordering, identity, and privacy.

**Tech stack:** Python 3.12+, standard-library dataclasses/enums/statistics/math/hashlib/json/UUID5, existing inherited-rerank telemetry and outcome contracts, pytest, Ruff, GitHub Actions.

## Global constraints

- Base branch is `feat/inherited-rerank-telemetry-v0`.
- Use matched replay only; no propensity, IPS, observational OPE, or online-causality claim.
- Evaluate one control/treatment policy pair, not individual memories.
- Require same space, router decision, candidate UUID set, base ranks, and base scores.
- Require explicit context and continuation SHA-256 fingerprints.
- Keep control and treatment roles stable across trials.
- Do not write feedback, telemetry, SQL, or migrations.
- Do not modify routing, retrieval, rerankers, telemetry, outcome contracts, or protected database files.
- Store no query, prompt, answer, memory content, command, output, secret, path, or arbitrary metadata.
- Keep the PR draft and unmerged.

### Task 1 — Matched trial and configuration contracts

**Files:**
- Create: `tests/test_paired_rerank_policy_evaluation.py`
- Create after RED: `src/nextgen_memory/paired_rerank_policy_evaluation.py`

- [ ] Write failing tests for `PairedRerankPolicyTrial`, `PairedPolicyEvaluationConfig`, `PairedPolicyVerdict`, and `PairedPolicyAbstentionReason`.
- [ ] Verify UUID/hash/outcome types, same space/decision, distinct policies, same candidate set, same base rank/score, and frozen values.
- [ ] Record ordinary PR RED because the production module is absent.
- [ ] Implement minimum contracts and deterministic trial deltas.

### Task 2 — Paired estimator and verdict gate

**Files:**
- Modify: `tests/test_paired_rerank_policy_evaluation.py`
- Modify: `src/nextgen_memory/paired_rerank_policy_evaluation.py`

- [ ] Write failing examples for insufficient pairs, high standard error, harmful, too costly, promising, neutral, and inconclusive verdicts.
- [ ] Verify sample standard deviation, standard error, confidence interval, success delta, resource deltas/ratios, top-change rate, applied-observation rate, and mean absolute adjustment.
- [ ] Implement `PairedRerankPolicyEvaluator.evaluate(...)` and `PairedRerankPolicyEvaluation`.
- [ ] Keep verdict ordering exactly as specified.

### Task 3 — Deterministic identities and conflict handling

- [ ] Test exact retry equality and byte-identical JSON.
- [ ] Test trial-order invariance.
- [ ] Deduplicate exact duplicate trials.
- [ ] Reject reused trial UUIDs with different content.
- [ ] Reject mixed spaces, policy pairs, metric fingerprints, or reversed roles.
- [ ] Implement config/trial/evaluation SHA-256 hashes and UUID5 identities.

### Task 4 — Generated experiments and paired-variance simulation

**Files:**
- Create: `tests/test_paired_rerank_policy_evaluation_properties.py`
- Create: `scripts/simulate_paired_rerank_policy_evaluation_v0.py`
- Create: `tests/test_paired_rerank_policy_evaluation_simulation.py`

- [ ] Generate at least 5,000 deterministic matched experiments.
- [ ] Verify matching, trial uniqueness, exact statistics, verdict ordering, finite intervals, deterministic identity, input permutation, and privacy.
- [ ] Simulate correlated control/treatment outcomes and show paired standard error below an independent/unpaired standard error.
- [ ] Simulate all six verdict classes and require deterministic JSON/hash output.

### Task 5 — Public API and documentation

**Files:**
- Create: `tests/test_paired_rerank_policy_evaluation_public_api.py`
- Modify after RED: `src/nextgen_memory/__init__.py`
- Create: `docs/paired-rerank-policy-evaluation-v0.md`
- Create: `docs/paired-rerank-policy-evaluation-v0-verification.md`

- [ ] Record one-failure API RED after internal GREEN.
- [ ] Export stable trial, config, verdict, abstention, evaluation, evaluator, errors, and fingerprint helpers.
- [ ] Document matching, estimator, verdict ordering, research basis, privacy, simulation, and non-goals.

### Task 6 — Final independent verification

- [ ] Open a stacked draft PR targeting `feat/inherited-rerank-telemetry-v0`.
- [ ] Require ordinary PR CI on Python 3.12 and 3.13.
- [ ] Run Ruff, full pytest, coverage, compileall, wheel build/install, deterministic simulation twice, exact diff, and high-signal secret scan.
- [ ] Confirm telemetry, rerankers, routing, retrieval, outcome contracts, and migrations are unchanged.
- [ ] Persist a machine-readable verification marker.
- [ ] Advance the canonical project checkpoint only after exact-head verification.
- [ ] Do not merge, deploy, or write policy outcomes to production storage.
