"""Deterministic planning and in-memory state for matched policy replays."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass, field
from enum import StrEnum
from math import isfinite
from uuid import NAMESPACE_URL, UUID, uuid5

from .causal_credit import OutcomeMeasurement
from .inherited_rerank_telemetry import InheritedRerankTelemetryBatch
from .paired_rerank_policy_evaluation import (
    PairedRerankPolicyEvaluationValidationError,
    PairedRerankPolicyTrial,
)

_SCHEMA = "nextgen-memory-paired-replay-experiment-registry-v0"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class PairedReplayRegistryValidationError(ValueError):
    """A registry value violates a bounded immutable contract."""


class PairedReplayRegistryConflictError(ValueError):
    """An immutable identity was reused with different content."""


class PairedReplayRegistryStateError(ValueError):
    """A registry operation is not valid in the current pair state."""


class ReplayArm(StrEnum):
    """One policy arm in a matched replay pair."""

    CONTROL = "control"
    TREATMENT = "treatment"


class ReplayArmOrder(StrEnum):
    """Counterbalanced execution order for a replay pair."""

    CONTROL_THEN_TREATMENT = "control_then_treatment"
    TREATMENT_THEN_CONTROL = "treatment_then_control"

    @property
    def first_arm(self) -> ReplayArm:
        if self is ReplayArmOrder.CONTROL_THEN_TREATMENT:
            return ReplayArm.CONTROL
        return ReplayArm.TREATMENT

    @property
    def second_arm(self) -> ReplayArm:
        if self is ReplayArmOrder.CONTROL_THEN_TREATMENT:
            return ReplayArm.TREATMENT
        return ReplayArm.CONTROL


class ReplayFailureCode(StrEnum):
    """Bounded terminal failure classifications."""

    EXECUTION_FAILED = "execution_failed"
    BUDGET_EXCEEDED = "budget_exceeded"
    CANCELLED = "cancelled"


class ReplayPairStatus(StrEnum):
    """State of one deterministic replay pair."""

    PLANNED = "planned"
    FIRST_ARM_RECORDED = "first_arm_recorded"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class PairedReplayExperimentSpec:
    """Immutable policies, identities, and budgets for one experiment."""

    experiment_id: UUID
    space_id: UUID
    control_policy_version: str
    control_policy_fingerprint: str
    treatment_policy_version: str
    treatment_policy_fingerprint: str
    continuation_set_hash: str
    order_seed_hash: str
    maximum_pairs: int
    maximum_tokens_per_arm: int
    maximum_latency_ms_per_arm: float
    maximum_total_tokens: int
    maximum_total_latency_ms: float
    registry_policy_version: str = "paired-replay-experiment-registry-v0"
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid("experiment_id", self.experiment_id)
        _require_uuid("space_id", self.space_id)
        control_version = _required_text("control_policy_version", self.control_policy_version)
        treatment_version = _required_text(
            "treatment_policy_version", self.treatment_policy_version
        )
        registry_version = _required_text("registry_policy_version", self.registry_policy_version)
        _require_hash("control_policy_fingerprint", self.control_policy_fingerprint)
        _require_hash("treatment_policy_fingerprint", self.treatment_policy_fingerprint)
        _require_hash("continuation_set_hash", self.continuation_set_hash)
        _require_hash("order_seed_hash", self.order_seed_hash)
        if self.control_policy_fingerprint == self.treatment_policy_fingerprint:
            raise PairedReplayRegistryValidationError(
                "control and treatment policy fingerprints must be distinct"
            )
        maximum_pairs = _positive_integer("maximum_pairs", self.maximum_pairs)
        maximum_tokens_per_arm = _positive_integer(
            "maximum_tokens_per_arm", self.maximum_tokens_per_arm
        )
        maximum_latency_ms_per_arm = _positive_number(
            "maximum_latency_ms_per_arm", self.maximum_latency_ms_per_arm
        )
        maximum_total_tokens = _positive_integer("maximum_total_tokens", self.maximum_total_tokens)
        maximum_total_latency_ms = _positive_number(
            "maximum_total_latency_ms", self.maximum_total_latency_ms
        )
        if maximum_total_tokens < 2 * maximum_tokens_per_arm:
            raise PairedReplayRegistryValidationError(
                "maximum_total_tokens must fit at least one complete pair"
            )
        if maximum_total_latency_ms < 2.0 * maximum_latency_ms_per_arm:
            raise PairedReplayRegistryValidationError(
                "maximum_total_latency_ms must fit at least one complete pair"
            )

        object.__setattr__(self, "control_policy_version", control_version)
        object.__setattr__(self, "treatment_policy_version", treatment_version)
        object.__setattr__(self, "registry_policy_version", registry_version)
        object.__setattr__(self, "maximum_pairs", maximum_pairs)
        object.__setattr__(self, "maximum_tokens_per_arm", maximum_tokens_per_arm)
        object.__setattr__(self, "maximum_latency_ms_per_arm", maximum_latency_ms_per_arm)
        object.__setattr__(self, "maximum_total_tokens", maximum_total_tokens)
        object.__setattr__(self, "maximum_total_latency_ms", maximum_total_latency_ms)
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": str(self.experiment_id),
            "space_id": str(self.space_id),
            "control_policy_version": self.control_policy_version,
            "control_policy_fingerprint": self.control_policy_fingerprint,
            "treatment_policy_version": self.treatment_policy_version,
            "treatment_policy_fingerprint": self.treatment_policy_fingerprint,
            "continuation_set_hash": self.continuation_set_hash,
            "order_seed_hash": self.order_seed_hash,
            "maximum_pairs": self.maximum_pairs,
            "maximum_tokens_per_arm": self.maximum_tokens_per_arm,
            "maximum_latency_ms_per_arm": self.maximum_latency_ms_per_arm,
            "maximum_total_tokens": self.maximum_total_tokens,
            "maximum_total_latency_ms": self.maximum_total_latency_ms,
            "registry_policy_version": self.registry_policy_version,
        }


@dataclass(frozen=True, slots=True)
class PairedReplayAssignment:
    """One context's pair identity and counterbalanced order."""

    id: UUID
    experiment_id: UUID
    space_id: UUID
    context_set_hash: str
    continuation_set_hash: str
    ordinal: int
    arm_order: ReplayArmOrder
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid("id", self.id)
        _require_uuid("experiment_id", self.experiment_id)
        _require_uuid("space_id", self.space_id)
        _require_hash("context_set_hash", self.context_set_hash)
        _require_hash("continuation_set_hash", self.continuation_set_hash)
        ordinal = _positive_integer("ordinal", self.ordinal)
        if not isinstance(self.arm_order, ReplayArmOrder):
            raise PairedReplayRegistryValidationError("arm_order must be a ReplayArmOrder")
        object.__setattr__(self, "ordinal", ordinal)
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "experiment_id": str(self.experiment_id),
            "space_id": str(self.space_id),
            "context_set_hash": self.context_set_hash,
            "continuation_set_hash": self.continuation_set_hash,
            "ordinal": self.ordinal,
            "arm_order": self.arm_order.value,
        }


