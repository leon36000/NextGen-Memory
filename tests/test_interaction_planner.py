from __future__ import annotations

import importlib
from uuid import UUID

import pytest

from nextgen_memory.interaction_credit import (
    InteractionEstimationMode,
    MemoryDependencyGraph,
)

planner_module = importlib.import_module("nextgen_memory.interaction_planner")
AdaptiveOrderPlanner = planner_module.AdaptiveOrderPlanner
AdaptiveOrderPlannerConfig = planner_module.AdaptiveOrderPlannerConfig
CoalitionRequestReason = planner_module.CoalitionRequestReason


def memory_id(index: int) -> UUID:
    return UUID(f"00000000-0000-5000-8000-{index:012d}")


def prefixes(order: tuple[UUID, ...]) -> tuple[frozenset[UUID], ...]:
    prefix: set[UUID] = set()
    result = [frozenset()]
    for player in order:
        prefix.add(player)
        result.append(frozenset(prefix))
    return tuple(result)


def test_exact_plan_enumerates_all_valid_orders_and_coalitions_when_budget_fits() -> None:
    graph = MemoryDependencyGraph(tuple(memory_id(index) for index in range(1, 4)))

    plan = AdaptiveOrderPlanner().plan(
        graph,
        evaluated_coalitions=(),
        budget=8,
    )

    assert plan.mode is InteractionEstimationMode.EXACT
    assert plan.orders == graph.topological_orders()
    assert plan.exact_complete is True
    assert plan.budget == 8
    assert plan.requested_coalition_count == 8
    assert plan.reused_coalition_count == 0
    assert {request.coalition for request in plan.requests} == set(
        graph.valid_coalitions()
    )
    assert plan.requests[0].coalition == frozenset()
    assert plan.requests[1].coalition == frozenset(graph.players)
    assert plan.requests[0].reason is CoalitionRequestReason.REQUIRED_BOUNDARY
    assert plan.requests[1].reason is CoalitionRequestReason.REQUIRED_BOUNDARY


def test_exact_plan_reuses_cache_and_requests_only_missing_coalitions() -> None:
    graph = MemoryDependencyGraph(tuple(memory_id(index) for index in range(1, 4)))
    empty = frozenset()
    full = frozenset(graph.players)

    plan = AdaptiveOrderPlanner().plan(
        graph,
        evaluated_coalitions=(empty, full),
        budget=6,
    )

    assert plan.mode is InteractionEstimationMode.EXACT
    assert plan.exact_complete is True
    assert plan.requested_coalition_count == 6
    assert plan.reused_coalition_count >= 2
    assert empty not in {request.coalition for request in plan.requests}
    assert full not in {request.coalition for request in plan.requests}


def test_sampled_plan_is_deterministic_valid_unique_and_budget_bounded() -> None:
    graph = MemoryDependencyGraph(tuple(memory_id(index) for index in range(1, 10)))
    planner = AdaptiveOrderPlanner(
        AdaptiveOrderPlannerConfig(
            seed=20260814,
            max_orders=32,
            candidate_pool_size=96,
        )
    )

    first = planner.plan(graph, evaluated_coalitions=(), budget=40)
    second = planner.plan(graph, evaluated_coalitions=(), budget=40)

    assert first == second
    assert first.mode is InteractionEstimationMode.SAMPLED
    assert first.exact_complete is False
    assert len(first.requests) <= 40
    assert len({request.coalition for request in first.requests}) == len(
        first.requests
    )
    assert all(graph.is_valid_order(order) for order in first.orders)
    assert all(graph.is_valid_coalition(request.coalition) for request in first.requests)
    assert first.requests[0].coalition == frozenset()
    assert first.requests[1].coalition == frozenset(graph.players)

    requested = {request.coalition for request in first.requests}
    for order in first.orders:
        assert set(prefixes(order)).issubset(requested)


