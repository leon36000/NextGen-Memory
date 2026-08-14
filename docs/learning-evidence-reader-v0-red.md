# Learning Evidence Reader v0 — RED Gates

The feature was specified before production implementation.

## Core RED

The initial behavior and SQL tests import `nextgen_memory.learning_evidence`. The accepted core RED is an ordinary pull-request matrix where Ruff passes and pytest collection fails because that module does not yet exist.

## Public API RED

After the internal module and 5,000-case property suite pass, `tests/test_learning_evidence_public_api.py` requires the stable root exports. The accepted API RED is an ordinary pull-request matrix where all internal behavior tests pass and only root-package export assertions fail.

Workflow-token-only commits are not accepted as final GREEN evidence.
