# Exact-SHA Merge Readiness Gate v0 — TDD RED Evidence

**Date:** 2026-08-30  
**Product base branch:** `candidate/exact-sha-review-attestation-registry-v0-r3-20260829`  
**Product base SHA:** `f4d9388c14dd1f746f904b3724767f73f82786fd`  
**Design/plan branch:** `feat/exact-sha-merge-readiness-gate-v0-20260830`  
**TDD branch:** `tdd/exact-sha-merge-readiness-gate-v0-red-20260830`

The tests-only contract defines:

- exact immutable candidate identity with separate expected and observed base, candidate, diff, and dependency-chain identities;
- exact composition with `ExactShaReviewRequest`, `ReviewAttestationRegistrySummary`, and `ReviewAttestationDecision`;
- externally supplied authentication boolean and authenticated-envelope evidence SHA-256, without any product-side signature claim;
- exact verification evidence for static analysis, compile, full suite, artifact integrity, isolated wheel, integration rehearsal, cross-Python identity, PostgreSQL replay, migration count, freshness, and immutable artifact/checkpoint digests;
- exact ordered dependency identities, contiguous ordinals, unique component/SHA identities, computed chain digest, prerequisite integration, equivalent-ref exclusion, single-writer reservation, and protected-branch controls;
- deterministic `READY`, `HOLD`, and `BLOCKED` records;
- hard-block precedence that suppresses all simultaneous hold reasons;
- every block and hold reason independently;
- exact authentication and review request/summary/decision identity bindings;
- exact freshness equality and adjacent finite boundaries;
- malformed and hostile-subclass fail-closed behavior;
- canonical JSON, SHA-256, UUID5, frozen/slotted values, material-field identity sensitivity, and privacy-safe output;
- 5,000 generated readiness combinations, 1,000 exact retries, and independent process hash-seed invariance;
- explicit package-root API.

The implementation module and package-root exports are absent from the immutable r3 base. Qualification requires all three test files to be Ruff-clean and syntactically valid. Each file must independently fail collection only because:

```text
nextgen_memory.merge_readiness_gate
```

Any syntax, fixture, name, setup, unrelated import, or existing-product regression failure invalidates the RED.

No implementation, stub, workflow product, migration, dependency, persistence adapter, GitHub client, signature verifier, merge executor, feedback writer, policy activation, deployment, release, database/network contact, filesystem/environment access, clock, randomness, model, agent, worker, lease, or background task belongs in this RED branch.

`READY` is explicitly advisory and never authorizes merge, migration, deployment, feedback, activation, or release.
