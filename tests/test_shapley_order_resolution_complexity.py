from __future__ import annotations

from uuid import UUID

import pytest

from nextgen_memory.interaction_credit import (
    InteractionEstimationMode,
    MemoryDependencyGraph,
    PrecedenceShapleyEstimator,
)


def _players(count: int) -> tuple[UUID, ...]:
    return tuple(
        UUID(f"00000000-0000-5000-8000-{index:012d}")
        for index in range(1, count + 1)
    )


def _fail_if_enumerated(_: MemoryDependencyGraph) -> tuple[tuple[UUID, ...], ...]:
    raise AssertionError("large-game order resolution must not enumerate all orders")


def test_large_game_requires_samples_before_topological_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = MemoryDependencyGraph(_players(9))
    monkeypatch.setattr(
        MemoryDependencyGraph,
        "topological_orders",
        _fail_if_enumerated,
    )

    with pytest.raises(ValueError, match="sampled orders are required"):
        PrecedenceShapleyEstimator().estimate(graph, ())


def test_large_game_validates_explicit_samples_without_global_enumeration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = MemoryDependencyGraph(_players(9))
    sampled_order = graph.players
    monkeypatch.setattr(
        MemoryDependencyGraph,
        "topological_orders",
        _fail_if_enumerated,
    )

    result = PrecedenceShapleyEstimator().estimate(
        graph,
        (),
        orders=(sampled_order,),
    )

    assert result.mode is InteractionEstimationMode.SAMPLED
    assert result.orders == (sampled_order,)
