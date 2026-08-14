from __future__ import annotations

from uuid import UUID

import pytest

from nextgen_memory.causal_credit import OutcomeMeasurement
from nextgen_memory.interaction_credit import (
    InteractionCreditAbstentionReason,
    InteractionCreditConfig,
    InteractionEstimationMode,
    InteractionTrial,
    MemoryDependencyGraph,
    PairInteractionKind,
)

MEMORY_A = UUID("00000000-0000-5000-8000-000000000001")
MEMORY_B = UUID("00000000-0000-5000-8000-000000000002")
MEMORY_C = UUID("00000000-0000-5000-8000-000000000003")
MEMORY_D = UUID("00000000-0000-5000-8000-000000000004")


def test_dependency_graph_freezes_transitive_prerequisites_and_validates_coalitions() -> None:
    graph = MemoryDependencyGraph(
        players=(MEMORY_C, MEMORY_A, MEMORY_B),
        prerequisites={
            MEMORY_C: frozenset({MEMORY_B}),
            MEMORY_B: frozenset({MEMORY_A}),
        },
    )

    assert graph.players == (MEMORY_A, MEMORY_B, MEMORY_C)
    assert graph.direct_prerequisites_of(MEMORY_C) == frozenset({MEMORY_B})
    assert graph.prerequisites_of(MEMORY_C) == frozenset({MEMORY_A, MEMORY_B})
    assert graph.is_ancestor(MEMORY_A, MEMORY_C) is True
    assert graph.is_ancestor(MEMORY_C, MEMORY_A) is False
    assert graph.is_valid_coalition(frozenset({MEMORY_A, MEMORY_B, MEMORY_C})) is True
    assert graph.is_valid_coalition(frozenset({MEMORY_B, MEMORY_C})) is False
    assert graph.is_valid_coalition(frozenset({MEMORY_A, MEMORY_C})) is False

    with pytest.raises(TypeError):
        graph.prerequisites[MEMORY_A] = frozenset()


def test_dependency_graph_valid_coalitions_are_deterministic_and_closed() -> None:
    graph = MemoryDependencyGraph(
        players=(MEMORY_A, MEMORY_B, MEMORY_C),
        prerequisites={MEMORY_C: frozenset({MEMORY_A})},
    )

    assert graph.valid_coalitions() == (
        frozenset(),
        frozenset({MEMORY_A}),
        frozenset({MEMORY_B}),
        frozenset({MEMORY_A, MEMORY_B}),
        frozenset({MEMORY_A, MEMORY_C}),
        frozenset({MEMORY_A, MEMORY_B, MEMORY_C}),
    )
    assert all(graph.is_valid_coalition(value) for value in graph.valid_coalitions())


def test_dependency_graph_rejects_duplicate_unknown_self_and_cycles() -> None:
    with pytest.raises(ValueError, match="duplicate player"):
        MemoryDependencyGraph(players=(MEMORY_A, MEMORY_A))
    with pytest.raises(ValueError, match="players must contain UUID"):
        MemoryDependencyGraph(players=(MEMORY_A, "not-a-uuid"))
    with pytest.raises(ValueError, match="unknown prerequisite"):
        MemoryDependencyGraph(
            players=(MEMORY_A, MEMORY_B),
            prerequisites={MEMORY_B: frozenset({MEMORY_C})},
        )
    with pytest.raises(ValueError, match="self-dependency"):
        MemoryDependencyGraph(
            players=(MEMORY_A, MEMORY_B),
            prerequisites={MEMORY_A: frozenset({MEMORY_A})},
        )
    with pytest.raises(ValueError, match="cycle"):
        MemoryDependencyGraph(
            players=(MEMORY_A, MEMORY_B),
            prerequisites={
                MEMORY_A: frozenset({MEMORY_B}),
                MEMORY_B: frozenset({MEMORY_A}),
            },
        )


def test_dependency_graph_rejects_unknown_coalition_members_and_invalid_orders() -> None:
    graph = MemoryDependencyGraph(
        players=(MEMORY_A, MEMORY_B, MEMORY_C),
        prerequisites={MEMORY_C: frozenset({MEMORY_A})},
    )

    with pytest.raises(ValueError, match="unknown memory"):
        graph.validate_coalition(frozenset({MEMORY_D}))
    with pytest.raises(ValueError, match="dependency-closed"):
        graph.validate_coalition(frozenset({MEMORY_C}))
    assert graph.is_valid_order((MEMORY_A, MEMORY_B, MEMORY_C)) is True
    assert graph.is_valid_order((MEMORY_B, MEMORY_A, MEMORY_C)) is True
    assert graph.is_valid_order((MEMORY_C, MEMORY_A, MEMORY_B)) is False
    assert graph.is_valid_order((MEMORY_A, MEMORY_B)) is False
    assert graph.is_valid_order((MEMORY_A, MEMORY_A, MEMORY_C)) is False


