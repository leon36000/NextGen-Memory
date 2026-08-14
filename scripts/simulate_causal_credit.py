"""Compare reward broadcast, paired leave-one-out credit, and abstention."""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from math import isfinite, sqrt
from statistics import fmean, stdev


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    """Fixed controls for the post-action causal-credit experiment."""

    seed: int = 20_260_814
    task_count: int = 5_000
    shadow_count: int = 4
    trial_count: int = 3
    noise_stddev: float = 0.03
    success_probability: float = 0.85
    causal_effect: float = 0.25
    helpful_threshold: float = 0.05
    harmful_threshold: float = -0.05
    max_standard_error: float = 0.10
    noisy_multiplier: float = 20.0

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        _validate_positive_integer("task_count", self.task_count)
        _validate_positive_integer("shadow_count", self.shadow_count)
        if (
            isinstance(self.trial_count, bool)
            or not isinstance(self.trial_count, int)
            or self.trial_count < 2
        ):
            raise ValueError("trial_count must be an integer greater than one")
        if not isfinite(self.noise_stddev) or self.noise_stddev < 0:
            raise ValueError("noise_stddev must be finite and non-negative")
        if (
            not isfinite(self.success_probability)
            or not 0.0 <= self.success_probability <= 1.0
        ):
            raise ValueError(
                "success_probability must be finite and between zero and one"
            )
        if not isfinite(self.causal_effect):
            raise ValueError("causal_effect must be finite")
        if not isfinite(self.helpful_threshold) or self.helpful_threshold <= 0:
            raise ValueError("helpful_threshold must be finite and positive")
        if not isfinite(self.harmful_threshold) or self.harmful_threshold >= 0:
            raise ValueError("harmful_threshold must be finite and negative")
        if not isfinite(self.max_standard_error) or self.max_standard_error < 0:
            raise ValueError("max_standard_error must be finite and non-negative")
        if not isfinite(self.noisy_multiplier) or self.noisy_multiplier <= 0:
            raise ValueError("noisy_multiplier must be finite and positive")


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Aggregate attribution quality for three credit strategies."""

    bundle_shadow_contamination_rate: float
    config: SimulationConfig
    loo_causal_detection_rate: float
    loo_shadow_false_credit_rate: float
    noisy_abstention_precision: float
    observed_success_rate: float

    def __post_init__(self) -> None:
        for name in (
            "bundle_shadow_contamination_rate",
            "loo_causal_detection_rate",
            "loo_shadow_false_credit_rate",
            "noisy_abstention_precision",
            "observed_success_rate",
        ):
            value = getattr(self, name)
            if not isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be finite and between zero and one")

    def to_json(self) -> str:
        """Return deterministic compact JSON for experiment artifacts."""

        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def simulate(config: SimulationConfig) -> SimulationResult:
    """Run a fixed-seed comparison of broadcast and paired causal credit.

    Every task retrieves one memory with true positive causal effect and a fixed
    number of zero-effect shadows. A separate zero-effect candidate receives
    much higher evaluator noise and should therefore be withheld by the
    standard-error gate.
    """

    rng = random.Random(config.seed)
    success_count = 0
    contaminated_shadows = 0
    false_shadow_credits = 0
    causal_detections = 0
    noisy_abstentions = 0

    for _ in range(config.task_count):
        task_succeeded = rng.random() < config.success_probability
        if task_succeeded:
            success_count += 1
            contaminated_shadows += config.shadow_count

        causal_effects = [
            config.causal_effect + rng.gauss(0.0, config.noise_stddev)
            for _ in range(config.trial_count)
        ]
        causal_mean, causal_se = _mean_and_standard_error(causal_effects)
        if (
            causal_se <= config.max_standard_error
            and causal_mean >= config.helpful_threshold
        ):
            causal_detections += 1

        for _ in range(config.shadow_count):
            shadow_effects = [
                rng.gauss(0.0, config.noise_stddev)
                for _ in range(config.trial_count)
            ]
            shadow_mean, shadow_se = _mean_and_standard_error(shadow_effects)
            if shadow_se <= config.max_standard_error and (
                shadow_mean >= config.helpful_threshold
                or shadow_mean <= config.harmful_threshold
            ):
                false_shadow_credits += 1

        noisy_effects = [
            rng.gauss(0.0, config.noise_stddev * config.noisy_multiplier)
            for _ in range(config.trial_count)
        ]
        _, noisy_se = _mean_and_standard_error(noisy_effects)
        if noisy_se > config.max_standard_error:
            noisy_abstentions += 1

    shadow_observations = config.task_count * config.shadow_count
    return SimulationResult(
        bundle_shadow_contamination_rate=(
            contaminated_shadows / shadow_observations
        ),
        config=config,
        loo_causal_detection_rate=causal_detections / config.task_count,
        loo_shadow_false_credit_rate=false_shadow_credits / shadow_observations,
        noisy_abstention_precision=noisy_abstentions / config.task_count,
        observed_success_rate=success_count / config.task_count,
    )


def _mean_and_standard_error(values: list[float]) -> tuple[float, float]:
    return fmean(values), stdev(values) / sqrt(len(values))


def _validate_positive_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def main() -> None:
    """Execute the default deterministic experiment."""

    print(simulate(SimulationConfig()).to_json())


if __name__ == "__main__":
    main()
