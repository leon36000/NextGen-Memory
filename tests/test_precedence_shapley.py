from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest

from nextgen_memory.causal_credit import OutcomeMeasurement
from nextgen_memory.interaction_credit import (
    InteractionCreditAbstentionReason,
    InteractionCreditConfig,
    InteractionEstimationMode,
    InteractionTrial,
    MemoryDependencyGraph,
    PrecedenceShapleyEstimator,
)

MEMORY_A = UUID("00000000-0000-5000-8000-000000000001")
MEMORY_B = UUID("00000000-0000-5000-8000-000000000002")
MEMORY_C = UUID("00000000-0000-5000-8000-000000000003")
CONTEXT_HASH = "a" * 64


def make_trial(
    graph: MemoryDependencyGraph,
    key: str,
    score_fn: Callable[[frozenset[UUID]], float],
    *,
    token_fn: Callable[[frozenset[UUID]], int] | None = None,
    latency_fn: Callable[[frozenset[UUID]], float] | None = None,
    omit: frozenset[frozenset[UUID]] = frozenset(),
    context_hash: str = CONTEXT_HASH,
) -> InteractionTrial:
    outcomes = {}
    for coalition in graph.valid_coalitions():
        if coalition in omit:
            continue
        score = score_fn(coalition)
        outcomes[coalition] = OutcomeMeasurement(
            score=score,
            task_success=score > 0,
            tokens=token_fn(coalition) if token_fn else 100,
            latency_ms=latency_fn(coalition) if latency_fn else 10.0,
        )
    return InteractionTrial(
        trial_key=key,
        context_hash=context_hash,
        continuation_hash=(key.encode("utf-8").hex() + "0" * 64)[:64],
        outcomes=outcomes,
    )


def credit_map(result):
    return {credit.memory_id: credit for credit in result.credits}


def test_additive_game_recovers_exact_values_and_closes() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B, MEMORY_C))

    def value(coalition: frozenset[UUID]) -> float:
        return (
            0.2 * (MEMORY_A in coalition)
            + 0.3 * (MEMORY_B in coalition)
            + 0.4 * (MEMORY_C in coalition)
        )

    trials = (
        make_trial(graph, "trial-1", value),
        make_trial(graph, "trial-2", value),
    )

    result = PrecedenceShapleyEstimator().estimate(graph, trials)
    credits = credit_map(result)

    assert result.mode is InteractionEstimationMode.EXACT
    assert result.orders == graph.topological_orders()
    assert result.usable_trial_count == 2
    assert result.abstentions == ()
    assert credits[MEMORY_A].score_value == pytest.approx(0.2)
    assert credits[MEMORY_B].score_value == pytest.approx(0.3)
    assert credits[MEMORY_C].score_value == pytest.approx(0.4)
    assert all(credit.score_standard_error == pytest.approx(0.0) for credit in result.credits)
    assert result.full_lift == pytest.approx(0.9)
    assert result.allocated_value == pytest.approx(0.9)
    assert result.closure_residual == pytest.approx(0.0, abs=1e-12)


def test_redundant_substitutes_split_lift_that_full_bundle_loo_misses() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))

    def value(coalition: frozenset[UUID]) -> float:
        return 1.0 if coalition else 0.0

    trials = (
        make_trial(graph, "trial-1", value),
        make_trial(graph, "trial-2", value),
    )
    result = PrecedenceShapleyEstimator().estimate(graph, trials)
    credits = credit_map(result)
    full = value(frozenset({MEMORY_A, MEMORY_B}))
    loo_a = full - value(frozenset({MEMORY_B}))
    loo_b = full - value(frozenset({MEMORY_A}))

    assert loo_a == loo_b == 0.0
    assert credits[MEMORY_A].score_value == pytest.approx(0.5)
    assert credits[MEMORY_B].score_value == pytest.approx(0.5)
    assert result.allocated_value == pytest.approx(result.full_lift)


