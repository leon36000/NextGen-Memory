# Interaction Credit v0 Design

## Status and authorization

The project owner approved continuation after Post-Action Causal Credit v0. The previous milestone explicitly identified interaction-aware subset attribution as the next research tranche. This specification turns that approval into a bounded implementation: structure-aware coalition valuation and budgeted precedence-constrained Shapley estimation.

Work is isolated on `feat/interaction-credit-v0`, stacked on `feat/post-action-causal-credit-v0`. It must not merge, retarget to `main`, modify the production Neon schema, or write production feedback without a later explicit owner decision.

## Why this tranche is separated from provenance propagation

The current project graph contains only 18 edges across eight heterogeneous relations (`authorizes`, `constrained_by`, `explains`, `followed_by`, `implements`, `motivates`, `superseded_by`, and `supported_by`). These edges are useful provenance facts, but they do not yet form a dense, typed causal DAG suitable for automatic reward propagation.

Propagating credit now would mix direct causal support, sequence, authorization, supersession, and implementation semantics. Interaction Credit v0 therefore solves the direct coalition problem first. Provenance propagation remains a separate future tranche gated on typed edge semantics and enough intervention-grounded node credit.

## Research basis

The design incorporates four recent findings:

1. **Removal protocol defines the game.** `Agents that Matter` shows that LOO, Shapley, introspective removal, and model replacement answer different questions; LOO is cost-effective but cannot resolve all interactions.
2. **Valid structure matters.** `SkillSV` shows that arbitrary flat coalitions can be invalid when units have dependencies and hierarchy. Attribution should average only over feasible orders and should not measure breakage.
3. **Budgeted adaptive sampling matters.** `SkillShapley` uses cache-aware one-flip evidence and adaptive coverage to approximate Shapley values under expensive evaluations.
4. **Semantic or graph propagation should follow direct attribution.** `Semantic Cooperative Games` and MemQ show that structure can allocate or propagate credit efficiently, but only after the support graph has clear semantics.

Primary references:

- https://arxiv.org/abs/2605.27621
- https://arxiv.org/abs/2608.04562
- https://arxiv.org/abs/2608.13173
- https://arxiv.org/abs/2607.18255
- https://arxiv.org/abs/2605.08374

## Problem

Leave-one-out from the full bundle handles isolated direct effects but fails in two important cases:

### Redundancy

Two memories are substitutes. Removing either one leaves the task successful:

```text
v({A, B}) = 1
v({A}) = 1
v({B}) = 1
v({}) = 0
```

Full-bundle LOO gives both memories zero even though the bundle lift is one.

### Synergy

Two memories are jointly necessary:

```text
v({C, D}) = 1
v({C}) = 0
v({D}) = 0
v({}) = 0
```

Full-bundle LOO gives both memories one, double-counting the total lift.

A Shapley-style allocation averages marginal contribution across valid predecessor contexts and preserves value closure. Structure constraints are required because some memories may depend on prerequisite memories; evaluating an invalid subset would measure broken context rather than contribution.

## Goals

1. Represent immutable matched coalition trials using existing normalized `OutcomeMeasurement` values.
2. Represent an explicit acyclic prerequisite graph over canonical memory UUIDs.
3. Accept only dependency-closed coalitions.
4. Estimate per-memory value by averaging marginal contributions over valid topological orders.
5. Use exact enumeration for small games and deterministic budgeted order sampling for larger games.
6. Average within each matched trial first, then compute uncertainty across trials to avoid treating correlated order paths as independent evidence.
7. Preserve score-value closure: the sum of player values must equal full-coalition lift within numerical tolerance.
8. Estimate pairwise second-difference effects and classify stable synergy or redundancy.
9. Produce explicit abstentions for insufficient trials, incomplete order paths, high variance, invalid structure, or non-comparable dependent pairs.
10. Plan additional coalition evaluations under a hard budget while maximizing reusable one-flip evidence and player-position coverage.
11. Generate a deterministic simulation demonstrating LOO failure, Shapley closure, interaction recovery, and budgeted-estimator behavior.
12. Introduce no database migration, feedback write, learned model, external ML dependency, or automatic rollout execution.

## Non-goals

- No production feedback persistence.
- No provenance-DAG credit propagation.
- No automatic calls to an LLM or environment evaluator.
- No Temporal workflow.
- No neural Shapley surrogate or learned interaction model.
- No arbitrary graph relation interpreted as a prerequisite automatically.
- No full high-order interaction tensor.
- No claim that the pairwise second-difference estimator is the formal Shapley interaction index.

## Approaches considered

### A. Full power-set Shapley

Evaluate all `2^n` coalitions and compute classical Shapley values. This is exact for unstructured games but becomes infeasible quickly and evaluates invalid dependency-breaking subsets.

### B. Leave-one-out plus pair tests

Add pair removals only after LOO ambiguity. This is simple and useful for diagnostics, but it is context-dependent, does not guarantee value closure, and can still misallocate higher-order interactions.

