# Exact-SHA Review Attestation Registry v0 — TDD RED v2 Evidence

**Date:** 2026-08-24  
**Base branch:** `candidate/advisory-policy-promotion-gate-v0-20260824`  
**Base SHA:** `f4f3aca9759b5b7a60691017c2211152c011ea92`  
**TDD branch:** `tdd/exact-sha-review-attestation-registry-v0-red-v2-20260825`

The tests-only contract defines:

- immutable exact review requests bound to repository, PR, base/candidate SHAs, diff, review packet, acceptance criteria, required model, trusted reviewer fingerprints, and approval threshold;
- immutable reviewer identities and exact attestations bound to request, candidate, reviewer, verdict, bounded finding codes, review artifact, evidence artifacts, and authenticated-envelope hash;
- idempotent exact retries and immutable request/reviewer conflicts;
- validation before mutation for all wrong request, repository, PR, candidate, model, and reviewer bindings;
- verdict/finding compatibility;
- bounded iterable consumption and canonical set semantics;
- deterministic summaries and advisory decisions with precedence `BLOCKED > EVIDENCE_BLOCKED > APPROVED > PENDING`;
- 5,000 generated traces and independent process hash-seed invariance;
- explicit package-root API.

The implementation module and package-root exports are absent from the immutable base. Qualification requires all three test files to be Ruff-clean and syntactically valid, and each file must independently fail collection only because:

```text
nextgen_memory.review_attestation_registry
```

No implementation, stub, workflow product, migration, dependency, persistence adapter, authentication claim, merge action, feedback writer, policy activation, deployment, or release behavior belongs in this RED branch.

## Fixture correction

RED v2 preserves the complete accepted test contract and corrects one invalid fixture from RED v1: authenticated-envelope SHA-256 values derived from suffixes `a` through `d` remain lowercase instead of being uppercased. This aligns the fixture with the explicit lowercase SHA-256 validation contract. No behavior assertion is removed or weakened.