def test_synergistic_complements_split_lift_without_loo_double_counting() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))

    def value(coalition: frozenset[UUID]) -> float:
        return 1.0 if {MEMORY_A, MEMORY_B}.issubset(coalition) else 0.0

    trials = (
        make_trial(graph, "trial-1", value),
        make_trial(graph, "trial-2", value),
    )
    result = PrecedenceShapleyEstimator().estimate(graph, trials)
    credits = credit_map(result)
    full = value(frozenset({MEMORY_A, MEMORY_B}))
    loo_total = (
        full - value(frozenset({MEMORY_B}))
        + full
        - value(frozenset({MEMORY_A}))
    )

    assert loo_total == 2.0
    assert credits[MEMORY_A].score_value == pytest.approx(0.5)
    assert credits[MEMORY_B].score_value == pytest.approx(0.5)
    assert result.full_lift == pytest.approx(1.0)
    assert result.allocated_value == pytest.approx(1.0)


def test_prerequisite_game_uses_only_valid_orders_and_preserves_cost_signs() -> None:
    graph = MemoryDependencyGraph(
        (MEMORY_A, MEMORY_B),
        prerequisites={MEMORY_B: frozenset({MEMORY_A})},
    )

    def score(coalition: frozenset[UUID]) -> float:
        return 0.2 * (MEMORY_A in coalition) + 0.3 * (MEMORY_B in coalition)

    def tokens(coalition: frozenset[UUID]) -> int:
        return 100 + 20 * (MEMORY_A in coalition) - 5 * (MEMORY_B in coalition)

    def latency(coalition: frozenset[UUID]) -> float:
        return 10.0 + 3 * (MEMORY_A in coalition) + 1 * (MEMORY_B in coalition)

    trials = (
        make_trial(graph, "trial-1", score, token_fn=tokens, latency_fn=latency),
        make_trial(graph, "trial-2", score, token_fn=tokens, latency_fn=latency),
    )

    result = PrecedenceShapleyEstimator().estimate(graph, trials)
    credits = credit_map(result)

    assert result.orders == ((MEMORY_A, MEMORY_B),)
    assert frozenset({MEMORY_B}) not in trials[0].outcomes
    assert credits[MEMORY_A].token_value == pytest.approx(20.0)
    assert credits[MEMORY_B].token_value == pytest.approx(-5.0)
    assert credits[MEMORY_A].latency_value_ms == pytest.approx(3.0)
    assert credits[MEMORY_B].latency_value_ms == pytest.approx(1.0)


def test_one_trial_abstains_but_still_reports_value_closure() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))
    trial = make_trial(
        graph,
        "trial-1",
        lambda coalition: 0.4 * (MEMORY_A in coalition) + 0.2 * (MEMORY_B in coalition),
    )

    result = PrecedenceShapleyEstimator().estimate(graph, (trial,))

    assert result.credits == ()
    assert {item.memory_id for item in result.abstentions} == {MEMORY_A, MEMORY_B}
    assert {item.reason for item in result.abstentions} == {
        InteractionCreditAbstentionReason.INSUFFICIENT_TRIALS
    }
    assert result.usable_trial_count == 1
    assert result.full_lift == pytest.approx(0.6)
    assert result.allocated_value == pytest.approx(0.6)
    assert result.closure_residual == pytest.approx(0.0)


def test_no_complete_order_path_abstains_without_fabricating_zero_effects() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))
    omitted = frozenset(
        {
            frozenset({MEMORY_A}),
            frozenset({MEMORY_B}),
        }
    )
    trials = (
        make_trial(graph, "trial-1", lambda coalition: float(bool(coalition)), omit=omitted),
        make_trial(graph, "trial-2", lambda coalition: float(bool(coalition)), omit=omitted),
    )

    result = PrecedenceShapleyEstimator().estimate(graph, trials)

    assert result.credits == ()
    assert result.usable_trial_count == 0
    assert result.full_lift == 0.0
    assert result.allocated_value == 0.0
    assert {item.reason for item in result.abstentions} == {
        InteractionCreditAbstentionReason.NO_COMPLETE_PATH
    }


