# Interaction Credit v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build dependency-aware coalition valuation that resolves redundancy and synergy using exact or budgeted precedence-constrained Shapley estimates, with deterministic planning and pairwise interaction diagnostics.

**Architecture:** A pure `interaction_credit` module owns immutable dependency graphs, matched coalition trials, exact/sampled attribution, closure diagnostics, and pairwise second differences. A separate `interaction_planner` module plans valid coalition evaluations under a hard budget by selecting topological orders that maximize reusable missing prefixes and player-position coverage. No database write, model call, or rollout execution is introduced.

**Tech Stack:** Python 3.12+, immutable dataclasses, standard-library `itertools`, `random`, `statistics`, `hashlib`, UUIDs, pytest, Ruff, GitHub Actions.

## Global Constraints

- Work only on `feat/interaction-credit-v0`, stacked on `feat/post-action-causal-credit-v0`.
- Do not merge, retarget to `main`, modify production Neon, or write production feedback.
- Do not add NumPy, SciPy, PyTorch, a learned model, an LLM evaluator, or another external runtime dependency.
- No graph relation receives prerequisite semantics implicitly; callers provide explicit prerequisites.
- Coalitions must be dependency-closed.
- Missing evaluations never become zero-valued outcomes.
- A `(trial, order)` contributes only when every prefix from empty to full is evaluated.
- Average order marginals within a trial before estimating uncertainty across trials.
- Closure residual above `1e-9` is a hard error.
- Contracts contain only UUIDs, normalized metrics, and cryptographic fingerprints.
- Record integrated RED CI evidence before each production slice.
- Final CI must pass Ruff and the complete test suite on Python 3.12 and 3.13.

---

### Task 1: Dependency graph and matched coalition-trial contracts

**Files:**
- Create: `tests/test_interaction_contracts.py`
- Create after RED: `src/nextgen_memory/interaction_credit.py`

**Interfaces:**
- Consumes: `OutcomeMeasurement` from `nextgen_memory.causal_credit`.
- Produces:
  - `MemoryDependencyGraph(players, prerequisites=None)`
  - `InteractionTrial(trial_key, context_hash, continuation_hash, outcomes)`
  - `InteractionCreditConfig(...)`
  - `InteractionEstimationMode`
  - `InteractionCreditAbstentionReason`
  - `PairInteractionKind`

- [ ] **Step 1: Write failing dependency-graph tests**

Create `tests/test_interaction_contracts.py` with fixed UUIDs and tests:

```python
def test_dependency_graph_freezes_transitive_prerequisites_and_validates_coalitions():
    graph = MemoryDependencyGraph(
        players=(a, b, c),
        prerequisites={c: frozenset({b}), b: frozenset({a})},
    )
    assert graph.prerequisites_of(c) == frozenset({a, b})
    assert graph.is_valid_coalition(frozenset({a, b, c})) is True
    assert graph.is_valid_coalition(frozenset({b, c})) is False


def test_dependency_graph_rejects_unknown_self_duplicate_and_cycles(): ...


def test_topological_orders_are_deterministic_and_valid():
    graph = MemoryDependencyGraph(
        players=(a, b, c),
        prerequisites={c: frozenset({a})},
    )
    orders = graph.topological_orders()
    assert orders == tuple(sorted(orders, key=lambda order: tuple(map(str, order))))
    assert all(graph.is_valid_order(order) for order in orders)
```

Use separate assertions for:

- duplicate player UUID;
- unknown prerequisite;
- self-dependency;
- cycle;
- coalition containing unknown UUID;
- order missing or duplicating a player.

- [ ] **Step 2: Write failing trial/config tests**

Assert:

```python
trial = InteractionTrial(
    trial_key="trial-1",
    context_hash="a" * 64,
    continuation_hash="b" * 64,
    outcomes={
        frozenset(): OutcomeMeasurement(0.0, False),
        frozenset({a}): OutcomeMeasurement(0.4, True),
    },
)
assert tuple(trial.outcomes) == (frozenset(), frozenset({a}))
with pytest.raises(TypeError):
    trial.outcomes[frozenset()] = OutcomeMeasurement(1.0, True)
```

Reject blank trial keys, malformed hashes, non-frozenset coalition keys, non-UUID members, duplicate normalized coalitions, and non-`OutcomeMeasurement` values.