@dataclass(frozen=True, slots=True)
class PairedReplayPlanSummary:
    """Bounded counts and worst-case reservation for one plan."""

    pair_count: int
    control_first_count: int
    treatment_first_count: int
    worst_case_total_tokens: int
    worst_case_total_latency_ms: float
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        pair_count = _positive_integer("pair_count", self.pair_count)
        control_count = _nonnegative_integer("control_first_count", self.control_first_count)
        treatment_count = _nonnegative_integer("treatment_first_count", self.treatment_first_count)
        tokens = _positive_integer("worst_case_total_tokens", self.worst_case_total_tokens)
        latency = _positive_number("worst_case_total_latency_ms", self.worst_case_total_latency_ms)
        if control_count + treatment_count != pair_count:
            raise PairedReplayRegistryValidationError("arm-order counts must partition pair_count")
        if abs(control_count - treatment_count) > 1:
            raise PairedReplayRegistryValidationError("arm-order counts must differ by at most one")
        object.__setattr__(self, "pair_count", pair_count)
        object.__setattr__(self, "control_first_count", control_count)
        object.__setattr__(self, "treatment_first_count", treatment_count)
        object.__setattr__(self, "worst_case_total_tokens", tokens)
        object.__setattr__(self, "worst_case_total_latency_ms", latency)
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "pair_count": self.pair_count,
            "control_first_count": self.control_first_count,
            "treatment_first_count": self.treatment_first_count,
            "worst_case_total_tokens": self.worst_case_total_tokens,
            "worst_case_total_latency_ms": self.worst_case_total_latency_ms,
        }


