# Paired Replay Experiment Registry v0 Design

**Date:** 2026-08-15
**Status:** approved under the project owner's standing architecture delegation
**Base:** `feat/paired-rerank-policy-evaluation-v0`

## 1. Goal

Paired Replay Experiment Registry v0 plans, counterbalances, and records strict control/treatment replays before they are passed to Paired Rerank Policy Evaluation v0.

It answers:

- which replay contexts belong to one policy experiment;
- which policy arm runs first for each context;
- whether control-first and treatment-first orders are balanced;
- whether the complete experiment fits declared token and latency budgets;
- which arm is currently allowed for each replay pair;
- whether arm results are exact retries, conflicts, over budget, out of order, or complete;
- which replay pairs are ready to become `PairedRerankPolicyTrial` values;
- which pairs failed or were cancelled without fabricating outcome evidence.

The registry does **not** execute agents, start background workers, create leases, call Temporal, query a database, or promote a policy.

## 2. Why this boundary is needed

Paired Rerank Policy Evaluation v0 can only make a valid comparison when control and treatment share one context, continuation contract, router decision, candidate set, and base ranking.

Without an explicit planner/registry, a caller could accidentally:

- run every control arm before every treatment arm and introduce temporal/order bias;
- execute treatment first for every context and confound policy with carryover;
- exceed the intended experiment budget;
- record the second arm before the first arm required by the counterbalanced plan;
- reuse one replay pair identity with different context or policy content;
- silently drop a failed arm and later treat an incomplete pair as evaluable;
- submit mismatched telemetry batches to the evaluator.

V0 makes these conditions explicit and deterministic before durable orchestration is introduced.

## 3. Research and experimental-design basis

The selected design uses three conservative principles:

1. **Matched pairs:** control and treatment are evaluated on the same context and continuation contract so treatment-minus-control can be estimated directly.
2. **Counterbalanced order:** control-first and treatment-first assignments differ by at most one pair, reducing systematic order and carryover bias.
3. **Common experiment budget:** the complete planned experiment must fit worst-case token and latency budgets before any arm is made schedulable.

The module performs deterministic counterbalancing from an externally supplied SHA-256 seed. It does not claim cryptographic randomization or online causal identification by itself.

## 4. Core planning contracts

### 4.1 `ReplayArm`

- `control`
- `treatment`

### 4.2 `ReplayArmOrder`

- `control_then_treatment`
- `treatment_then_control`

Convenience properties expose `first_arm` and `second_arm`.

### 4.3 `PairedReplayExperimentSpec`

One immutable experiment contract:

- `experiment_id`;
- `space_id`;
- control policy version and fingerprint;
- treatment policy version and fingerprint;
- `continuation_set_hash`;
- `order_seed_hash`;
- `maximum_pairs`;
- `maximum_tokens_per_arm`;
- `maximum_latency_ms_per_arm`;
- `maximum_total_tokens`;
- `maximum_total_latency_ms`;
- registry policy version.

Validation requires:

- UUID and SHA-256 formats;
- distinct control and treatment policy fingerprints;
- non-empty normalized policy versions;
- positive pair and per-arm budgets;
- total budgets large enough for at least one complete pair;
- finite latency values.

### 4.4 Replay contexts

The planner accepts a sequence of SHA-256 `context_set_hash` values.

- at least one context is required;
- duplicate context hashes are rejected rather than silently deduplicated;
- count may not exceed `maximum_pairs`;
- no query or context text enters the plan.

### 4.5 `PairedReplayAssignment`

One immutable context pair:

- deterministic pair UUID;
- experiment and space UUIDs;
- one context and continuation hash;
- deterministic ordinal;
- arm order;
- deterministic content hash.

Pair identity is UUID5 under `experiment_id` and the context/continuation hashes. It does not change when the counterbalance seed changes, while plan identity does change.

### 4.6 `PairedReplayPlanSummary`

- pair count;
- control-first count;
- treatment-first count;
- worst-case total tokens;
- worst-case total latency;
- deterministic content hash.

The two order counts partition the pair count and differ by at most one.

### 4.7 `PairedReplayPlan`

One immutable plan:

- deterministic plan UUID;
- full experiment spec;
- assignments in deterministic execution ordinal order;
- summary;
- deterministic content hash.

Input context order does not affect the plan.

## 5. Balanced deterministic planner

`BalancedPairedReplayPlanner.plan(spec, context_hashes)`:

1. validates the spec and unique contexts;
2. computes one deterministic permutation key per context:

```text
SHA256(order_seed_hash + ":" + context_set_hash)
```

3. sorts contexts by permutation key, then context hash;
4. chooses the starting arm from the low bit of `order_seed_hash`;
5. alternates control-first and treatment-first assignments;
6. calculates worst-case total tokens and latency;
7. rejects the plan when either total budget is exceeded;
8. computes assignment hashes, plan hash, and UUID5 identity.

For any plan, the difference between control-first and treatment-first counts is at most one.

Changing only the order seed may change order assignments and plan identity, but not pair identities.

## 6. Schedulable arm contract

### 6.1 `PairedReplayStep`

One immutable arm that is currently permitted to run:

- deterministic step UUID;
- plan, experiment, pair, and space UUIDs;
- replay arm;
- order position `1` or `2`;
- context and continuation hashes;
- policy version and fingerprint for that arm;
- per-arm token and latency limits;
- deterministic content hash.

Step identity is UUID5 under the pair UUID and arm name.

The registry exposes only the first unrecorded arm required by the assignment order. It never exposes both arms of one pair simultaneously.

## 7. Result and failure contracts

### 7.1 `PairedReplayArmResult`

One immutable completed arm:

- step, pair, experiment, and arm identities;
- exact `InheritedRerankTelemetryBatch`;
- exact `OutcomeMeasurement`;
- deterministic content hash.

The registry validates:

- the result belongs to the currently schedulable step;
- telemetry space and policy identity match the step;
- outcome tokens and latency do not exceed per-arm limits;
- exact retry is idempotent;
- same step identity with different immutable content fails closed.

### 7.2 `ReplayFailureCode`

- `execution_failed`
- `budget_exceeded`
- `cancelled`

### 7.3 `PairedReplayFailureRecord`

One immutable terminal failure for the currently schedulable arm:

- deterministic failure UUID;
- pair, step, experiment, and arm identities;
- failure code;
- deterministic content hash.

No free-form error message or raw stack trace is stored.

## 8. Registry state machine

### 8.1 `ReplayPairStatus`

- `planned`
- `first_arm_recorded`
- `complete`
- `failed`
- `cancelled`

### 8.2 `InMemoryPairedReplayExperimentRegistry`

The registry is an in-memory reference adapter.

#### Register plan

- exact plan retry is idempotent;
- reused experiment UUID with different immutable plan content raises `PairedReplayRegistryConflictError`;
- plan, pair, and step identities are indexed deterministically.

#### Next steps

`next_steps(experiment_id)` returns one schedulable arm per non-terminal pair, ordered by assignment ordinal.

#### Record arm result

- only the current step may be recorded;
- recording the second arm before the first fails;
- exact retry is idempotent;
- conflicting retry fails;
- first arm moves pair to `first_arm_recorded`;
- before storing the second arm, the registry constructs `PairedRerankPolicyTrial` using both results and the assignment hashes;
- if telemetry batches are not truly matched, trial construction fails and the second result is not stored;
- successful second arm moves the pair to `complete`.

#### Record failure

- failure may target only the current schedulable step;
- exact retry is idempotent;
- failure after completion or a result after failure is rejected;
- `cancelled` maps to `ReplayPairStatus.CANCELLED`; other codes map to `FAILED`.

#### Completed trials

`completed_trials(experiment_id)` returns only complete `PairedRerankPolicyTrial` values in assignment ordinal order. Incomplete or failed pairs never appear.

## 9. Registry snapshot and summary

`PairedReplayPairSnapshot` exposes:

- pair UUID;
- assignment ordinal and arm order;
- current status;
- recorded arms;
- next step when schedulable;
- failure code when terminal;
- completed trial UUID when complete.

`PairedReplayExperimentSummary` exposes:

- pair count;
- planned count;
- first-arm-recorded count;
- complete count;
- failed count;
- cancelled count;
- recorded arm count;
- completed trial count;
- actual tokens and latency recorded so far;
- deterministic content hash.

Status counts partition the pair count.

## 10. Budget semantics

Planning uses worst-case reservation:

```text
worst_case_total_tokens = pair_count × 2 × maximum_tokens_per_arm
worst_case_total_latency_ms = pair_count × 2 × maximum_latency_ms_per_arm
```

A plan is rejected when these totals exceed experiment budgets.

Recording additionally requires each arm outcome to remain within its per-arm limits. A caller that already exceeded a limit must record a `budget_exceeded` failure rather than insert an over-budget outcome.

The registry does not infer monetary cost and does not extend a budget automatically.

## 11. Deterministic identity and privacy

All hashes use compact canonical JSON with sorted keys and `allow_nan=False`.

The plan and registry contain only:

- UUIDs;
- SHA-256 policy/context/continuation/seed fingerprints;
- enums, counts, ordinals, and budgets;
- aggregate telemetry batches and outcomes;
- deterministic hashes.

They exclude:

- query, prompt, answer, or memory bodies;
- command, stdout, stderr, patch, or environment;
- secret, API key, token string, or connection URL;
- relation/edge paths and free-form failure notes;
- worker identity, lease timestamp, retry delay, or background task handle.

## 12. Testing strategy

The suite must cover:

1. immutable spec, assignment, plan, step, result, failure, snapshot, and summary contracts;
2. deterministic plan identity under input permutation;
3. seed-sensitive order and seed-insensitive pair identity;
4. order counts differ by at most one;
5. pair-count and worst-case token/latency budget rejection;
6. duplicate context rejection;
7. exact register retry and conflicting experiment reuse;
8. one schedulable step per pair;
9. control-first and treatment-first order enforcement;
10. policy/space/step mismatch rejection;
11. per-arm token and latency limit rejection;
12. exact result retry and conflicting retry;
13. complete trial creation only after both matched arms;
14. mismatched router decision/candidate/base ranking rejected before second-arm mutation;
15. failure and cancellation terminal semantics;
16. completed-trial filtering and deterministic order;
17. summary partition and actual-resource accounting;
18. at least 5,000 deterministic generated plans and registry traces preserving identities, balance, budgets, order, idempotence, state transitions, and privacy;
19. stable root-package exports.

## 13. Non-goals

V0 does not:

- execute an agent or model;
- call Temporal or create durable workflows;
- claim randomized assignment when the seed was not sampled externally;
- create worker leases or concurrency control;
- persist plans, results, or failures;
- retry failed arms under the same pair identity;
- replace Paired Rerank Policy Evaluation v0;
- write feedback or policy verdicts;
- schedule online production traffic;
- modify a database schema;
- merge or deploy any branch.

## 14. Success criteria

The feature is complete when an experiment can be planned within worst-case budgets, arm order is deterministically counterbalanced, the registry exposes only the correct next arm, exact retries are idempotent, mismatched pairs never become trials, 5,000 generated traces preserve all invariants, and the complete repository is green on Python 3.12 and 3.13 without database or protected-pipeline changes.
