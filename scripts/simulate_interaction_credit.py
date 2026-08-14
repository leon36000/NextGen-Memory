"""Reproduce LOO interaction failures and constrained-Shapley recovery."""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from math import isfinite
from uuid import UUID

from nextgen_memory.causal_credit import OutcomeMeasurement
from nextgen_memory.interaction_credit import (
    InteractionTrial,
    MemoryDependencyGraph,
    PrecedenceShapleyEstimator,
)
from nextgen_memory.interaction_planner import (
    AdaptiveOrderPlanner,
    AdaptiveOrderPlannerConfig,
)
from nextgen_memory.pairwise_interactions import PairwiseInteractionEstimator

REDUNDANT_A = UUID("00000000-0000-5000-8000-000000000001")
REDUNDANT_B = UUID("00000000-0000-5000-8000-000000000002")
MIXED_A = UUID("00000000-0000-5000-8000-000000000011")
MIXED_B = UUID("00000000-0000-5000-8000-000000000012")
MIXED_C = UUID("00000000-0000-5000-8000-000000000013")
MIXED_D = UUID("00000000-0000-5000-8000-000000000014")
MIXED_E = UUID("00000000-0000-5000-8000-000000000015")
CONTEXT_HASH = "a" * 64


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Fixed controls for the deterministic interaction-credit experiment."""

    seed: int = 20_260_814
    trial_count: int = 5
    noise_stddev: float = 0.01
    sampled_order_budget: int = 12

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        if (
            isinstance(self.trial_count, bool)
            or not isinstance(self.trial_count, int)
            or self.trial_count < 2
        ):
            raise ValueError("trial_count must be an integer greater than one")
        if not isfinite(self.noise_stddev) or self.noise_stddev < 0:
            raise ValueError("noise_stddev must be finite and non-negative")
        if (
            isinstance(self.sampled_order_budget, bool)
            or not isinstance(self.sampled_order_budget, int)
            or self.sampled_order_budget <= 0
        ):
            raise ValueError("sampled_order_budget must be a positive integer")


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Exact, sampled, and pairwise diagnostics for controlled memory games."""

    config: SimulationConfig
    exact_closure_error: float
    redundancy_interaction: float
    redundant_loo_total: float
    redundant_shapley_total: float
    sampled_closure_error: float
    sampled_order_count: int
    sampled_rank_agreement: float
    sampled_requested_coalitions: int
    synergy_interaction: float
    synergy_loo_total: float
    synergy_shapley_total: float

    def __post_init__(self) -> None:
        for name in (
            "exact_closure_error",
            "redundancy_interaction",
            "redundant_loo_total",
            "redundant_shapley_total",
            "sampled_closure_error",
            "sampled_rank_agreement",
            "synergy_interaction",
            "synergy_loo_total",
            "synergy_shapley_total",
        ):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if not 0.0 <= self.sampled_rank_agreement <= 1.0:
            raise ValueError("sampled_rank_agreement must be between zero and one")
        _validate_nonnegative_integer("sampled_order_count", self.sampled_order_count)
        _validate_nonnegative_integer(
            "sampled_requested_coalitions",
            self.sampled_requested_coalitions,
        )

    def to_json(self) -> str:
        """Return deterministic compact JSON for experiment artifacts."""

        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def simulate(config: SimulationConfig) -> SimulationResult:
    """Compare LOO, exact constrained Shapley, and budgeted order sampling."""

    redundant_graph = MemoryDependencyGraph((REDUNDANT_A, REDUNDANT_B))
    redundant_trials = _deterministic_trials(
        redundant_graph,
        config.trial_count,
        lambda coalition: 1.0 if coalition else 0.0,
        prefix="redundant",
    )
    redundant_result = PrecedenceShapleyEstimator().estimate(
        redundant_graph,
        redundant_trials,
    )
    redundant_pair = PairwiseInteractionEstimator().estimate(
        redundant_graph,
        redundant_trials,
    )[0]
    redundant_full = 1.0
    redundant_loo_total = (
        redundant_full - 1.0
        + redundant_full
        - 1.0
    )

    synergy_graph = MemoryDependencyGraph((REDUNDANT_A, REDUNDANT_B))
    synergy_trials = _deterministic_trials(
        synergy_graph,
        config.trial_count,
        lambda coalition: (
            1.0
            if {REDUNDANT_A, REDUNDANT_B}.issubset(coalition)
            else 0.0
        ),
        prefix="synergy",
    )
    synergy_result = PrecedenceShapleyEstimator().estimate(
        synergy_graph,
        synergy_trials,
    )
    synergy_pair = PairwiseInteractionEstimator().estimate(
        synergy_graph,
        synergy_trials,
    )[0]
    synergy_full = 1.0
    synergy_loo_total = (
        synergy_full - 0.0
        + synergy_full
        - 0.0
    )

    mixed_graph = MemoryDependencyGraph(
        (MIXED_A, MIXED_B, MIXED_C, MIXED_D, MIXED_E),
        prerequisites={MIXED_E: frozenset({MIXED_B})},
    )
    mixed_trials = _noisy_trials(mixed_graph, config)
    exact_result = PrecedenceShapleyEstimator().estimate(
        mixed_graph,
        mixed_trials,
    )

    plan = AdaptiveOrderPlanner(
        AdaptiveOrderPlannerConfig(
            seed=config.seed,
            candidate_pool_size=128,
            coverage_weight=3.0,
        )
    ).plan(
        mixed_graph,
        evaluated_coalitions=(),
        budget=config.sampled_order_budget,
    )
    sampled_coalitions = frozenset(
        request.coalition for request in plan.requests
    )
    sampled_trials = tuple(
        InteractionTrial(
            trial_key=f"sampled-{trial.trial_key}",
            context_hash=trial.context_hash,
            continuation_hash=trial.continuation_hash,
            outcomes={
                coalition: outcome
                for coalition, outcome in trial.outcomes.items()
                if coalition in sampled_coalitions
            },
        )
        for trial in mixed_trials
    )
    sampled_result = PrecedenceShapleyEstimator().estimate(
        mixed_graph,
        sampled_trials,
        orders=plan.orders,
    )

    exact_values = {
        credit.memory_id: credit.score_value
        for credit in exact_result.credits
    }
    sampled_values = {
        credit.memory_id: credit.score_value
        for credit in sampled_result.credits
    }
    rank_agreement = _pairwise_rank_agreement(exact_values, sampled_values)

    return SimulationResult(
        config=config,
        exact_closure_error=abs(exact_result.closure_residual),
        redundancy_interaction=_require_interaction(
            redundant_pair.mean_second_difference
        ),
        redundant_loo_total=redundant_loo_total,
        redundant_shapley_total=sum(
            credit.score_value for credit in redundant_result.credits
        ),
        sampled_closure_error=abs(sampled_result.closure_residual),
        sampled_order_count=len(plan.orders),
        sampled_rank_agreement=rank_agreement,
        sampled_requested_coalitions=plan.requested_coalition_count,
        synergy_interaction=_require_interaction(
            synergy_pair.mean_second_difference
        ),
        synergy_loo_total=synergy_loo_total,
        synergy_shapley_total=sum(
            credit.score_value for credit in synergy_result.credits
        ),
    )


