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
- **Python kernel:** zero-dependency typed contracts, fail-closed candidate eligibility, and a
  deterministic sparse router used before learned routing is justified.
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

The research expert now has an executable MongoDB Atlas read path:

- native MongoDB 8.0 `$rankFusion` over `rag_autoembed_v1` and `rag_lexical_v1`;
- mandatory canonical `space_id` isolation and `status=active` filtering;
- typed, immutable query/result contracts and fail-closed result mapping;
- deterministic rows compatible with `ngm.retrieval_events`;
- no raw query text in retrieval telemetry;
- idempotent canonical Neon identities for the ten initial Atlas research sources.

See `docs/retrieval-v1.md` for the query contract, privacy boundary, and verified live smoke result.

## Repository map

- `src/nextgen_memory/`: framework contracts, routing kernel, and research retrieval adapter.
- `tests/`: behavior, retrieval, telemetry, and migration-contract tests.
- `migrations/neon/`: reproducible canonical ledger migrations and research identity seed.
- `migrations/mongodb/`: rich-payload collection contracts.
- `docs/router-v0.md`: router semantics and non-goals.
- `docs/retrieval-v1.md`: native hybrid research retrieval and telemetry contract.
- `docs/superpowers/specs/`: approved research/design specifications.
- `docs/superpowers/plans/`: implementation plans.

## Status

Schema `0.1.1`, Router v0, and Research Retrieval v1 are the current foundation. Learned routing,
utility-aware reranking, context compilation, state-adjudication replay, Temporal workflows, and SWE
execution governance follow only after their contracts and supervision data are verified.