### C. Precedence-constrained Shapley over valid topological orders — selected

Treat prerequisite edges as a partial order. A valid order adds memories only after prerequisites. Every prefix is therefore a valid coalition. The value of a memory is its average marginal contribution when added across valid orders. Exact enumeration is used for small games; deterministic adaptive sampling is used under a budget.

This approach is selected because it:

- avoids malformed coalitions;
- preserves telescoping value closure on every complete order path;
- supports exact and approximate modes with one interface;
- reuses coalition evaluations across many order paths;
- separates direct allocation from later graph propagation.

## Architecture

```text
selected-and-used memory IDs
  + explicit prerequisite constraints
  -> MemoryDependencyGraph

matched coalition evaluations
  -> InteractionTrial[]

MemoryDependencyGraph + evaluated coalition cache + budget
  -> AdaptiveOrderPlanner
  -> selected valid topological orders
  -> missing coalition requests

complete order paths across matched trials
  -> PrecedenceShapleyEstimator
  -> per-memory score/token/latency values
  -> closure diagnostics and abstentions

available four-coalition contexts
  -> PairwiseInteractionEstimator
  -> synergy / redundancy / additive / uncertain diagnostics
```

## Core contracts

### `MemoryDependencyGraph`

Contains:

- sorted tuple of canonical player UUIDs;
- immutable mapping `memory_id -> prerequisites`;
- transitive prerequisite closure;
- deterministic topological-order generation.

Validation:

- every player and prerequisite is a UUID;
- prerequisites belong to the player set;
- no self-dependency;
- no cycle;
- no duplicate players.

A coalition is valid when every included memory's full prerequisite closure is included.

Relation interpretation is external. Callers may compile selected `memory_edges` relations into prerequisites, but v0 never assumes that `supported_by`, `implements`, or another relation means `requires`.

### `InteractionTrial`

One matched evaluation contains:

- non-empty `trial_key`;
- 64-character lowercase `context_hash`;
- 64-character lowercase `continuation_hash`;
- immutable mapping from `frozenset[UUID]` coalition to `OutcomeMeasurement`.

All trials in one estimate must share the same context hash. Continuation hashes may differ across trials but are fixed across all coalitions inside each trial.

### `CoalitionRequest`

Contains:

- canonical coalition;
- order identifier;
- prefix position;
- reason (`required_boundary`, `missing_prefix`, or `coverage`);
- deterministic request key.

Requests contain UUIDs and hashes only; no prompt or source payload.

## Precedence-constrained Shapley estimator

For valid topological order `π` and player `i`, let `Pπ(i)` be the players preceding `i`. The per-trial marginal is:

```text
Δπ,t(i) = v_t(Pπ(i) ∪ {i}) - v_t(Pπ(i))
```

For one trial, average across complete selected orders:

```text
φ_t(i) = mean_π Δπ,t(i)
```

Across matched trials:

```text
φ(i) = mean_t φ_t(i)
SE(i) = sample_stddev_t(φ_t(i)) / sqrt(T)
```

The same calculation is applied separately to:

- outcome score;
- tokens;
- latency.

Positive token or latency value means the memory increases cost on average.

### Why uncertainty is computed across trials

Different order paths within one trial reuse the same underlying outcomes and are correlated. Treating each path as an independent sample would produce overconfident standard errors. v0 averages across orders within a trial, then estimates uncertainty only across matched trials.

### Complete-path rule

A `(trial, order)` path is usable only when every prefix from empty coalition to full coalition has an evaluated outcome. Partial paths are not averaged opportunistically, because missing edges could bias specific players or predecessor sizes.

### Exact and approximate modes

- If player count is at or below `exact_player_limit` and every valid order is supplied or enumerable, mode is `exact`.
- Otherwise mode is `sampled` using planner-selected valid orders.
- The estimator reports order count, usable trial count, path coverage, and per-player uncertainty.

### Default configuration

| Parameter | Value |
|---|---:|
| exact player limit | 8 |
| minimum matched trials | 2 |
| maximum per-player standard error | 0.10 |
| closure tolerance | 1e-9 |
| maximum sampled orders | 256 |
| pairwise interaction threshold | 0.05 |
| pairwise maximum standard error | 0.10 |

## Value closure

Every complete order telescopes:

```text
Σ_i Δπ,t(i) = v_t(full) - v_t(empty)
```

Averaging preserves the identity. The result reports:

```text
full_lift = mean_t[v_t(full) - v_t(empty)]
allocated_value = Σ_i φ(i)
closure_residual = allocated_value - full_lift
```

A residual above tolerance is a hard error, not a warning. This detects implementation errors, incomplete paths, and inconsistent aggregation.

## Pairwise interaction diagnostics

For incomparable players `i` and `j`, and valid base coalition `S` excluding both:

```text
I_t,S(i,j) =
    v_t(S ∪ {i,j})
  - v_t(S ∪ {i})
  - v_t(S ∪ {j})
  + v_t(S)
```