@dataclass(frozen=True, slots=True)
class PairedReplayPlan:
    """One complete deterministic experiment plan."""

    id: UUID
    spec: PairedReplayExperimentSpec
    assignments: tuple[PairedReplayAssignment, ...]
    summary: PairedReplayPlanSummary
    content_hash: str

    def __post_init__(self) -> None:
        _require_uuid("id", self.id)
        if not isinstance(self.spec, PairedReplayExperimentSpec):
            raise PairedReplayRegistryValidationError("spec must be a PairedReplayExperimentSpec")
        assignments = tuple(self.assignments)
        if not assignments:
            raise PairedReplayRegistryValidationError("assignments must contain at least one pair")
        if any(not isinstance(item, PairedReplayAssignment) for item in assignments):
            raise PairedReplayRegistryValidationError(
                "assignments must contain PairedReplayAssignment values"
            )
        if tuple(item.ordinal for item in assignments) != tuple(range(1, len(assignments) + 1)):
            raise PairedReplayRegistryValidationError(
                "assignments must use contiguous deterministic ordinals"
            )
        if len({item.id for item in assignments}) != len(assignments):
            raise PairedReplayRegistryValidationError("assignment pair identities must be unique")
        if any(
            item.experiment_id != self.spec.experiment_id
            or item.space_id != self.spec.space_id
            or item.continuation_set_hash != self.spec.continuation_set_hash
            for item in assignments
        ):
            raise PairedReplayRegistryValidationError("assignments must match the experiment spec")
        if not isinstance(self.summary, PairedReplayPlanSummary):
            raise PairedReplayRegistryValidationError("summary must be a PairedReplayPlanSummary")
        if self.summary.pair_count != len(assignments):
            raise PairedReplayRegistryValidationError("summary pair_count must match assignments")
        _require_hash("content_hash", self.content_hash)
        expected_hash = _hash_payload(self._identity_payload(assignments))
        if self.content_hash != expected_hash:
            raise PairedReplayRegistryValidationError(
                "plan content_hash does not match immutable content"
            )
        expected_id = _stable_uuid("plan", self.content_hash)
        if self.id != expected_id:
            raise PairedReplayRegistryValidationError("plan id does not match immutable content")
        object.__setattr__(self, "assignments", assignments)

    def _identity_payload(
        self, assignments: tuple[PairedReplayAssignment, ...]
    ) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "spec": self.spec.to_dict(),
            "spec_content_hash": self.spec.content_hash,
            "assignments": [item.to_dict() for item in assignments],
            "assignment_content_hashes": [item.content_hash for item in assignments],
            "summary": self.summary.to_dict(),
            "summary_content_hash": self.summary.content_hash,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": _SCHEMA,
            "id": str(self.id),
            "content_hash": self.content_hash,
            "spec": self.spec.to_dict(),
            "assignments": [item.to_dict() for item in self.assignments],
            "summary": self.summary.to_dict(),
        }

    def render_json(self) -> str:
        return _canonical_json(self.to_dict())


class BalancedPairedReplayPlanner:
    """Create a counterbalanced deterministic plan before any arm can run."""

    __slots__ = ()

    def plan(
        self,
        spec: PairedReplayExperimentSpec,
        context_hashes: Iterable[str],
    ) -> PairedReplayPlan:
        if not isinstance(spec, PairedReplayExperimentSpec):
            raise PairedReplayRegistryValidationError("spec must be a PairedReplayExperimentSpec")
        contexts = _normalize_context_hashes(context_hashes)
        if len(contexts) > spec.maximum_pairs:
            raise PairedReplayRegistryValidationError("context count exceeds maximum_pairs")
        worst_case_tokens = len(contexts) * 2 * spec.maximum_tokens_per_arm
        worst_case_latency = len(contexts) * 2.0 * spec.maximum_latency_ms_per_arm
        if worst_case_tokens > spec.maximum_total_tokens:
            raise PairedReplayRegistryValidationError(
                "worst-case token budget exceeds maximum_total_tokens"
            )
        if worst_case_latency > spec.maximum_total_latency_ms:
            raise PairedReplayRegistryValidationError(
                "worst-case latency budget exceeds maximum_total_latency_ms"
            )

        ordered_contexts = tuple(
            sorted(
                contexts,
                key=lambda value: (
                    hashlib.sha256(f"{spec.order_seed_hash}:{value}".encode("ascii")).hexdigest(),
                    value,
                ),
            )
        )
        start_with_control = int(spec.order_seed_hash[-1], 16) % 2 == 0
        order_by_context: dict[str, ReplayArmOrder] = {}
        for position, context_hash in enumerate(ordered_contexts):
            control_first = (position % 2 == 0) == start_with_control
            order_by_context[context_hash] = (
                ReplayArmOrder.CONTROL_THEN_TREATMENT
                if control_first
                else ReplayArmOrder.TREATMENT_THEN_CONTROL
            )

        assignments: list[PairedReplayAssignment] = []
        for ordinal, context_hash in enumerate(sorted(contexts), start=1):
            assignments.append(
                PairedReplayAssignment(
                    id=_pair_uuid(spec, context_hash),
                    experiment_id=spec.experiment_id,
                    space_id=spec.space_id,
                    context_set_hash=context_hash,
                    continuation_set_hash=spec.continuation_set_hash,
                    ordinal=ordinal,
                    arm_order=order_by_context[context_hash],
                )
            )
        frozen_assignments = tuple(assignments)
        control_count = sum(
            item.arm_order is ReplayArmOrder.CONTROL_THEN_TREATMENT for item in frozen_assignments
        )
        summary = PairedReplayPlanSummary(
            pair_count=len(frozen_assignments),
            control_first_count=control_count,
            treatment_first_count=len(frozen_assignments) - control_count,
            worst_case_total_tokens=worst_case_tokens,
            worst_case_total_latency_ms=worst_case_latency,
        )
        payload = {
            "schema": _SCHEMA,
            "spec": spec.to_dict(),
            "spec_content_hash": spec.content_hash,
            "assignments": [item.to_dict() for item in frozen_assignments],
            "assignment_content_hashes": [item.content_hash for item in frozen_assignments],
            "summary": summary.to_dict(),
            "summary_content_hash": summary.content_hash,
        }
        content_hash = _hash_payload(payload)
        return PairedReplayPlan(
            id=_stable_uuid("plan", content_hash),
            spec=spec,
            assignments=frozen_assignments,
            summary=summary,
            content_hash=content_hash,
        )


