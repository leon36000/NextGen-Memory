"""Fail-closed eligibility checks that run before memory relevance scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .domain import MemoryCandidate, RoutingRequest


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    eligible: bool
    reasons: tuple[str, ...] = ()


def evaluate_candidate_eligibility(
    request: RoutingRequest,
    candidate: MemoryCandidate,
    *,
    at: datetime | None = None,
) -> EligibilityResult:
    """Return whether a memory is admissible before any semantic ranking occurs."""

    if at is not None and at.utcoffset() is None:
        raise ValueError("evaluation time must be timezone-aware")
    now = at or datetime.now(UTC)
    reasons: list[str] = []
    scope = request.scope

    if candidate.space_id != scope.space_id:
        reasons.append("space_mismatch")
    if candidate.project_key != scope.project_key:
        reasons.append("project_mismatch")
    if candidate.repository_key is not None and candidate.repository_key != scope.repository_key:
        reasons.append("repository_mismatch")
    if candidate.branch is not None and candidate.branch != scope.branch:
        reasons.append("branch_mismatch")
    if candidate.user_id is not None and candidate.user_id != scope.user_id:
        reasons.append("user_mismatch")
    if candidate.agent_id is not None and candidate.agent_id != scope.agent_id:
        reasons.append("agent_mismatch")
    if not candidate.required_permissions <= scope.permissions:
        reasons.append("missing_permission")
    if candidate.sensitivity.rank > scope.sensitivity_clearance.rank:
        reasons.append("sensitivity_exceeded")
    if candidate.authority < request.minimum_authority:
        reasons.append("authority_too_low")
    if candidate.valid_from is not None and now < candidate.valid_from:
        reasons.append("not_yet_valid")
    if candidate.valid_to is not None and now > candidate.valid_to:
        reasons.append("expired")
    if candidate.quarantined:
        reasons.append("quarantined")

    return EligibilityResult(eligible=not reasons, reasons=tuple(reasons))
