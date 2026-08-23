# Inherited Credit Ledger v0 — RED Gate

The persistence behavior contract is defined before production implementation in `tests/test_provenance_credit_persistence.py`.

The accepted RED evidence is an ordinary pull-request CI run where:

1. Ruff passes on Python 3.12 and 3.13;
2. pytest collection fails because `nextgen_memory.provenance_credit_persistence` does not exist;
3. no persistence module or migration exists;
4. inherited evidence is not inserted into `memory_feedback` and `node_utility` remains unchanged.

Workflow-token commits without ordinary pull-request jobs are not accepted as functional RED or final GREEN evidence.
