"""Context-averaged pairwise second-difference diagnostics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import combinations
from math import isfinite, sqrt
from statistics import fmean, stdev
from uuid import UUID

from .interaction_credit import (
    InteractionCreditConfig,
    InteractionTrial,
    MemoryDependencyGraph,
    PairInteractionKind,
)


@dataclass(frozen=True, slots=True)
class PairInteractionEstimate:
    """One pairwise second-difference classification and its evidence."""

    left_memory_id: UUID
    right_memory_id: UUID
    kind: PairInteractionKind
    mean_second_difference: float | None
    standard_error: float | None
    trial_count: int
    context_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.left_memory_id, UUID):
            raise ValueError("left_memory_id must be a UUID")
        if not isinstance(self.right_memory_id, UUID):
            raise ValueError("right_memory_id must be a UUID")
        if str(self.left_memory_id) >= str(self.right_memory_id):
            raise ValueError("pair memory IDs must be lexicographically ordered")
        if not isinstance(self.kind, PairInteractionKind):
            raise ValueError("kind must be a PairInteractionKind")
        _validate_nonnegative_integer("trial_count", self.trial_count)
        _validate_nonnegative_integer("context_count", self.context_count)
        for name in ("mean_second_difference", "standard_error"):
            value = getattr(self, name)
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} must be finite when supplied")
        if (self.mean_second_difference is None) != (self.standard_error is None):
            raise ValueError(
                "mean_second_difference and standard_error must be supplied together"
            )


class PairwiseInteractionEstimator:
    """Classify stable context-averaged pairwise second differences."""

    def __init__(self, config: InteractionCreditConfig | None = None) -> None:
        self.config = config or InteractionCreditConfig()

    def estimate(
        self,
        graph: MemoryDependencyGraph,
        trials: Sequence[InteractionTrial],
    ) -> tuple[PairInteractionEstimate, ...]:
        if not isinstance(graph, MemoryDependencyGraph):
            raise ValueError("graph must be a MemoryDependencyGraph")
        normalized_trials = tuple(trials)
        self._validate_trials(graph, normalized_trials)

        estimates: list[PairInteractionEstimate] = []
        for left, right in combinations(graph.players, 2):
            if graph.is_ancestor(left, right) or graph.is_ancestor(right, left):
                estimates.append(
                    PairInteractionEstimate(
                        left_memory_id=left,
                        right_memory_id=right,
                        kind=PairInteractionKind.NOT_COMPARABLE,
                        mean_second_difference=None,
                        standard_error=None,
                        trial_count=0,
                        context_count=0,
                    )
                )
                continue

            per_trial: list[float] = []
            context_count = 0
            for trial in normalized_trials:
                trial_differences = self._trial_differences(
                    graph,
                    trial,
                    left,
                    right,
                )
                if not trial_differences:
                    continue
                context_count += len(trial_differences)
                per_trial.append(fmean(trial_differences))

            if not per_trial:
                estimates.append(
                    PairInteractionEstimate(
                        left_memory_id=left,
                        right_memory_id=right,
                        kind=PairInteractionKind.INSUFFICIENT_CONTEXTS,
                        mean_second_difference=None,
                        standard_error=None,
                        trial_count=0,
                        context_count=0,
                    )
                )
                continue
            if len(per_trial) < self.config.min_trials:
                estimates.append(
                    PairInteractionEstimate(
                        left_memory_id=left,
                        right_memory_id=right,
                        kind=PairInteractionKind.INSUFFICIENT_TRIALS,
                        mean_second_difference=None,
                        standard_error=None,
                        trial_count=len(per_trial),
                        context_count=context_count,
                    )
                )
                continue

            mean = fmean(per_trial)
            standard_error = stdev(per_trial) / sqrt(len(per_trial))
            if standard_error > self.config.max_interaction_standard_error:
                kind = PairInteractionKind.UNCERTAIN
            elif mean >= self.config.interaction_threshold:
                kind = PairInteractionKind.SYNERGY
            elif mean <= -self.config.interaction_threshold:
                kind = PairInteractionKind.REDUNDANCY
            else:
                kind = PairInteractionKind.ADDITIVE

            estimates.append(
                PairInteractionEstimate(
                    left_memory_id=left,
                    right_memory_id=right,
                    kind=kind,
                    mean_second_difference=mean,
                    standard_error=standard_error,
                    trial_count=len(per_trial),
                    context_count=context_count,
                )
            )

        return tuple(estimates)

    @staticmethod
    def _trial_differences(
        graph: MemoryDependencyGraph,
        trial: InteractionTrial,
        left: UUID,
        right: UUID,
    ) -> tuple[float, ...]:
        outcomes = trial.outcomes
        values: list[float] = []
        for base in outcomes:
            if left in base or right in base:
                continue
            with_left = base.union({left})
            with_right = base.union({right})
            with_both = base.union({left, right})
            coalitions = (base, with_left, with_right, with_both)
            if not all(graph.is_valid_coalition(value) for value in coalitions):
                continue
            if not all(value in outcomes for value in coalitions):
                continue
            values.append(
                outcomes[with_both].score
                - outcomes[with_left].score
                - outcomes[with_right].score
                + outcomes[base].score
            )
        return tuple(values)

    @staticmethod
    def _validate_trials(
        graph: MemoryDependencyGraph,
        trials: tuple[InteractionTrial, ...],
    ) -> None:
        seen_keys: set[str] = set()
        context_hashes: set[str] = set()
        for trial in trials:
            if not isinstance(trial, InteractionTrial):
                raise ValueError("trials must contain InteractionTrial instances")
            if trial.trial_key in seen_keys:
                raise ValueError("duplicate trial_key")
            seen_keys.add(trial.trial_key)
            context_hashes.add(trial.context_hash)
            for coalition in trial.outcomes:
                graph.validate_coalition(coalition)
        if len(context_hashes) > 1:
            raise ValueError("all trials must share one context_hash")


def _validate_nonnegative_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
