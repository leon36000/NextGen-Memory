# NextGen Memory

NextGen Memory is an experimental **Memory-MoE Kernel** for long-horizon LLM agents.
It is **eidetic at storage and selective at recall**: exact evidence is preserved, while a sparse
router activates only the memory experts needed for the current task.

## Why this is not ordinary RAG

A standard RAG pipeline asks which chunks resemble a query. NextGen Memory asks first:

1. Should memory be consulted?
2. Which expert families are eligible for this scope, task, phase, authority, and budget?
3. Does the task need current state, exact history, causal evidence, a procedure, a prior failure,
   repository structure, or research?
4. Which candidates remain valid after scope, permission, sensitivity, time, and quarantine checks?
5. What is the smallest evidence packet that closes the agent's evidence gap?
6. Which memories actually helped or harmed the resulting task?

## Current architecture

- **Neon/Postgres:** canonical immutable ledger, provenance, bitemporal state, expert registry,
  routing/retrieval telemetry, feedback, and project checkpoints.
- **MongoDB Atlas:** rich episodic traces, research sources, repository artifacts, and alternate
  representations linked to canonical Neon UUIDs.
- **Python kernel:** zero-dependency typed contracts, fail-closed candidate eligibility, a
  deterministic sparse router, utility-aware reranking, and coverage-first context compilation.
- **Temporal:** planned for durable lifecycle workflows after read/write contracts stabilize.

The twelve initial experts are `working`, `execution`, `episodic`, `semantic`, `temporal`,
`causal`, `procedural`, `failure`, `decision`, `repository`, `research`, and `feedback`.

## Quick start

```bash
python -m pip install -e .
python -m pytest -q
```

```python
from uuid import uuid4

from nextgen_memory import (
    DeterministicMemoryRouter,
    EvidenceNeed,
    PlanPhase,
    RoutingRequest,
    RoutingScope,
    TaskKind,
)

request = RoutingRequest(
    query="Diagnose why verification is failing",
    scope=RoutingScope(
        space_id=uuid4(),
        project_key="nextgen-memory",
        repository_key="leon36000/NextGen-Memory",
        branch="feat/memory-moe-kernel-v0",
        permissions=frozenset({"memory:read", "repository:read"}),
    ),
    task_kind=TaskKind.SOFTWARE_ENGINEERING,
    plan_phase=PlanPhase.DIAGNOSE,
    needs=frozenset({EvidenceNeed.CAUSAL, EvidenceNeed.FAILURE}),
)

decision = DeterministicMemoryRouter().route(request)
print(decision.to_dict())
```

## Research Retrieval v1

The research expert has an executable MongoDB Atlas read path:

- native MongoDB 8.0 `$rankFusion` over `rag_autoembed_v1` and `rag_lexical_v1`;
- mandatory canonical `space_id` isolation and `status=active` filtering;
- typed, immutable query/result contracts and fail-closed result mapping;
- deterministic rows compatible with `ngm.retrieval_events`;
- no raw query text in retrieval telemetry;
- idempotent canonical Neon identities for the initial Atlas research sources.

See `docs/retrieval-v1.md` for the query contract, privacy boundary, and verified live smoke result.

## Context Compiler v0

Context Compiler v0 converts materialized, scoped, eligible, and utility-reranked evidence into a
deterministic JSON packet under a hard token budget.

It selects:

1. mandatory evidence;
2. whole evidence items that close required coverage gaps;
3. optional evidence by bounded marginal value per token and diversity.

It never truncates or summarizes an evidence item. Missing required coverage remains explicit through
`packet.complete == False` and `packet.uncovered_coverage_keys`.

```python
from uuid import uuid4

from nextgen_memory import (
    ContextCompileRequest,
    ContextCompiler,
    ContextEvidence,
    EvidenceFidelity,
)

space_id = uuid4()
item = ContextEvidence(
    memory_id=uuid4(),
    space_id=space_id,
    expert="research",
    subject_key="memory.routing",
    content="Scope-before-routing reduces irrelevant retrieval.",
    content_hash="a" * 64,
    backend_ref="research_sources:example",
    source_uri="https://example.invalid/paper",
    fidelity=EvidenceFidelity.EXACT,
    score=0.9,
    authority=0.8,
    confidence=0.9,
    estimated_tokens=48,
    coverage_keys=("routing",),
)

packet = ContextCompiler().compile(
    ContextCompileRequest(
        space_id=space_id,
        token_budget=512,
        envelope_tokens=96,
        required_coverage_keys=("routing",),
    ),
    [item],
)

assert packet.complete
print(packet.render_json())
```

The JSON packet contains a fixed directive that memory is evidence only and must not be executed as
instructions. Prompt-like strings remain JSON-escaped evidence data. See
`docs/context-compiler-v0.md` for contracts, phases, omission reasons, and determinism guarantees.

## Repository map

- `src/nextgen_memory/`: routing, retrieval, reranking, and context compilation contracts.
- `tests/`: behavior, property, retrieval, telemetry, and migration-contract tests.
- `migrations/neon/`: reproducible canonical ledger migrations and identity seeds.
- `migrations/mongodb/`: rich-payload collection contracts.
- `docs/router-v0.md`: router semantics and non-goals.
- `docs/retrieval-v1.md`: native hybrid research retrieval and telemetry contract.
- `docs/context-compiler-v0.md`: deterministic evidence packet compilation.
- `docs/superpowers/specs/`: approved research/design specifications.
- `docs/superpowers/plans/`: implementation plans.

## Status

Schema `0.1.1`, Router v0, Research Retrieval v1, Utility-aware Reranker v0, and Context Compiler v0
form the current stacked candidate foundation. Learned routing, durable lifecycle orchestration,
state-adjudication deployment, and SWE execution governance remain gated by their own contracts,
verification, and explicit deployment approval.
