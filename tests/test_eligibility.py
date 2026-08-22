from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from nextgen_memory.domain import (
    ExpertKey,
    MemoryCandidate,
    RoutingRequest,
    RoutingScope,
    Sensitivity,
    TaskKind,
)
from nextgen_memory.eligibility import evaluate_candidate_eligibility


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


def make_request() -> RoutingRequest:
    return RoutingRequest(
        query="Recall the active architecture",
        scope=make_scope(),
        task_kind=TaskKind.PROJECT_CONTINUITY,
        minimum_authority=0.5,
    )


def make_candidate(request: RoutingRequest) -> MemoryCandidate:
    return MemoryCandidate(
        memory_id=uuid4(),
        space_id=request.scope.space_id,
        expert=ExpertKey.DECISION,
        project_key=request.scope.project_key,
        repository_key=request.scope.repository_key,
        branch=request.scope.branch,
        user_id=request.scope.user_id,
        agent_id=request.scope.agent_id,
        required_permissions=frozenset({"memory:read"}),
        sensitivity=Sensitivity.INTERNAL,
        authority=0.9,
    )


def test_candidate_with_matching_scope_is_eligible() -> None:
    request = make_request()
    result = evaluate_candidate_eligibility(request, make_candidate(request))

    assert result.eligible is True
    assert result.reasons == ()


def test_scope_repository_branch_and_principal_mismatches_fail_closed() -> None:
    request = make_request()
    candidate = make_candidate(request)

    cases = (
        (replace(candidate, space_id=uuid4()), "space_mismatch"),
        (replace(candidate, project_key="other"), "project_mismatch"),
        (replace(candidate, repository_key="other/repo"), "repository_mismatch"),
        (replace(candidate, branch="main"), "branch_mismatch"),
        (replace(candidate, user_id="other-user"), "user_mismatch"),
        (replace(candidate, agent_id="other-agent"), "agent_mismatch"),
    )

    for changed, reason in cases:
        result = evaluate_candidate_eligibility(request, changed)
        assert result.eligible is False
        assert reason in result.reasons


def test_permissions_sensitivity_authority_validity_and_quarantine_are_enforced() -> None:
    request = make_request()
    candidate = make_candidate(request)
    now = datetime.now(UTC)

    cases = (
        (replace(candidate, required_permissions=frozenset({"admin"})), "missing_permission"),
        (replace(candidate, sensitivity=Sensitivity.SECRET), "sensitivity_exceeded"),
        (replace(candidate, authority=0.2), "authority_too_low"),
        (replace(candidate, valid_from=now + timedelta(hours=1)), "not_yet_valid"),
        (replace(candidate, valid_to=now - timedelta(hours=1)), "expired"),
        (replace(candidate, quarantined=True), "quarantined"),
    )

    for changed, reason in cases:
        result = evaluate_candidate_eligibility(request, changed, at=now)
        assert result.eligible is False
        assert reason in result.reasons


def test_global_candidate_can_omit_repository_branch_and_principals() -> None:
    request = make_request()
    candidate = replace(
        make_candidate(request),
        repository_key=None,
        branch=None,
        user_id=None,
        agent_id=None,
    )

    assert evaluate_candidate_eligibility(request, candidate).eligible is True


def test_eligibility_rejects_naive_evaluation_time() -> None:
    request = make_request()

    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_candidate_eligibility(request, make_candidate(request), at=datetime.now())
