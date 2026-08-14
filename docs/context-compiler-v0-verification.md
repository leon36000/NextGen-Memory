# Context Compiler v0 Verification Gate

Context Compiler v0 is accepted as a verified candidate only when all of the following hold on the exact pull-request head:

1. the branch contains the current verified `feat/utility-aware-reranker-v0` base;
2. Ruff passes on the complete tree;
3. the complete test suite passes on Python 3.12 and Python 3.13;
4. the deterministic 5,000-case property test passes without budget, scope, uniqueness, mandatory-admission, coverage-accounting, JSON, or permutation violations;
5. source compilation succeeds;
6. the PR remains scoped to compiler contracts, tests, exports, and documentation;
7. no Neon/Mongo migration, default-branch mutation, merge, or deployment occurs;
8. the final evidence comes from an ordinary user-triggered pull-request matrix. A workflow-token commit without normal PR jobs is not sufficient verification evidence.

The compiler is intentionally database-free. Its packet and omission records may later be persisted by a separate telemetry adapter, but raw query text and evidence content are outside that control-plane telemetry contract.
