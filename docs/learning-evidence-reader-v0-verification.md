# Learning Evidence Reader v0 Verification Gate

Learning Evidence Reader v0 is accepted as a verified candidate only when all of the following hold on the exact pull-request head:

1. the branch contains the current verified `feat/inherited-credit-ledger-v0` base;
2. Ruff passes on the complete repository;
3. the complete test suite passes on Python 3.12 and Python 3.13;
4. the deterministic 5,000-case property test passes under request and row permutations;
5. direct and inherited evidence remain distinct nested contracts;
6. no `score`, `utility`, or `combined_utility` property is introduced;
7. `NodeUtilityReader` and utility-reranker scoring remain unchanged;
8. missing, duplicate, unexpected, malformed, or cross-space rows fail closed;
9. exact SQL succeeds against the isolated candidate branch and no query targets Neon main;
10. compileall, coverage, wheel build/install, exact diff review, and privacy/secret checks succeed;
11. the final evidence comes from an ordinary user-triggered pull-request matrix. A workflow-token commit without normal PR jobs is not sufficient.

No merge, schema promotion, or inherited-evidence scoring change is authorized by this gate.
