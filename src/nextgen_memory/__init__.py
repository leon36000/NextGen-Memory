"""Public API for the NextGen Memory kernel."""

from .domain import (
    EvidenceNeed,
    ExactnessNeed,
    ExpertAllocation,
    ExpertKey,
    MemoryCandidate,
    PlanPhase,
    RiskLevel,
    RoutingDecision,
    RoutingRequest,
    RoutingScope,
    Sensitivity,
    TaskKind,
    TemporalIntent,
)
from .eligibility import EligibilityResult, evaluate_candidate_eligibility
from .router import DeterministicMemoryRouter
from .telemetry import (
    InMemoryRoutingDecisionSink,
    RoutingDecisionSink,
    RoutingTelemetryRecord,
)

__all__ = [
    "DeterministicMemoryRouter",
    "EligibilityResult",
    "EvidenceNeed",
    "ExactnessNeed",
    "ExpertAllocation",
    "ExpertKey",
    "InMemoryRoutingDecisionSink",
    "MemoryCandidate",
    "PlanPhase",
    "RiskLevel",
    "RoutingDecision",
    "RoutingDecisionSink",
    "RoutingRequest",
    "RoutingScope",
    "RoutingTelemetryRecord",
    "Sensitivity",
    "TaskKind",
    "TemporalIntent",
    "evaluate_candidate_eligibility",
]
