# Advisory Policy Promotion Gate v0 — TDD RED v4 Evidence

**Date:** 2026-08-24
**Base branch:** `candidate/paired-replay-experiment-registry-v0-20260824`
**Base SHA:** `91d14e9ff9f8c89d05cb2349b012a6681bf3d828`
**Original RED SHA:** `75540537f84a2a8bfed191d192c80f33ea81e112`
**Corrected RED v4 branch:** `tdd/advisory-policy-promotion-gate-v0-red-v4-20260824`

The three tests-only contract files are Ruff-clean and syntactically valid. The registry/evaluation mismatch fixture preserves a valid registry partition by pairing 23 completed trials with one active pair. Against the immutable base, every test file independently reaches only the absence of `nextgen_memory.policy_promotion_gate`; the implementation and package-root exports are absent.

This corrected RED v4 supersedes the original test tree for product qualification without rewriting the original immutable evidence.