@dataclass(frozen=True, slots=True)
class PairedReplayStep:
    """The only arm currently permitted for one replay pair."""

    pair_id: UUID
    experiment_id: UUID
    space_id: UUID
    arm: ReplayArm
    order_position: int
    context_set_hash: str
    continuation_set_hash: str
    policy_version: str
    policy_fingerprint: str
    maximum_tokens: int
    maximum_latency_ms: float
    id: UUID = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid("pair_id", self.pair_id)
        _require_uuid("experiment_id", self.experiment_id)
        _require_uuid("space_id", self.space_id)
        if not isinstance(self.arm, ReplayArm):
            raise PairedReplayRegistryValidationError("arm must be a ReplayArm")
        if self.order_position not in (1, 2) or isinstance(self.order_position, bool):
            raise PairedReplayRegistryValidationError("order_position must be one or two")
        _require_hash("context_set_hash", self.context_set_hash)
        _require_hash("continuation_set_hash", self.continuation_set_hash)
        policy_version = _required_text("policy_version", self.policy_version)
        _require_hash("policy_fingerprint", self.policy_fingerprint)
        maximum_tokens = _positive_integer("maximum_tokens", self.maximum_tokens)
        maximum_latency_ms = _positive_number("maximum_latency_ms", self.maximum_latency_ms)
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "maximum_tokens", maximum_tokens)
        object.__setattr__(self, "maximum_latency_ms", maximum_latency_ms)
        object.__setattr__(
            self,
            "id",
            _stable_uuid("step", str(self.pair_id), self.arm.value),
        )
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "pair_id": str(self.pair_id),
            "experiment_id": str(self.experiment_id),
            "space_id": str(self.space_id),
            "arm": self.arm.value,
            "order_position": self.order_position,
            "context_set_hash": self.context_set_hash,
            "continuation_set_hash": self.continuation_set_hash,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "maximum_tokens": self.maximum_tokens,
            "maximum_latency_ms": self.maximum_latency_ms,
        }


@dataclass(frozen=True, slots=True)
class PairedReplayArmResult:
    """One completed bounded arm result."""

    step_id: UUID
    pair_id: UUID
    experiment_id: UUID
    arm: ReplayArm
    telemetry_batch: InheritedRerankTelemetryBatch
    outcome: OutcomeMeasurement
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid("step_id", self.step_id)
        _require_uuid("pair_id", self.pair_id)
        _require_uuid("experiment_id", self.experiment_id)
        if not isinstance(self.arm, ReplayArm):
            raise PairedReplayRegistryValidationError("arm must be a ReplayArm")
        if not isinstance(self.telemetry_batch, InheritedRerankTelemetryBatch):
            raise PairedReplayRegistryValidationError(
                "telemetry_batch must be an InheritedRerankTelemetryBatch"
            )
        if not isinstance(self.outcome, OutcomeMeasurement):
            raise PairedReplayRegistryValidationError("outcome must be an OutcomeMeasurement")
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "step_id": str(self.step_id),
            "pair_id": str(self.pair_id),
            "experiment_id": str(self.experiment_id),
            "arm": self.arm.value,
            "telemetry_batch_id": str(self.telemetry_batch.id),
            "telemetry_content_hash": self.telemetry_batch.content_hash,
            "telemetry_space_id": str(self.telemetry_batch.space_id),
            "telemetry_router_decision_id": str(self.telemetry_batch.router_decision_id),
            "telemetry_policy_version": self.telemetry_batch.policy_version,
            "telemetry_policy_fingerprint": (self.telemetry_batch.policy_fingerprint),
            "outcome": _outcome_payload(self.outcome),
        }


@dataclass(frozen=True, slots=True)
class PairedReplayFailureRecord:
    """A bounded terminal failure for the currently schedulable step."""

    step_id: UUID
    pair_id: UUID
    experiment_id: UUID
    arm: ReplayArm
    code: ReplayFailureCode
    id: UUID = field(init=False)
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid("step_id", self.step_id)
        _require_uuid("pair_id", self.pair_id)
        _require_uuid("experiment_id", self.experiment_id)
        if not isinstance(self.arm, ReplayArm):
            raise PairedReplayRegistryValidationError("arm must be a ReplayArm")
        if not isinstance(self.code, ReplayFailureCode):
            raise PairedReplayRegistryValidationError("code must be a ReplayFailureCode")
        object.__setattr__(
            self,
            "id",
            _stable_uuid("failure", str(self.step_id), self.code.value),
        )
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "step_id": str(self.step_id),
            "pair_id": str(self.pair_id),
            "experiment_id": str(self.experiment_id),
            "arm": self.arm.value,
            "code": self.code.value,
        }


