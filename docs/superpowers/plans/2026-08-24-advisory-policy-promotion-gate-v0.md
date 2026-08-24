# Advisory Policy Promotion Gate v0 — Implementation Plan

**Date:** 2026-08-24
**Base:** `candidate/paired-replay-experiment-registry-v0-20260824`

1. Preserve the original RED and create RED v2 with a valid registry-partition mismatch fixture.
2. Prove new RED tests for non-negative cost thresholds and failed/cancelled registry states.
3. Apply only the minimal threshold and registry-completeness fixes.
4. Export the bounded public API and canonical identities.
5. Run malformed-input, threshold-neighborhood, generated-property, retry, hash-seed, full-suite, audit, and isolated-wheel checks.
6. Publish an immutable candidate only after every check passes.
7. Require independent Python 3.12/3.13 exact-SHA verification and genuine GPT-5.6 Sol approval before merge.

Merge, deployment, migration, feedback, activation, and release remain separate operations.
