# Advisory Policy Promotion Gate v0 — TDD RED Evidence

**Date:** 2026-08-24
**Base branch:** `candidate/paired-replay-experiment-registry-v0-20260824`
**Base SHA:** `91d14e9ff9f8c89d05cb2349b012a6681bf3d828`
**TDD branch:** `tdd/advisory-policy-promotion-gate-v0-red-20260824`

The three tests-only contract files are Ruff-clean and syntactically valid. Each file independently reaches only the absence of `nextgen_memory.policy_promotion_gate` when collected against the immutable base. The implementation and package-root exports are absent.

This RED fixes advisory promote/hold/reject behavior, hard-rejection precedence, threshold neighborhoods, registry completeness, generated properties, deterministic identity, retries, privacy and public API before implementation qualification.