Validate exact defaults:

```python
config = InteractionCreditConfig()
assert config.exact_player_limit == 8
assert config.min_trials == 2
assert config.max_standard_error == 0.10
assert config.closure_tolerance == 1e-9
assert config.max_sampled_orders == 256
assert config.interaction_threshold == 0.05
assert config.max_interaction_standard_error == 0.10
```

Reject boolean/non-integer limits, non-finite thresholds, negative tolerances, and `interaction_threshold <= 0`.

- [ ] **Step 3: Push tests-only commit and record integrated RED**

```bash
git add tests/test_interaction_contracts.py
git commit -m "test: define interaction credit contracts"
git push -u origin feat/interaction-credit-v0
```

Open a stacked draft PR targeting `feat/post-action-causal-credit-v0`. GitHub CI must pass Ruff and fail only because `nextgen_memory.interaction_credit` does not exist.

- [ ] **Step 4: Implement immutable graph and trial contracts**

In `src/nextgen_memory/interaction_credit.py`:

```python
class MemoryDependencyGraph:
    def __init__(
        self,
        players: Sequence[UUID],
        prerequisites: Mapping[UUID, Collection[UUID]] | None = None,
    ) -> None: ...

    @property
    def players(self) -> tuple[UUID, ...]: ...

    def direct_prerequisites_of(self, memory_id: UUID) -> frozenset[UUID]: ...
    def prerequisites_of(self, memory_id: UUID) -> frozenset[UUID]: ...
    def is_ancestor(self, ancestor: UUID, descendant: UUID) -> bool: ...
    def is_valid_coalition(self, coalition: frozenset[UUID]) -> bool: ...
    def validate_coalition(self, coalition: frozenset[UUID]) -> None: ...
    def is_valid_order(self, order: Sequence[UUID]) -> bool: ...
    def topological_orders(self) -> tuple[tuple[UUID, ...], ...]: ...
```

Enumerate topological orders with deterministic backtracking over lexicographically sorted available UUIDs. Freeze mappings using `MappingProxyType`.

Implement `InteractionTrial` as a frozen slotted dataclass. Sort outcome items by `(len(coalition), sorted UUID strings)` before freezing so iteration is deterministic.

- [ ] **Step 5: Run focused GREEN and Ruff**

```bash
python -m pytest tests/test_interaction_contracts.py -q
python -m ruff check src/nextgen_memory/interaction_credit.py tests/test_interaction_contracts.py
```

Expected: all focused tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/nextgen_memory/interaction_credit.py tests/test_interaction_contracts.py
git commit -m "feat: add interaction credit contracts"
```

---

### Task 2: Exact and sampled precedence-constrained Shapley estimator

**Files:**
- Modify: `src/nextgen_memory/interaction_credit.py`
- Create: `tests/test_precedence_shapley.py`

**Interfaces:**
- Produces:
  - `MemoryInteractionCredit`
  - `MemoryInteractionAbstention`
  - `InteractionCreditResult`
  - `PrecedenceShapleyEstimator.estimate(graph, trials, orders=None)`

Exact signatures:

```python
@dataclass(frozen=True, slots=True)
class MemoryInteractionCredit:
    memory_id: UUID
    score_value: float
    score_standard_error: float
    token_value: float
    latency_value_ms: float
    trial_count: int
    order_count: int


@dataclass(frozen=True, slots=True)
class MemoryInteractionAbstention:
    memory_id: UUID
    reason: InteractionCreditAbstentionReason
    usable_trial_count: int
    score_standard_error: float | None = None


@dataclass(frozen=True, slots=True)
class InteractionCreditResult:
    mode: InteractionEstimationMode
    players: tuple[UUID, ...]
    orders: tuple[tuple[UUID, ...], ...]
    credits: tuple[MemoryInteractionCredit, ...]
    abstentions: tuple[MemoryInteractionAbstention, ...]
    usable_trial_count: int
    full_lift: float
    allocated_value: float
    closure_residual: float
    context_set_hash: str
    continuation_set_hash: str


class PrecedenceShapleyEstimator:
    def __init__(self, config: InteractionCreditConfig | None = None) -> None: ...

    def estimate(
        self,
        graph: MemoryDependencyGraph,
        trials: Sequence[InteractionTrial],
        *,
        orders: Sequence[Sequence[UUID]] | None = None,
    ) -> InteractionCreditResult: ...
