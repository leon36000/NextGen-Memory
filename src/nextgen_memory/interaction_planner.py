"""Deterministic planning of valid coalition evaluations under a hard budget."""

from __future__ import annotations

import hashlib
import random
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite, sqrt
from uuid import UUID

from .interaction_credit import InteractionEstimationMode, MemoryDependencyGraph


class CoalitionRequestReason(StrEnum):
    """Why a coalition evaluation was requested."""

    REQUIRED_BOUNDARY = "required_boundary"
    MISSING_PREFIX = "missing_prefix"
    COVERAGE = "coverage"


@dataclass(frozen=True, slots=True)
class AdaptiveOrderPlannerConfig:
    """Controls for deterministic adaptive topological-order sampling."""

    seed: int = 20_260_814
    exact_player_limit: int = 8
    max_orders: int = 256
    candidate_pool_size: int = 64
    coverage_weight: float = 1.0
    boundary_weight: float = 1000.0

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise ValueError("seed must be an integer")
        _validate_positive_integer("exact_player_limit", self.exact_player_limit)
        _validate_positive_integer("max_orders", self.max_orders)
        _validate_positive_integer("candidate_pool_size", self.candidate_pool_size)
        _validate_nonnegative_finite("coverage_weight", self.coverage_weight)
        _validate_nonnegative_finite("boundary_weight", self.boundary_weight)


@dataclass(frozen=True, slots=True)
class CoalitionRequest:
    """One deterministic request for a valid coalition outcome."""

    coalition: frozenset[UUID]
    order_id: str
    prefix_position: int
    reason: CoalitionRequestReason
    request_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.coalition, frozenset) or any(
            not isinstance(memory_id, UUID) for memory_id in self.coalition
        ):
            raise ValueError("coalition must be a frozenset of UUID values")
        if not self.order_id:
            raise ValueError("order_id must not be empty")
        _validate_nonnegative_integer("prefix_position", self.prefix_position)
        if not isinstance(self.reason, CoalitionRequestReason):
            raise ValueError("reason must be a CoalitionRequestReason")
        _validate_hash("request_key", self.request_key)


@dataclass(frozen=True, slots=True)
class InteractionOrderPlan:
    """Selected valid orders and their unique missing coalition requests."""

    mode: InteractionEstimationMode
    orders: tuple[tuple[UUID, ...], ...]
    requests: tuple[CoalitionRequest, ...]
    reused_coalition_count: int
    requested_coalition_count: int
    budget: int
    exact_complete: bool

    def __post_init__(self) -> None:
        _validate_nonnegative_integer(
            "reused_coalition_count",
            self.reused_coalition_count,
        )
        _validate_nonnegative_integer(
            "requested_coalition_count",
            self.requested_coalition_count,
        )
        _validate_nonnegative_integer("budget", self.budget)
        if self.requested_coalition_count != len(self.requests):
            raise ValueError("requested_coalition_count must match requests")
        if self.requested_coalition_count > self.budget:
            raise ValueError("requested coalitions exceed budget")
        if not isinstance(self.exact_complete, bool):
            raise ValueError("exact_complete must be a boolean")


