# Autonomous Engineering and Blind Review Policy

## Purpose

This policy defines how M-HEAD / NextGen Memory advances quickly without trading away correctness. It removes ceremonial owner gates, preserves evidence-based decision making, prohibits placeholder implementation, and gives agents conditional merge authority through an independent GPT-5.6 Sol review.

## Operating principles

1. **Autonomy by default.** The principal agent resolves engineering questions from repository truth, tests, primary research, and independent review instead of repeatedly asking the owner.
2. **No false completion.** Claims are tied to an exact SHA and reproducible evidence. Incomplete work is described as incomplete.
3. **No stubs.** Production and merge-candidate code must implement the promised behavior completely. A RED test is evidence of TDD, not a deliverable.
4. **Proportional rigor.** Verification scales with risk; low-risk changes avoid wasteful full-system ceremony, while identity/privacy/persistence/release changes receive deep adversarial proof.
5. **Independent approval.** GPT-5.6 Sol reviews every task and alone provides the final blind merge verdict.
6. **Bounded parallelism.** At most two GPT-5.6 Luna implementation workers run concurrently, only on independent scopes.
7. **Continuous progress.** An active orchestrator proceeds from one verified ready item to the next until a real blocker is reached.

## Task lifecycle

### 1. Rehydrate

The coordinator reads the exact Git state, active PR/issue, relevant architecture/contracts, tests, and durable checkpoint. Conflicts are resolved in favor of Git source and executable evidence.

### 2. Define the task contract

The coordinator writes a compact task contract containing:

- problem and evidence;
- in-scope and out-of-scope behavior;
- compatibility and safety invariants;
- acceptance criteria;
- required verification level;
- expected files/contract surfaces.

No owner question is required when this can be determined from authoritative evidence.

### 3. Sol task consultation

Sol receives the task contract and relevant evidence, not a proposed implementation conclusion. Sol identifies hidden risks, missing acceptance criteria, research needs, and likely contract collisions.

For routine tasks this is a fast review. For difficult tasks it is a deep independent analysis using source, experiments, and primary research.

### 4. Dispatch

The coordinator either implements directly or dispatches one or two Luna workers. Two workers may run only when their changes do not overlap in files, migrations, public API, or semantic ownership.

Typical safe pairings:

- implementation + independent test/oracle development;
- two unrelated issues in isolated worktrees;
- code change + documentation/research on a separate surface.

Unsafe pairings:

- two workers modifying the same module;
- concurrent migration numbering;
- separate writers changing the same public contract;
- implementation and “review” by the same context.

### 5. Implement completely

Use RED→GREEN when behavior changes. The implementation must satisfy the whole accepted task contract. No placeholders, disabled branches presented as features, or deferred essential behavior remain in merge scope.

### 6. Verify proportionately

The coordinator executes the required focused, regression, static, integration, migration, privacy, and exact-head CI checks. Evidence is captured as commands/results or CI identifiers tied to the candidate SHA.

### 7. Blind Sol final review

Sol receives only:

- task contract and acceptance criteria;
- exact base and candidate SHAs;
- exact diff/changed paths;
- relevant source and stable contracts;
- test, lint, CI, migration, and experiment evidence;
- declared residual risks.

Sol does **not** receive worker identity, worker self-assessment, persuasive implementation narrative, previous review conclusions, or an expected verdict.

Sol returns exactly one verdict:

- `APPROVE` — evidence proves the task contract and no blocking issue remains;
- `CHANGES_REQUIRED` — concrete correctness, compatibility, security, quality, or evidence defects remain;
- `BLOCKED_BY_EVIDENCE` — the implementation may be plausible, but the submitted evidence cannot support the requested claim.

The verdict records the exact candidate SHA. A moved SHA invalidates approval.

### 8. Merge or iterate

The coordinator may merge after `APPROVE` when exact-head CI is green, target/dependency order is correct, no blocking issue remains, and the merge is within granted repository authority.

After `CHANGES_REQUIRED`, fix the findings and repeat verification and blind review. After `BLOCKED_BY_EVIDENCE`, obtain the missing proof or narrow the claim; do not relabel it ready.

### 9. Checkpoint and continue

Update issue/PR status from exact evidence, write a durable checkpoint, then automatically select the next highest-priority ready item.

## No-stub rule

The following are forbidden in a merged task unless explicitly required as the final behavior:

- `pass`, ellipsis bodies, `NotImplementedError`, placeholder exceptions, constant fake responses, empty adapters, no-op writes, hard-coded success, or ignored error paths;
- an interface advertised as supported while the concrete path is absent;
- TODO/FIXME as a substitute for acceptance criteria;
- mocks standing in for required cross-store, migration, network-protocol, or integration proof;
- comments or docs claiming a future behavior is already implemented.

A deliberately unsupported capability is acceptable only when the public contract explicitly marks it unsupported and fails closed with tested behavior.

## No-false-DONE evidence record

A completion record includes:

```text
status: complete | partial | blocked | review_pending
base_sha:
candidate_sha:
changed_paths:
acceptance_criteria:
focused_tests:
regression_tests:
static_checks:
integration_or_migration_evidence:
ci_runs:
sol_verdict:
sol_reviewed_sha:
open_risks:
next_action:
```

Missing fields are reported as missing. They are never inferred from a worker report.

## Productive verification matrix

| Change | Required evidence before merge |
|---|---|
| Prose-only docs | rendered/format/link checks as applicable, diff check, Sol fast review |
| Tests/fixtures only | focused suite proves intended RED or regression, Ruff, diff review, Sol review |
| Contained implementation | focused RED→GREEN, relevant regression, Ruff/static checks, Sol review |
| Public API or identity | adversarial contract tests, full suite, compatibility diff, blind Sol review |
| Retrieval/privacy/security | mutation/failure tests, no-leak evidence, full suite, blind Sol review |
| Persistence/migration | fresh install + replay/upgrade + conflict/idempotency tests, full suite, blind Sol review |
| Canonical integration/release | all required exact-head CI, artifact/manifest checks, dependency review, blind Sol approval |

## Research standard

Research is considered complete only when it supports a concrete engineering decision. The evidence packet records primary sources, dates/versions, experiments, conflicting evidence, and the resulting decision. Inference is labelled as inference.

## Automatic relaunch boundary

An agent running in a single interactive response cannot truthfully continue after that runtime ends. Automatic relaunch therefore belongs to an external orchestrator. When such an orchestrator is available, it should invoke this loop again from the durable checkpoint. Without one, the coordinator must stop honestly after writing the exact next action; it must never claim background work is running.
