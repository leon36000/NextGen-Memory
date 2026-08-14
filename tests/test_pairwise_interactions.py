from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest

from nextgen_memory.causal_credit import OutcomeMeasurement
from nextgen_memory.interaction_credit import (
    InteractionCreditConfig,
    InteractionTrial,
    MemoryDependencyGraph,
    PairInteractionKind,
    PairwiseInteractionEstimator,
)

MEMORY_A = UUID("00000000-0000-5000-8000-000000000001")
MEMORY_B = UUID("00000000-0000-5000-8000-000000000002")
MEMORY_C = UUID("00000000-0000-5000-8000-000000000003")
CONTEXT_HASH = "a" * 64


def make_trial(
    graph: MemoryDependencyGraph,
    key: str,
    value: Callable[[frozenset[UUID]], float],
    *,
    omit: frozenset[frozenset[UUID]] = frozenset(),
) -> InteractionTrial:
    return InteractionTrial(
        trial_key=key,
        context_hash=CONTEXT_HASH,
        continuation_hash=(key.encode("utf-8").hex() + "0" * 64)[:64],
        outcomes={
            coalition: OutcomeMeasurement(value(coalition), value(coalition) > 0)
            for coalition in graph.valid_coalitions()
            if coalition not in omit
        },
    )


def only_pair(estimates):
    assert len(estimates) == 1
    return estimates[0]


def test_redundant_pair_has_stable_negative_second_difference() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))
    value = lambda coalition: 1.0 if coalition else 0.0
    trials = (
        make_trial(graph, "trial-1", value),
        make_trial(graph, "trial-2", value),
    )

    estimate = only_pair(PairwiseInteractionEstimator().estimate(graph, trials))

    assert estimate.left_memory_id == MEMORY_A
    assert estimate.right_memory_id == MEMORY_B
    assert estimate.kind is PairInteractionKind.REDUNDANCY
    assert estimate.mean_second_difference == pytest.approx(-1.0)
    assert estimate.standard_error == pytest.approx(0.0)
    assert estimate.trial_count == 2
    assert estimate.context_count == 2


def test_synergistic_pair_has_stable_positive_second_difference() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))

    def value(coalition: frozenset[UUID]) -> float:
        return 1.0 if {MEMORY_A, MEMORY_B}.issubset(coalition) else 0.0

    trials = (
        make_trial(graph, "trial-1", value),
        make_trial(graph, "trial-2", value),
    )

    estimate = only_pair(PairwiseInteractionEstimator().estimate(graph, trials))

    assert estimate.kind is PairInteractionKind.SYNERGY
    assert estimate.mean_second_difference == pytest.approx(1.0)
    assert estimate.standard_error == pytest.approx(0.0)


def test_additive_pair_has_near_zero_second_difference() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))

    def value(coalition: frozenset[UUID]) -> float:
        return 0.2 * (MEMORY_A in coalition) + 0.3 * (MEMORY_B in coalition)

    trials = (
        make_trial(graph, "trial-1", value),
        make_trial(graph, "trial-2", value),
    )

    estimate = only_pair(PairwiseInteractionEstimator().estimate(graph, trials))

    assert estimate.kind is PairInteractionKind.ADDITIVE
    assert estimate.mean_second_difference == pytest.approx(0.0, abs=1e-12)


def test_ancestor_descendant_pair_is_not_comparable() -> None:
    graph = MemoryDependencyGraph(
        (MEMORY_A, MEMORY_B),
        prerequisites={MEMORY_B: frozenset({MEMORY_A})},
    )
    trials = (
        make_trial(graph, "trial-1", lambda coalition: 0.1 * len(coalition)),
        make_trial(graph, "trial-2", lambda coalition: 0.1 * len(coalition)),
    )

    estimate = only_pair(PairwiseInteractionEstimator().estimate(graph, trials))

    assert estimate.kind is PairInteractionKind.NOT_COMPARABLE
    assert estimate.mean_second_difference is None
    assert estimate.standard_error is None
    assert estimate.trial_count == 0
    assert estimate.context_count == 0


def test_missing_four_coalition_context_is_explicit() -> None:
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

    estimate = only_pair(PairwiseInteractionEstimator().estimate(graph, trials))

    assert estimate.kind is PairInteractionKind.INSUFFICIENT_CONTEXTS
    assert estimate.mean_second_difference is None
    assert estimate.standard_error is None
    assert estimate.trial_count == 0


def test_one_matched_trial_is_insufficient_for_pair_classification() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))
    trial = make_trial(graph, "trial-1", lambda coalition: float(bool(coalition)))

    estimate = only_pair(PairwiseInteractionEstimator().estimate(graph, (trial,)))

    assert estimate.kind is PairInteractionKind.INSUFFICIENT_TRIALS
    assert estimate.mean_second_difference is None
    assert estimate.standard_error is None
    assert estimate.trial_count == 1
    assert estimate.context_count == 1


def test_high_cross_trial_variance_is_uncertain() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))

    def positive(coalition: frozenset[UUID]) -> float:
        return 0.8 if {MEMORY_A, MEMORY_B}.issubset(coalition) else 0.0

    def negative(coalition: frozenset[UUID]) -> float:
        return 0.8 if len(coalition) == 1 else 0.0

    trials = (
        make_trial(graph, "trial-1", positive),
        make_trial(graph, "trial-2", negative),
    )

    estimate = only_pair(PairwiseInteractionEstimator().estimate(graph, trials))

    assert estimate.kind is PairInteractionKind.UNCERTAIN
    assert estimate.mean_second_difference == pytest.approx(-0.4)
    assert estimate.standard_error > 0.10


def test_pairs_are_unique_and_sorted_lexicographically() -> None:
    graph = MemoryDependencyGraph((MEMORY_C, MEMORY_A, MEMORY_B))
    trials = (
        make_trial(graph, "trial-1", lambda coalition: 0.1 * len(coalition)),
        make_trial(graph, "trial-2", lambda coalition: 0.1 * len(coalition)),
    )

    estimates = PairwiseInteractionEstimator().estimate(graph, trials)
    pairs = tuple(
        (estimate.left_memory_id, estimate.right_memory_id)
        for estimate in estimates
    )

    assert pairs == (
        (MEMORY_A, MEMORY_B),
        (MEMORY_A, MEMORY_C),
        (MEMORY_B, MEMORY_C),
    )


def test_pairwise_estimator_respects_custom_thresholds() -> None:
    graph = MemoryDependencyGraph((MEMORY_A, MEMORY_B))

    def value(coalition: frozenset[UUID]) -> float:
        base = 0.1 * len(coalition)
        return base + (0.03 if {MEMORY_A, MEMORY_B}.issubset(coalition) else 0.0)

    trials = (
        make_trial(graph, "trial-1", value),
        make_trial(graph, "trial-2", value),
    )

    default = only_pair(PairwiseInteractionEstimator().estimate(graph, trials))
    sensitive = only_pair(
        PairwiseInteractionEstimator(
            InteractionCreditConfig(interaction_threshold=0.02)
        ).estimate(graph, trials)
    )

    assert default.kind is PairInteractionKind.ADDITIVE
    assert sensitive.kind is PairInteractionKind.SYNERGY
