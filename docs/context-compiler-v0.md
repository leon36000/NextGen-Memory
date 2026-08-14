# Context Compiler v0

## Status

TDD RED. The approved design and implementation plan are committed, and the behavior contract is expressed in `tests/test_context_compiler.py`.

The next accepted evidence is an ordinary pull-request CI run where Ruff passes and test collection fails because `nextgen_memory.context_compiler` does not yet exist. Production code is added only after that failure is recorded.

## Boundary

Context Compiler v0 will consume already scoped, eligible, materialized, and utility-reranked evidence. It will select whole evidence items under a hard token budget, close required coverage gaps first, preserve provenance, and render canonical JSON that treats memory content as evidence rather than instructions.

It performs no retrieval, summarization, database write, learned inference, or raw-query telemetry.
