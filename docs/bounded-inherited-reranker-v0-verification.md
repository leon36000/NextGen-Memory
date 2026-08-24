# Bounded Inherited Reranker v0 Verification Gate

Bounded Inherited Reranker v0 is accepted as a verified candidate only when every condition below holds on the exact pull-request head.

## Stack and scope

1. The branch contains the current verified `feat/learning-evidence-reader-v0` base.
2. The diff contains only the bounded reranker module, tests, simulation, exports, and documentation.
3. `src/nextgen_memory/utility_reranker.py` remains unchanged.
4. `src/nextgen_memory/neon_utility.py` and `NodeUtilityReader` remain unchanged.
5. No migration, database writer, eligibility rule, routing rule, or retrieval query changes.

## Functional verification

6. Ruff passes on the complete repository.
7. The complete test suite passes on Python 3.12 and Python 3.13.
8. The public package exports exactly the stable v0 contracts.
9. The 10,000-case deterministic ranking property suite passes.
10. The 2,000-case direct-evidence permutation check proves no inherited double counting.
11. Candidate-order and evidence-mapping-order permutations are invariant.
12. Final ranks are unique and contiguous.
13. Every final score is finite.
14. Every inherited component remains within `maximum_absolute_adjustment`.
15. No-evidence, minimum-count, and minimum-confidence gates apply exactly zero adjustment.
16. Missing, unexpected, duplicate, malformed, or cross-space evidence fails closed.
17. The original `RerankedMemory` object and its base score breakdown remain unchanged.

## Simulation verification

18. The deterministic five-scenario simulation produces the same bytes on repeated execution.
19. Naive inherited-mean addition produces four false promotions.
20. The bounded policy produces zero false promotions.
21. The bounded policy preserves the one strong, consistent promotion.
22. The maximum applied absolute adjustment is `0.05` under the default policy.

## Independent reproduction

23. `compileall` succeeds for source and simulation modules.
24. Coverage is measured on the exact head.
25. A wheel is built, installed, and its public API imported.
26. The exact base-to-head diff passes `git diff --check`.
27. High-signal secret scanning and the aggregate-only privacy boundary pass.
28. The final evidence comes from an ordinary user-triggered pull-request matrix on the exact final head. Workflow-token commits without ordinary PR jobs are not sufficient.

## Release boundary

This gate authorizes neither merge nor deployment. It does not authorize database mutation, migration promotion, automatic inherited-evidence scoring in production, or learned coefficient training.