```

- [ ] **Step 1: Write failing exact-allocation tests**

Create games with at least two identical matched trials.

Additive game:

```python
v(S) = 0.2 * [a in S] + 0.3 * [b in S] + 0.4 * [c in S]
```

Assert exact values `(0.2, 0.3, 0.4)`, zero standard errors, full lift `0.9`, allocated value `0.9`, and residual approximately zero.

Redundancy game:

```python
v(S) = 1.0 if a in S or b in S else 0.0
```

Assert exact values `0.5` and `0.5`. Compute full-bundle LOO in the test and assert it is zero for both.

Synergy game:

```python
v(S) = 1.0 if {a, b} <= S else 0.0
```

Assert exact values `0.5` and `0.5`. Compute full-bundle LOO and assert it gives `1.0` to both while Shapley closes at one.

- [ ] **Step 2: Write failing structure, cost, and uncertainty tests**

Use `b` requiring `a`; assert only `(a, b)` is valid and the estimator never evaluates `(b,)`.

Token/latency game:

```python
OutcomeMeasurement(
    score=score,
    task_success=score > 0,
    tokens=100 + 20 * [a in S] - 5 * [b in S],
    latency_ms=10 + 3 * [a in S] + 1 * [b in S],
)
```

Assert `a.token_value == 20`, `b.token_value == -5`, `a.latency_value_ms == 3`, and `b.latency_value_ms == 1`.

Add tests for:

- mixed context hashes -> hard `ValueError`;
- duplicate trial keys -> hard `ValueError`;
- invalid coalition in a trial -> hard `ValueError`;
- explicit invalid order -> hard `ValueError`;
- one trial -> per-memory `INSUFFICIENT_TRIALS` abstention;
- missing one prefix in every order -> `NO_COMPLETE_PATH` abstention;
- high cross-trial variance -> `HIGH_VARIANCE` abstention;
- `orders=None` with player count above exact limit -> hard error requiring sampled orders;
- exact mode only when every valid topological order is present;
- closure mismatch injected through a test-only monkeypatch -> hard error.

- [ ] **Step 3: Run focused RED**

```bash
python -m pytest tests/test_precedence_shapley.py -q
```

Expected: missing estimator/result contracts.

- [ ] **Step 4: Implement complete-order trial aggregation**

Algorithm:

```python
for trial in trials:
    complete_orders = [
        order for order in selected_orders
        if all(prefix in trial.outcomes for prefix in prefixes(order))
    ]
    if not complete_orders:
        continue
    for memory_id in graph.players:
        per_order_score = []
        per_order_tokens = []
        per_order_latency = []
        for order in complete_orders:
            before, after = edge_for(order, memory_id)
            per_order_score.append(v(after).score - v(before).score)
            per_order_tokens.append(v(after).tokens - v(before).tokens)
            per_order_latency.append(v(after).latency_ms - v(before).latency_ms)
        per_trial[memory_id].append(
            (
                fmean(per_order_score),
                fmean(per_order_tokens),
                fmean(per_order_latency),
            )
        )
```

Compute standard error only across trial-level score values. For `T == 1`, represent uncertainty as infinity internally and abstain before constructing finite result contracts.

Compute context and continuation set hashes using SHA-256 over sorted unique fingerprints.

- [ ] **Step 5: Enforce exact-mode and closure invariants**

Exact mode requires:

```python
len(graph.players) <= config.exact_player_limit
and selected_orders == graph.topological_orders()
```

Otherwise use `SAMPLED` mode. Reject omitted orders above the exact limit.

For every usable trial, require empty and full coalition outcomes through the complete-path rule. Calculate closure using all player means, including high-variance estimates before abstention. Reject `abs(closure_residual) > closure_tolerance`.

- [ ] **Step 6: Run focused GREEN and Ruff**

```bash
python -m pytest tests/test_precedence_shapley.py -q
python -m ruff check src/nextgen_memory/interaction_credit.py tests/test_precedence_shapley.py
```

- [ ] **Step 7: Commit**

```bash
git add src/nextgen_memory/interaction_credit.py tests/test_precedence_shapley.py
git commit -m "feat: estimate precedence constrained Shapley credit"
```

---

### Task 3: Pairwise interaction diagnostics

**Files:**
- Modify: `src/nextgen_memory/interaction_credit.py`
- Create: `tests/test_pairwise_interactions.py`

**Interfaces:**
- Produces:
  - `PairInteractionEstimate`
  - `PairwiseInteractionEstimator.estimate(graph, trials)`

```python
@dataclass(frozen=True, slots=True)
class PairInteractionEstimate:
    left_memory_id: UUID
    right_memory_id: UUID
    kind: PairInteractionKind
    mean_second_difference: float | None
    standard_error: float | None
    trial_count: int
    context_count: int


