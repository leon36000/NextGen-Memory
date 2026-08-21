# M-HEAD / NextGen Memory — Agent Guide

This file defines repository-local operating rules for humans and coding agents. It intentionally contains stable rules only. Current task state, branch/PR identifiers, live infrastructure observations, test counts, and unmerged SHAs belong in the project checkpoint/memory system, not here.

## 1. Establish truth before editing

Before changing code:

1. Inspect `git status`, branch/HEAD, recent history, and relevant worktrees.
2. Read `README.md`, `docs/architecture-and-contracts.md`, `pyproject.toml`, `.github/workflows/ci.yml`, and `src/nextgen_memory/__init__.py`.
3. Read the subsystem document and tests for the area being changed.
4. For an active design tranche, read the matching `docs/superpowers/specs/` and `docs/superpowers/plans/` documents, but treat them as design/history rather than proof of current implementation state.
5. If project checkpoint/memory services are available, recover the latest applicable checkpoint and reconcile it with Git. Git is authoritative for code.

Do not infer completion from a plan checkbox, chat history, PR prose, or an agent report. Verify the actual source, diff, exact head, and executable evidence.

## 2. Authority hierarchy

For code and behavior:

1. Git source + executable tests at the exact reviewed SHA.
2. `src/nextgen_memory/__init__.py` for package-root public API.
3. Migrations for durable database contracts.
4. `docs/architecture-and-contracts.md` for stable cross-system boundaries/invariants.
5. Subsystem docs.
6. Dated specs/plans for design rationale and implementation intent.
7. External checkpoint memory for current progress and handoff state.

If these disagree, reconcile against source/tests and record the resolution in the durable checkpoint system.

## 3. Autonomous execution is the default

Agents are expected to make evidence-based engineering decisions without repeatedly asking the owner for routine clarification or approval.

- Resolve ambiguity from source, tests, architecture, issue/PR history, primary documentation, and independent review.
- Prefer a safe, reversible, contract-preserving choice and record the decision.
- Do not stop for ceremonial approvals, redundant restatements, or a full-suite gate after every tiny edit.
- Escalate to the owner only when an external authority is genuinely required, such as unavailable credentials, a legally or operationally restricted action, contradictory owner directives, or an irreversible production action not already authorized by repository policy.
- A difficult question is not, by itself, a reason to ask the owner. Investigate it rigorously and consult the designated reviewer.

Detailed orchestration and merge rules are defined in `docs/autonomous-engineering-policy.md`.

## 4. Agent orchestration

### 4.1 Roles

- **Principal/coordinator:** owns task decomposition, source-of-truth reconciliation, integration, verification, documentation, issue hygiene, and the final evidence packet.
- **Implementation workers:** use GPT-5.6 Luna when that model is exposed. Run no more than **two Luna workers concurrently**. Parallelize only independent tasks with isolated branches/worktrees and non-overlapping write ownership.
- **Independent reviewer:** use GPT-5.6 Sol when that model is exposed. Sol is read-only for the reviewed change and must not author the implementation it approves.

If a named model is unavailable, do not silently claim it was used. Implementation may continue, but any merge that requires Sol remains `review_pending` until an actual Sol review is available.

### 4.2 Sol consultation for every task

Every task receives an independent Sol consultation:

- routine work uses a concise fast review of the task contract, assumptions, and risk;
- difficult or high-impact work uses a deeper independent analysis grounded in source and research;
- before merge, Sol performs a **blind final review** of the exact candidate SHA.

The final blind-review packet contains the task contract, acceptance criteria, exact diff, relevant source/contracts, tests and command outputs, CI evidence, and known risks. It excludes worker identity, persuasive summaries, and prior reviewer conclusions.

### 4.3 Concurrency and write ownership

- Never run more than two Luna implementation workers at once.
- Keep one writer per file or contract surface.
- Use isolated branches/worktrees for independent work.
- A coordinator may integrate verified commits, but must inspect the diff and rerun the appropriate acceptance checks.
- Agent output is advisory until verified against Git and executable evidence.

## 5. No stubs, placeholders, or fake completion

Production or merge-candidate changes must not contain implementation stubs or false success paths.

Forbidden in merge scope unless the contract explicitly requires the behavior:

- `pass`, `...`, `NotImplementedError`, placeholder returns, empty adapters, fake success values, disabled branches presented as implemented, or no-op persistence/execution paths;
- TODO/FIXME markers standing in for required behavior;
- tests that merely assert symbol existence while omitting the promised behavior;
- mocks or fakes used as a substitute for required integration evidence;
- stale PR descriptions or checklists that claim work not present at the exact head.

A test-only RED commit is allowed during TDD on a development branch, but it is never a completed deliverable and must not be merged or described as ready.

Partial work must be labelled `partial`, `blocked`, or `review_pending` with the exact missing evidence. No `DONE`, `READY`, or equivalent claim is accepted without proof.

## 6. Proportional verification, not ritual gates

Verification depth follows change risk. Use the smallest evidence set that actually proves the claim, then strengthen it at integration boundaries.

### Level 0 — documentation or non-behavioral metadata

- validate formatting/links or applicable generators;
- inspect exact diff and `git diff --check`;
- run only tests affected by generated or executable documentation;
- obtain Sol fast review before merge.

### Level 1 — local behavior with a contained contract surface

- focused RED→GREEN tests;
- relevant regression suite;
- Ruff/static checks for touched code;
- exact diff inspection and Sol review.

### Level 2 — public API, identity, privacy, retrieval scope, persistence, migrations, concurrency, or cross-subsystem behavior

- focused adversarial tests plus full relevant regression;
- full repository suite before integration;
- migration/fresh-install/upgrade or offline integration evidence where applicable;
- privacy/identity/failure-path review;
- blind Sol review of the exact candidate SHA.

### Level 3 — merge to a canonical integration/release branch

- exact-head required CI green;
- all blocking review findings resolved;
- changed-path and dependency review;
- documentation and migration manifests consistent;
- reproducible evidence packet tied to the exact SHA;
- explicit Sol `APPROVE` verdict on that SHA.

Do not rerun expensive global checks after every formatting edit when their inputs did not materially change. Do rerun them after code changes that invalidate the previous evidence and at the integration boundary.

## 7. Merge authority

An agent may merge without asking the owner when all of the following are true:

1. the target branch, merge method, and dependency order are correct;
2. exact-head CI and risk-proportionate verification are green;
3. no unresolved blocking finding remains;
4. documentation and durable contracts are consistent with the diff;
5. GPT-5.6 Sol has issued an explicit blind-review `APPROVE` for the exact head SHA;
6. the merge does not itself perform an unauthorized production deployment, destructive data operation, secret rotation, billing action, or other externally restricted operation.

A Sol approval is invalid if the reviewed SHA moved. Any change after approval requires a new exact-head review, except a mechanically proven metadata-only change that cannot affect the reviewed content and is explicitly covered by the review policy.

`CHANGES_REQUIRED` returns the task to implementation. `BLOCKED_BY_EVIDENCE` means the claim must be narrowed or the missing evidence obtained; it is not approval.

## 8. Development discipline

- Prefer focused TDD for behavioral changes: RED → minimal complete implementation → GREEN.
- “Minimal” means the smallest complete production implementation satisfying the contract, not a stub.
- After focused tests, run Ruff and the complete relevant regression suite; before integration run the risk-appropriate full suite.
- Inspect `git diff`, `git diff --check`, and exact changed paths before claiming completion.
- Use independent read-only review for security/privacy, identity, retrieval scope, persistence, and merge decisions.
- Never accept an agent's `DONE`/`READY` without verifying the repository state and evidence.

The configured CI currently runs Ruff and pytest on Python 3.12 and 3.13. Useful local acceptance checks include:

```bash
python3.12 -m pytest -q
python3 -m ruff check .
git diff --check
```

Do not invent a local Python 3.13 requirement on a host that does not provide it; cross-version acceptance belongs to an environment that actually has that interpreter, including the configured CI matrix.

## 9. Research discipline

Research is part of implementation when a decision depends on external behavior, evolving APIs, scientific claims, security properties, or non-obvious trade-offs.

- Prefer primary sources: official documentation, standards, source code, specifications, and peer-reviewed papers.
- Record dates, versions, assumptions, and the exact decision supported by each source.
- Distinguish verified facts, repository evidence, experiments, and inference.
- Use multiple independent sources or experiments for critical decisions.
- Do not replace repository inspection with generic advice.
- Deep research should accelerate a concrete decision or implementation; it must not become an unbounded substitute for shipping verified work.

## 10. Continuous engineering loop

Within an active orchestrated run, continue automatically through the highest-priority ready work:

1. rehydrate Git and durable project state;
2. select the next unblocked issue or acceptance gap;
3. consult Sol on the task/risk;
4. dispatch at most two independent Luna workers when useful;
5. implement, test, review, and integrate;
6. update docs/issues/checkpoints;
7. select the next ready item and repeat.

Stop only for a real external blocker, contradictory authoritative contracts, exhausted safe work, or an operation outside granted authority. When the current runtime cannot self-trigger another turn, write an exact checkpoint and next action so an external loop orchestrator can relaunch deterministically. Never claim that asynchronous work is continuing when no orchestrator is actually running.

## 11. Compatibility surfaces

Unless a task explicitly changes a contract and supplies migration/regression evidence, preserve:

- package-root exports in `src/nextgen_memory/__init__.py`;
- `ResearchRetrievalQuery` / `ResearchRetrievalHit`;
- `MongoResearchIndexConfig`, `build_research_hybrid_pipeline`, and `MongoResearchRetriever` behavior;
- retrieval telemetry schema and privacy properties;
- deterministic router identities, ordering, and expert semantics;
- Neon schema meanings, append-only/idempotency guarantees, and canonical UUID identities;
- Mongo-to-Neon canonical identity linkage;
- context-compiler packet identity, byte-preserving evidence, dependency rules, and omission semantics;
- causal/interaction credit abstention and value-closure rules.

Internal modules are not automatically package-root APIs. If an internal subsystem becomes public, update `src/nextgen_memory/__init__.py`, regression coverage, and stable documentation in the same reviewed change.

## 12. Cross-cutting safety invariants

### Scope and fail-closed behavior

- Eligibility/scope/permission/lifecycle/sensitivity checks precede semantic usefulness.
- Retrieval scope, active-status, and required source-type constraints belong inside the ranking/pre-filter boundary; a later filter must never repair an unsafe ranking stage.
- Unknown or malformed safety-critical structures fail closed.
- Backend/capability failure must not silently weaken retrieval semantics or select an unplanned fallback. Any supported fallback must be explicit in the governing contract and preserve its safety guarantees.

### Identity and determinism

- Use canonical, explicit serialization/fingerprinting rules; never fall back to arbitrary `str(obj)` for identity.
- Reject non-finite numbers and ambiguous unsupported types at identity boundaries.
- Preserve order for execution-order sequences; normalize order only where a contract explicitly declares set semantics.
- Treat mutable subclasses/aliases as hostile at security- or identity-sensitive boundaries; snapshot or require exact immutable/built-in representations where needed.
- Deterministic UUID/hash/audit identities must bind the complete privacy-safe policy they claim to represent.

### Privacy

Privacy-safe outputs, deterministic identities, telemetry, exceptions, and committed operational evidence must not accidentally contain production/user payloads that their contract excludes, including raw prompts, queries, vectors, retrieved content, provider payloads, or connection material.

Use allowlisted safe-output construction instead of blacklist redaction. Synthetic examples, fixtures, and explanatory documentation are allowed when clearly non-sensitive and not copied from protected runtime payloads.

### Persistence

- Neon/Postgres is the canonical identity/ledger/state/telemetry/feedback/checkpoint plane.
- MongoDB Atlas stores rich payloads, traces, research sources, and repository artifacts linked to canonical identities.
- Read-only or preproduction components must not gain durable write behavior accidentally; any write path requires an explicit contract, tests, and the appropriate migration/integration review.
- Live integration probes are explicit and bounded, and their results must not be treated as permanent capability guarantees.

## 13. Documentation and issue hygiene

Update `docs/architecture-and-contracts.md` in the same change when a public API, persistent schema, cross-subsystem ownership boundary, supported workflow, or stable safety invariant changes.

Do not commit ephemeral status such as current worktree paths, active task IDs, temporary SHAs, one-off test counts, live cluster/index state, or current failures into stable architecture documentation. Put that information in the project checkpoint/memory system with the commit/base SHA and verification evidence.

Every material blocker, debt item, or deferred contract discovered during work must be resolved in scope or recorded as a linked issue with severity, evidence, acceptance criteria, and dependency ordering. PR prose is not a substitute for a backlog.

At handoff, record at minimum: baseline SHA, candidate SHA/branch, completed scope, incomplete scope, test/lint/CI evidence, review verdict, risks, and exact next action. Never store secrets.