class AdaptiveOrderPlanner:
    """Select complete valid order paths while reusing evaluated coalitions."""

    def __init__(self, config: AdaptiveOrderPlannerConfig | None = None) -> None:
        self.config = config or AdaptiveOrderPlannerConfig()

    def plan(
        self,
        graph: MemoryDependencyGraph,
        evaluated_coalitions: Collection[frozenset[UUID]],
        budget: int,
    ) -> InteractionOrderPlan:
        if not isinstance(graph, MemoryDependencyGraph):
            raise ValueError("graph must be a MemoryDependencyGraph")
        _validate_nonnegative_integer("budget", budget)
        evaluated = self._validate_cache(graph, evaluated_coalitions)

        if len(graph.players) <= self.config.exact_player_limit:
            exact = self._try_exact_plan(graph, evaluated, budget)
            if exact is not None:
                return exact
        return self._sampled_plan(graph, evaluated, budget)

    def _try_exact_plan(
        self,
        graph: MemoryDependencyGraph,
        evaluated: frozenset[frozenset[UUID]],
        budget: int,
    ) -> InteractionOrderPlan | None:
        all_orders = graph.topological_orders()
        valid_coalitions = graph.valid_coalitions()
        missing = tuple(
            coalition for coalition in valid_coalitions if coalition not in evaluated
        )
        if len(missing) > budget:
            return None

        empty = frozenset()
        full = frozenset(graph.players)
        ordered_missing = tuple(
            coalition
            for coalition in (empty, full)
            if coalition in missing
        ) + tuple(
            coalition
            for coalition in missing
            if coalition not in {empty, full}
        )
        requests = tuple(
            self._request_for_exact_coalition(
                coalition,
                graph,
                all_orders,
                empty,
                full,
            )
            for coalition in ordered_missing
        )
        used = {
            prefix
            for order in all_orders
            for prefix in _prefixes(order)
        }
        return InteractionOrderPlan(
            mode=InteractionEstimationMode.EXACT,
            orders=all_orders,
            requests=requests,
            reused_coalition_count=len(used.intersection(evaluated)),
            requested_coalition_count=len(requests),
            budget=budget,
            exact_complete=True,
        )

    def _request_for_exact_coalition(
        self,
        coalition: frozenset[UUID],
        graph: MemoryDependencyGraph,
        orders: tuple[tuple[UUID, ...], ...],
        empty: frozenset[UUID],
        full: frozenset[UUID],
    ) -> CoalitionRequest:
        if coalition == empty:
            order_id = "boundary-empty"
            position = 0
            reason = CoalitionRequestReason.REQUIRED_BOUNDARY
        elif coalition == full:
            order_id = "boundary-full"
            position = len(graph.players)
            reason = CoalitionRequestReason.REQUIRED_BOUNDARY
        else:
            order = next(
                order
                for order in orders
                if coalition in _prefixes(order)
            )
            order_id = _order_id(order)
            position = _prefixes(order).index(coalition)
            reason = CoalitionRequestReason.MISSING_PREFIX
        return CoalitionRequest(
            coalition=coalition,
            order_id=order_id,
            prefix_position=position,
            reason=reason,
            request_key=_request_key(coalition),
        )

    def _sampled_plan(
        self,
        graph: MemoryDependencyGraph,
        evaluated: frozenset[frozenset[UUID]],
        budget: int,
    ) -> InteractionOrderPlan:
        rng = random.Random(self.config.seed)
        requested: set[frozenset[UUID]] = set()
        requests: list[CoalitionRequest] = []
        selected_orders: list[tuple[UUID, ...]] = []
        selected_set: set[tuple[UUID, ...]] = set()
        position_counts: dict[tuple[UUID, int], int] = {}
        empty = frozenset()
        full = frozenset(graph.players)

        for coalition, position, label in (
            (empty, 0, "boundary-empty"),
            (full, len(graph.players), "boundary-full"),
        ):
            if coalition in evaluated or coalition in requested:
                continue
            if len(requests) >= budget:
                break
            requested.add(coalition)
            requests.append(
                CoalitionRequest(
                    coalition=coalition,
                    order_id=label,
                    prefix_position=position,
                    reason=CoalitionRequestReason.REQUIRED_BOUNDARY,
                    request_key=_request_key(coalition),
                )
            )

        while len(selected_orders) < self.config.max_orders:
            remaining_budget = budget - len(requests)
            candidates = self._candidate_orders(
                graph,
                rng,
                selected_set,
            )
            scored: list[
                tuple[
                    float,
                    tuple[str, ...],
                    tuple[UUID, ...],
                    tuple[frozenset[UUID], ...],
                ]
            ] = []
            for order in candidates:
                order_prefixes = _prefixes(order)
                missing = tuple(
                    prefix
                    for prefix in order_prefixes
                    if prefix not in evaluated and prefix not in requested
                )
                if len(missing) > remaining_budget:
                    continue
                coverage = sum(
                    1.0 / sqrt(position_counts.get((player, position), 0) + 1)
                    for position, player in enumerate(order)
                )
                boundary_bonus = self.config.boundary_weight * sum(
                    boundary in missing for boundary in (empty, full)
                )
                score = (
                    len(missing)
                    + self.config.coverage_weight * coverage
                    + boundary_bonus
                )
                scored.append(
                    (
                        score,
                        _order_sort_key(order),
                        order,
                        missing,
                    )
                )
            if not scored:
                break

            scored.sort(key=lambda item: (-item[0], item[1]))
            _, _, order, missing = scored[0]
            selected_orders.append(order)
            selected_set.add(order)
            order_id = _order_id(order)
            prefix_positions = {
                coalition: position
                for position, coalition in enumerate(_prefixes(order))
            }
            for coalition in missing:
                if coalition in requested or coalition in evaluated:
                    continue
                requested.add(coalition)
                requests.append(
                    CoalitionRequest(
                        coalition=coalition,
                        order_id=order_id,
                        prefix_position=prefix_positions[coalition],
                        reason=(
                            CoalitionRequestReason.REQUIRED_BOUNDARY
                            if coalition in {empty, full}
                            else CoalitionRequestReason.MISSING_PREFIX
                        ),
                        request_key=_request_key(coalition),
                    )
                )
            for position, player in enumerate(order):
                key = (player, position)
                position_counts[key] = position_counts.get(key, 0) + 1

        used = {
            prefix
            for order in selected_orders
            for prefix in _prefixes(order)
        }
        return InteractionOrderPlan(
            mode=InteractionEstimationMode.SAMPLED,
            orders=tuple(selected_orders),
            requests=tuple(requests),
            reused_coalition_count=len(used.intersection(evaluated)),
            requested_coalition_count=len(requests),
            budget=budget,
            exact_complete=False,
        )

    def _candidate_orders(
        self,
        graph: MemoryDependencyGraph,
        rng: random.Random,
        selected: set[tuple[UUID, ...]],
    ) -> tuple[tuple[UUID, ...], ...]:
        candidates: set[tuple[UUID, ...]] = set()
        attempts = 0
        maximum_attempts = self.config.candidate_pool_size * 20
        while (
            len(candidates) < self.config.candidate_pool_size
            and attempts < maximum_attempts
        ):
            attempts += 1
            order = _random_topological_order(graph, rng)
            if order not in selected:
                candidates.add(order)
        return tuple(sorted(candidates, key=_order_sort_key))

    @staticmethod
    def _validate_cache(
        graph: MemoryDependencyGraph,
        evaluated_coalitions: Collection[frozenset[UUID]],
    ) -> frozenset[frozenset[UUID]]:
        if not isinstance(evaluated_coalitions, Collection):
            raise ValueError("evaluated_coalitions must be a collection")
        normalized: set[frozenset[UUID]] = set()
        for coalition in evaluated_coalitions:
            graph.validate_coalition(coalition)
            normalized.add(coalition)
        return frozenset(normalized)