class PairwiseInteractionEstimator:
    def __init__(self, config: InteractionCreditConfig | None = None) -> None: ...

    def estimate(
        self,
        graph: MemoryDependencyGraph,
        trials: Sequence[InteractionTrial],
    ) -> tuple[PairInteractionEstimate, ...]: ...
```

- [ ] **Step 1: Write failing sign and classification tests**

For redundancy `v(S)=1 if a or b`, assert mean second difference `-1.0` and `REDUNDANCY`.

For synergy `v(S)=1 if a and b`, assert `+1.0` and `SYNERGY`.

For additive `v(S)=0.2[a]+0.3[b]`, assert approximately zero and `ADDITIVE`.

- [ ] **Step 2: Write failing abstention tests**

Assert:

- ancestor/descendant pair -> `NOT_COMPARABLE`, values `None`;
- no complete four-coalition context -> `INSUFFICIENT_CONTEXTS`;
- one trial -> `INSUFFICIENT_TRIALS`;
- high cross-trial variance -> `UNCERTAIN`;
- output pairs are sorted lexicographically and appear once.

- [ ] **Step 3: Run focused RED**

```bash
python -m pytest tests/test_pairwise_interactions.py -q
```

- [ ] **Step 4: Implement context-averaged second differences**

For each incomparable pair `(i, j)` and trial, enumerate outcome coalitions `S` that exclude both and satisfy availability of:

```python
S
S | {i}
S | {j}
S | {i, j}
```

Validate all four coalitions through the dependency graph. Average second differences within the trial, then calculate mean and standard error across trials. Classify with the config threshold and standard-error limit.

- [ ] **Step 5: Run focused GREEN and Ruff**

```bash
python -m pytest tests/test_pairwise_interactions.py -q
python -m ruff check src/nextgen_memory/interaction_credit.py tests/test_pairwise_interactions.py
```

- [ ] **Step 6: Commit**

```bash
git add src/nextgen_memory/interaction_credit.py tests/test_pairwise_interactions.py
git commit -m "feat: diagnose pairwise memory interactions"
```

---

### Task 4: Deterministic adaptive topological-order planner

**Files:**
- Create: `tests/test_interaction_planner.py`
- Create after RED: `src/nextgen_memory/interaction_planner.py`

**Interfaces:**
- Consumes: `MemoryDependencyGraph`.
- Produces:
  - `CoalitionRequestReason`
  - `CoalitionRequest`
  - `InteractionOrderPlan`
  - `AdaptiveOrderPlannerConfig`
  - `AdaptiveOrderPlanner.plan(graph, evaluated_coalitions, budget)`

```python
@dataclass(frozen=True, slots=True)
class AdaptiveOrderPlannerConfig:
    seed: int = 20260814
    exact_player_limit: int = 8
    max_orders: int = 256
    candidate_pool_size: int = 64
    coverage_weight: float = 1.0
    boundary_weight: float = 1000.0


@dataclass(frozen=True, slots=True)
class CoalitionRequest:
    coalition: frozenset[UUID]
    order_id: str
    prefix_position: int
    reason: CoalitionRequestReason
    request_key: str


@dataclass(frozen=True, slots=True)
class InteractionOrderPlan:
    mode: InteractionEstimationMode
    orders: tuple[tuple[UUID, ...], ...]
    requests: tuple[CoalitionRequest, ...]
    reused_coalition_count: int
    requested_coalition_count: int
    budget: int
    exact_complete: bool