@dataclass(frozen=True, slots=True)
class PairedReplayPairSnapshot:
    """Privacy-safe immutable snapshot of one pair state."""

    pair_id: UUID
    experiment_id: UUID
    ordinal: int
    arm_order: ReplayArmOrder
    status: ReplayPairStatus
    recorded_arms: tuple[ReplayArm, ...]
    next_step: PairedReplayStep | None
    failure_code: ReplayFailureCode | None
    completed_trial_id: UUID | None
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid("pair_id", self.pair_id)
        _require_uuid("experiment_id", self.experiment_id)
        ordinal = _positive_integer("ordinal", self.ordinal)
        if not isinstance(self.arm_order, ReplayArmOrder):
            raise PairedReplayRegistryValidationError("arm_order must be a ReplayArmOrder")
        if not isinstance(self.status, ReplayPairStatus):
            raise PairedReplayRegistryValidationError("status must be a ReplayPairStatus")
        arms = tuple(self.recorded_arms)
        if any(not isinstance(arm, ReplayArm) for arm in arms):
            raise PairedReplayRegistryValidationError("recorded_arms must contain ReplayArm values")
        if len(arms) != len(set(arms)) or len(arms) > 2:
            raise PairedReplayRegistryValidationError("recorded_arms must be unique and bounded")
        if self.next_step is not None and not isinstance(self.next_step, PairedReplayStep):
            raise PairedReplayRegistryValidationError(
                "next_step must be a PairedReplayStep or null"
            )
        if self.failure_code is not None and not isinstance(self.failure_code, ReplayFailureCode):
            raise PairedReplayRegistryValidationError(
                "failure_code must be a ReplayFailureCode or null"
            )
        if self.completed_trial_id is not None:
            _require_uuid("completed_trial_id", self.completed_trial_id)
        object.__setattr__(self, "ordinal", ordinal)
        object.__setattr__(self, "recorded_arms", arms)
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "pair_id": str(self.pair_id),
            "experiment_id": str(self.experiment_id),
            "ordinal": self.ordinal,
            "arm_order": self.arm_order.value,
            "status": self.status.value,
            "recorded_arms": [arm.value for arm in self.recorded_arms],
            "next_step": (self.next_step.to_dict() if self.next_step is not None else None),
            "failure_code": (self.failure_code.value if self.failure_code is not None else None),
            "completed_trial_id": (
                str(self.completed_trial_id) if self.completed_trial_id is not None else None
            ),
        }


@dataclass(frozen=True, slots=True)
class PairedReplayExperimentSummary:
    """State partition and actual resource use for one experiment."""

    experiment_id: UUID
    pair_count: int
    planned_count: int
    first_arm_recorded_count: int
    complete_count: int
    failed_count: int
    cancelled_count: int
    recorded_arm_count: int
    completed_trial_count: int
    actual_tokens: int
    actual_latency_ms: float
    content_hash: str = field(init=False)

    def __post_init__(self) -> None:
        _require_uuid("experiment_id", self.experiment_id)
        fields = (
            "pair_count",
            "planned_count",
            "first_arm_recorded_count",
            "complete_count",
            "failed_count",
            "cancelled_count",
            "recorded_arm_count",
            "completed_trial_count",
            "actual_tokens",
        )
        normalized = {name: _nonnegative_integer(name, getattr(self, name)) for name in fields}
        if normalized["pair_count"] <= 0:
            raise PairedReplayRegistryValidationError("pair_count must be positive")
        if (
            normalized["planned_count"]
            + normalized["first_arm_recorded_count"]
            + normalized["complete_count"]
            + normalized["failed_count"]
            + normalized["cancelled_count"]
            != normalized["pair_count"]
        ):
            raise PairedReplayRegistryValidationError("status counts must partition pair_count")
        if normalized["completed_trial_count"] != normalized["complete_count"]:
            raise PairedReplayRegistryValidationError(
                "completed_trial_count must equal complete_count"
            )
        if normalized["recorded_arm_count"] > normalized["pair_count"] * 2:
            raise PairedReplayRegistryValidationError("recorded_arm_count exceeds pair capacity")
        latency = _nonnegative_number("actual_latency_ms", self.actual_latency_ms)
        for name, value in normalized.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "actual_latency_ms", latency)
        object.__setattr__(self, "content_hash", _hash_payload(self.to_dict()))

    def to_dict(self) -> dict[str, object]:
        return {
            "experiment_id": str(self.experiment_id),
            "pair_count": self.pair_count,
            "planned_count": self.planned_count,
            "first_arm_recorded_count": self.first_arm_recorded_count,
            "complete_count": self.complete_count,
            "failed_count": self.failed_count,
            "cancelled_count": self.cancelled_count,
            "recorded_arm_count": self.recorded_arm_count,
            "completed_trial_count": self.completed_trial_count,
            "actual_tokens": self.actual_tokens,
            "actual_latency_ms": self.actual_latency_ms,
        }


@dataclass(slots=True)
class _PairState:
    assignment: PairedReplayAssignment
    status: ReplayPairStatus = ReplayPairStatus.PLANNED
    results: dict[ReplayArm, PairedReplayArmResult] = field(default_factory=dict)
    failure: PairedReplayFailureRecord | None = None
    trial: PairedRerankPolicyTrial | None = None


