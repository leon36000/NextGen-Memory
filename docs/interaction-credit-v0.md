# Interaction Credit v0

## Purpose

Post-Action Causal Credit v0 measures a memory by removing it from the full bundle. That paired leave-one-out intervention is trustworthy for isolated direct effects, but it cannot allocate value correctly when memories are substitutes or complements.

Interaction Credit v0 adds a dependency-aware cooperative-game layer:

```text
explicit prerequisite graph
+ matched coalition outcomes
+ exact or sampled valid topological orders
→ per-memory constrained-Shapley values
→ pairwise synergy/redundancy diagnostics
→ closure and uncertainty evidence
```

The feature is pure and non-persistent. It plans and evaluates normalized coalition evidence already supplied by a caller. It does not execute model rollouts, write feedback, alter Neon, or propagate values through the project provenance graph.

## Why leave-one-out is insufficient

### Redundant substitutes

Either memory is sufficient:

```text
v({A, B}) = 1
v({A}) = 1
v({B}) = 1
v({}) = 0
```

Full-bundle LOO assigns:

```text
A = v({A, B}) - v({B}) = 0
B = v({A, B}) - v({A}) = 0
```

It loses the entire bundle lift. Constrained Shapley averages the contexts where each memory arrives first and allocates `0.5` to each.

### Synergistic complements

Both memories are required:

```text
v({A, B}) = 1
v({A}) = 0
v({B}) = 0
v({}) = 0
```

Full-bundle LOO assigns one to each memory, producing a total of two for a bundle worth one. Shapley allocates `0.5` to each and preserves value closure.

## Explicit prerequisite graph

`MemoryDependencyGraph` receives canonical memory UUIDs and an explicit mapping from memory to prerequisite UUIDs. It validates:

- unique UUID players;
- known prerequisites;
- no self-dependencies;
- no cycles;
- dependency-closed coalitions;
- valid topological orders.

The graph freezes direct and transitive prerequisites and deterministically enumerates valid coalitions and topological orders.

No existing `memory_edges.relation` is interpreted automatically as a prerequisite. Relation semantics must be compiled deliberately by a caller.

## Current provenance-graph audit

The project space currently contains 18 `memory_edges` rows across heterogeneous relations:

| Relation | Count |
|---|---:|
| `authorizes` | 1 |
| `constrained_by` | 1 |
| `explains` | 1 |
| `followed_by` | 3 |
| `implements` | 1 |
| `motivates` | 1 |
| `superseded_by` | 4 |
| `supported_by` | 6 |

These relations mix sequence, support, correction, implementation, authorization, and explanation. They are not yet a typed causal DAG. Automatic provenance-credit propagation is therefore deliberately deferred.

## Matched coalition trials

`InteractionTrial` stores:

- a unique trial key;
- one frozen context SHA-256 fingerprint;
- one continuation SHA-256 fingerprint;
- an immutable mapping from `frozenset[UUID]` coalition to `OutcomeMeasurement`.

All trials in one estimate must share the same context hash. Missing coalitions remain missing; they are never treated as zero-valued outcomes.

Each `OutcomeMeasurement` supplies normalized score, success, token count, and latency. Score must remain in `[-1, 1]`.

## Precedence-constrained Shapley allocation

For a valid topological order `π` and memory `i`, let `Pπ(i)` be the memories before `i`:

```text
Δπ,t(i) = v_t(Pπ(i) ∪ {i}) - v_t(Pπ(i))
```

Within each matched trial:

```text
φ_t(i) = mean across complete selected orders of Δπ,t(i)
```

Across trials:

```text
φ(i)  = mean_t φ_t(i)
SE(i) = sample_stddev_t(φ_t(i)) / sqrt(T)
```

The same path calculation allocates score, token, and latency values. Positive token or latency allocation means the memory increases cost.

### Complete-path rule

A `(trial, order)` path contributes only when every prefix exists:

```text
{}
{π1}
{π1, π2}
...
full coalition
```

Partial paths are not averaged opportunistically. Doing so could overrepresent particular memories or predecessor sizes.

### Trial-level uncertainty

Different orders inside one trial reuse coalition outcomes and are correlated. v0 first averages across orders within the trial, then computes standard error across independent matched trials. It does not count order paths as independent samples.

## Exact and sampled modes

Default configuration:

| Parameter | Value |
|---|---:|
| exact player limit | 8 |
| minimum matched trials | 2 |
| maximum score standard error | 0.10 |
| closure tolerance | `1e-9` |
| maximum sampled orders | 256 |
| pair-interaction threshold | 0.05 |
| maximum pair standard error | 0.10 |

