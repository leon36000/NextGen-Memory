"""Telemetry ports and privacy-preserving routing records."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID

from .domain import RoutingDecision, RoutingRequest


@dataclass(frozen=True, slots=True)
class RoutingTelemetryRecord:
    request_id: UUID
    space_id: UUID
    query_hash: str
    query_features: Mapping[str, Any]
    decision: RoutingDecision

    def __post_init__(self) -> None:
        if len(self.query_hash) != 64:
            raise ValueError("query_hash must be a SHA-256 hexadecimal digest")
        object.__setattr__(self, "query_features", MappingProxyType(dict(self.query_features)))

    @classmethod
    def from_route(
        cls,
        request: RoutingRequest,
        decision: RoutingDecision,
    ) -> RoutingTelemetryRecord:
        features = {
            "scope": request.scope.to_dict(),
            "task_kind": request.task_kind.value,
            "plan_phase": request.plan_phase.value,
            "needs": sorted(need.value for need in request.needs),
            "temporal_intent": request.temporal_intent.value,
            "exactness": request.exactness.value,
            "risk": request.risk.value,
            "uncertainty": request.uncertainty,
            "token_budget": request.token_budget,
            "latency_budget_ms": request.latency_budget_ms,
            "max_experts": request.max_experts,
            "minimum_authority": request.minimum_authority,
            "query_length": len(request.query),
        }
        return cls(
            request_id=request.request_id,
            space_id=request.scope.space_id,
            query_hash=sha256(request.query.encode("utf-8")).hexdigest(),
            query_features=features,
            decision=decision,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": str(self.request_id),
            "space_id": str(self.space_id),
            "query_hash": self.query_hash,
            "query_features": dict(self.query_features),
            "decision": self.decision.to_dict(),
        }


class RoutingDecisionSink(Protocol):
    def record(self, record: RoutingTelemetryRecord) -> None:
        """Persist or emit a privacy-preserving routing record."""
        ...


class InMemoryRoutingDecisionSink:
    """Small deterministic sink useful for tests and local experiments."""

    def __init__(self) -> None:
        self.records: list[RoutingTelemetryRecord] = []

    def record(self, record: RoutingTelemetryRecord) -> None:
        self.records.append(record)