def test_sampled_plan_seed_changes_selected_orders() -> None:
    graph = MemoryDependencyGraph(tuple(memory_id(index) for index in range(1, 10)))
    first = AdaptiveOrderPlanner(
        AdaptiveOrderPlannerConfig(seed=1, candidate_pool_size=32)
    ).plan(graph, (), budget=25)
    second = AdaptiveOrderPlanner(
        AdaptiveOrderPlannerConfig(seed=2, candidate_pool_size=32)
    ).plan(graph, (), budget=25)

    assert first.orders != second.orders


def test_sampled_plan_reuses_boundaries_and_covers_multiple_player_positions() -> None:
    graph = MemoryDependencyGraph(tuple(memory_id(index) for index in range(1, 10)))
    empty = frozenset()
    full = frozenset(graph.players)
    plan = AdaptiveOrderPlanner(
        AdaptiveOrderPlannerConfig(
            seed=20260814,
            max_orders=64,
            candidate_pool_size=128,
            coverage_weight=3.0,
        )
    ).plan(
        graph,
        evaluated_coalitions=(empty, full),
        budget=120,
    )

    assert plan.reused_coalition_count >= 2
    assert empty not in {request.coalition for request in plan.requests}
    assert full not in {request.coalition for request in plan.requests}
    position_sets = {
        player: {
            position
            for order in plan.orders
            for position, current in enumerate(order)
            if current == player
        }
        for player in graph.players
    }
    assert len(plan.orders) >= 3
    assert all(len(positions) >= 2 for positions in position_sets.values())


def test_dependency_constrained_plans_never_request_invalid_coalitions() -> None:
    a, b, c, d = tuple(memory_id(index) for index in range(1, 5))
    graph = MemoryDependencyGraph(
        (a, b, c, d),
        prerequisites={c: frozenset({a}), d: frozenset({b})},
    )

    plan = AdaptiveOrderPlanner().plan(graph, (), budget=12)

    assert all(graph.is_valid_order(order) for order in plan.orders)
    assert all(graph.is_valid_coalition(request.coalition) for request in plan.requests)
    assert frozenset({c}) not in {request.coalition for request in plan.requests}
    assert frozenset({d}) not in {request.coalition for request in plan.requests}


def test_request_keys_are_stable_and_do_not_expose_payloads() -> None:
    graph = MemoryDependencyGraph(tuple(memory_id(index) for index in range(1, 4)))

    first = AdaptiveOrderPlanner().plan(graph, (), budget=8)
    second = AdaptiveOrderPlanner().plan(graph, (), budget=8)

    assert [request.request_key for request in first.requests] == [
        request.request_key for request in second.requests
    ]
    assert all(len(request.request_key) == 64 for request in first.requests)
    assert all(request.order_id for request in first.requests)
    assert all(request.prefix_position >= 0 for request in first.requests)


@pytest.mark.parametrize("budget", [-1, True, 1.5])
def test_invalid_budget_fails_closed(budget: object) -> None:
    graph = MemoryDependencyGraph((memory_id(1), memory_id(2)))

    with pytest.raises(ValueError, match="budget"):
        AdaptiveOrderPlanner().plan(graph, (), budget=budget)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"seed": True},
        {"exact_player_limit": 0},
        {"max_orders": 0},
        {"candidate_pool_size": 0},
        {"coverage_weight": -1.0},
        {"coverage_weight": float("nan")},
        {"boundary_weight": -1.0},
    ],
)
def test_invalid_planner_configuration_fails_closed(
    kwargs: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        AdaptiveOrderPlannerConfig(**kwargs)


def test_invalid_cached_coalitions_fail_closed() -> None:
    a, b, c = tuple(memory_id(index) for index in range(1, 4))
    graph = MemoryDependencyGraph(
        (a, b, c),
        prerequisites={c: frozenset({a})},
    )

    with pytest.raises(ValueError, match="frozenset"):
        AdaptiveOrderPlanner().plan(graph, ((a,),), budget=5)
    with pytest.raises(ValueError, match="unknown memory"):
        AdaptiveOrderPlanner().plan(
            graph,
            (frozenset({memory_id(99)}),),
            budget=5,
        )
    with pytest.raises(ValueError, match="dependency-closed"):
        AdaptiveOrderPlanner().plan(graph, (frozenset({c}),), budget=5)
