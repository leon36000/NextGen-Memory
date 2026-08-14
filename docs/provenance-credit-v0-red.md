# Provenance Credit v0 — RED Gate

The behavior contract is defined in `tests/test_provenance_credit.py` before production implementation.

The accepted RED evidence is an ordinary pull-request CI run where:

1. Ruff passes on Python 3.12 and 3.13;
2. pytest collection fails because `nextgen_memory.provenance_credit` does not exist;
3. no production module, persistence code, or database migration is present.

After that failure is recorded, implementation proceeds in minimal test-backed slices. Workflow-token commits without ordinary pull-request jobs are not accepted as the final RED or GREEN evidence.
