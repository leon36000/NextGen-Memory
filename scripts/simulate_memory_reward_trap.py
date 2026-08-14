"""Reproduce bundle-reward contamination versus counterfactual credit."""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from math import isfinite


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Fixed experimental controls for the memory-reward-trap simulation."""

    seed: int = 20_260_814
    task_count: int = 5_000
    shadow_count: int = 4
    success_probability: float = 0.85
    contamination_threshold: float = 0.5

    def __post_init__(self) -> None:
        _validate_positive_integer("task_count", self.task_count)
        _validate_positive_integer("shadow_count", self.shadow_count)
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise ValueError("seed must be an integer")
        for name in ("success_probability", "contamination_threshold"):
            value = getattr(self, name)
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and between zero and one")


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Aggregate contamination and causal-ranking rates."""

    config: SimulationConfig
    observed_success_rate: float
    naive_shadow_contamination_rate: float
    counterfactual_shadow_contamination_rate: float
    naive_causal_rank_rate: float
    counterfactual_causal_rank_rate: float

    def __post_init__(self) -> None:
        for name in (
            "observed_success_rate",
            "naive_shadow_contamination_rate",
            "counterfactual_shadow_contamination_rate",
            "naive_causal_rank_rate",
            "counterfactual_causal_rank_rate",
        ):
            value = getattr(self, name)
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and between zero and one")

    def to_json(self) -> str:
        """Return deterministic, compact JSON suitable for experiment artifacts."""

        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def simulate(config: SimulationConfig) -> SimulationResult:
    """Compare naive bundle rewards with individual counterfactual credit.

    Each task contains one genuinely causal memory and `shadow_count` memories that
    are always co-retrieved but do not change the outcome. Naive credit propagates
    the task reward to every retrieved memory. Counterfactual credit updates only
    the memory whose removal changes a successful outcome.
    """

    rng = random.Random(config.seed)
    success_count = 0
    naive_contaminated_shadows = 0
    counterfactual_contaminated_shadows = 0
    naive_causal_top_count = 0
    counterfactual_causal_top_count = 0

    for _ in range(config.task_count):
        success = rng.random() < config.success_probability
        if success:
            success_count += 1

        naive_bundle_score = 1.0 if success else -1.0
        if naive_bundle_score >= config.contamination_threshold:
            naive_contaminated_shadows += config.shadow_count

        counterfactual_shadow_score = 0.0
        if counterfactual_shadow_score >= config.contamination_threshold:
            counterfactual_contaminated_shadows += config.shadow_count

        # Under naive propagation all bundle members tie; order is arbitrary.
        if rng.randrange(config.shadow_count + 1) == 0:
            naive_causal_top_count += 1

        # Under counterfactual credit the causal memory is top-ranked exactly
        # when it produced the successful outcome; shadows stay at the prior.
        if success:
            counterfactual_causal_top_count += 1

    shadow_observations = config.task_count * config.shadow_count
    return SimulationResult(
        config=config,
        observed_success_rate=success_count / config.task_count,
        naive_shadow_contamination_rate=(
            naive_contaminated_shadows / shadow_observations
        ),
        counterfactual_shadow_contamination_rate=(
            counterfactual_contaminated_shadows / shadow_observations
        ),
        naive_causal_rank_rate=naive_causal_top_count / config.task_count,
        counterfactual_causal_rank_rate=(
            counterfactual_causal_top_count / config.task_count
        ),
    )


def main() -> None:
    """Run the default deterministic simulation and print one JSON object."""

    print(simulate(SimulationConfig()).to_json())


def _validate_positive_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


if __name__ == "__main__":
    main()
