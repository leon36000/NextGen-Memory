from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from nextgen_memory.domain import (
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


def make_scope() -> RoutingScope:
    return RoutingScope(
        space_id=uuid4(),
        project_key="nextgen-memory",
        repository_key="leon36000/NextGen-Memory",
        branch="feat/memory-moe-kernel-v0",
        user_id="leon36000",
        agent_id="gpt-5.6-pro",
        permissions=frozenset({"memory:read", "repository:read"}),
        sensitivity_clearance=Sensitivity.INTERNAL,
    )


def make_request(**overrides: object) -> RoutingRequest:
    values: dict[str, object] = {
        "request_id": uuid4(),
        "query": "Diagnose the failing verification step",
        "scope": make_scope(),
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
        "minimum_authority": 0.5,
    }
    values.update(overrides)
    return RoutingRequest(**values)


def test_request_rejects_empty_query() -> None:
    with pytest.raises(ValueError, match="query"):
        make_request(query="   ")


def test_request_rejects_invalid_budgets_and_probability_ranges() -> None:
    with pytest.raises(ValueError, match="token_budget"):
        make_request(token_budget=0)
    with pytest.raises(ValueError, match="uncertainty"):
        make_request(uncertainty=1.1)
    with pytest.raises(ValueError, match="minimum_authority"):
        make_request(minimum_authority=-0.1)


def test_decision_rejects_selected_expert_outside_eligibility_mask() -> None:
    request = make_request()
    allocation = ExpertAllocation(
        expert=ExpertKey.RESEARCH,
        token_budget=300,
        score=1.0,
        reasons=("test",),
    )

    with pytest.raises(ValueError, match="eligible"):
        RoutingDecision(
            decision_id=uuid4(),
            request_id=request.request_id,
            eligible_experts=(ExpertKey.WORKING,),
            allocations=(allocation,),
            escalation_experts=(),
            token_budget=request.token_budget,
            confidence=0.8,
            policy_version="test",
        )


def test_decision_rejects_allocations_over_total_budget() -> None:
    request = make_request(token_budget=500)
    allocations = (
        ExpertAllocation(ExpertKey.WORKING, 300, 1.0, ("always",)),
        ExpertAllocation(ExpertKey.SEMANTIC, 300, 0.8, ("task",)),
    )

    with pytest.raises(ValueError, match="token budget"):
        RoutingDecision(
            decision_id=uuid4(),
            request_id=request.request_id,
            eligible_experts=(ExpertKey.WORKING, ExpertKey.SEMANTIC),
            allocations=allocations,
            escalation_experts=(),
            token_budget=request.token_budget,
            confidence=0.8,
            policy_version="test",
        )


def test_decision_serialization_is_json_ready() -> None:
    request_id = UUID("11111111-1111-1111-1111-111111111111")
    decision = RoutingDecision(
        decision_id=UUID("22222222-2222-2222-2222-222222222222"),
        request_id=request_id,
        eligible_experts=(ExpertKey.WORKING, ExpertKey.SEMANTIC, ExpertKey.EPISODIC),
        allocations=(
            ExpertAllocation(ExpertKey.WORKING, 400, 2.0, ("active task",)),
            ExpertAllocation(ExpertKey.SEMANTIC, 600, 1.5, ("stable knowledge",)),
        ),
        escalation_experts=(ExpertKey.EPISODIC,),
        token_budget=1200,
        confidence=0.9,
        policy_version="deterministic-v0",
    )

    payload = decision.to_dict()

    assert payload["decision_id"] == "22222222-2222-2222-2222-222222222222"
    assert payload["request_id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["selected_experts"] == ["working", "semantic"]
    assert payload["expert_budgets"] == {"working": 400, "semantic": 600}
    assert payload["escalation_experts"] == ["episodic"]


def test_candidate_validates_temporal_and_authority_fields() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="authority"):
        MemoryCandidate(
            memory_id=uuid4(),
            space_id=uuid4(),
            expert=ExpertKey.SEMANTIC,
            project_key="nextgen-memory",
            authority=1.1,
        )
    with pytest.raises(ValueError, match="valid_to"):
        MemoryCandidate(
            memory_id=uuid4(),
            space_id=uuid4(),
            expert=ExpertKey.SEMANTIC,
            project_key="nextgen-memory",
            valid_from=now,
            valid_to=now.replace(year=now.year - 1),
        )


def test_package_exports_core_router_api() -> None:
    from nextgen_memory import (
        DeterministicMemoryRouter,
        RoutingTelemetryRecord,
        evaluate_candidate_eligibility,
    )

    assert DeterministicMemoryRouter.__name__ == "DeterministicMemoryRouter"
    assert RoutingTelemetryRecord.__name__ == "RoutingTelemetryRecord"
    assert callable(evaluate_candidate_eligibility)


def test_candidate_rejects_naive_validity_timestamps() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        MemoryCandidate(
            memory_id=uuid4(),
            space_id=uuid4(),
            expert=ExpertKey.TEMPORAL,
            project_key="nextgen-memory",
            valid_from=datetime.now(),
        )
