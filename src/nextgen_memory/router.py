"""Deterministic sparse Memory-MoE router used before learned routing exists."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from .domain import (
    EvidenceNeed,
    ExactnessNeed,
    ExpertAllocation,
    ExpertKey,
    PlanPhase,
    RiskLevel,
    RoutingDecision,
    RoutingRequest,
    TaskKind,
    TemporalIntent,
)
from .telemetry import RoutingDecisionSink, RoutingTelemetryRecord

POLICY_VERSION = "deterministic-v1"
MIN_EXPERT_TOKENS = 300


@dataclass(frozen=True, slots=True)
class ExpertProfile:
    expert: ExpertKey
    default_budget: int
    hard_max_budget: int
    requires_repository: bool = False
    requires_repository_permission: bool = False
    maintenance_only: bool = False


EXPERT_PROFILES: tuple[ExpertProfile, ...] = (
    ExpertProfile(ExpertKey.WORKING, 600, 1200),
    ExpertProfile(ExpertKey.EXECUTION, 900, 1800),
    ExpertProfile(ExpertKey.EPISODIC, 1200, 3200),
    ExpertProfile(ExpertKey.SEMANTIC, 800, 2000),
    ExpertProfile(ExpertKey.TEMPORAL, 800, 1800),
    ExpertProfile(ExpertKey.CAUSAL, 900, 2200),
    ExpertProfile(ExpertKey.PROCEDURAL, 1000, 2400),
    ExpertProfile(ExpertKey.FAILURE, 900, 2200),
    ExpertProfile(ExpertKey.DECISION, 700, 1600),
    ExpertProfile(
        ExpertKey.REPOSITORY,
        1200,
        3000,
        requires_repository=True,
        requires_repository_permission=True,
    ),
    ExpertProfile(ExpertKey.RESEARCH, 1200, 3200),
    ExpertProfile(ExpertKey.FEEDBACK, 400, 1000, maintenance_only=True),
)
PROFILE_BY_EXPERT = {profile.expert: profile for profile in EXPERT_PROFILES}


TASK_SCORES: dict[TaskKind, dict[ExpertKey, float]] = {
    TaskKind.SOFTWARE_ENGINEERING: {
        ExpertKey.WORKING: 100,
        ExpertKey.REPOSITORY: 80,
        ExpertKey.EXECUTION: 78,
        ExpertKey.DECISION: 50,
        ExpertKey.SEMANTIC: 45,
        ExpertKey.PROCEDURAL: 35,
        ExpertKey.FAILURE: 30,
    },
    TaskKind.RESEARCH: {
        ExpertKey.WORKING: 100,
        ExpertKey.RESEARCH: 90,
        ExpertKey.SEMANTIC: 75,
        ExpertKey.CAUSAL: 40,
        ExpertKey.DECISION: 30,
    },
    TaskKind.PROJECT_CONTINUITY: {
        ExpertKey.WORKING: 100,
        ExpertKey.DECISION: 90,
        ExpertKey.TEMPORAL: 85,
        ExpertKey.SEMANTIC: 75,
        ExpertKey.EPISODIC: 20,
    },
    TaskKind.MEMORY_MAINTENANCE: {
        ExpertKey.WORKING: 100,
        ExpertKey.FEEDBACK: 95,
        ExpertKey.TEMPORAL: 60,
        ExpertKey.SEMANTIC: 55,
        ExpertKey.CAUSAL: 40,
    },
    TaskKind.TOOL_EXECUTION: {
        ExpertKey.WORKING: 100,
        ExpertKey.EXECUTION: 90,
        ExpertKey.FAILURE: 65,
        ExpertKey.PROCEDURAL: 55,
    },
    TaskKind.GENERAL: {
        ExpertKey.WORKING: 100,
        ExpertKey.SEMANTIC: 80,
        ExpertKey.DECISION: 50,
    },
}

PHASE_SCORES: dict[PlanPhase, dict[ExpertKey, float]] = {
    PlanPhase.UNKNOWN: {},
    PlanPhase.UNDERSTAND: {
        ExpertKey.SEMANTIC: 50,
        ExpertKey.DECISION: 45,
        ExpertKey.TEMPORAL: 20,
    },
    PlanPhase.LOCATE: {
        ExpertKey.REPOSITORY: 75,
        ExpertKey.EXECUTION: 35,
        ExpertKey.SEMANTIC: 30,
    },
    PlanPhase.PLAN: {
        ExpertKey.DECISION: 60,
        ExpertKey.PROCEDURAL: 55,
        ExpertKey.FAILURE: 30,
        ExpertKey.REPOSITORY: 20,
    },
    PlanPhase.EDIT: {
        ExpertKey.EXECUTION: 70,
        ExpertKey.REPOSITORY: 60,
        ExpertKey.FAILURE: 55,
        ExpertKey.PROCEDURAL: 50,
        ExpertKey.DECISION: 25,
    },
    PlanPhase.VERIFY: {
        ExpertKey.EXECUTION: 75,
        ExpertKey.FAILURE: 60,
        ExpertKey.DECISION: 40,
        ExpertKey.REPOSITORY: 30,
    },
    PlanPhase.DIAGNOSE: {
        ExpertKey.CAUSAL: 70,
        ExpertKey.FAILURE: 65,
        ExpertKey.EXECUTION: 60,
        ExpertKey.REPOSITORY: 50,
    },
    PlanPhase.SYNTHESIZE: {
        ExpertKey.SEMANTIC: 60,
        ExpertKey.RESEARCH: 50,
        ExpertKey.CAUSAL: 25,
    },
    PlanPhase.ANSWER: {
        ExpertKey.SEMANTIC: 40,
        ExpertKey.DECISION: 20,
    },
}

NEED_SCORES: dict[EvidenceNeed, dict[ExpertKey, float]] = {
    EvidenceNeed.CURRENT_STATE: {ExpertKey.TEMPORAL: 100, ExpertKey.DECISION: 60},
    EvidenceNeed.HISTORICAL: {ExpertKey.EPISODIC: 100, ExpertKey.TEMPORAL: 80},
    EvidenceNeed.EXACT_EVIDENCE: {ExpertKey.EPISODIC: 120},
    EvidenceNeed.CAUSAL: {ExpertKey.CAUSAL: 100},
    EvidenceNeed.PROCEDURE: {ExpertKey.PROCEDURAL: 100},
    EvidenceNeed.FAILURE: {ExpertKey.FAILURE: 110},
    EvidenceNeed.DECISION: {ExpertKey.DECISION: 100},
    EvidenceNeed.REPOSITORY: {ExpertKey.REPOSITORY: 100},
    EvidenceNeed.RESEARCH: {ExpertKey.RESEARCH: 100},
    EvidenceNeed.EXECUTION: {ExpertKey.EXECUTION: 100},
    EvidenceNeed.FEEDBACK: {ExpertKey.FEEDBACK: 100},
}

ESCALATION_ORDER: dict[TaskKind, tuple[ExpertKey, ...]] = {
    TaskKind.SOFTWARE_ENGINEERING: (
        ExpertKey.EPISODIC,
        ExpertKey.SEMANTIC,
        ExpertKey.DECISION,
        ExpertKey.TEMPORAL,
        ExpertKey.PROCEDURAL,
        ExpertKey.RESEARCH,
    ),
    TaskKind.RESEARCH: (
        ExpertKey.EPISODIC,
        ExpertKey.TEMPORAL,
        ExpertKey.DECISION,
        ExpertKey.RESEARCH,
    ),
    TaskKind.PROJECT_CONTINUITY: (
        ExpertKey.EPISODIC,
        ExpertKey.CAUSAL,
        ExpertKey.RESEARCH,
    ),
    TaskKind.MEMORY_MAINTENANCE: (
        ExpertKey.EPISODIC,
        ExpertKey.CAUSAL,
        ExpertKey.RESEARCH,
    ),
    TaskKind.TOOL_EXECUTION: (
        ExpertKey.EPISODIC,
        ExpertKey.CAUSAL,
        ExpertKey.DECISION,
    ),
    TaskKind.GENERAL: (
        ExpertKey.EPISODIC,
        ExpertKey.TEMPORAL,
        ExpertKey.CAUSAL,
        ExpertKey.RESEARCH,
    ),
}


class DeterministicMemoryRouter:
    """Pure, reproducible routing policy that produces telemetry-ready decisions."""

    def route(
        self,
        request: RoutingRequest,
        *,
        sink: RoutingDecisionSink | None = None,
    ) -> RoutingDecision:
        eligible = self._eligible_experts(request)
        scores, reasons = self._score_experts(request, eligible)
        selected = self._select_experts(request, eligible, scores)
        budgets = self._allocate_budgets(request.token_budget, selected, scores)
        allocations = tuple(
            ExpertAllocation(
                expert=expert,
                token_budget=budgets[expert],
                score=round(scores[expert], 3),
                reasons=tuple(reasons[expert]),
            )
            for expert in selected
        )
        escalation = self._escalation_experts(request, eligible, selected, scores)
        confidence = self._confidence(request, selected, scores)
        decision_id = _routing_decision_id(
            request=request,
            eligible=eligible,
            allocations=allocations,
            escalation=escalation,
            confidence=confidence,
        )
        decision = RoutingDecision(
            decision_id=decision_id,
            request_id=request.request_id,
            eligible_experts=eligible,
            allocations=allocations,
            escalation_experts=escalation,
            token_budget=request.token_budget,
            confidence=confidence,
            policy_version=POLICY_VERSION,
        )
        if sink is not None:
            sink.record(RoutingTelemetryRecord.from_route(request, decision))
        return decision

    def _eligible_experts(self, request: RoutingRequest) -> tuple[ExpertKey, ...]:
        result: list[ExpertKey] = []
        for profile in EXPERT_PROFILES:
            if profile.requires_repository and request.scope.repository_key is None:
                continue
            if (
                profile.requires_repository_permission
                and "repository:read" not in request.scope.permissions
            ):
                continue
            if profile.maintenance_only and request.task_kind is not TaskKind.MEMORY_MAINTENANCE:
                continue
            result.append(profile.expert)
        return tuple(result)

    def _score_experts(
        self,
        request: RoutingRequest,
        eligible: tuple[ExpertKey, ...],
    ) -> tuple[dict[ExpertKey, float], dict[ExpertKey, list[str]]]:
        scores: dict[ExpertKey, float] = defaultdict(float)
        reasons: dict[ExpertKey, list[str]] = defaultdict(list)

        self._apply_scores(
            scores,
            reasons,
            TASK_SCORES[request.task_kind],
            f"task:{request.task_kind.value}",
        )
        self._apply_scores(
            scores,
            reasons,
            PHASE_SCORES[request.plan_phase],
            f"phase:{request.plan_phase.value}",
        )
        for need in sorted(request.needs, key=lambda item: item.value):
            self._apply_scores(scores, reasons, NEED_SCORES[need], f"need:{need.value}")

        if request.temporal_intent is TemporalIntent.CURRENT:
            self._apply_scores(
                scores,
                reasons,
                {ExpertKey.TEMPORAL: 50, ExpertKey.DECISION: 20},
                "temporal:current",
            )
        elif request.temporal_intent is TemporalIntent.HISTORICAL:
            self._apply_scores(
                scores,
                reasons,
                {ExpertKey.EPISODIC: 60, ExpertKey.TEMPORAL: 60},
                "temporal:historical",
            )
        elif request.temporal_intent is TemporalIntent.COMPARATIVE:
            self._apply_scores(
                scores,
                reasons,
                {ExpertKey.TEMPORAL: 70, ExpertKey.EPISODIC: 40},
                "temporal:comparative",
            )

        if request.exactness is ExactnessNeed.EXACT:
            self._apply_scores(
                scores,
                reasons,
                {ExpertKey.EPISODIC: 70},
                "exactness:exact",
            )
        elif request.exactness is ExactnessNeed.SEMANTIC:
            self._apply_scores(
                scores,
                reasons,
                {ExpertKey.SEMANTIC: 20},
                "exactness:semantic",
            )

        if request.risk is RiskLevel.HIGH:
            self._apply_scores(
                scores,
                reasons,
                {
                    ExpertKey.FAILURE: 80,
                    ExpertKey.PROCEDURAL: 40,
                    ExpertKey.DECISION: 20,
                },
                "risk:high",
            )
        elif request.risk is RiskLevel.MEDIUM:
            self._apply_scores(
                scores,
                reasons,
                {ExpertKey.FAILURE: 20},
                "risk:medium",
            )

        if request.uncertainty >= 0.65:
            self._apply_scores(
                scores,
                reasons,
                {ExpertKey.EPISODIC: 30, ExpertKey.CAUSAL: 20},
                "uncertainty:high",
            )

        eligible_set = set(eligible)
        filtered_scores = {expert: scores[expert] for expert in eligible}
        filtered_reasons = {expert: reasons[expert] for expert in eligible}
        for expert in set(scores) - eligible_set:
            filtered_scores.pop(expert, None)
            filtered_reasons.pop(expert, None)
        return filtered_scores, filtered_reasons

    @staticmethod
    def _apply_scores(
        scores: dict[ExpertKey, float],
        reasons: dict[ExpertKey, list[str]],
        additions: dict[ExpertKey, float],
        reason: str,
    ) -> None:
        for expert, amount in additions.items():
            scores[expert] += amount
            reasons[expert].append(reason)

    def _select_experts(
        self,
        request: RoutingRequest,
        eligible: tuple[ExpertKey, ...],
        scores: dict[ExpertKey, float],
    ) -> tuple[ExpertKey, ...]:
        budget_cap = max(1, request.token_budget // MIN_EXPERT_TOKENS)
        count = min(request.max_experts, budget_cap)
        ranked = sorted(
            (expert for expert in eligible if scores.get(expert, 0.0) > 0),
            key=lambda expert: (-scores[expert], self._profile_index(expert)),
        )
        return tuple(ranked[:count])

    def _allocate_budgets(
        self,
        total_budget: int,
        selected: tuple[ExpertKey, ...],
        scores: dict[ExpertKey, float],
    ) -> dict[ExpertKey, int]:
        if not selected:
            return {}
        minimum = min(MIN_EXPERT_TOKENS, total_budget // len(selected))
        allocations = {expert: minimum for expert in selected}
        remaining = total_budget - minimum * len(selected)

        while remaining > 0:
            open_experts = [
                expert
                for expert in selected
                if allocations[expert] < PROFILE_BY_EXPERT[expert].hard_max_budget
            ]
            if not open_experts:
                break
            total_score = sum(max(scores[expert], 1.0) for expert in open_experts)
            progressed = False
            for expert in open_experts:
                capacity = PROFILE_BY_EXPERT[expert].hard_max_budget - allocations[expert]
                share = max(1, int(remaining * max(scores[expert], 1.0) / total_score))
                addition = min(capacity, share, remaining)
                if addition:
                    allocations[expert] += addition
                    remaining -= addition
                    progressed = True
                if remaining == 0:
                    break
            if not progressed:
                break
        return allocations

    def _escalation_experts(
        self,
        request: RoutingRequest,
        eligible: tuple[ExpertKey, ...],
        selected: tuple[ExpertKey, ...],
        scores: dict[ExpertKey, float],
    ) -> tuple[ExpertKey, ...]:
        selected_set = set(selected)
        eligible_set = set(eligible)
        preferred = [
            expert
            for expert in ESCALATION_ORDER[request.task_kind]
            if expert in eligible_set and expert not in selected_set
        ]
        remainder = sorted(
            (
                expert
                for expert in eligible
                if expert not in selected_set and expert not in preferred
            ),
            key=lambda expert: (-scores.get(expert, 0.0), self._profile_index(expert)),
        )
        return tuple((*preferred, *remainder))

    @staticmethod
    def _confidence(
        request: RoutingRequest,
        selected: tuple[ExpertKey, ...],
        scores: dict[ExpertKey, float],
    ) -> float:
        value = 0.94 - 0.35 * request.uncertainty
        if request.task_kind is TaskKind.GENERAL:
            value -= 0.12
        if not request.needs:
            value -= 0.05
        if not selected or max((scores.get(expert, 0.0) for expert in selected), default=0) < 100:
            value -= 0.08
        return round(min(0.99, max(0.1, value)), 3)

    @staticmethod
    def _profile_index(expert: ExpertKey) -> int:
        return next(
            index for index, profile in enumerate(EXPERT_PROFILES) if profile.expert is expert
        )

def _routing_decision_id(
    *,
    request: RoutingRequest,
    eligible: tuple[ExpertKey, ...],
    allocations: tuple[ExpertAllocation, ...],
    escalation: tuple[ExpertKey, ...],
    confidence: float,
) -> UUID:
    """Bind one UUID to the complete privacy-safe routing policy and outcome."""

    payload: dict[str, object] = {
        "request": {
            "request_id": str(request.request_id),
            "query_hash": hashlib.sha256(
                request.query.encode("utf-8")
            ).hexdigest(),
            "scope_fingerprint": _canonical_json_sha256(
                request.scope.to_dict()
            ),
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
        },
        "outcome": {
            "eligible_experts": [expert.value for expert in eligible],
            "allocations": [
                allocation.to_dict() for allocation in allocations
            ],
            "escalation_experts": [
                expert.value for expert in escalation
            ],
            "confidence": confidence,
            "policy_version": POLICY_VERSION,
        },
    }
    digest = _canonical_json_sha256(payload)
    return uuid5(
        NAMESPACE_URL,
        f"nextgen-memory:routing-decision:{POLICY_VERSION}:{digest}",
    )


def _canonical_json_sha256(value: object) -> str:
    """Hash an explicitly built JSON value without arbitrary string fallback."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