class InMemoryPairedReplayExperimentRegistry:
    """Reference state machine with no persistence or execution behavior."""

    __slots__ = ("_plans", "_states")

    def __init__(self) -> None:
        self._plans: dict[UUID, PairedReplayPlan] = {}
        self._states: dict[UUID, dict[UUID, _PairState]] = {}

    def register_plan(self, plan: PairedReplayPlan) -> None:
        if not isinstance(plan, PairedReplayPlan):
            raise PairedReplayRegistryValidationError("plan must be a PairedReplayPlan")
        existing = self._plans.get(plan.spec.experiment_id)
        if existing is not None:
            if existing.content_hash == plan.content_hash and existing == plan:
                return
            raise PairedReplayRegistryConflictError(
                "experiment plan conflict for immutable experiment id"
            )
        self._plans[plan.spec.experiment_id] = plan
        self._states[plan.spec.experiment_id] = {
            assignment.id: _PairState(assignment=assignment) for assignment in plan.assignments
        }

    def next_steps(self, experiment_id: UUID) -> tuple[PairedReplayStep, ...]:
        plan, states = self._experiment(experiment_id)
        steps: list[PairedReplayStep] = []
        for assignment in plan.assignments:
            state = states[assignment.id]
            next_step = self._next_step(plan, state)
            if next_step is not None:
                steps.append(next_step)
        return tuple(steps)

    def record_arm_result(self, result: PairedReplayArmResult) -> None:
        if not isinstance(result, PairedReplayArmResult):
            raise PairedReplayRegistryValidationError("result must be a PairedReplayArmResult")
        plan, states = self._experiment(result.experiment_id)
        state = self._pair_state(states, result.pair_id)
        prior = state.results.get(result.arm)
        if prior is not None:
            if prior.content_hash == result.content_hash and prior == result:
                return
            raise PairedReplayRegistryConflictError(
                "arm result conflict for immutable step identity"
            )
        if state.status in {
            ReplayPairStatus.COMPLETE,
            ReplayPairStatus.FAILED,
            ReplayPairStatus.CANCELLED,
        }:
            raise PairedReplayRegistryStateError(
                "cannot record a result for a terminal replay pair"
            )
        expected = self._next_step(plan, state)
        if expected is None or not _step_matches_result(expected, result):
            raise PairedReplayRegistryStateError(
                "result does not match the currently schedulable step"
            )
        self._validate_result(plan.spec, expected, state, result)
        proposed = dict(state.results)
        proposed[result.arm] = result
        trial: PairedRerankPolicyTrial | None = None
        if len(proposed) == 2:
            trial = self._build_trial(plan, state.assignment, proposed)
        state.results[result.arm] = result
        if trial is None:
            state.status = ReplayPairStatus.FIRST_ARM_RECORDED
        else:
            state.trial = trial
            state.status = ReplayPairStatus.COMPLETE

    def record_failure(self, failure: PairedReplayFailureRecord) -> None:
        if not isinstance(failure, PairedReplayFailureRecord):
            raise PairedReplayRegistryValidationError("failure must be a PairedReplayFailureRecord")
        plan, states = self._experiment(failure.experiment_id)
        state = self._pair_state(states, failure.pair_id)
        if state.failure is not None:
            if state.failure.content_hash == failure.content_hash and state.failure == failure:
                return
            raise PairedReplayRegistryConflictError("failure conflict for immutable step identity")
        if state.status in {
            ReplayPairStatus.COMPLETE,
            ReplayPairStatus.FAILED,
            ReplayPairStatus.CANCELLED,
        }:
            raise PairedReplayRegistryStateError(
                "cannot record a failure for a terminal replay pair"
            )
        expected = self._next_step(plan, state)
        if expected is None or not _step_matches_failure(expected, failure):
            raise PairedReplayRegistryStateError(
                "failure does not match the currently schedulable step"
            )
        state.failure = failure
        state.status = (
            ReplayPairStatus.CANCELLED
            if failure.code is ReplayFailureCode.CANCELLED
            else ReplayPairStatus.FAILED
        )

    def pair_snapshots(self, experiment_id: UUID) -> tuple[PairedReplayPairSnapshot, ...]:
        plan, states = self._experiment(experiment_id)
        snapshots: list[PairedReplayPairSnapshot] = []
        for assignment in plan.assignments:
            state = states[assignment.id]
            arms = tuple(
                arm for arm in (ReplayArm.CONTROL, ReplayArm.TREATMENT) if arm in state.results
            )
            snapshots.append(
                PairedReplayPairSnapshot(
                    pair_id=assignment.id,
                    experiment_id=assignment.experiment_id,
                    ordinal=assignment.ordinal,
                    arm_order=assignment.arm_order,
                    status=state.status,
                    recorded_arms=arms,
                    next_step=self._next_step(plan, state),
                    failure_code=(state.failure.code if state.failure is not None else None),
                    completed_trial_id=(state.trial.trial_id if state.trial is not None else None),
                )
            )
        return tuple(snapshots)

    def completed_trials(self, experiment_id: UUID) -> tuple[PairedRerankPolicyTrial, ...]:
        plan, states = self._experiment(experiment_id)
        return tuple(
            states[assignment.id].trial
            for assignment in plan.assignments
            if states[assignment.id].trial is not None
        )

    def summary(self, experiment_id: UUID) -> PairedReplayExperimentSummary:
        plan, states = self._experiment(experiment_id)
        counts = {status: 0 for status in ReplayPairStatus}
        recorded_arm_count = 0
        actual_tokens = 0
        actual_latency_ms = 0.0
        completed_trial_count = 0
        for assignment in plan.assignments:
            state = states[assignment.id]
            counts[state.status] += 1
            recorded_arm_count += len(state.results)
            actual_tokens += sum(result.outcome.tokens for result in state.results.values())
            actual_latency_ms += sum(result.outcome.latency_ms for result in state.results.values())
            completed_trial_count += int(state.trial is not None)
        return PairedReplayExperimentSummary(
            experiment_id=experiment_id,
            pair_count=len(plan.assignments),
            planned_count=counts[ReplayPairStatus.PLANNED],
            first_arm_recorded_count=counts[ReplayPairStatus.FIRST_ARM_RECORDED],
            complete_count=counts[ReplayPairStatus.COMPLETE],
            failed_count=counts[ReplayPairStatus.FAILED],
            cancelled_count=counts[ReplayPairStatus.CANCELLED],
            recorded_arm_count=recorded_arm_count,
            completed_trial_count=completed_trial_count,
            actual_tokens=actual_tokens,
            actual_latency_ms=actual_latency_ms,
        )

    def _experiment(self, experiment_id: UUID) -> tuple[PairedReplayPlan, dict[UUID, _PairState]]:
        _require_uuid("experiment_id", experiment_id)
        plan = self._plans.get(experiment_id)
        if plan is None:
            raise PairedReplayRegistryStateError("experiment is not registered")
        return plan, self._states[experiment_id]

    @staticmethod
    def _pair_state(states: Mapping[UUID, _PairState], pair_id: UUID) -> _PairState:
        _require_uuid("pair_id", pair_id)
        state = states.get(pair_id)
        if state is None:
            raise PairedReplayRegistryStateError("pair is not registered in the experiment")
        return state

    def _next_step(self, plan: PairedReplayPlan, state: _PairState) -> PairedReplayStep | None:
        if state.status is ReplayPairStatus.PLANNED:
            arm = state.assignment.arm_order.first_arm
            order_position = 1
        elif state.status is ReplayPairStatus.FIRST_ARM_RECORDED:
            arm = state.assignment.arm_order.second_arm
            order_position = 2
        else:
            return None
        policy_version, policy_fingerprint = _policy_identity(plan.spec, arm)
        return PairedReplayStep(
            pair_id=state.assignment.id,
            experiment_id=plan.spec.experiment_id,
            space_id=plan.spec.space_id,
            arm=arm,
            order_position=order_position,
            context_set_hash=state.assignment.context_set_hash,
            continuation_set_hash=state.assignment.continuation_set_hash,
            policy_version=policy_version,
            policy_fingerprint=policy_fingerprint,
            maximum_tokens=plan.spec.maximum_tokens_per_arm,
            maximum_latency_ms=plan.spec.maximum_latency_ms_per_arm,
        )

    @staticmethod
    def _validate_result(
        spec: PairedReplayExperimentSpec,
        step: PairedReplayStep,
        state: _PairState,
        result: PairedReplayArmResult,
    ) -> None:
        batch = result.telemetry_batch
        if batch.space_id != spec.space_id:
            raise PairedReplayRegistryValidationError(
                "telemetry space does not match the replay experiment"
            )
        if (
            batch.policy_version != step.policy_version
            or batch.policy_fingerprint != step.policy_fingerprint
        ):
            raise PairedReplayRegistryValidationError(
                "telemetry policy identity does not match the replay step"
            )
        if result.outcome.tokens > step.maximum_tokens:
            raise PairedReplayRegistryValidationError("outcome exceeds the per-arm token limit")
        if result.outcome.latency_ms > step.maximum_latency_ms:
            raise PairedReplayRegistryValidationError("outcome exceeds the per-arm latency limit")
        if state.results:
            first = next(iter(state.results.values()))
            if first.telemetry_batch.router_decision_id != batch.router_decision_id:
                raise PairedReplayRegistryValidationError(
                    "control and treatment must share one router decision"
                )

    @staticmethod
    def _build_trial(
        plan: PairedReplayPlan,
        assignment: PairedReplayAssignment,
        results: Mapping[ReplayArm, PairedReplayArmResult],
    ) -> PairedRerankPolicyTrial:
        control = results[ReplayArm.CONTROL]
        treatment = results[ReplayArm.TREATMENT]
        try:
            return PairedRerankPolicyTrial(
                trial_id=_stable_uuid("trial", str(assignment.id)),
                space_id=plan.spec.space_id,
                context_set_hash=assignment.context_set_hash,
                continuation_set_hash=assignment.continuation_set_hash,
                control_batch=control.telemetry_batch,
                treatment_batch=treatment.telemetry_batch,
                control_outcome=control.outcome,
                treatment_outcome=treatment.outcome,
            )
        except PairedRerankPolicyEvaluationValidationError as exc:
            raise PairedReplayRegistryValidationError(
                "control and treatment telemetry do not form a matched trial"
            ) from exc


