"""Stable domain contracts for the NextGen Memory routing kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from math import isfinite
from typing import Any
from uuid import UUID, uuid4


class ExpertKey(StrEnum):
    WORKING = "working"
    EXECUTION = "execution"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    TEMPORAL = "temporal"
    CAUSAL = "causal"
    PROCEDURAL = "procedural"
    FAILURE = "failure"
    DECISION = "decision"
    REPOSITORY = "repository"
    RESEARCH = "research"
    FEEDBACK = "feedback"


class TaskKind(StrEnum):
    SOFTWARE_ENGINEERING = "software_engineering"
    RESEARCH = "research"
    PROJECT_CONTINUITY = "project_continuity"
    MEMORY_MAINTENANCE = "memory_maintenance"
    TOOL_EXECUTION = "tool_execution"
    GENERAL = "general"


class PlanPhase(StrEnum):
    UNKNOWN = "unknown"
    UNDERSTAND = "understand"
    LOCATE = "locate"
    PLAN = "plan"
    EDIT = "edit"
    VERIFY = "verify"
    DIAGNOSE = "diagnose"
    SYNTHESIZE = "synthesize"
    ANSWER = "answer"


class EvidenceNeed(StrEnum):
    CURRENT_STATE = "current_state"
    HISTORICAL = "historical"
    EXACT_EVIDENCE = "exact_evidence"
    CAUSAL = "causal"
    PROCEDURE = "procedure"
    FAILURE = "failure"
    DECISION = "decision"
    REPOSITORY = "repository"
    RESEARCH = "research"
    EXECUTION = "execution"
    FEEDBACK = "feedback"


class TemporalIntent(StrEnum):
    NONE = "none"
    CURRENT = "current"
    HISTORICAL = "historical"
    COMPARATIVE = "comparative"


class ExactnessNeed(StrEnum):
    LOW = "low"
    SEMANTIC = "semantic"
    EXACT = "exact"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    SECRET = "secret"

    @property
    def rank(self) -> int:
        return {
            Sensitivity.PUBLIC: 0,
            Sensitivity.INTERNAL: 1,
            Sensitivity.SENSITIVE: 2,
            Sensitivity.SECRET: 3,
        }[self]


@dataclass(frozen=True, slots=True)
class RoutingScope:
    """Hard scope and authorization information used before retrieval."""

    space_id: UUID
    project_key: str
    repository_key: str | None = None
    branch: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    sensitivity_clearance: Sensitivity = Sensitivity.INTERNAL

    def __post_init__(self) -> None:
        if not self.project_key.strip():
            raise ValueError("project_key must not be empty")
        object.__setattr__(self, "project_key", self.project_key.strip())
        object.__setattr__(self, "permissions", frozenset(self.permissions))
        for name in ("repository_key", "branch", "user_id", "agent_id"):
            value = getattr(self, name)
            if value is not None:
                normalized = value.strip()
                if not normalized:
                    raise ValueError(f"{name} must be non-empty when supplied")
                object.__setattr__(self, name, normalized)

    def to_dict(self) -> dict[str, Any]:
        return {
            "space_id": str(self.space_id),
            "project_key": self.project_key,
            "repository_key": self.repository_key,
            "branch": self.branch,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "permissions": sorted(self.permissions),
            "sensitivity_clearance": self.sensitivity_clearance.value,
        }


@dataclass(frozen=True, slots=True)
class RoutingRequest:
    query: str
    scope: RoutingScope
    request_id: UUID = field(default_factory=uuid4)
    task_kind: TaskKind = TaskKind.GENERAL
    plan_phase: PlanPhase = PlanPhase.UNKNOWN
    needs: frozenset[EvidenceNeed] = field(default_factory=frozenset)
    temporal_intent: TemporalIntent = TemporalIntent.NONE
    exactness: ExactnessNeed = ExactnessNeed.SEMANTIC
    risk: RiskLevel = RiskLevel.LOW
    uncertainty: float = 0.5
    token_budget: int = 2400
    latency_budget_ms: int = 1000
    max_experts: int = 5
    minimum_authority: float = 0.0

    def __post_init__(self) -> None:
        query = self.query.strip()
        if not query:
            raise ValueError("query must not be empty")
        if self.token_budget <= 0:
            raise ValueError("token_budget must be greater than zero")
        if self.latency_budget_ms <= 0:
            raise ValueError("latency_budget_ms must be greater than zero")
        if self.max_experts <= 0:
            raise ValueError("max_experts must be greater than zero")
        _validate_probability("uncertainty", self.uncertainty)
        _validate_probability("minimum_authority", self.minimum_authority)
        object.__setattr__(self, "query", query)
        object.__setattr__(self, "needs", frozenset(self.needs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": str(self.request_id),
            "query": self.query,
            "scope": self.scope.to_dict(),
            "task_kind": self.task_kind.value,
            "plan_phase": self.plan_phase.value,
            "needs": sorted(need.value for need in self.needs),
            "temporal_intent": self.temporal_intent.value,
            "exactness": self.exactness.value,
            "risk": self.risk.value,
            "uncertainty": self.uncertainty,
            "token_budget": self.token_budget,
            "latency_budget_ms": self.latency_budget_ms,
            "max_experts": self.max_experts,
            "minimum_authority": self.minimum_authority,
        }


@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    memory_id: UUID
    space_id: UUID
    expert: ExpertKey
    project_key: str
    repository_key: str | None = None
    branch: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    required_permissions: frozenset[str] = field(default_factory=frozenset)
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    authority: float = 0.5
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    quarantined: bool = False

    def __post_init__(self) -> None:
        if not self.project_key.strip():
            raise ValueError("project_key must not be empty")
        _validate_probability("authority", self.authority)
        for name in ("valid_from", "valid_to"):
            value = getattr(self, name)
            if value is not None and value.utcoffset() is None:
                raise ValueError(f"{name} must be timezone-aware")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to < self.valid_from
        ):
            raise ValueError("valid_to must be greater than or equal to valid_from")
        object.__setattr__(self, "project_key", self.project_key.strip())
        object.__setattr__(self, "required_permissions", frozenset(self.required_permissions))


@dataclass(frozen=True, slots=True)
class ExpertAllocation:
    expert: ExpertKey
    token_budget: int
    score: float
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.token_budget <= 0:
            raise ValueError("expert token_budget must be greater than zero")
        if not isfinite(self.score):
            raise ValueError("expert score must be finite")
        object.__setattr__(self, "reasons", tuple(self.reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "expert": self.expert.value,
            "token_budget": self.token_budget,
            "score": self.score,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    decision_id: UUID
    request_id: UUID
    eligible_experts: tuple[ExpertKey, ...]
    allocations: tuple[ExpertAllocation, ...]
    escalation_experts: tuple[ExpertKey, ...]
    token_budget: int
    confidence: float
    policy_version: str

    def __post_init__(self) -> None:
        eligible = tuple(self.eligible_experts)
        allocations = tuple(self.allocations)
        escalation = tuple(self.escalation_experts)
        selected = tuple(allocation.expert for allocation in allocations)
        if len(set(eligible)) != len(eligible):
            raise ValueError("eligible experts must be unique")
        if len(set(selected)) != len(selected):
            raise ValueError("selected experts must be unique")
        if not set(selected) <= set(eligible):
            raise ValueError("selected experts must be eligible")
        if set(escalation) & set(selected):
            raise ValueError("escalation experts must not already be selected")
        if not set(escalation) <= set(eligible):
            raise ValueError("escalation experts must be eligible")
        if self.token_budget <= 0:
            raise ValueError("token budget must be greater than zero")
        if sum(allocation.token_budget for allocation in allocations) > self.token_budget:
            raise ValueError("allocated tokens exceed the token budget")
        _validate_probability("confidence", self.confidence)
        if not self.policy_version.strip():
            raise ValueError("policy_version must not be empty")
        object.__setattr__(self, "eligible_experts", eligible)
        object.__setattr__(self, "allocations", allocations)
        object.__setattr__(self, "escalation_experts", escalation)
        object.__setattr__(self, "policy_version", self.policy_version.strip())

    @property
    def selected_experts(self) -> tuple[ExpertKey, ...]:
        return tuple(allocation.expert for allocation in self.allocations)

    @property
    def expert_budgets(self) -> dict[ExpertKey, int]:
        return {allocation.expert: allocation.token_budget for allocation in self.allocations}

    @property
    def total_allocated_tokens(self) -> int:
        return sum(allocation.token_budget for allocation in self.allocations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": str(self.decision_id),
            "request_id": str(self.request_id),
            "eligible_experts": [expert.value for expert in self.eligible_experts],
            "selected_experts": [expert.value for expert in self.selected_experts],
            "expert_budgets": {
                expert.value: budget for expert, budget in self.expert_budgets.items()
            },
            "allocations": [allocation.to_dict() for allocation in self.allocations],
            "escalation_experts": [expert.value for expert in self.escalation_experts],
            "token_budget": self.token_budget,
            "confidence": self.confidence,
            "policy_version": self.policy_version,
        }


def _validate_probability(name: str, value: float) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")