def test_topological_orders_are_deterministic_and_valid() -> None:
    graph = MemoryDependencyGraph(
        players=(MEMORY_A, MEMORY_B, MEMORY_C),
        prerequisites={MEMORY_C: frozenset({MEMORY_A})},
    )

    orders = graph.topological_orders()

    assert orders == (
        (MEMORY_A, MEMORY_B, MEMORY_C),
        (MEMORY_A, MEMORY_C, MEMORY_B),
        (MEMORY_B, MEMORY_A, MEMORY_C),
    )
    assert all(graph.is_valid_order(order) for order in orders)


def test_interaction_trial_is_immutable_and_iterates_coalitions_deterministically() -> None:
    trial = InteractionTrial(
        trial_key="  trial-1  ",
        context_hash="a" * 64,
        continuation_hash="b" * 64,
        outcomes={
            frozenset({MEMORY_A, MEMORY_B}): OutcomeMeasurement(0.8, True),
            frozenset({MEMORY_A}): OutcomeMeasurement(0.4, True),
            frozenset(): OutcomeMeasurement(0.0, False),
        },
    )

    assert trial.trial_key == "trial-1"
    assert tuple(trial.outcomes) == (
        frozenset(),
        frozenset({MEMORY_A}),
        frozenset({MEMORY_A, MEMORY_B}),
    )
    with pytest.raises(TypeError):
        trial.outcomes[frozenset()] = OutcomeMeasurement(1.0, True)


def test_interaction_trial_rejects_invalid_keys_hashes_and_measurements() -> None:
    base = {
        "trial_key": "trial-1",
        "context_hash": "a" * 64,
        "continuation_hash": "b" * 64,
        "outcomes": {frozenset(): OutcomeMeasurement(0.0, False)},
    }

    with pytest.raises(ValueError, match="trial_key"):
        InteractionTrial(**{**base, "trial_key": "   "})
    with pytest.raises(ValueError, match="context_hash"):
        InteractionTrial(**{**base, "context_hash": "invalid"})
    with pytest.raises(ValueError, match="continuation_hash"):
        InteractionTrial(**{**base, "continuation_hash": "invalid"})
    with pytest.raises(ValueError, match="coalition keys must be frozenset"):
        InteractionTrial(**{**base, "outcomes": {(MEMORY_A,): OutcomeMeasurement(0.1, True)}})
    with pytest.raises(ValueError, match="coalition members must be UUID"):
        InteractionTrial(
            **{
                **base,
                "outcomes": {frozenset({"not-a-uuid"}): OutcomeMeasurement(0.1, True)},
            }
        )
    with pytest.raises(ValueError, match="OutcomeMeasurement"):
        InteractionTrial(**{**base, "outcomes": {frozenset(): object()}})


def test_interaction_config_defaults_and_enums_are_stable() -> None:
    config = InteractionCreditConfig()

    assert config.exact_player_limit == 8
    assert config.min_trials == 2
    assert config.max_standard_error == 0.10
    assert config.closure_tolerance == 1e-9
    assert config.max_sampled_orders == 256
    assert config.interaction_threshold == 0.05
    assert config.max_interaction_standard_error == 0.10
    assert InteractionEstimationMode.EXACT.value == "exact"
    assert InteractionEstimationMode.SAMPLED.value == "sampled"
    assert InteractionCreditAbstentionReason.NO_COMPLETE_PATH.value == "no_complete_path"
    assert PairInteractionKind.REDUNDANCY.value == "redundancy"
    assert PairInteractionKind.SYNERGY.value == "synergy"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"exact_player_limit": 0},
        {"exact_player_limit": True},
        {"min_trials": 0},
        {"max_sampled_orders": 0},
        {"max_standard_error": -0.1},
        {"max_standard_error": float("nan")},
        {"closure_tolerance": -1.0},
        {"interaction_threshold": 0.0},
        {"max_interaction_standard_error": -0.1},
    ],
)
def test_interaction_config_rejects_invalid_controls(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        InteractionCreditConfig(**kwargs)