def _normalize_context_hashes(context_hashes: Iterable[str]) -> tuple[str, ...]:
    if isinstance(context_hashes, (str, bytes, Mapping)):
        raise PairedReplayRegistryValidationError("context hashes must be a bounded collection")
    if not isinstance(context_hashes, (Sequence, Set)):
        try:
            values = tuple(context_hashes)
        except TypeError as exc:
            raise PairedReplayRegistryValidationError("context hashes must be iterable") from exc
    else:
        values = tuple(context_hashes)
    if not values:
        raise PairedReplayRegistryValidationError("at least one context_set_hash is required")
    for value in values:
        _require_hash("context_set_hash", value)
    if len(values) != len(set(values)):
        raise PairedReplayRegistryValidationError(
            "duplicate context_set_hash values are not allowed"
        )
    return tuple(sorted(values))


def _pair_uuid(spec: PairedReplayExperimentSpec, context_set_hash: str) -> UUID:
    return uuid5(
        spec.experiment_id,
        ":".join(
            (
                _SCHEMA,
                "pair",
                str(spec.space_id),
                context_set_hash,
                spec.continuation_set_hash,
                spec.control_policy_version,
                spec.control_policy_fingerprint,
                spec.treatment_policy_version,
                spec.treatment_policy_fingerprint,
                spec.registry_policy_version,
            )
        ),
    )