Within each trial, average all available valid base contexts. Across trials, compute mean and standard error.

Classification:

- `synergy`: stable mean ≥ `+interaction_threshold`;
- `redundancy`: stable mean ≤ `-interaction_threshold`;
- `additive`: stable absolute mean below threshold;
- `uncertain`: standard error too high or too few trials;
- `not_comparable`: one player is a prerequisite ancestor of the other;
- `insufficient_contexts`: no complete four-coalition context.

This is explicitly named a **context-averaged second-difference diagnostic**, not a formal Shapley interaction index.

## Adaptive order planner

### Exact small-game mode

For small games, enumerate all deterministic topological orders. Request the union of missing prefixes, bounded by the caller's budget. If the full exact set does not fit, switch to sampled mode rather than claiming exactness.

### Sampled mode

Generate candidate topological orders using a deterministic randomized Kahn algorithm seeded by configuration. Score each candidate using:

```text
new_coalition_count
+ coverage_weight * Σ_i 1 / sqrt(position_count[i, position_i] + 1)
+ boundary_weight for missing empty/full coalitions
```

Select the best order whose missing prefixes fit the remaining budget. Update coverage counts and repeat until budget or order limit is exhausted.

Properties:

- deterministic for fixed seed, graph, cache, and budget;
- never requests an invalid coalition;
- never exceeds budget;
- always prioritizes empty and full boundaries;
- reuses already evaluated coalitions;
- exposes selected orders and requested coalitions for audit;
- does not execute evaluations.

## Error handling and abstention

Hard errors:

- malformed UUIDs or hashes;
- cyclic dependency graph;
- invalid coalition in a trial;
- mixed context hashes;
- duplicate trial keys;
- non-finite outcome values;
- closure failure;
- claimed exact mode without complete valid-order coverage.

Per-memory abstention:

- insufficient matched trials;
- no complete sampled order path;
- high standard error.

Per-pair abstention:

- dependency comparability;
- insufficient four-coalition contexts;
- insufficient trials;
- high standard error.

Infrastructure failures propagate. No missing evaluation is converted into a zero value.

## Security and privacy

- Contracts contain canonical UUIDs, normalized metrics, and cryptographic fingerprints only.
- No query, prompt, answer, command, output, note, secret, token, diff, patch, environment, or source payload enters interaction credit.
- No database write exists in v0.
- No graph relation is assigned prerequisite semantics implicitly.

## Testing strategy

### Dependency graph

1. validates and freezes acyclic prerequisites;
2. rejects self-dependencies, unknown nodes, duplicates, and cycles;
3. generates deterministic valid topological orders;
4. rejects non-closed coalitions.

### Exact attribution

1. additive game recovers exact player values;
2. redundancy game splits lift and closes value;
3. synergy game splits lift without double-counting;
4. prerequisite game uses only valid orders;
5. token and latency values preserve sign;
6. mixed contexts and duplicate trials fail;
7. incomplete paths abstain rather than bias;
8. high trial variance abstains;
9. closure residual remains within tolerance.

### Pair diagnostics

1. redundant pair is negative;
2. synergistic pair is positive;
3. additive pair is near zero;
4. ancestor/descendant pair is not comparable;
5. missing four-coalition context abstains;
6. high variance is uncertain.

### Planner

1. exact mode enumerates all valid orders when budget permits;
2. sampled mode is deterministic;
3. budget is never exceeded;
4. requested coalitions are valid and unique;
5. empty/full boundaries are prioritized;
6. existing cache entries are reused;
7. position coverage improves across selected orders.

### Simulation

A fixed-seed simulation must show:

- LOO gives zero to redundant substitutes;
- LOO double-counts synergistic complements;
- precedence-Shapley allocations preserve closure;
- pair diagnostics recover redundancy and synergy signs;
- budgeted sampled estimates approach exact rankings;
- byte-identical JSON across repeated runs.

Integrated verification requires Ruff and the complete test suite on Python 3.12 and 3.13.

## Deliverables

- `src/nextgen_memory/interaction_credit.py`
- `src/nextgen_memory/interaction_planner.py`
- `scripts/simulate_interaction_credit.py`
- focused tests and public exports
- `docs/interaction-credit-v0.md`
- updated README
- stacked draft PR with RED→GREEN evidence
- deterministic simulation artifact and verification report
- append-only Neon project checkpoint only; no schema migration

## Future tranche: Provenance Credit v0

Provenance propagation begins only after:

1. direct intervention-grounded feedback exists for a meaningful set of nodes;
2. graph relations are classified as causal, derivational, temporal, administrative, or corrective;
3. propagation direction is explicit per relation;
4. cycles and supersession semantics are resolved;
5. structural decay and uncertainty are calibrated on held-out tasks;
6. propagated credit is stored separately from direct credit.

The future method may combine MemQ-style structural TD traces with confidence decay, but direct and propagated evidence must never be conflated.