def _random_topological_order(
    graph: MemoryDependencyGraph,
    rng: random.Random,
) -> tuple[UUID, ...]:
    remaining = set(graph.players)
    prefix: list[UUID] = []
    seen: set[UUID] = set()
    while remaining:
        available = sorted(
            (
                player
                for player in remaining
                if graph.direct_prerequisites_of(player).issubset(seen)
            ),
            key=str,
        )
        if not available:
            raise ValueError("dependency graph has no valid topological continuation")
        chosen = rng.choice(available)
        prefix.append(chosen)
        seen.add(chosen)
        remaining.remove(chosen)
    return tuple(prefix)


def _prefixes(order: Sequence[UUID]) -> tuple[frozenset[UUID], ...]:
    prefix: set[UUID] = set()
    result: list[frozenset[UUID]] = [frozenset()]
    for player in order:
        prefix.add(player)
        result.append(frozenset(prefix))
    return tuple(result)


def _request_key(coalition: frozenset[UUID]) -> str:
    members = ":".join(sorted(str(memory_id) for memory_id in coalition))
    return hashlib.sha256(
        f"interaction-credit-v0:{members}".encode("utf-8")
    ).hexdigest()


def _order_id(order: Sequence[UUID]) -> str:
    members = ":".join(str(memory_id) for memory_id in order)
    return hashlib.sha256(f"interaction-order-v0:{members}".encode()).hexdigest()


def _order_sort_key(order: Sequence[UUID]) -> tuple[str, ...]:
    return tuple(str(memory_id) for memory_id in order)


def _validate_hash(name: str, value: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
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
