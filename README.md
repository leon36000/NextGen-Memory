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
5. Which relevant memories have credible evidence of helping or harming comparable work?
6. What is the smallest evidence packet that closes the agent's evidence gap?
7. Which selected memories actually changed the resulting task outcome?
8. Is the causal evidence strong enough to update utility, or should the system abstain?

## Current architecture

- **Neon/Postgres:** canonical immutable ledger, provenance, bitemporal state, expert registry,
  routing/retrieval telemetry, aggregate utility evidence, causal feedback, and project checkpoints.
- **MongoDB Atlas:** rich episodic traces, research sources, repository artifacts, and alternate
  representations linked to canonical Neon UUIDs.
- **Python kernel:** zero-dependency typed contracts, fail-closed candidate eligibility, a
  deterministic sparse router, scoped hybrid retrieval, evidence-shrunk utility reranking, and
  paired post-action causal attribution.
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

## Scope-safe Research Retrieval

The research expert has an executable MongoDB Atlas read path:

- native MongoDB 8.0 `$rankFusion` over `rag_autoembed_v1` and `rag_lexical_v2`;
- canonical `space_id` and `status=active` filters inside both retrieval channels;
- typed, immutable query/result contracts and fail-closed result mapping;
- deterministic rows compatible with `ngm.retrieval_events`;
- no raw query text in retrieval telemetry;
- idempotent canonical Neon identities for the initial Atlas research sources.

See `docs/retrieval-v1.md` for the query contract, privacy boundary, and verified live smoke result.

## Utility-Aware Reranker v0

The retrieval path can oversample candidates, read scoped aggregate evidence from
`ngm.node_utility`, and rerank with:

- normalized retrieval relevance;
- strongly shrunk reward and verdict utility;
- an independent harm-risk penalty;
- bounded token and latency costs;
- a complete deterministic score breakdown.

No-feedback memories remain neutral. Backend failures propagate rather than silently falling back to
unscoped or evidence-free ranking. The fixed-seed reward-trap simulation shows why task reward must
not be copied to every co-retrieved memory.

See `docs/utility-reranker-v0.md` for equations, defaults, simulation results, and the training gate
for a later learned reranker.

## Post-Action Causal Credit v0

A completed task can now be evaluated using matched interventions:

```text
full memory bundle
no-memory baseline
full bundle minus each selected-and-used memory
```

The assigner computes paired marginal effects, sample standard error, cost deltas, and success-rate
changes. It emits `decisive`, `helpful`, or `harmful` credit only when evidence is stable. It abstains
for missing ablations, too few trials, high variance, unused memories, weak effects, or ambiguous
redundancy.

Stable credits become deterministic UUID5 feedback rows with canonical hashes and an insert-then-read-
back verification contract. Raw prompts, answers, commands, outputs, notes, secrets, diffs, and
patches are excluded. The additive Neon migration remains a verified candidate and has not been
applied to production.

See `docs/causal-credit-v0.md` for the intervention model, migration verification, simulation results,
and deployment gate.

## Repository map

- `src/nextgen_memory/`: routing, retrieval, utility, causal credit, telemetry, and immutable contracts.
- `tests/`: behavior, retrieval, utility, causal attribution, telemetry, and migration-contract tests.
- `scripts/`: deterministic research and verification simulations.
- `migrations/neon/`: reproducible canonical ledger, identity, execution, and causal-feedback migrations.
- `migrations/mongodb/`: rich-payload collection and index contracts.
- `docs/router-v0.md`: router semantics and non-goals.
- `docs/retrieval-v1.md`: native hybrid research retrieval and telemetry contract.
- `docs/utility-reranker-v0.md`: evidence-shrunk utility-aware reranking.
- `docs/causal-credit-v0.md`: paired post-action causal attribution and feedback persistence.
- `docs/superpowers/specs/`: approved research/design specifications.
- `docs/superpowers/plans/`: implementation plans.

## Status

Schema `0.1.1`, Router v0, scope-safe Research Retrieval, Utility-Aware Reranker v0, and Post-Action
Causal Credit v0 are the current research foundation. Learned routing, subset interaction credit,
redundancy-aware context compilation, Temporal orchestration, and latent-memory injection follow only
after their contracts and intervention-grounded supervision data are verified.
