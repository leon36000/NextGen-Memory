# Inherited Rerank Telemetry v0 Verification Gate

Inherited Rerank Telemetry v0 is accepted as a verified candidate only when every condition below holds on the exact pull-request head.

## Stack and scope

1. The branch contains the current verified `feat/bounded-inherited-reranker-v0` base.
2. The diff contains only telemetry contracts, tests, exports, design/plan, and operating documentation.
3. `bounded_inherited_reranker.py`, `utility_reranker.py`, `neon_utility.py`, routing, retrieval, eligibility, context compilation, and all migrations remain unchanged.
4. No SQL, database writer, timestamp generator, direct-feedback field, or arbitrary metadata mapping is introduced.

## Functional verification

5. Ruff passes on the complete repository.
6. The complete test suite passes on Python 3.12 and Python 3.13.
7. The public package exports exactly the stable v0 telemetry API.
8. Exact retries recreate equal batches, UUIDs, hashes, and canonical JSON.
9. Changed score, rank, disposition, aggregate, decision, or policy changes the deterministic batch identity.
10. Observations are unique by canonical memory UUID and stored in contiguous final-rank order.
11. Base and final ranks are positive, unique, and contiguous.
12. Base and final scores are finite.
13. Every final score satisfies `base_score + applied_component` within the fixed tolerance.
14. Every applied component remains within the supplied bounded-reranker hard cap.
15. Gated and no-evidence observations have exactly zero applied component.
16. Disposition counts and rank-change counts each partition the candidate set exactly.
17. Empty batches use zero counts, null top memories, and `top_changed = false`.
18. Missing, duplicate, malformed, inconsistent, or unsupported inputs fail closed.
19. The in-memory sink is idempotent for exact retry and detects same-ID content conflicts.

## Generated verification

20. The deterministic 5,000-case property suite passes twice.
21. Input-order permutations produce byte-identical JSON.
22. The generated cases cover empty, applied, no-evidence, count-gated, confidence-gated, promoted, demoted, unchanged, and top-changed results.
23. Policy and router-decision changes produce different batch identities.
24. Generated telemetry contains none of the forbidden raw-content, direct-feedback, secret, or path fields.

## Independent reproduction

25. `compileall` succeeds for the source package.
26. Coverage is measured on the exact final head.
27. A wheel is built, installed, and the stable public API imports successfully.
28. The exact base-to-head diff passes `git diff --check`.
29. Canonical example JSON is generated twice and is byte-identical.
30. High-signal secret scanning and the aggregate-only privacy boundary pass.
31. The final evidence comes from an ordinary user-triggered pull-request matrix on the exact final head. Workflow-token commits without ordinary PR jobs are not sufficient.

## Release boundary

This gate authorizes neither merge nor deployment. It does not authorize a telemetry database schema, retention policy, production emission, inherited-reranker activation, or learned coefficient training.
