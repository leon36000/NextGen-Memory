# Bounded Inherited Reranker v0 — RED Gate

The score equation, fail-closed input contract, and immutability requirements are specified before the production module exists.

The accepted core RED is an ordinary pull-request CI run where:

1. Ruff passes on Python 3.12 and 3.13;
2. pytest collection fails because `nextgen_memory.bounded_inherited_reranker` does not exist;
3. `utility_reranker.py`, `neon_utility.py`, and every database migration remain unchanged;
4. no score combines direct and inherited evidence implicitly.

Production implementation begins only after this exact failure is recorded. Workflow-token-only commits are not accepted as final GREEN evidence.
