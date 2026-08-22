from __future__ import annotations

import re
from dataclasses import replace
from uuid import UUID

import pytest

import nextgen_memory.router as router_module
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

REQUEST_ID = UUID("22222222-2222-2222-2222-222222222222")
SPACE_ID = UUID("11111111-1111-1111-1111-111111111111")


def scope(**overrides: object) -> RoutingScope:
    values: dict[str, object] = {
        "space_id": SPACE_ID,
        "project_key": "nextgen-memory",
        "repository_key": "leon36000/NextGen-Memory",
        "branch": "feat/memory-moe-kernel-v0",
        "user_id": "private-user-17",
        "agent_id": "private-agent-23",
        "permissions": frozenset({"memory:read", "repository:read"}),
    }
    values.update(overrides)
    return RoutingScope(**values)  # type: ignore[arg-type]


def request(**overrides: object) -> RoutingRequest:
    values: dict[str, object] = {
        "request_id": REQUEST_ID,
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
        "minimum_authority": 0.1,
    }
    values.update(overrides)
    return RoutingRequest(**values)  # type: ignore[arg-type]


def decision_id(value: RoutingRequest, router: DeterministicMemoryRouter | None = None):
    return (router or DeterministicMemoryRouter()).route(value).decision_id


def test_identical_normalized_request_keeps_one_deterministic_identity() -> None:
    first = request()
    second = request(
        query="  Diagnose why verification is failing  ",
        scope=scope(
            permissions=frozenset({"repository:read", "memory:read"}),
        ),
        needs=frozenset({EvidenceNeed.FAILURE, EvidenceNeed.CAUSAL}),
    )

    assert decision_id(first) == decision_id(second)


@pytest.mark.parametrize(
    "changed",
    [
        request(query="Diagnose a different verification failure"),
        request(scope=scope(project_key="nextgen-memory-other")),
        request(scope=scope(repository_key=None, branch=None)),
        request(scope=scope(permissions=frozenset({"memory:read"}))),
        request(task_kind=TaskKind.RESEARCH),
        request(plan_phase=PlanPhase.PLAN),
        request(needs=frozenset({EvidenceNeed.RESEARCH})),
        request(temporal_intent=TemporalIntent.HISTORICAL),
        request(exactness=ExactnessNeed.EXACT),
        request(risk=RiskLevel.HIGH),
        request(uncertainty=0.9),
        request(token_budget=2600),
        request(latency_budget_ms=900),
        request(max_experts=4),
        request(minimum_authority=0.3),
    ],
)
def test_same_request_id_cannot_alias_a_different_routing_policy(
    changed: RoutingRequest,
) -> None:
    assert changed.request_id == REQUEST_ID
    assert decision_id(changed) != decision_id(request())


class ChangedConfidenceRouter(DeterministicMemoryRouter):
    @staticmethod
    def _confidence(
        request: RoutingRequest,
        selected: tuple[ExpertKey, ...],
        scores: dict[ExpertKey, float],
    ) -> float:
        del request, selected, scores
        return 0.123


class ChangedEligibilityRouter(DeterministicMemoryRouter):
    def _eligible_experts(self, request: RoutingRequest) -> tuple[ExpertKey, ...]:
        return tuple(
            expert
            for expert in super()._eligible_experts(request)
            if expert is not ExpertKey.RESEARCH
        )


class ChangedAllocationsRouter(DeterministicMemoryRouter):
    def _allocate_budgets(
        self,
        total_budget: int,
        selected: tuple[ExpertKey, ...],
        scores: dict[ExpertKey, float],
    ) -> dict[ExpertKey, int]:
        allocations = super()._allocate_budgets(total_budget, selected, scores)
        if len(selected) >= 2:
            first, last = selected[0], selected[-1]
            allocations[first] -= 1
            allocations[last] += 1
        return allocations


class ChangedEscalationRouter(DeterministicMemoryRouter):
    def _escalation_experts(
        self,
        request: RoutingRequest,
        eligible: tuple[ExpertKey, ...],
        selected: tuple[ExpertKey, ...],
        scores: dict[ExpertKey, float],
    ) -> tuple[ExpertKey, ...]:
        return tuple(
            reversed(
                super()._escalation_experts(
                    request,
                    eligible,
                    selected,
                    scores,
                )
            )
        )


@pytest.mark.parametrize(
    "changed_router",
    [
        ChangedConfidenceRouter(),
        ChangedEligibilityRouter(),
        ChangedAllocationsRouter(),
        ChangedEscalationRouter(),
    ],
)
def test_decision_identity_binds_the_deterministic_route_outcome(
    changed_router: DeterministicMemoryRouter,
) -> None:
    routing_request = request()
    baseline = DeterministicMemoryRouter().route(routing_request)
    changed = changed_router.route(routing_request)

    assert changed.to_dict() != baseline.to_dict()
    assert changed.decision_id != baseline.decision_id


def test_uuid5_name_contains_only_version_and_canonical_sha256(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str] = []
    sentinel_query = "raw-query-never-in-identity-name"
    sentinel_user = "raw-user-never-in-identity-name"
    sentinel_agent = "raw-agent-never-in-identity-name"

    def capture_uuid5(namespace: object, name: str) -> UUID:
        del namespace
        captured.append(name)
        return UUID("33333333-3333-5333-8333-333333333333")

    monkeypatch.setattr(router_module, "uuid5", capture_uuid5)
    result = DeterministicMemoryRouter().route(
        request(
            query=sentinel_query,
            scope=scope(user_id=sentinel_user, agent_id=sentinel_agent),
        )
    )

    assert result.policy_version == "deterministic-v1"
    assert result.decision_id == UUID("33333333-3333-5333-8333-333333333333")
    assert len(captured) == 1
    assert re.fullmatch(
        r"nextgen-memory:routing-decision:deterministic-v1:[0-9a-f]{64}",
        captured[0],
    )
    assert sentinel_query not in captured[0]
    assert sentinel_user not in captured[0]
    assert sentinel_agent not in captured[0]


def test_request_id_remains_bound_inside_the_complete_identity() -> None:
    base = request()
    changed = replace(
        base,
        request_id=UUID("44444444-4444-4444-8444-444444444444"),
    )

    assert decision_id(base) != decision_id(changed)
