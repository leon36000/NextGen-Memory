"""Dependency-aware coalition contracts and interaction-credit estimation."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations
from math import isfinite, sqrt
from statistics import fmean, stdev
from types import MappingProxyType
from uuid import UUID

from .causal_credit import OutcomeMeasurement

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class InteractionEstimationMode(StrEnum):
    """Whether every valid order or a sampled order set was evaluated."""

    EXACT = "exact"
    SAMPLED = "sampled"


class InteractionCreditAbstentionReason(StrEnum):
    """Why a player did not receive a stable interaction-credit estimate."""

    INSUFFICIENT_TRIALS = "insufficient_trials"
    NO_COMPLETE_PATH = "no_complete_path"
    HIGH_VARIANCE = "high_variance"


class PairInteractionKind(StrEnum):
    """Classification for a context-averaged pairwise second difference."""

    SYNERGY = "synergy"
    REDUNDANCY = "redundancy"
    ADDITIVE = "additive"
    UNCERTAIN = "uncertain"
    NOT_COMPARABLE = "not_comparable"
    INSUFFICIENT_CONTEXTS = "insufficient_contexts"
    INSUFFICIENT_TRIALS = "insufficient_trials"


@dataclass(frozen=True, slots=True)
class InteractionCreditConfig:
    """Conservative controls for exact and sampled interaction attribution."""

    exact_player_limit: int = 8
    min_trials: int = 2
    max_standard_error: float = 0.10
    closure_tolerance: float = 1e-9
    max_sampled_orders: int = 256
    interaction_threshold: float = 0.05
    max_interaction_standard_error: float = 0.10

    def __post_init__(self) -> None:
        _validate_positive_integer("exact_player_limit", self.exact_player_limit)
        _validate_positive_integer("min_trials", self.min_trials)
        _validate_positive_integer("max_sampled_orders", self.max_sampled_orders)
        _validate_nonnegative_finite(
            "max_standard_error",
            self.max_standard_error,
        )
        _validate_nonnegative_finite(
            "closure_tolerance",
            self.closure_tolerance,
        )
        if (
            not isfinite(self.interaction_threshold)
            or self.interaction_threshold <= 0
        ):
            raise ValueError(
                "interaction_threshold must be finite and greater than zero"
            )
        _validate_nonnegative_finite(
            "max_interaction_standard_error",
            self.max_interaction_standard_error,
        )


class MemoryDependencyGraph:
    """A deterministic acyclic prerequisite graph over canonical memory UUIDs."""

    __slots__ = (
        "_direct_prerequisites",
        "_player_set",
        "_players",
        "_prerequisites",
        "_topological_orders",
        "_valid_coalitions",
    )

    def __init__(
        self,
        players: Sequence[UUID],
        prerequisites: Mapping[UUID, Collection[UUID]] | None = None,
    ) -> None:
        raw_players = tuple(players)
        for player in raw_players:
            if not isinstance(player, UUID):
                raise ValueError("players must contain UUID values")
        if len(set(raw_players)) != len(raw_players):
            raise ValueError("duplicate player UUID")

        self._players = tuple(sorted(raw_players, key=str))
        self._player_set = frozenset(self._players)
        raw_prerequisites = prerequisites or {}
        if not isinstance(raw_prerequisites, Mapping):
            raise ValueError("prerequisites must be a mapping")

        direct: dict[UUID, frozenset[UUID]] = {
            player: frozenset() for player in self._players
        }
        for player, dependencies in raw_prerequisites.items():
            if not isinstance(player, UUID) or player not in self._player_set:
                raise ValueError("prerequisite mapping contains unknown player")
            if not isinstance(dependencies, Collection):
                raise ValueError("prerequisites for a player must be a collection")
            normalized: set[UUID] = set()
            for dependency in dependencies:
                if not isinstance(dependency, UUID):
                    raise ValueError("prerequisites must contain UUID values")
                if dependency not in self._player_set:
                    raise ValueError("unknown prerequisite memory")
                if dependency == player:
                    raise ValueError("memory prerequisite self-dependency")
                normalized.add(dependency)
            direct[player] = frozenset(normalized)

        closure = self._build_transitive_closure(direct)
        self._direct_prerequisites = MappingProxyType(direct)
        self._prerequisites = MappingProxyType(closure)
        self._topological_orders: tuple[tuple[UUID, ...], ...] | None = None
        self._valid_coalitions: tuple[frozenset[UUID], ...] | None = None

    @property
    def players(self) -> tuple[UUID, ...]:
        """Return canonical players in deterministic UUID order."""

        return self._players

    @property
    def prerequisites(self) -> Mapping[UUID, frozenset[UUID]]:
        """Return the immutable transitive prerequisite closure."""

        return self._prerequisites

    def direct_prerequisites_of(self, memory_id: UUID) -> frozenset[UUID]:
        """Return direct prerequisites for one canonical player."""

        self._require_player(memory_id)
        return self._direct_prerequisites[memory_id]

    def prerequisites_of(self, memory_id: UUID) -> frozenset[UUID]:
        """Return all transitive prerequisites for one canonical player."""

        self._require_player(memory_id)
        return self._prerequisites[memory_id]

    def is_ancestor(self, ancestor: UUID, descendant: UUID) -> bool:
        """Return whether ``ancestor`` is a transitive prerequisite."""

        self._require_player(ancestor)
        self._require_player(descendant)
        return ancestor in self._prerequisites[descendant]

    def is_valid_coalition(self, coalition: frozenset[UUID]) -> bool:
        """Return whether a coalition is canonical and dependency-closed."""

        if not isinstance(coalition, frozenset):
            return False
        if any(not isinstance(memory_id, UUID) for memory_id in coalition):
            return False
        if not coalition.issubset(self._player_set):
            return False
        return all(
            self._prerequisites[memory_id].issubset(coalition)
            for memory_id in coalition
        )

    def validate_coalition(self, coalition: frozenset[UUID]) -> None:
        """Fail closed when a coalition is malformed or violates dependencies."""

        if not isinstance(coalition, frozenset):
            raise ValueError("coalition must be a frozenset")
        if any(not isinstance(memory_id, UUID) for memory_id in coalition):
            raise ValueError("coalition members must be UUID values")
        unknown = coalition.difference(self._player_set)
        if unknown:
            raise ValueError("coalition contains unknown memory")
        if not self.is_valid_coalition(coalition):
            raise ValueError("coalition must be dependency-closed")

    def is_valid_order(self, order: Sequence[UUID]) -> bool:
        """Return whether an order is a topological permutation of all players."""

        normalized = tuple(order)
        if len(normalized) != len(self._players):
            return False
        if any(not isinstance(memory_id, UUID) for memory_id in normalized):
            return False
        if len(set(normalized)) != len(normalized):
            return False
        if frozenset(normalized) != self._player_set:
            return False

        seen: set[UUID] = set()
        for memory_id in normalized:
            if not self._prerequisites[memory_id].issubset(seen):
                return False
            seen.add(memory_id)
        return True

    def topological_orders(self) -> tuple[tuple[UUID, ...], ...]:
        """Enumerate every valid topological order deterministically."""

        if self._topological_orders is None:
            orders: list[tuple[UUID, ...]] = []

            def visit(prefix: tuple[UUID, ...], remaining: frozenset[UUID]) -> None:
                if not remaining:
                    orders.append(prefix)
                    return
                prefix_set = frozenset(prefix)
                available = tuple(
                    memory_id
                    for memory_id in sorted(remaining, key=str)
                    if self._direct_prerequisites[memory_id].issubset(prefix_set)
                )
                for memory_id in available:
                    visit((*prefix, memory_id), remaining.difference({memory_id}))

            visit((), self._player_set)
            self._topological_orders = tuple(orders)
        return self._topological_orders

    def valid_coalitions(self) -> tuple[frozenset[UUID], ...]:
        """Enumerate every dependency-closed subset deterministically."""

        if self._valid_coalitions is None:
            coalitions: list[frozenset[UUID]] = []
            for size in range(len(self._players) + 1):
                for members in combinations(self._players, size):
                    coalition = frozenset(members)
                    if self.is_valid_coalition(coalition):
                        coalitions.append(coalition)
            self._valid_coalitions = tuple(coalitions)
        return self._valid_coalitions

    def _require_player(self, memory_id: UUID) -> None:
        if not isinstance(memory_id, UUID) or memory_id not in self._player_set:
            raise ValueError("unknown memory player")

    @staticmethod
    def _build_transitive_closure(
        direct: Mapping[UUID, frozenset[UUID]],
    ) -> dict[UUID, frozenset[UUID]]:
        closure: dict[UUID, frozenset[UUID]] = {}
        visiting: set[UUID] = set()

        def resolve(memory_id: UUID) -> frozenset[UUID]:
            existing = closure.get(memory_id)
            if existing is not None:
                return existing
            if memory_id in visiting:
                raise ValueError("memory prerequisite graph contains a cycle")
            visiting.add(memory_id)
            ancestors: set[UUID] = set()
            for prerequisite in direct[memory_id]:
                ancestors.add(prerequisite)
                ancestors.update(resolve(prerequisite))
            visiting.remove(memory_id)
            result = frozenset(ancestors)
            closure[memory_id] = result
            return result

        for memory_id in direct:
            resolve(memory_id)
        return closure


@dataclass(frozen=True, slots=True)
class InteractionTrial:
    """Matched outcomes for dependency-aware memory coalitions."""

    trial_key: str
    context_hash: str
    continuation_hash: str
    outcomes: Mapping[frozenset[UUID], OutcomeMeasurement]

    def __post_init__(self) -> None:
        trial_key = self.trial_key.strip()
        if not trial_key:
            raise ValueError("trial_key must not be empty")
        _validate_hash("context_hash", self.context_hash)
        _validate_hash("continuation_hash", self.continuation_hash)
        if not isinstance(self.outcomes, Mapping):
            raise ValueError("outcomes must be a mapping")
        if not self.outcomes:
            raise ValueError("outcomes must contain at least one coalition")

        normalized: list[tuple[frozenset[UUID], OutcomeMeasurement]] = []
        for coalition, measurement in self.outcomes.items():
            if not isinstance(coalition, frozenset):
                raise ValueError("coalition keys must be frozenset values")
            if any(not isinstance(memory_id, UUID) for memory_id in coalition):
                raise ValueError("coalition members must be UUID values")
            if not isinstance(measurement, OutcomeMeasurement):
                raise ValueError("outcome values must be OutcomeMeasurement instances")
            normalized.append((coalition, measurement))

        normalized.sort(key=lambda item: _coalition_sort_key(item[0]))
        object.__setattr__(self, "trial_key", trial_key)
        object.__setattr__(self, "outcomes", MappingProxyType(dict(normalized)))


@dataclass(frozen=True, slots=True)
class MemoryInteractionCredit:
    """Stable per-memory value allocated across valid predecessor contexts."""

    memory_id: UUID
    score_value: float
    score_standard_error: float
    token_value: float
    latency_value_ms: float
    trial_count: int
    order_count: int

    def __post_init__(self) -> None:
        if not isinstance(self.memory_id, UUID):
            raise ValueError("memory_id must be a UUID")
        for name in (
            "score_value",
            "score_standard_error",
            "token_value",
            "latency_value_ms",
        ):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        _validate_positive_integer("trial_count", self.trial_count)
        _validate_positive_integer("order_count", self.order_count)


@dataclass(frozen=True, slots=True)
class MemoryInteractionAbstention:
    """Explicit reason a player did not receive a stable value estimate."""

    memory_id: UUID
    reason: InteractionCreditAbstentionReason
    usable_trial_count: int
    score_standard_error: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.memory_id, UUID):
            raise ValueError("memory_id must be a UUID")
        _validate_nonnegative_integer("usable_trial_count", self.usable_trial_count)
        if self.score_standard_error is not None and not isfinite(
            self.score_standard_error
        ):
            raise ValueError("score_standard_error must be finite when supplied")


@dataclass(frozen=True, slots=True)
class InteractionCreditResult:
    """Complete allocation, uncertainty, and closure evidence for one game."""

    mode: InteractionEstimationMode
    players: tuple[UUID, ...]
    orders: tuple[tuple[UUID, ...], ...]
    credits: tuple[MemoryInteractionCredit, ...]
    abstentions: tuple[MemoryInteractionAbstention, ...]
    usable_trial_count: int
    full_lift: float
    allocated_value: float
    closure_residual: float
    context_set_hash: str
    continuation_set_hash: str

    def __post_init__(self) -> None:
        _validate_nonnegative_integer("usable_trial_count", self.usable_trial_count)
        for name in ("full_lift", "allocated_value", "closure_residual"):
            if not isfinite(getattr(self, name)):
                raise ValueError(f"{name} must be finite")
        _validate_hash("context_set_hash", self.context_set_hash)
        _validate_hash("continuation_set_hash", self.continuation_set_hash)


@dataclass(frozen=True, slots=True)
class _TrialPlayerValue:
    score: float
    tokens: float
    latency_ms: float


class PrecedenceShapleyEstimator:
    """Average marginal value across complete valid topological-order paths."""

    def __init__(self, config: InteractionCreditConfig | None = None) -> None:
        self.config = config or InteractionCreditConfig()

    def estimate(
        self,
        graph: MemoryDependencyGraph,
        trials: Sequence[InteractionTrial],
        *,
        orders: Sequence[Sequence[UUID]] | None = None,
    ) -> InteractionCreditResult:
        if not isinstance(graph, MemoryDependencyGraph):
            raise ValueError("graph must be a MemoryDependencyGraph")
        normalized_orders, mode = self._resolve_orders(graph, orders)
        normalized_trials = tuple(trials)
        self._validate_trials(graph, normalized_trials)

        context_set_hash = _hash_fingerprint_set(
            trial.context_hash for trial in normalized_trials
        )
        continuation_set_hash = _hash_fingerprint_set(
            trial.continuation_hash for trial in normalized_trials
        )
        per_player: dict[UUID, list[_TrialPlayerValue]] = {
            memory_id: [] for memory_id in graph.players
        }
        full_lifts: list[float] = []
        contributing_orders: set[tuple[UUID, ...]] = set()

        for trial in normalized_trials:
            complete_orders = tuple(
                order
                for order in normalized_orders
                if all(prefix in trial.outcomes for prefix in _prefixes(order))
            )
            if not complete_orders:
                continue
            contributing_orders.update(complete_orders)
            full_lifts.append(
                trial.outcomes[frozenset(graph.players)].score
                - trial.outcomes[frozenset()].score
            )
            for memory_id in graph.players:
                scores: list[float] = []
                tokens: list[float] = []
                latencies: list[float] = []
                for order in complete_orders:
                    before, after = _edge_for(order, memory_id)
                    before_outcome = trial.outcomes[before]
                    after_outcome = trial.outcomes[after]
                    scores.append(after_outcome.score - before_outcome.score)
                    tokens.append(after_outcome.tokens - before_outcome.tokens)
                    latencies.append(
                        after_outcome.latency_ms - before_outcome.latency_ms
                    )
                per_player[memory_id].append(
                    _TrialPlayerValue(
                        score=fmean(scores),
                        tokens=fmean(tokens),
                        latency_ms=fmean(latencies),
                    )
                )

        usable_trial_count = len(full_lifts)
        if usable_trial_count == 0:
            return InteractionCreditResult(
                mode=mode,
                players=graph.players,
                orders=normalized_orders,
                credits=(),
                abstentions=tuple(
                    MemoryInteractionAbstention(
                        memory_id=memory_id,
                        reason=InteractionCreditAbstentionReason.NO_COMPLETE_PATH,
                        usable_trial_count=0,
                    )
                    for memory_id in graph.players
                ),
                usable_trial_count=0,
                full_lift=0.0,
                allocated_value=0.0,
                closure_residual=0.0,
                context_set_hash=context_set_hash,
                continuation_set_hash=continuation_set_hash,
            )

        means: dict[UUID, _TrialPlayerValue] = {}
        standard_errors: dict[UUID, float] = {}
        for memory_id, values in per_player.items():
            if len(values) != usable_trial_count:
                raise ValueError("complete order paths must cover every memory player")
            score_values = [value.score for value in values]
            means[memory_id] = _TrialPlayerValue(
                score=fmean(score_values),
                tokens=fmean(value.tokens for value in values),
                latency_ms=fmean(value.latency_ms for value in values),
            )
            standard_errors[memory_id] = (
                stdev(score_values) / sqrt(len(score_values))
                if len(score_values) > 1
                else float("inf")
            )

        full_lift = fmean(full_lifts)
        allocated_value = sum(value.score for value in means.values())
        closure_residual = allocated_value - full_lift
        if abs(closure_residual) > self.config.closure_tolerance:
            raise ValueError(
                "interaction credit closure residual exceeds closure_tolerance"
            )

        credits: list[MemoryInteractionCredit] = []
        abstentions: list[MemoryInteractionAbstention] = []
        order_count = len(contributing_orders)
        for memory_id in graph.players:
            if usable_trial_count < self.config.min_trials:
                abstentions.append(
                    MemoryInteractionAbstention(
                        memory_id=memory_id,
                        reason=(
                            InteractionCreditAbstentionReason.INSUFFICIENT_TRIALS
                        ),
                        usable_trial_count=usable_trial_count,
                    )
                )
                continue
            standard_error = standard_errors[memory_id]
            if standard_error > self.config.max_standard_error:
                abstentions.append(
                    MemoryInteractionAbstention(
                        memory_id=memory_id,
                        reason=InteractionCreditAbstentionReason.HIGH_VARIANCE,
                        usable_trial_count=usable_trial_count,
                        score_standard_error=standard_error,
                    )
                )
                continue
            value = means[memory_id]
            credits.append(
                MemoryInteractionCredit(
                    memory_id=memory_id,
                    score_value=value.score,
                    score_standard_error=standard_error,
                    token_value=value.tokens,
                    latency_value_ms=value.latency_ms,
                    trial_count=usable_trial_count,
                    order_count=order_count,
                )
            )

        return InteractionCreditResult(
            mode=mode,
            players=graph.players,
            orders=normalized_orders,
            credits=tuple(credits),
            abstentions=tuple(abstentions),
            usable_trial_count=usable_trial_count,
            full_lift=full_lift,
            allocated_value=allocated_value,
            closure_residual=closure_residual,
            context_set_hash=context_set_hash,
            continuation_set_hash=continuation_set_hash,
        )

    def _resolve_orders(
        self,
        graph: MemoryDependencyGraph,
        orders: Sequence[Sequence[UUID]] | None,
    ) -> tuple[tuple[tuple[UUID, ...], ...], InteractionEstimationMode]:
        all_orders = graph.topological_orders()
        if orders is None:
            if len(graph.players) > self.config.exact_player_limit:
                raise ValueError(
                    "sampled orders are required above exact_player_limit"
                )
            return all_orders, InteractionEstimationMode.EXACT

        normalized = tuple(tuple(order) for order in orders)
        if not normalized:
            raise ValueError("at least one sampled order is required")
        if len(normalized) > self.config.max_sampled_orders:
            raise ValueError("orders exceed max_sampled_orders")
        if len(set(normalized)) != len(normalized):
            raise ValueError("orders must not contain duplicates")
        if any(not graph.is_valid_order(order) for order in normalized):
            raise ValueError("every order must be a valid topological order")
        normalized = tuple(sorted(normalized, key=_order_sort_key))
        mode = (
            InteractionEstimationMode.EXACT
            if len(graph.players) <= self.config.exact_player_limit
            and normalized == all_orders
            else InteractionEstimationMode.SAMPLED
        )
        return normalized, mode

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


def _prefixes(order: Sequence[UUID]) -> tuple[frozenset[UUID], ...]:
    prefix: set[UUID] = set()
    values: list[frozenset[UUID]] = [frozenset()]
    for memory_id in order:
        prefix.add(memory_id)
        values.append(frozenset(prefix))
    return tuple(values)


def _edge_for(
    order: Sequence[UUID],
    memory_id: UUID,
) -> tuple[frozenset[UUID], frozenset[UUID]]:
    prefix: set[UUID] = set()
    for current in order:
        before = frozenset(prefix)
        prefix.add(current)
        if current == memory_id:
            return before, frozenset(prefix)
    raise ValueError("memory_id is absent from topological order")


def _hash_fingerprint_set(values: Collection[str] | Sequence[str] | object) -> str:
    ordered = sorted(set(values))
    return hashlib.sha256(":".join(ordered).encode("utf-8")).hexdigest()


def _coalition_sort_key(coalition: frozenset[UUID]) -> tuple[int, tuple[str, ...]]:
    return len(coalition), tuple(sorted(str(memory_id) for memory_id in coalition))


def _order_sort_key(order: Sequence[UUID]) -> tuple[str, ...]:
    return tuple(str(memory_id) for memory_id in order)


def _validate_hash(name: str, value: str) -> None:
    if _HASH_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 hex digest")


def _validate_positive_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")


def _validate_nonnegative_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _validate_nonnegative_finite(name: str, value: float) -> None:
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")
