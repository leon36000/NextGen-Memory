# Advisory Policy Promotion Gate v0 — Implementation Plan

**Date:** 2026-08-24
**Base:** `candidate/paired-replay-experiment-registry-v0-20260824`

1. Record a Ruff-clean tests-only module-absence RED from the immutable base.
2. Add strict immutable policy identity, paired evidence, readiness, threshold, request, and record types.
3. Validate UUID, SHA-256, Git SHA, identifier, enum, bool, integer, finite-number, interval, rate, registry-partition, and non-negative cost-threshold contracts before decision logic.
4. Implement hard rejection in fixed precedence and prevent simultaneous hold reasons from leaking into a reject record.
5. Implement bounded hold conditions, including every active, failed, or cancelled registry state, and permit promotion only for a fully qualified `promising` evaluation.
6. Bind all material inputs to canonical SHA-256 and UUID5 decision identity without echoing free-form content.
7. Prove threshold equality and one-ULP neighborhoods, malformed inputs, identity drift, terminal registry states, 5,000 generated valid requests, reject precedence, material-input identity sensitivity, process-hash-seed invariance, and package exports.
8. Run Ruff, compileall, focused/full tests, strict dependency/privacy/stub audit, isolated wheel installation, Python 3.12/3.13 exact-SHA verification, and cross-Python byte-identity evidence.
9. Publish an immutable candidate and blind GPT-5.6 Sol packet only after every verifier job succeeds.

Merge, deployment, policy activation, telemetry emission, feedback, migration application, and release publication remain separate operations.