```

- [ ] **Step 1: Write failing exact-plan tests**

For three independent players and a budget covering all unique prefixes:

```python
plan = AdaptiveOrderPlanner().plan(graph, evaluated_coalitions=(), budget=8)
assert plan.mode is InteractionEstimationMode.EXACT
assert plan.orders == graph.topological_orders()
assert plan.exact_complete is True
assert {request.coalition for request in plan.requests} == set(graph.valid_coalitions())
assert len(plan.requests) <= 8
```

Add `MemoryDependencyGraph.valid_coalitions()` in Task 1 implementation if needed; it returns all dependency-closed subsets sorted by size and UUIDs.

- [ ] **Step 2: Write failing sampled-plan tests**

Use nine independent players. Assert:

- fixed seed produces identical plans;
- different seed can produce a different order set;
- budget is never exceeded;
- every request coalition is valid;
- requests are unique;
- empty and full are first when missing;
- cached empty/full are reused and not requested;
- every selected order's missing prefixes are present in requests;
- position coverage for each player has at least two distinct positions when budget permits;
- invalid budget, seed, weights, and cache coalitions fail closed.

- [ ] **Step 3: Push tests and record RED**

```bash
python -m pytest tests/test_interaction_planner.py -q
```

Expected: missing `nextgen_memory.interaction_planner`.

- [ ] **Step 4: Implement exact planning**

Enumerate unique prefixes for all valid orders. If all missing prefixes fit the budget, return exact mode. Requests are sorted with empty first, full second, then `(size, UUID tuple)`.

- [ ] **Step 5: Implement deterministic sampled planning**

Use randomized Kahn order generation:

```python
while available:
    choice = rng.choice(sorted(available, key=str))
    order.append(choice)
```

Generate `candidate_pool_size` candidate orders per round. For each candidate:

```python
missing = unique prefixes not in cache or already requested
coverage = sum(
    1 / sqrt(position_counts[(memory_id, position)] + 1)
    for position, memory_id in enumerate(order)
)
score = len(missing) + coverage_weight * coverage
```

Add `boundary_weight` when empty/full remain missing. Select the highest score whose missing set fits the remaining budget. Break ties by order UUID strings. Stop when no candidate fits or `max_orders` is reached.

Every request receives deterministic:

```python
request_key = sha256(
    "interaction-credit-v0:" + ":".join(sorted(str(id) for id in coalition))
).hexdigest()
```

- [ ] **Step 6: Run focused GREEN and Ruff**

```bash
python -m pytest tests/test_interaction_planner.py -q
python -m ruff check src/nextgen_memory/interaction_planner.py tests/test_interaction_planner.py
```

- [ ] **Step 7: Commit**

```bash
git add src/nextgen_memory/interaction_planner.py tests/test_interaction_planner.py
git commit -m "feat: plan budgeted interaction coalitions"
```

---

### Task 5: Deterministic interaction-credit simulation

**Files:**
- Create: `tests/test_interaction_credit_simulation.py`
- Create after RED: `scripts/simulate_interaction_credit.py`

**Interfaces:**
- Produces:
  - `SimulationConfig(seed=20260814, trial_count=5, noise_stddev=0.01, sampled_order_budget=12)`
  - `SimulationResult`
  - `simulate(config) -> SimulationResult`
  - deterministic CLI JSON.

- [ ] **Step 1: Write failing simulation tests**

Assert default results satisfy:

```python
assert result.redundant_loo_total == pytest.approx(0.0)
assert result.redundant_shapley_total == pytest.approx(1.0, abs=0.03)
assert result.redundancy_interaction < -0.90
assert result.synergy_loo_total == pytest.approx(2.0)
assert result.synergy_shapley_total == pytest.approx(1.0, abs=0.03)
assert result.synergy_interaction > 0.90
assert result.exact_closure_error <= 1e-9
assert result.sampled_closure_error <= 1e-9
assert result.sampled_rank_agreement >= 0.80
```

Also assert two runs return identical dataclasses and byte-identical sorted JSON.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_interaction_credit_simulation.py -q
```

Expected: simulation module missing.

- [ ] **Step 3: Implement three controlled games**

Use fixed UUIDs and standard-library randomness.

1. Redundant pair: either memory provides score one.
2. Synergistic pair: both memories required for score one.
3. Five-player mixed game:

```text
A = +0.30
B = +0.25
C/D redundant shared lift = +0.25
E requires B and adds +0.20
```

Add Gaussian score noise per matched trial, clipped to `[-1, 1]`. Generate complete coalition outcomes for exact estimation. Use the adaptive planner to select sampled orders and retain only the prefixes needed for those orders in a second trial set.

