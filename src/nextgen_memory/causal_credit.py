"""Paired, fixed-context causal credit for memories used in an action."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite, sqrt
from statistics import fmean, stdev
from types import MappingProxyType
from uuid import UUID

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class CreditVerdict(StrEnum):
    """Persistable node-level verdicts supported by ``memory_feedback``."""

    DECISIVE = "decisive"
    HELPFUL = "helpful"
    HARMFUL = "harmful"
    NEUTRAL = "neutral"


class CreditAbstentionReason(StrEnum):
    """Why node-level causal credit was intentionally withheld."""

    NOT_SELECTED = "not_selected"
    NOT_USED = "not_used"
    MISSING_ABLATION = "missing_ablation"
    INSUFFICIENT_TRIALS = "insufficient_trials"
    HIGH_VARIANCE = "high_variance"
    BELOW_THRESHOLD = "below_threshold"
    INTERACTION_AMBIGUOUS = "interaction_ambiguous"


@dataclass(frozen=True, slots=True)
class OutcomeMeasurement:
    """Normalized evaluation of one counterfactual variant."""

    score: float
    task_success: bool
    tokens: int = 0
    latency_ms: float = 0.0

    def __post_init__(self) -> None:
        if not isfinite(self.score) or not -1.0 <= self.score <= 1.0:
            raise ValueError("score must be finite and between -1 and 1")
        if not isinstance(self.task_success, bool):
            raise ValueError("task_success must be a boolean")
        _validate_nonnegative_integer("tokens", self.tokens)
        if not isfinite(self.latency_ms) or self.latency_ms < 0:
            raise ValueError("latency_ms must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class CounterfactualTrial:
    """Full, baseline, and leave-one-memory-out outcomes for one matched replay."""

    trial_key: str
    context_hash: str
    continuation_hash: str
    full: OutcomeMeasurement
    no_memory: OutcomeMeasurement
    without_memory: Mapping[UUID, OutcomeMeasurement]

    def __post_init__(self) -> None:
        trial_key = self.trial_key.strip()
        if not trial_key:
            raise ValueError("trial_key must not be empty")
        _validate_hash("context_hash", self.context_hash)
        _validate_hash("continuation_hash", self.continuation_hash)
        if not isinstance(self.full, OutcomeMeasurement):
            raise ValueError("full must be an OutcomeMeasurement")
        if not isinstance(self.no_memory, OutcomeMeasurement):
            raise ValueError("no_memory must be an OutcomeMeasurement")
        if not isinstance(self.without_memory, Mapping):
            raise ValueError("without_memory must be a mapping")

        frozen: dict[UUID, OutcomeMeasurement] = {}
        for memory_id, measurement in self.without_memory.items():
            if not isinstance(memory_id, UUID):
                raise ValueError("without_memory keys must be UUIDs")
            if not isinstance(measurement, OutcomeMeasurement):
                raise ValueError(
                    "without_memory values must be OutcomeMeasurement instances"
                )
            frozen[memory_id] = measurement

        object.__setattr__(self, "trial_key", trial_key)
        object.__setattr__(self, "without_memory", MappingProxyType(frozen))


@dataclass(frozen=True, slots=True)
class CreditTarget:
    """Canonical retrieval-use evidence for one candidate memory."""

    memory_id: UUID
    retrieval_event_id: UUID
    router_decision_id: UUID
    selected_for_context: bool
    used_in_action: bool

    def __post_init__(self) -> None:
        for name in ("memory_id", "retrieval_event_id", "router_decision_id"):
            if not isinstance(getattr(self, name), UUID):
                raise ValueError(f"{name} must be a UUID")
        if not isinstance(self.selected_for_context, bool):
            raise ValueError("selected_for_context must be a boolean")
        if not isinstance(self.used_in_action, bool):
            raise ValueError("used_in_action must be a boolean")


@dataclass(frozen=True, slots=True)
class CausalCreditConfig:
    """Conservative thresholds for paired memory attribution."""

    min_trials: int = 2
    helpful_threshold: float = 0.05
    decisive_threshold: float = 0.20
    harmful_threshold: float = -0.05
    neutral_band: float = 0.02
    max_standard_error: float = 0.10
    reward_clip: float = 1.0
    record_neutral: bool = False

    def __post_init__(self) -> None:
        _validate_positive_integer("min_trials", self.min_trials)
        for name in (
            "helpful_threshold",
            "decisive_threshold",
            "harmful_threshold",
            "neutral_band",
            "max_standard_error",
            "reward_clip",
        ):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if self.helpful_threshold <= 0:
            raise ValueError("helpful_threshold must be greater than zero")
        if self.decisive_threshold < self.helpful_threshold:
            raise ValueError(
                "decisive_threshold must be greater than or equal to helpful_threshold"
            )
        if self.harmful_threshold >= 0:
            raise ValueError("harmful_threshold must be less than zero")
        if self.neutral_band < 0:
            raise ValueError("neutral_band must be non-negative")
        if self.neutral_band >= self.helpful_threshold:
            raise ValueError("neutral_band must be smaller than helpful_threshold")
        if self.harmful_threshold >= -self.neutral_band:
            raise ValueError(
                "harmful_threshold magnitude must exceed the neutral band"
            )
        if self.max_standard_error < 0:
            raise ValueError("max_standard_error must be non-negative")
        if self.reward_clip <= 0:
            raise ValueError("reward_clip must be greater than zero")
        if not isinstance(self.record_neutral, bool):
            raise ValueError("record_neutral must be a boolean")


@dataclass(frozen=True, slots=True)
class AttributedMemoryCredit:
    """Stable memory-specific marginal effect ready for feedback persistence."""

    memory_id: UUID
    retrieval_event_id: UUID
    router_decision_id: UUID
    verdict: CreditVerdict
    reward: float
    task_success: bool
    token_delta: int
    latency_delta_ms: float
    trial_count: int
    mean_full_score: float
    mean_no_memory_score: float
    mean_without_memory_score: float
    mean_bundle_uplift: float
    mean_effect: float
    standard_error: float
    full_success_rate: float
    without_success_rate: float
    context_set_hash: str
    continuation_set_hash: str

    def __post_init__(self) -> None:
        _validate_positive_integer("trial_count", self.trial_count)
        for name in (
            "reward",
            "latency_delta_ms",
            "mean_full_score",
            "mean_no_memory_score",
            "mean_without_memory_score",
            "mean_bundle_uplift",
            "mean_effect",
            "standard_error",
            "full_success_rate",
            "without_success_rate",
        ):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        if not 0.0 <= self.full_success_rate <= 1.0:
            raise ValueError("full_success_rate must be between zero and one")
        if not 0.0 <= self.without_success_rate <= 1.0:
            raise ValueError("without_success_rate must be between zero and one")
        _validate_hash("context_set_hash", self.context_set_hash)
        _validate_hash("continuation_set_hash", self.continuation_set_hash)


@dataclass(frozen=True, slots=True)
class CreditAbstention:
    """Explicit reason why a target did not receive node-level feedback."""

    memory_id: UUID
    retrieval_event_id: UUID
    router_decision_id: UUID
    reason: CreditAbstentionReason
    mean_effect: float | None = None
    standard_error: float | None = None

    def __post_init__(self) -> None:
        for name in ("mean_effect", "standard_error"):
            value = getattr(self, name)
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} must be finite when supplied")


@dataclass(frozen=True, slots=True)
class CreditAssignmentResult:
    """Credits and abstentions for one router decision and matched task replay."""

    router_decision_id: UUID | None
    credits: tuple[AttributedMemoryCredit, ...]
    abstentions: tuple[CreditAbstention, ...]
    interaction_ambiguous: bool
    context_set_hash: str | None
    continuation_set_hash: str | None


@dataclass(frozen=True, slots=True)
class _ProvisionalCredit:
    target: CreditTarget
    trial_count: int
    mean_full_score: float
    mean_no_memory_score: float
    mean_without_memory_score: float
    mean_bundle_uplift: float
    mean_effect: float
    standard_error: float
    full_success_rate: float
    without_success_rate: float
    token_delta: int
    latency_delta_ms: float


class CausalCreditAssigner:
    """Assign paired leave-one-out credit and abstain when evidence is weak."""

    def __init__(self, config: CausalCreditConfig | None = None) -> None:
        self.config = config or CausalCreditConfig()

    def assign(
        self,
        targets: Sequence[CreditTarget],
        trials: Sequence[CounterfactualTrial],
    ) -> CreditAssignmentResult:
        targets = tuple(targets)
        trials = tuple(trials)
        router_decision_id = _validate_targets(targets)
        _validate_trials(trials)

        if trials:
            context_set_hash = _hash_fingerprint_set(
                trial.context_hash for trial in trials
            )
            continuation_set_hash = _hash_fingerprint_set(
                trial.continuation_hash for trial in trials
            )
        else:
            context_set_hash = None
            continuation_set_hash = None

        abstentions: list[CreditAbstention] = []
        provisional: list[_ProvisionalCredit] = []

        for target in targets:
            if not target.selected_for_context:
                abstentions.append(
                    _abstain(target, CreditAbstentionReason.NOT_SELECTED)
                )
                continue
            if not target.used_in_action:
                abstentions.append(_abstain(target, CreditAbstentionReason.NOT_USED))
                continue
            if len(trials) < self.config.min_trials:
                abstentions.append(
                    _abstain(target, CreditAbstentionReason.INSUFFICIENT_TRIALS)
                )
                continue
            if any(target.memory_id not in trial.without_memory for trial in trials):
                abstentions.append(
                    _abstain(target, CreditAbstentionReason.MISSING_ABLATION)
                )
                continue

            item = _measure_target(target, trials)
            if item.standard_error > self.config.max_standard_error:
                abstentions.append(
                    _abstain(
                        target,
                        CreditAbstentionReason.HIGH_VARIANCE,
                        mean_effect=item.mean_effect,
                        standard_error=item.standard_error,
                    )
                )
                continue
            provisional.append(item)

        interaction_ambiguous = bool(provisional) and (
            fmean(item.mean_bundle_uplift for item in provisional)
            >= self.config.helpful_threshold
            and all(
                abs(item.mean_effect) <= self.config.neutral_band
                for item in provisional
            )
        )
        if interaction_ambiguous:
            abstentions.extend(
                _abstain(
                    item.target,
                    CreditAbstentionReason.INTERACTION_AMBIGUOUS,
                    mean_effect=item.mean_effect,
                    standard_error=item.standard_error,
                )
                for item in provisional
            )
            provisional = []

        credits: list[AttributedMemoryCredit] = []
        for item in provisional:
            verdict = self._classify(item)
            if verdict is None:
                abstentions.append(
                    _abstain(
                        item.target,
                        CreditAbstentionReason.BELOW_THRESHOLD,
                        mean_effect=item.mean_effect,
                        standard_error=item.standard_error,
                    )
                )
                continue
            if context_set_hash is None or continuation_set_hash is None:
                raise ValueError("classified credit requires matched trial fingerprints")
            reward = max(
                -self.config.reward_clip,
                min(item.mean_effect, self.config.reward_clip),
            )
            credits.append(
                AttributedMemoryCredit(
                    memory_id=item.target.memory_id,
                    retrieval_event_id=item.target.retrieval_event_id,
                    router_decision_id=item.target.router_decision_id,
                    verdict=verdict,
                    reward=reward,
                    task_success=item.full_success_rate > 0.5,
                    token_delta=item.token_delta,
                    latency_delta_ms=item.latency_delta_ms,
                    trial_count=item.trial_count,
                    mean_full_score=item.mean_full_score,
                    mean_no_memory_score=item.mean_no_memory_score,
                    mean_without_memory_score=item.mean_without_memory_score,
                    mean_bundle_uplift=item.mean_bundle_uplift,
                    mean_effect=item.mean_effect,
                    standard_error=item.standard_error,
                    full_success_rate=item.full_success_rate,
                    without_success_rate=item.without_success_rate,
                    context_set_hash=context_set_hash,
                    continuation_set_hash=continuation_set_hash,
                )
            )

        return CreditAssignmentResult(
            router_decision_id=router_decision_id,
            credits=tuple(credits),
            abstentions=tuple(abstentions),
            interaction_ambiguous=interaction_ambiguous,
            context_set_hash=context_set_hash,
            continuation_set_hash=continuation_set_hash,
        )

    def _classify(self, item: _ProvisionalCredit) -> CreditVerdict | None:
        if (
            item.mean_effect >= self.config.decisive_threshold
            and item.full_success_rate > item.without_success_rate
        ):
            return CreditVerdict.DECISIVE
        if item.mean_effect >= self.config.helpful_threshold:
            return CreditVerdict.HELPFUL
        if item.mean_effect <= self.config.harmful_threshold:
            return CreditVerdict.HARMFUL
        if (
            self.config.record_neutral
            and abs(item.mean_effect) <= self.config.neutral_band
        ):
            return CreditVerdict.NEUTRAL
        return None


def _validate_targets(targets: tuple[CreditTarget, ...]) -> UUID | None:
    seen: set[UUID] = set()
    router_ids: set[UUID] = set()
    for target in targets:
        if not isinstance(target, CreditTarget):
            raise ValueError("targets must contain CreditTarget instances")
        if target.memory_id in seen:
            raise ValueError("duplicate credit target memory_id")
        seen.add(target.memory_id)
        router_ids.add(target.router_decision_id)
    if len(router_ids) > 1:
        raise ValueError("all targets must share one router_decision_id")
    return next(iter(router_ids), None)


def _validate_trials(trials: tuple[CounterfactualTrial, ...]) -> None:
    seen: set[str] = set()
    contexts: set[str] = set()
    for trial in trials:
        if not isinstance(trial, CounterfactualTrial):
            raise ValueError("trials must contain CounterfactualTrial instances")
        if trial.trial_key in seen:
            raise ValueError("duplicate trial_key")
        seen.add(trial.trial_key)
        contexts.add(trial.context_hash)
    if len(contexts) > 1:
        raise ValueError("all trials must share one context_hash")


def _measure_target(
    target: CreditTarget,
    trials: tuple[CounterfactualTrial, ...],
) -> _ProvisionalCredit:
    full_scores = [trial.full.score for trial in trials]
    no_memory_scores = [trial.no_memory.score for trial in trials]
    without_scores = [
        trial.without_memory[target.memory_id].score for trial in trials
    ]
    effects = [
        full - without
        for full, without in zip(full_scores, without_scores, strict=True)
    ]
    bundle_uplifts = [
        full - baseline
        for full, baseline in zip(full_scores, no_memory_scores, strict=True)
    ]
    token_deltas = [
        trial.full.tokens - trial.without_memory[target.memory_id].tokens
        for trial in trials
    ]
    latency_deltas = [
        trial.full.latency_ms
        - trial.without_memory[target.memory_id].latency_ms
        for trial in trials
    ]
    full_success_rate = fmean(
        1.0 if trial.full.task_success else 0.0 for trial in trials
    )
    without_success_rate = fmean(
        1.0 if trial.without_memory[target.memory_id].task_success else 0.0
        for trial in trials
    )
    standard_error = (
        stdev(effects) / sqrt(len(effects)) if len(effects) > 1 else float("inf")
    )
    return _ProvisionalCredit(
        target=target,
        trial_count=len(trials),
        mean_full_score=fmean(full_scores),
        mean_no_memory_score=fmean(no_memory_scores),
        mean_without_memory_score=fmean(without_scores),
        mean_bundle_uplift=fmean(bundle_uplifts),
        mean_effect=fmean(effects),
        standard_error=standard_error,
        full_success_rate=full_success_rate,
        without_success_rate=without_success_rate,
        token_delta=round(fmean(token_deltas)),
        latency_delta_ms=fmean(latency_deltas),
    )


def _abstain(
    target: CreditTarget,
    reason: CreditAbstentionReason,
    *,
    mean_effect: float | None = None,
    standard_error: float | None = None,
) -> CreditAbstention:
    return CreditAbstention(
        memory_id=target.memory_id,
        retrieval_event_id=target.retrieval_event_id,
        router_decision_id=target.router_decision_id,
        reason=reason,
        mean_effect=mean_effect,
        standard_error=standard_error,
    )


def _hash_fingerprint_set(values: Sequence[str] | object) -> str:
    ordered = sorted(set(values))
    return hashlib.sha256(":".join(ordered).encode("utf-8")).hexdigest()


def _validate_hash(name: str, value: str) -> None:
    if _HASH_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _validate_nonnegative_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _validate_positive_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