def test_high_cross_trial_variance_withholds_unstable_player_credit() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))
    orders = ((MEMORY_A, MEMORY_B),)

    def first_value(coalition: frozenset[UUID]) -> float:
        return 0.6 * (MEMORY_A in coalition) + 0.2 * (MEMORY_B in coalition)

    def second_value(coalition: frozenset[UUID]) -> float:
        return -0.6 * (MEMORY_A in coalition) + 0.2 * (MEMORY_B in coalition)

    result = PrecedenceShapleyEstimator().estimate(
        graph,
        (
            make_trial(graph, "trial-1", first_value),
            make_trial(graph, "trial-2", second_value),
        ),
        orders=orders,
    )

    credits = credit_map(result)
    abstentions = {item.memory_id: item for item in result.abstentions}
    assert result.mode is InteractionEstimationMode.SAMPLED
    assert MEMORY_A not in credits
    assert abstentions[MEMORY_A].reason is InteractionCreditAbstentionReason.HIGH_VARIANCE
    assert abstentions[MEMORY_A].score_standard_error > 0.10
    assert credits[MEMORY_B].score_value == pytest.approx(0.2)
    assert result.closure_residual == pytest.approx(0.0)


def test_estimator_rejects_invalid_trials_contexts_and_orders() -> None:
    graph = MemoryDependencyGraph(
        (MEMORY_A, MEMORY_B),
        prerequisites={MEMORY_B: frozenset({MEMORY_A})},
    )
    valid = make_trial(graph, "trial-1", lambda coalition: 0.1 * len(coalition))
    mixed_context = make_trial(
        graph,
        "trial-2",
        lambda coalition: 0.1 * len(coalition),
        context_hash="c" * 64,
    )

    with pytest.raises(ValueError, match="context_hash"):
        PrecedenceShapleyEstimator().estimate(graph, (valid, mixed_context))
    with pytest.raises(ValueError, match="duplicate trial_key"):
        PrecedenceShapleyEstimator().estimate(graph, (valid, valid))
    with pytest.raises(ValueError, match="valid topological order"):
        PrecedenceShapleyEstimator().estimate(
            graph,
            (valid, make_trial(graph, "trial-2", lambda coalition: 0.1 * len(coalition))),
            orders=((MEMORY_B, MEMORY_A),),
        )

    invalid_trial = InteractionTrial(
        trial_key="invalid-coalition",
        context_hash=CONTEXT_HASH,
        continuation_hash="d" * 64,
        outcomes={
            frozenset(): OutcomeMeasurement(0.0, False),
            frozenset({MEMORY_B}): OutcomeMeasurement(0.5, True),
        },
    )
    with pytest.raises(ValueError, match="dependency-closed"):
        PrecedenceShapleyEstimator().estimate(graph, (valid, invalid_trial))


def test_explicit_order_subset_is_sampled_and_large_game_requires_orders() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))
    trials = (
        make_trial(graph, "trial-1", lambda coalition: 0.1 * len(coalition)),
        make_trial(graph, "trial-2", lambda coalition: 0.1 * len(coalition)),
    )

    sampled = PrecedenceShapleyEstimator().estimate(
        graph,
        trials,
        orders=((MEMORY_A, MEMORY_B),),
    )
    assert sampled.mode is InteractionEstimationMode.SAMPLED

    large_players = tuple(
        UUID(f"00000000-0000-5000-8000-{index:012d}") for index in range(10, 19)
    )
    large_graph = MemoryDependencyGraph(large_players)
    with pytest.raises(ValueError, match="sampled orders are required"):
        PrecedenceShapleyEstimator().estimate(large_graph, ())


def test_sampled_order_count_is_bounded_by_configuration() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B, MEMORY_C))
    trials = (
        make_trial(graph, "trial-1", lambda coalition: 0.1 * len(coalition)),
        make_trial(graph, "trial-2", lambda coalition: 0.1 * len(coalition)),
    )
    estimator = PrecedenceShapleyEstimator(
        InteractionCreditConfig(max_sampled_orders=1)
    )

    with pytest.raises(ValueError, match="max_sampled_orders"):
        estimator.estimate(
            graph,
            trials,
            orders=graph.topological_orders()[:2],
        )