Compute rank agreement as pairwise concordance between exact and sampled score-value rankings.

- [ ] **Step 4: Verify deterministic command output**

```bash
python scripts/simulate_interaction_credit.py > /tmp/interaction-a.json
python scripts/simulate_interaction_credit.py > /tmp/interaction-b.json
cmp /tmp/interaction-a.json /tmp/interaction-b.json
sha256sum /tmp/interaction-a.json
```

- [ ] **Step 5: Run focused GREEN and Ruff**

```bash
python -m pytest tests/test_interaction_credit_simulation.py -q
python -m ruff check scripts/simulate_interaction_credit.py tests/test_interaction_credit_simulation.py
```

- [ ] **Step 6: Commit**

```bash
git add scripts/simulate_interaction_credit.py tests/test_interaction_credit_simulation.py
git commit -m "test: simulate interaction-aware memory credit"
```

---

### Task 6: Public API, documentation, and integrated verification

**Files:**
- Modify: `src/nextgen_memory/__init__.py`
- Create: `tests/test_interaction_credit_public_api.py`
- Create: `docs/interaction-credit-v0.md`
- Modify: `README.md`

**Interfaces:**
- Exports every approved graph, trial, estimator, pair diagnostic, planner, and request contract.

- [ ] **Step 1: Write failing public-API test**

Import from `nextgen_memory`:

```python
MemoryDependencyGraph
InteractionTrial
InteractionCreditConfig
InteractionEstimationMode
InteractionCreditAbstentionReason
MemoryInteractionCredit
MemoryInteractionAbstention
InteractionCreditResult
PrecedenceShapleyEstimator
PairInteractionKind
PairInteractionEstimate
PairwiseInteractionEstimator
AdaptiveOrderPlannerConfig
CoalitionRequestReason
CoalitionRequest
InteractionOrderPlan
AdaptiveOrderPlanner
```

Assert importing `nextgen_memory` does not load `numpy`, `scipy`, `torch`, `tensorflow`, `pymongo`, or `psycopg`.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/test_interaction_credit_public_api.py -q
```

Expected: root exports are absent.

- [ ] **Step 3: Add exports and documentation**

`docs/interaction-credit-v0.md` must document:

- redundancy and synergy examples;
- precedence-constrained allocation equation;
- complete-path and trial-level uncertainty rules;
- exact versus sampled mode;
- closure invariant;
- pair diagnostic naming limitation;
- planner budget behavior;
- simulation output and SHA-256;
- current graph audit and why provenance propagation is deferred;
- deployment/non-persistence boundary.

Update README architecture, repository map, and status. Do not claim provenance propagation is implemented.

- [ ] **Step 4: Run full verification**

```bash
python -m pytest -q
python -m ruff check src tests scripts
python -m compileall -q src scripts
python -m build --no-isolation
```

Inspect:

```bash
git diff --check
grep -RInE 'postgres(ql)?://|mongodb\+srv://|api[_-]?key\s*=' src tests scripts docs README.md || true
grep -RInE 'query_text|stdout|stderr|prompt|secret|token|patch_text' src/nextgen_memory/interaction_credit.py src/nextgen_memory/interaction_planner.py || true
```

- [ ] **Step 5: Update stacked draft PR with exact evidence**

Record:

- every RED workflow ID and expected missing component;
- final GREEN workflow ID;
- Python 3.12 and 3.13 test counts;
- deterministic simulation metrics and SHA-256;
- exact and sampled closure results;
- current production graph relation counts;
- confirmation of no schema migration, feedback write, merge, or `main` mutation.

- [ ] **Step 6: Write append-only project checkpoint**

Insert `ENGINEERING_V0_6_INTERACTION_CREDIT_VERIFIED` into `ngm.project_checkpoints` only after all verification evidence is fresh. Derive it from `c1f8668e-84b7-4906-9dfc-9d06daae8f3f`. Store PR number, head SHA, workflow ID, test counts, simulation metrics, graph audit, and production non-mutation.

- [ ] **Step 7: Commit documentation and exports**

```bash
git add src/nextgen_memory/__init__.py tests/test_interaction_credit_public_api.py docs/interaction-credit-v0.md README.md
git commit -m "docs: expose and verify interaction credit v0"
```
