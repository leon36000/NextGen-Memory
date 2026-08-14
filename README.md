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

## Repository map

- `src/nextgen_memory/`: framework contracts and routing kernel.
- `tests/`: behavior and migration-contract tests.
- `migrations/neon/`: reproducible canonical ledger migrations.
- `migrations/mongodb/`: rich-payload collection contracts.
- `docs/router-v0.md`: router semantics and non-goals.
- `docs/superpowers/specs/`: approved research/design specification.
- `docs/superpowers/plans/`: implementation plans.

## Status

Bootstrap schema `0.1.1` and Router v0 are the current foundation. Learned routing, retrieval
execution, state-adjudication replay, Temporal workflows, and SWE execution governance follow only
after their contracts and supervision data are verified.
