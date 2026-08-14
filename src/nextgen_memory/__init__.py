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
from .mongodb_retrieval import (
    MongoResearchIndexConfig,
    MongoResearchRetriever,
    build_research_hybrid_pipeline,
)
from .retrieval import ResearchRetrievalHit, ResearchRetrievalQuery
from .retrieval_telemetry import (
    RETRIEVAL_EVENT_INSERT_SQL,
    RetrievalEvent,
    RetrievalEventWriter,
    build_retrieval_events,
)
from .router import DeterministicMemoryRouter
from .telemetry import (
    InMemoryRoutingDecisionSink,
    RoutingDecisionSink,
    RoutingTelemetryRecord,
)

__all__ = [
    "RETRIEVAL_EVENT_INSERT_SQL",
    "DeterministicMemoryRouter",
    "EligibilityResult",
    "EvidenceNeed",
    "ExactnessNeed",
    "ExpertAllocation",
    "ExpertKey",
    "InMemoryRoutingDecisionSink",
    "MemoryCandidate",
    "MongoResearchIndexConfig",
    "MongoResearchRetriever",
    "PlanPhase",
    "ResearchRetrievalHit",
    "ResearchRetrievalQuery",
    "RetrievalEvent",
    "RetrievalEventWriter",
    "RiskLevel",
    "RoutingDecision",
    "RoutingDecisionSink",
    "RoutingRequest",
    "RoutingScope",
    "RoutingTelemetryRecord",
    "Sensitivity",
    "TaskKind",
    "TemporalIntent",
    "build_research_hybrid_pipeline",
    "build_retrieval_events",
    "evaluate_candidate_eligibility",
]