def _deterministic_trials(
    graph: MemoryDependencyGraph,
    trial_count: int,
    value,
    *,
    prefix: str,
) -> tuple[InteractionTrial, ...]:
    return tuple(
        InteractionTrial(
            trial_key=f"{prefix}-{index}",
            context_hash=CONTEXT_HASH,
            continuation_hash=_continuation_hash(prefix, index),
            outcomes={
                coalition: OutcomeMeasurement(
                    score=value(coalition),
                    task_success=value(coalition) > 0,
                )
                for coalition in graph.valid_coalitions()
            },
        )
        for index in range(trial_count)
    )


def _noisy_trials(
    graph: MemoryDependencyGraph,
    config: SimulationConfig,
) -> tuple[InteractionTrial, ...]:
    rng = random.Random(config.seed)
    trials: list[InteractionTrial] = []
    for trial_index in range(config.trial_count):
        outcomes = {}
        for coalition in graph.valid_coalitions():
            base_score = _mixed_value(coalition)
            score = _clip_score(base_score + rng.gauss(0.0, config.noise_stddev))
            outcomes[coalition] = OutcomeMeasurement(
                score=score,
                task_success=score >= 0.5,
                tokens=100 + 7 * len(coalition),
                latency_ms=10.0 + 1.5 * len(coalition),
            )
        trials.append(
            InteractionTrial(
                trial_key=f"mixed-{trial_index}",
                context_hash=CONTEXT_HASH,
                continuation_hash=_continuation_hash("mixed", trial_index),
                outcomes=outcomes,
            )
        )
    return tuple(trials)


def _mixed_value(coalition: frozenset[UUID]) -> float:
    return (
        0.30 * (MIXED_A in coalition)
        + 0.25 * (MIXED_B in coalition)
        + 0.25 * (MIXED_C in coalition or MIXED_D in coalition)
        + 0.20 * (MIXED_E in coalition)
    )


def _pairwise_rank_agreement(
    exact: dict[UUID, float],
    sampled: dict[UUID, float],
) -> float:
    if set(exact) != set(sampled):
        raise ValueError("exact and sampled estimates must cover identical players")
    players = tuple(sorted(exact, key=str))
    agreements = 0
    comparisons = 0
    for left_index, left in enumerate(players):
        for right in players[left_index + 1 :]:
            exact_delta = exact[left] - exact[right]
            if abs(exact_delta) <= 1e-9:
                continue
            sampled_delta = sampled[left] - sampled[right]
            comparisons += 1
            if exact_delta * sampled_delta > 0:
                agreements += 1
    return agreements / comparisons if comparisons else 1.0


def _continuation_hash(prefix: str, index: int) -> str:
    import hashlib

    return hashlib.sha256(f"{prefix}:{index}".encode()).hexdigest()


def _clip_score(value: float) -> float:
    return max(-1.0, min(1.0, value))


def _require_interaction(value: float | None) -> float:
    if value is None:
        raise ValueError("controlled pair must produce a finite interaction estimate")
    return value


def _validate_nonnegative_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def main() -> None:
    """Run the default deterministic interaction-credit experiment."""

    print(simulate(SimulationConfig()).to_json())


if __name__ == "__main__":
    main()
