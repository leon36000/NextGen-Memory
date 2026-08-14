from uuid import UUID, uuid4

from nextgen_memory.domain import (
    EvidenceNeed,
    ExactnessNeed,
    ExpertKey,
    PlanPhase,
    RiskLevel,
    RoutingRequest,
    RoutingScope,
    TaskKind,
    TemporalIntent,
)
from nextgen_memory.router import DeterministicMemoryRouter
from nextgen_memory.telemetry import InMemoryRoutingDecisionSink


def scope(*, repository: bool = True) -> RoutingScope:
    return RoutingScope(
        space_id=UUID("11111111-1111-1111-1111-111111111111"),
        project_key="nextgen-memory",
        repository_key="leon36000/NextGen-Memory" if repository else None,
        branch="feat/memory-moe-kernel-v0" if repository else None,
        permissions=frozenset({"memory:read", "repository:read"}),
    )


def request(**overrides: object) -> RoutingRequest:
    values: dict[str, object] = {
        "request_id": UUID("22222222-2222-2222-2222-222222222222"),
        "query": "Diagnose why verification is failing",
        "scope": scope(),
        "task_kind": TaskKind.SOFTWARE_ENGINEERING,
        "plan_phase": PlanPhase.DIAGNOSE,
        "needs": frozenset({EvidenceNeed.CAUSAL, EvidenceNeed.FAILURE}),
        "temporal_intent": TemporalIntent.CURRENT,
        "exactness": ExactnessNeed.SEMANTIC,
        "risk": RiskLevel.MEDIUM,
        "uncertainty": 0.4,
        "token_budget": 2400,
        "latency_budget_ms": 800,
        "max_experts": 5,
    }
    values.update(overrides)
    return RoutingRequest(**values)


def selected(decision: object) -> set[ExpertKey]:
    return set(decision.selected_experts)


def test_swe_diagnosis_routes_to_execution_repository_failure_and_causal_memory() -> None:
    decision = DeterministicMemoryRouter().route(request())

    assert {
        ExpertKey.WORKING,
        ExpertKey.EXECUTION,
        ExpertKey.REPOSITORY,
        ExpertKey.FAILURE,
        ExpertKey.CAUSAL,
    } <= selected(decision)
    assert decision.total_allocated_tokens <= decision.token_budget
    assert set(decision.selected_experts) <= set(decision.eligible_experts)


def test_risky_edit_prioritizes_failure_and_procedural_memory() -> None:
    decision = DeterministicMemoryRouter().route(
        request(
            query="Modify the migration safely",
            plan_phase=PlanPhase.EDIT,
            risk=RiskLevel.HIGH,
            needs=frozenset({EvidenceNeed.PROCEDURE, EvidenceNeed.FAILURE}),
        )
    )

    assert ExpertKey.FAILURE in selected(decision)
    assert ExpertKey.PROCEDURAL in selected(decision)
    assert ExpertKey.EXECUTION in selected(decision)


def test_research_task_uses_research_and_semantic_without_repository_scope() -> None:
    decision = DeterministicMemoryRouter().route(
        request(
            query="Compare recent agent-memory architectures",
            scope=scope(repository=False),
            task_kind=TaskKind.RESEARCH,
            plan_phase=PlanPhase.SYNTHESIZE,
            needs=frozenset({EvidenceNeed.RESEARCH, EvidenceNeed.CAUSAL}),
        )
    )

    assert ExpertKey.RESEARCH in selected(decision)
    assert ExpertKey.SEMANTIC in selected(decision)
    assert ExpertKey.REPOSITORY not in decision.eligible_experts
    assert ExpertKey.REPOSITORY not in selected(decision)


def test_project_continuity_routes_to_decision_temporal_and_semantic() -> None:
    decision = DeterministicMemoryRouter().route(
        request(
            query="What is the current state of NextGen Memory?",
            scope=scope(repository=False),
            task_kind=TaskKind.PROJECT_CONTINUITY,
            plan_phase=PlanPhase.UNDERSTAND,
            needs=frozenset({EvidenceNeed.CURRENT_STATE, EvidenceNeed.DECISION}),
        )
    )

    assert {
        ExpertKey.WORKING,
        ExpertKey.DECISION,
        ExpertKey.TEMPORAL,
        ExpertKey.SEMANTIC,
    } <= selected(decision)


def test_exact_historical_recall_activates_episodic_and_temporal_memory() -> None:
    decision = DeterministicMemoryRouter().route(
        request(
            query="What exactly happened during the failed migration?",
            needs=frozenset({EvidenceNeed.HISTORICAL, EvidenceNeed.EXACT_EVIDENCE}),
            temporal_intent=TemporalIntent.HISTORICAL,
            exactness=ExactnessNeed.EXACT,
        )
    )

    assert ExpertKey.EPISODIC in selected(decision)
    assert ExpertKey.TEMPORAL in selected(decision)


def test_low_budget_keeps_route_sparse_and_within_budget() -> None:
    decision = DeterministicMemoryRouter().route(
        request(token_budget=600, max_experts=6, needs=frozenset({EvidenceNeed.CAUSAL}))
    )

    assert len(decision.allocations) <= 2
    assert decision.total_allocated_tokens <= 600
    assert all(allocation.token_budget > 0 for allocation in decision.allocations)


def test_feedback_is_excluded_from_normal_context_but_available_for_memory_maintenance() -> None:
    normal = DeterministicMemoryRouter().route(request())
    maintenance = DeterministicMemoryRouter().route(
        request(
            query="Evaluate router performance",
            scope=scope(repository=False),
            task_kind=TaskKind.MEMORY_MAINTENANCE,
            plan_phase=PlanPhase.VERIFY,
            needs=frozenset({EvidenceNeed.FEEDBACK}),
        )
    )

    assert ExpertKey.FEEDBACK not in selected(normal)
    assert ExpertKey.FEEDBACK in selected(maintenance)


def test_router_is_deterministic_and_records_decision_once() -> None:
    router = DeterministicMemoryRouter()
    sink = InMemoryRoutingDecisionSink()
    routing_request = request(request_id=uuid4())

    first = router.route(routing_request, sink=sink)
    second = router.route(routing_request)

    assert first == second
    assert len(sink.records) == 1
    record = sink.records[0]
    assert record.request_id == routing_request.request_id
    assert record.decision == first
    assert len(record.query_hash) == 64
    payload = record.to_dict()
    assert "query" not in payload["query_features"]
    assert payload["query_hash"] == record.query_hash
    assert not (set(first.escalation_experts) & set(first.selected_experts))