Exact mode requires all valid topological orders and at most eight players. Larger or budget-constrained games require an explicit sampled order set.

Per-memory results are withheld when:

- no selected order has a complete path;
- fewer than two matched trials are usable;
- cross-trial standard error exceeds the configured maximum.

## Mandatory value closure

Every complete order telescopes:

```text
Σ_i Δπ,t(i) = v_t(full) - v_t(empty)
```

The result reports:

```text
full_lift
allocated_value = Σ_i φ(i)
closure_residual = allocated_value - full_lift
```

A residual above `1e-9` raises an error. Closure is not an informational metric; it is an invariant that detects incomplete or inconsistent allocation.

## Pairwise interaction diagnostics

`PairwiseInteractionEstimator` is intentionally separate from the Shapley allocator. For incomparable memories `i` and `j`, it evaluates available valid contexts `S`:

```text
I_t,S(i,j) =
    v_t(S ∪ {i, j})
  - v_t(S ∪ {i})
  - v_t(S ∪ {j})
  + v_t(S)
```

It averages complete contexts inside each trial, then computes mean and standard error across trials.

Classifications:

- `synergy`: stable value at least `+0.05`;
- `redundancy`: stable value at most `-0.05`;
- `additive`: stable value inside the threshold band;
- `uncertain`: excessive cross-trial variance;
- `not_comparable`: one memory is a prerequisite ancestor of the other;
- `insufficient_contexts`: no complete four-coalition context;
- `insufficient_trials`: fewer than two matched trial estimates.

This is a **context-averaged second-difference diagnostic**, not a formal Shapley interaction index.

## Budgeted coalition planner

`AdaptiveOrderPlanner` does not execute evaluations. It returns valid topological orders and deterministic missing-coalition requests.

### Exact mode

When every valid coalition fits the budget, the planner returns all topological orders and the complete set of dependency-closed coalitions. Empty and full boundaries are requested first.

### Sampled mode

For larger or constrained games, a deterministic randomized Kahn algorithm generates candidate topological orders. Candidates are scored using:

- number of reusable missing prefixes;
- inverse-frequency player-position coverage;
- boundary priority.

The planner:

- never exceeds the hard coalition budget;
- never requests an invalid coalition;
- reuses cached coalitions;
- emits unique SHA-256 request keys;
- preserves complete prefix paths for selected orders;
- is deterministic for fixed graph, cache, seed, and budget.

## Deterministic simulation

Run:

```bash
python scripts/simulate_interaction_credit.py
```

Default controls:

```text
seed = 20260814
matched trials = 5
score noise = 0.01
sampled coalition budget = 12
```

Verified result:

| Metric | Result |
|---|---:|
| redundant LOO total | `0.0` |
| redundant Shapley total | `1.0` |
| redundancy second difference | `-1.0` |
| synergy LOO total | `2.0` |
| synergy Shapley total | `1.0` |
| synergy second difference | `+1.0` |
| exact closure error | `0.0` |
| sampled closure error | `0.0` |
| sampled rank agreement | `0.80` |
| sampled topological orders | `10` |
| requested coalitions | `12 / 12` |

The mixed game contains five memories:

- `A`: direct lift `+0.30`;
- `B`: direct lift `+0.25`;
- `C/D`: redundant shared lift `+0.25`;
- `E`: requires `B` and contributes `+0.20`.

The sampled estimator uses exactly the coalitions requested by the planner and the same underlying outcomes as exact evaluation. Its closure remains exact; the 0.80 rank agreement measures approximation under the 12-coalition budget.

## Research boundary

Interaction Credit v0 allocates direct coalition value. It does not yet answer how direct value should flow to:

- source evidence;
- consolidated procedures;
- derived summaries;
- superseded memories;
- causal ancestors in a provenance DAG.

Provenance Credit v0 remains gated on:

1. enough intervention-grounded direct feedback;
2. typed relation categories and directions;
3. explicit cycle and supersession semantics;
4. calibrated structural decay and uncertainty;
5. strict separation of direct and propagated credit.

## Security and privacy

Interaction contracts contain only:

- canonical UUIDs;
- normalized outcome metrics;
- coalition membership;
- cryptographic fingerprints;
- deterministic request hashes.

They contain no query, prompt, answer, command, output, note, secret, token, diff, patch, environment, connection string, or source payload.

## Deployment state

- no database migration;
- no production feedback write;
- no automatic rollout execution;
- no learned model or external ML dependency;
- no merge or default-branch mutation.

This tranche is a research and evaluation substrate. Persistence of interaction-aware credit will require a separate design and explicit owner approval.