def _policy_identity(spec: PairedReplayExperimentSpec, arm: ReplayArm) -> tuple[str, str]:
    if arm is ReplayArm.CONTROL:
        return spec.control_policy_version, spec.control_policy_fingerprint
    return spec.treatment_policy_version, spec.treatment_policy_fingerprint


def _step_matches_result(step: PairedReplayStep, result: PairedReplayArmResult) -> bool:
    return (
        result.step_id == step.id
        and result.pair_id == step.pair_id
        and result.experiment_id == step.experiment_id
        and result.arm is step.arm
    )


def _step_matches_failure(step: PairedReplayStep, failure: PairedReplayFailureRecord) -> bool:
    return (
        failure.step_id == step.id
        and failure.pair_id == step.pair_id
        and failure.experiment_id == step.experiment_id
        and failure.arm is step.arm
    )


def _outcome_payload(outcome: OutcomeMeasurement) -> dict[str, object]:
    return {
        "score": outcome.score,
        "task_success": outcome.task_success,
        "tokens": outcome.tokens,
        "latency_ms": outcome.latency_ms,
    }


def _stable_uuid(kind: str, *parts: str) -> UUID:
    return uuid5(NAMESPACE_URL, ":".join((_SCHEMA, kind, *parts)))


def _canonical_json(value: object) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _hash_payload(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise PairedReplayRegistryValidationError(f"{name} must be a UUID")
    return value


def _require_hash(name: str, value: object) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise PairedReplayRegistryValidationError(f"{name} must be a lowercase SHA-256 value")
    return value


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise PairedReplayRegistryValidationError(f"{name} must be text")
    normalized = value.strip()
    if not normalized:
        raise PairedReplayRegistryValidationError(f"{name} must not be empty")
    if len(normalized) > 128:
        raise PairedReplayRegistryValidationError(f"{name} exceeds the bounded length")
    return normalized


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PairedReplayRegistryValidationError(f"{name} must be a positive integer")
    return value


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PairedReplayRegistryValidationError(f"{name} must be a non-negative integer")
    return value


def _positive_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PairedReplayRegistryValidationError(f"{name} must be a positive finite number")
    normalized = float(value)
    if not isfinite(normalized) or normalized <= 0.0:
        raise PairedReplayRegistryValidationError(f"{name} must be a positive finite number")
    return normalized


def _nonnegative_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PairedReplayRegistryValidationError(f"{name} must be a non-negative finite number")
    normalized = float(value)
    if not isfinite(normalized) or normalized < 0.0:
        raise PairedReplayRegistryValidationError(f"{name} must be a non-negative finite number")
    return normalized


__all__ = [
    "BalancedPairedReplayPlanner",
    "InMemoryPairedReplayExperimentRegistry",
    "PairedReplayArmResult",
    "PairedReplayAssignment",
    "PairedReplayExperimentSpec",
    "PairedReplayExperimentSummary",
    "PairedReplayFailureRecord",
    "PairedReplayPairSnapshot",
    "PairedReplayPlan",
    "PairedReplayPlanSummary",
    "PairedReplayRegistryConflictError",
    "PairedReplayRegistryStateError",
    "PairedReplayRegistryValidationError",
    "PairedReplayStep",
    "ReplayArm",
    "ReplayArmOrder",
    "ReplayFailureCode",
    "ReplayPairStatus",
]
