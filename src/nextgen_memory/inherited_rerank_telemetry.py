"""Deterministic aggregate-only telemetry for inherited reranking."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from math import isclose, isfinite
from typing import Any, Protocol
from uuid import NAMESPACE_URL, UUID, uuid5

from .bounded_inherited_reranker import (
    BoundedInheritedRerankerConfig,
    InheritedAwareRerankedMemory,
    InheritedEvidenceDisposition,
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = "nextgen-memory-inherited-rerank-telemetry-v0"
_SCORE_TOLERANCE = 1e-12


class InheritedRerankTelemetryValidationError(ValueError):
    """Telemetry inputs or immutable records violate the v0 contract."""


class InheritedRerankTelemetryConflictError(RuntimeError):
    """One deterministic telemetry identity was reused with different content."""


@dataclass(frozen=True, slots=True)
class InheritedRerankObservation:
    """One aggregate-only observation for a canonical memory."""

    id: UUID
    batch_id: UUID
    space_id: UUID
    router_decision_id: UUID
    memory_id: UUID
    base_rank: int
    base_score: float
    final_rank: int
    final_score: float
    rank_delta: int
    applied_component: float
    uncapped_component: float
    disposition: InheritedEvidenceDisposition
    contribution_count: int
    value_sum: float | None
    absolute_value_sum: float | None
    standard_error_sum: float | None
    minimum_structural_confidence: float | None
    count_shrinkage: float
    path_coherence: float
    uncertainty_reliability: float
    confidence_reliability: float
    policy_version: str
    policy_fingerprint: str
    content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "id",
            "batch_id",
            "space_id",
            "router_decision_id",
            "memory_id",
        ):
            _require_uuid(name, getattr(self, name))
        base_rank = _positive_integer("base_rank", self.base_rank)
        final_rank = _positive_integer("final_rank", self.final_rank)
        rank_delta = _integer("rank_delta", self.rank_delta)
        if rank_delta != base_rank - final_rank:
            raise InheritedRerankTelemetryValidationError(
                "rank_delta must equal base_rank minus final_rank"
            )
        base_score = _finite_number("base_score", self.base_score)
        final_score = _finite_number("final_score", self.final_score)
        applied_component = _finite_number(
            "applied_component", self.applied_component
        )
        uncapped_component = _finite_number(
            "uncapped_component", self.uncapped_component
        )
        if not isinstance(self.disposition, InheritedEvidenceDisposition):
            raise InheritedRerankTelemetryValidationError(
                "disposition must be an InheritedEvidenceDisposition"
            )
        contribution_count = _nonnegative_integer(
            "contribution_count", self.contribution_count
        )
        value_sum = _optional_finite_number("value_sum", self.value_sum)
        absolute_value_sum = _optional_finite_number(
            "absolute_value_sum", self.absolute_value_sum
        )
        standard_error_sum = _optional_finite_number(
            "standard_error_sum", self.standard_error_sum
        )
        minimum_structural_confidence = _optional_probability(
            "minimum_structural_confidence",
            self.minimum_structural_confidence,
        )
        count_shrinkage = _probability(
            "count_shrinkage", self.count_shrinkage
        )
        path_coherence = _probability(
            "path_coherence", self.path_coherence
        )
        uncertainty_reliability = _probability(
            "uncertainty_reliability",
            self.uncertainty_reliability,
        )
        confidence_reliability = _probability(
            "confidence_reliability",
            self.confidence_reliability,
        )
        policy_version = _required_text(
            "policy_version", self.policy_version
        )
        _require_hash("policy_fingerprint", self.policy_fingerprint)
        _require_hash("content_hash", self.content_hash)

        observed_values = (
            value_sum,
            absolute_value_sum,
            standard_error_sum,
            minimum_structural_confidence,
        )
        if contribution_count == 0:
            if any(value is not None for value in observed_values):
                raise InheritedRerankTelemetryValidationError(
                    "zero contribution_count requires null inherited aggregates"
                )
            if self.disposition is not InheritedEvidenceDisposition.NO_EVIDENCE:
                raise InheritedRerankTelemetryValidationError(
                    "zero contribution_count requires no_evidence disposition"
                )
            if applied_component != 0.0 or uncapped_component != 0.0:
                raise InheritedRerankTelemetryValidationError(
                    "no-evidence observation must have zero components"
                )
        else:
            if any(value is None for value in observed_values):
                raise InheritedRerankTelemetryValidationError(
                    "observed inherited evidence requires every aggregate"
                )
            assert value_sum is not None
            assert absolute_value_sum is not None
            assert standard_error_sum is not None
            if absolute_value_sum < 0.0:
                raise InheritedRerankTelemetryValidationError(
                    "absolute_value_sum must be non-negative"
                )
            if absolute_value_sum + _SCORE_TOLERANCE < abs(value_sum):
                raise InheritedRerankTelemetryValidationError(
                    "absolute_value_sum cannot be smaller than abs(value_sum)"
                )
            if standard_error_sum < 0.0:
                raise InheritedRerankTelemetryValidationError(
                    "standard_error_sum must be non-negative"
                )
        if (
            self.disposition is not InheritedEvidenceDisposition.APPLIED
            and applied_component != 0.0
        ):
            raise InheritedRerankTelemetryValidationError(
                "gated inherited evidence must have zero applied_component"
            )

        object.__setattr__(self, "base_rank", base_rank)
        object.__setattr__(self, "base_score", base_score)
        object.__setattr__(self, "final_rank", final_rank)
        object.__setattr__(self, "final_score", final_score)
        object.__setattr__(self, "rank_delta", rank_delta)
        object.__setattr__(self, "applied_component", applied_component)
        object.__setattr__(self, "uncapped_component", uncapped_component)
        object.__setattr__(self, "contribution_count", contribution_count)
        object.__setattr__(self, "value_sum", value_sum)
        object.__setattr__(
            self, "absolute_value_sum", absolute_value_sum
        )
        object.__setattr__(self, "standard_error_sum", standard_error_sum)
        object.__setattr__(
            self,
            "minimum_structural_confidence",
            minimum_structural_confidence,
        )
        object.__setattr__(self, "count_shrinkage", count_shrinkage)
        object.__setattr__(self, "path_coherence", path_coherence)
        object.__setattr__(
            self,
            "uncertainty_reliability",
            uncertainty_reliability,
        )
        object.__setattr__(
            self,
            "confidence_reliability",
            confidence_reliability,
        )
        object.__setattr__(self, "policy_version", policy_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "batch_id": str(self.batch_id),
            "space_id": str(self.space_id),
            "router_decision_id": str(self.router_decision_id),
            "memory_id": str(self.memory_id),
            "base_rank": self.base_rank,
            "base_score": self.base_score,
            "final_rank": self.final_rank,
            "final_score": self.final_score,
            "rank_delta": self.rank_delta,
            "applied_component": self.applied_component,
            "uncapped_component": self.uncapped_component,
            "disposition": self.disposition.value,
            "contribution_count": self.contribution_count,
            "value_sum": self.value_sum,
            "absolute_value_sum": self.absolute_value_sum,
            "standard_error_sum": self.standard_error_sum,
            "minimum_structural_confidence": (
                self.minimum_structural_confidence
            ),
            "count_shrinkage": self.count_shrinkage,
            "path_coherence": self.path_coherence,
            "uncertainty_reliability": self.uncertainty_reliability,
            "confidence_reliability": self.confidence_reliability,
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class InheritedRerankSummary:
    """One deterministic batch-level summary without a combined utility score."""

    candidate_count: int
    applied_count: int
    no_evidence_count: int
    below_minimum_count: int
    below_minimum_confidence: int
    promoted_count: int
    demoted_count: int
    unchanged_count: int
    top_changed: bool
    base_top_memory_id: UUID | None
    final_top_memory_id: UUID | None
    signed_adjustment_sum: float
    absolute_adjustment_sum: float
    maximum_absolute_adjustment_observed: float
    configured_hard_cap: float
    content_hash: str

    def __post_init__(self) -> None:
        counts: dict[str, int] = {}
        for name in (
            "candidate_count",
            "applied_count",
            "no_evidence_count",
            "below_minimum_count",
            "below_minimum_confidence",
            "promoted_count",
            "demoted_count",
            "unchanged_count",
        ):
            counts[name] = _nonnegative_integer(name, getattr(self, name))
        if (
            counts["applied_count"]
            + counts["no_evidence_count"]
            + counts["below_minimum_count"]
            + counts["below_minimum_confidence"]
            != counts["candidate_count"]
        ):
            raise InheritedRerankTelemetryValidationError(
                "disposition counts must partition candidate_count"
            )
        if (
            counts["promoted_count"]
            + counts["demoted_count"]
            + counts["unchanged_count"]
            != counts["candidate_count"]
        ):
            raise InheritedRerankTelemetryValidationError(
                "rank-change counts must partition candidate_count"
            )
        if not isinstance(self.top_changed, bool):
            raise InheritedRerankTelemetryValidationError(
                "top_changed must be a boolean"
            )
        if counts["candidate_count"] == 0:
            if (
                self.base_top_memory_id is not None
                or self.final_top_memory_id is not None
                or self.top_changed
            ):
                raise InheritedRerankTelemetryValidationError(
                    "empty summary requires null top memories and top_changed false"
                )
        else:
            _require_uuid("base_top_memory_id", self.base_top_memory_id)
            _require_uuid("final_top_memory_id", self.final_top_memory_id)
            expected_top_changed = (
                self.base_top_memory_id != self.final_top_memory_id
            )
            if self.top_changed != expected_top_changed:
                raise InheritedRerankTelemetryValidationError(
                    "top_changed does not match top-memory identities"
                )

        signed_adjustment_sum = _finite_number(
            "signed_adjustment_sum", self.signed_adjustment_sum
        )
        absolute_adjustment_sum = _nonnegative_number(
            "absolute_adjustment_sum", self.absolute_adjustment_sum
        )
        maximum_absolute_adjustment_observed = _nonnegative_number(
            "maximum_absolute_adjustment_observed",
            self.maximum_absolute_adjustment_observed,
        )
        configured_hard_cap = _nonnegative_number(
            "configured_hard_cap", self.configured_hard_cap
        )
        if abs(signed_adjustment_sum) > (
            absolute_adjustment_sum + _SCORE_TOLERANCE
        ):
            raise InheritedRerankTelemetryValidationError(
                "absolute adjustment sum is smaller than signed adjustment magnitude"
            )
        if maximum_absolute_adjustment_observed > (
            configured_hard_cap + _SCORE_TOLERANCE
        ):
            raise InheritedRerankTelemetryValidationError(
                "observed adjustment exceeds configured hard cap"
            )
        if maximum_absolute_adjustment_observed > (
            absolute_adjustment_sum + _SCORE_TOLERANCE
        ):
            raise InheritedRerankTelemetryValidationError(
                "maximum adjustment exceeds absolute adjustment sum"
            )
        _require_hash("content_hash", self.content_hash)

        for name, value in counts.items():
            object.__setattr__(self, name, value)
        object.__setattr__(
            self, "signed_adjustment_sum", signed_adjustment_sum
        )
        object.__setattr__(
            self, "absolute_adjustment_sum", absolute_adjustment_sum
        )
        object.__setattr__(
            self,
            "maximum_absolute_adjustment_observed",
            maximum_absolute_adjustment_observed,
        )
        object.__setattr__(self, "configured_hard_cap", configured_hard_cap)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "applied_count": self.applied_count,
            "no_evidence_count": self.no_evidence_count,
            "below_minimum_count": self.below_minimum_count,
            "below_minimum_confidence": self.below_minimum_confidence,
            "promoted_count": self.promoted_count,
            "demoted_count": self.demoted_count,
            "unchanged_count": self.unchanged_count,
            "top_changed": self.top_changed,
            "base_top_memory_id": (
                str(self.base_top_memory_id)
                if self.base_top_memory_id is not None
                else None
            ),
            "final_top_memory_id": (
                str(self.final_top_memory_id)
                if self.final_top_memory_id is not None
                else None
            ),
            "signed_adjustment_sum": self.signed_adjustment_sum,
            "absolute_adjustment_sum": self.absolute_adjustment_sum,
            "maximum_absolute_adjustment_observed": (
                self.maximum_absolute_adjustment_observed
            ),
            "configured_hard_cap": self.configured_hard_cap,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class InheritedRerankTelemetryBatch:
    """One immutable deterministic reranking telemetry batch."""

    id: UUID
    space_id: UUID
    router_decision_id: UUID
    policy_version: str
    policy_fingerprint: str
    observations: tuple[InheritedRerankObservation, ...]
    summary: InheritedRerankSummary
    content_hash: str

    def __post_init__(self) -> None:
        _require_uuid("id", self.id)
        _require_uuid("space_id", self.space_id)
        _require_uuid("router_decision_id", self.router_decision_id)
        policy_version = _required_text(
            "policy_version", self.policy_version
        )
        _require_hash("policy_fingerprint", self.policy_fingerprint)
        observations = tuple(self.observations)
        if any(
            not isinstance(item, InheritedRerankObservation)
            for item in observations
        ):
            raise InheritedRerankTelemetryValidationError(
                "observations must contain InheritedRerankObservation values"
            )
        if not isinstance(self.summary, InheritedRerankSummary):
            raise InheritedRerankTelemetryValidationError(
                "summary must be an InheritedRerankSummary"
            )
        if self.summary.candidate_count != len(observations):
            raise InheritedRerankTelemetryValidationError(
                "summary candidate_count must equal observation count"
            )
        memory_ids = [item.memory_id for item in observations]
        observation_ids = [item.id for item in observations]
        base_ranks = [item.base_rank for item in observations]
        final_ranks = [item.final_rank for item in observations]
        if len(memory_ids) != len(set(memory_ids)):
            raise InheritedRerankTelemetryValidationError(
                "observations contain duplicate memory UUIDs"
            )
        if len(observation_ids) != len(set(observation_ids)):
            raise InheritedRerankTelemetryValidationError(
                "observations contain duplicate observation UUIDs"
            )
        if len(base_ranks) != len(set(base_ranks)):
            raise InheritedRerankTelemetryValidationError(
                "observations contain duplicate base ranks"
            )
        if len(final_ranks) != len(set(final_ranks)):
            raise InheritedRerankTelemetryValidationError(
                "observations contain duplicate final ranks"
            )
        if final_ranks != list(range(1, len(observations) + 1)):
            raise InheritedRerankTelemetryValidationError(
                "observations must be stored in contiguous final-rank order"
            )
        for item in observations:
            if item.batch_id != self.id:
                raise InheritedRerankTelemetryValidationError(
                    "observation batch_id does not match batch id"
                )
            if item.space_id != self.space_id:
                raise InheritedRerankTelemetryValidationError(
                    "observation space does not match batch space"
                )
            if item.router_decision_id != self.router_decision_id:
                raise InheritedRerankTelemetryValidationError(
                    "observation decision does not match batch decision"
                )
            if item.policy_version != policy_version:
                raise InheritedRerankTelemetryValidationError(
                    "observation policy version does not match batch"
                )
            if item.policy_fingerprint != self.policy_fingerprint:
                raise InheritedRerankTelemetryValidationError(
                    "observation policy fingerprint does not match batch"
                )
        _require_hash("content_hash", self.content_hash)
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "observations", observations)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "id": str(self.id),
            "space_id": str(self.space_id),
            "router_decision_id": str(self.router_decision_id),
            "policy_version": self.policy_version,
            "policy_fingerprint": self.policy_fingerprint,
            "observations": [item.to_dict() for item in self.observations],
            "summary": self.summary.to_dict(),
            "content_hash": self.content_hash,
        }

    def render_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


class InheritedRerankTelemetrySink(Protocol):
    """Backend-neutral sink for deterministic telemetry batches."""

    def record(self, batch: InheritedRerankTelemetryBatch) -> None: ...


class InMemoryInheritedRerankTelemetrySink:
    """Idempotent deterministic sink for tests and local experiments."""

    def __init__(self) -> None:
        self._batches: dict[UUID, InheritedRerankTelemetryBatch] = {}

    def record(self, batch: InheritedRerankTelemetryBatch) -> None:
        if not isinstance(batch, InheritedRerankTelemetryBatch):
            raise InheritedRerankTelemetryValidationError(
                "batch must be an InheritedRerankTelemetryBatch"
            )
        existing = self._batches.get(batch.id)
        if existing is None:
            self._batches[batch.id] = batch
            return
        if existing != batch:
            raise InheritedRerankTelemetryConflictError(
                "inherited rerank telemetry batch conflict"
            )

    @property
    def batches(self) -> tuple[InheritedRerankTelemetryBatch, ...]:
        return tuple(
            self._batches[batch_id]
            for batch_id in sorted(self._batches, key=str)
        )


def fingerprint_bounded_inherited_policy(
    config: BoundedInheritedRerankerConfig,
) -> str:
    """Hash every bounded inherited policy field that changes behavior."""

    if not isinstance(config, BoundedInheritedRerankerConfig):
        raise InheritedRerankTelemetryValidationError(
            "config must be a BoundedInheritedRerankerConfig"
        )
    return _hash_payload(_policy_payload(config))


def build_inherited_rerank_telemetry(
    *,
    space_id: UUID,
    router_decision_id: UUID,
    config: BoundedInheritedRerankerConfig,
    results: Sequence[InheritedAwareRerankedMemory],
) -> InheritedRerankTelemetryBatch:
    """Build deterministic aggregate-only telemetry from inherited reranking."""

    _require_uuid("space_id", space_id)
    _require_uuid("router_decision_id", router_decision_id)
    if not isinstance(config, BoundedInheritedRerankerConfig):
        raise InheritedRerankTelemetryValidationError(
            "config must be a BoundedInheritedRerankerConfig"
        )
    normalized_results = tuple(results)
    if any(
        not isinstance(item, InheritedAwareRerankedMemory)
        for item in normalized_results
    ):
        raise InheritedRerankTelemetryValidationError(
            "results must contain InheritedAwareRerankedMemory values"
        )

    candidate_ids = [item.base.hit.memory_id for item in normalized_results]
    if len(candidate_ids) != len(set(candidate_ids)):
        raise InheritedRerankTelemetryValidationError(
            "results contain duplicate candidate memory UUIDs"
        )
    base_ranks = [item.base.final_rank for item in normalized_results]
    final_ranks = [item.final_rank for item in normalized_results]
    _require_contiguous_ranks("base ranks", base_ranks)
    _require_contiguous_ranks("final ranks", final_ranks)

    policy_fingerprint = fingerprint_bounded_inherited_policy(config)
    observation_payloads: list[dict[str, Any]] = []
    for item in normalized_results:
        base_score = _finite_number("base score", item.base.final_score)
        final_score = _finite_number("final score", item.final_score)
        inherited = item.inherited_breakdown
        if inherited.policy_version != config.policy_version:
            raise InheritedRerankTelemetryValidationError(
                "result policy version does not match config policy"
            )
        if abs(inherited.applied_component) > (
            config.maximum_absolute_adjustment + _SCORE_TOLERANCE
        ):
            raise InheritedRerankTelemetryValidationError(
                "applied component exceeds configured cap"
            )
        if not isclose(
            final_score,
            base_score + inherited.applied_component,
            rel_tol=0.0,
            abs_tol=_SCORE_TOLERANCE,
        ):
            raise InheritedRerankTelemetryValidationError(
                "final score violates inherited score equation"
            )
        payload = {
            "space_id": str(space_id),
            "router_decision_id": str(router_decision_id),
            "memory_id": str(item.base.hit.memory_id),
            "base_rank": item.base.final_rank,
            "base_score": base_score,
            "final_rank": item.final_rank,
            "final_score": final_score,
            "rank_delta": item.base.final_rank - item.final_rank,
            "applied_component": inherited.applied_component,
            "uncapped_component": inherited.uncapped_component,
            "disposition": inherited.disposition.value,
            "contribution_count": inherited.contribution_count,
            "value_sum": inherited.value_sum,
            "absolute_value_sum": inherited.absolute_value_sum,
            "standard_error_sum": inherited.standard_error_sum,
            "minimum_structural_confidence": (
                inherited.minimum_structural_confidence
            ),
            "count_shrinkage": inherited.count_shrinkage,
            "path_coherence": inherited.path_coherence,
            "uncertainty_reliability": inherited.uncertainty_reliability,
            "confidence_reliability": inherited.confidence_reliability,
            "policy_version": config.policy_version,
            "policy_fingerprint": policy_fingerprint,
        }
        observation_payloads.append(
            {**payload, "content_hash": _hash_payload(payload)}
        )

    summary_payload = _build_summary_payload(
        normalized_results,
        configured_hard_cap=config.maximum_absolute_adjustment,
    )
    summary_hash = _hash_payload(summary_payload)
    batch_content_hash = _hash_payload(
        {
            "space_id": str(space_id),
            "router_decision_id": str(router_decision_id),
            "policy_version": config.policy_version,
            "policy_fingerprint": policy_fingerprint,
            "observation_hashes": [
                payload["content_hash"]
                for payload in sorted(
                    observation_payloads,
                    key=lambda value: value["memory_id"],
                )
            ],
            "summary_content_hash": summary_hash,
        }
    )
    batch_id = uuid5(
        NAMESPACE_URL,
        f"{_SCHEMA}:{batch_content_hash}",
    )
    observations = tuple(
        sorted(
            (
                _observation_from_payload(
                    payload,
                    batch_id=batch_id,
                )
                for payload in observation_payloads
            ),
            key=lambda item: item.final_rank,
        )
    )
    summary = InheritedRerankSummary(
        candidate_count=summary_payload["candidate_count"],
        applied_count=summary_payload["applied_count"],
        no_evidence_count=summary_payload["no_evidence_count"],
        below_minimum_count=summary_payload["below_minimum_count"],
        below_minimum_confidence=(
            summary_payload["below_minimum_confidence"]
        ),
        promoted_count=summary_payload["promoted_count"],
        demoted_count=summary_payload["demoted_count"],
        unchanged_count=summary_payload["unchanged_count"],
        top_changed=summary_payload["top_changed"],
        base_top_memory_id=(
            UUID(summary_payload["base_top_memory_id"])
            if summary_payload["base_top_memory_id"] is not None
            else None
        ),
        final_top_memory_id=(
            UUID(summary_payload["final_top_memory_id"])
            if summary_payload["final_top_memory_id"] is not None
            else None
        ),
        signed_adjustment_sum=summary_payload["signed_adjustment_sum"],
        absolute_adjustment_sum=(
            summary_payload["absolute_adjustment_sum"]
        ),
        maximum_absolute_adjustment_observed=(
            summary_payload["maximum_absolute_adjustment_observed"]
        ),
        configured_hard_cap=summary_payload["configured_hard_cap"],
        content_hash=summary_hash,
    )
    return InheritedRerankTelemetryBatch(
        id=batch_id,
        space_id=space_id,
        router_decision_id=router_decision_id,
        policy_version=config.policy_version,
        policy_fingerprint=policy_fingerprint,
        observations=observations,
        summary=summary,
        content_hash=batch_content_hash,
    )


def _policy_payload(
    config: BoundedInheritedRerankerConfig,
) -> dict[str, Any]:
    return {
        "inherited_weight": config.inherited_weight,
        "maximum_absolute_adjustment": (
            config.maximum_absolute_adjustment
        ),
        "prior_contribution_count": config.prior_contribution_count,
        "minimum_contribution_count": config.minimum_contribution_count,
        "minimum_structural_confidence": (
            config.minimum_structural_confidence
        ),
        "value_scale": config.value_scale,
        "uncertainty_floor": config.uncertainty_floor,
        "policy_version": config.policy_version,
    }


def _observation_from_payload(
    payload: Mapping[str, Any],
    *,
    batch_id: UUID,
) -> InheritedRerankObservation:
    memory_id = UUID(payload["memory_id"])
    return InheritedRerankObservation(
        id=uuid5(batch_id, f"observation:{memory_id}"),
        batch_id=batch_id,
        space_id=UUID(payload["space_id"]),
        router_decision_id=UUID(payload["router_decision_id"]),
        memory_id=memory_id,
        base_rank=payload["base_rank"],
        base_score=payload["base_score"],
        final_rank=payload["final_rank"],
        final_score=payload["final_score"],
        rank_delta=payload["rank_delta"],
        applied_component=payload["applied_component"],
        uncapped_component=payload["uncapped_component"],
        disposition=InheritedEvidenceDisposition(payload["disposition"]),
        contribution_count=payload["contribution_count"],
        value_sum=payload["value_sum"],
        absolute_value_sum=payload["absolute_value_sum"],
        standard_error_sum=payload["standard_error_sum"],
        minimum_structural_confidence=(
            payload["minimum_structural_confidence"]
        ),
        count_shrinkage=payload["count_shrinkage"],
        path_coherence=payload["path_coherence"],
        uncertainty_reliability=payload["uncertainty_reliability"],
        confidence_reliability=payload["confidence_reliability"],
        policy_version=payload["policy_version"],
        policy_fingerprint=payload["policy_fingerprint"],
        content_hash=payload["content_hash"],
    )


def _build_summary_payload(
    results: Sequence[InheritedAwareRerankedMemory],
    *,
    configured_hard_cap: float,
) -> dict[str, Any]:
    dispositions = [item.inherited_breakdown.disposition for item in results]
    rank_deltas = [item.base.final_rank - item.final_rank for item in results]
    adjustments = [
        item.inherited_breakdown.applied_component for item in results
    ]
    candidate_count = len(results)
    base_top = next(
        (
            item.base.hit.memory_id
            for item in results
            if item.base.final_rank == 1
        ),
        None,
    )
    final_top = next(
        (item.base.hit.memory_id for item in results if item.final_rank == 1),
        None,
    )
    return {
        "candidate_count": candidate_count,
        "applied_count": dispositions.count(
            InheritedEvidenceDisposition.APPLIED
        ),
        "no_evidence_count": dispositions.count(
            InheritedEvidenceDisposition.NO_EVIDENCE
        ),
        "below_minimum_count": dispositions.count(
            InheritedEvidenceDisposition.BELOW_MINIMUM_COUNT
        ),
        "below_minimum_confidence": dispositions.count(
            InheritedEvidenceDisposition.BELOW_MINIMUM_CONFIDENCE
        ),
        "promoted_count": sum(delta > 0 for delta in rank_deltas),
        "demoted_count": sum(delta < 0 for delta in rank_deltas),
        "unchanged_count": sum(delta == 0 for delta in rank_deltas),
        "top_changed": (
            candidate_count > 0 and base_top is not None and base_top != final_top
        ),
        "base_top_memory_id": str(base_top) if base_top is not None else None,
        "final_top_memory_id": (
            str(final_top) if final_top is not None else None
        ),
        "signed_adjustment_sum": sum(adjustments),
        "absolute_adjustment_sum": sum(abs(value) for value in adjustments),
        "maximum_absolute_adjustment_observed": max(
            (abs(value) for value in adjustments),
            default=0.0,
        ),
        "configured_hard_cap": configured_hard_cap,
    }


def _require_contiguous_ranks(name: str, ranks: Sequence[int]) -> None:
    normalized: list[int] = []
    for rank in ranks:
        normalized.append(_positive_integer(name, rank))
    if len(normalized) != len(set(normalized)):
        raise InheritedRerankTelemetryValidationError(
            f"{name} contain duplicate values"
        )
    if sorted(normalized) != list(range(1, len(normalized) + 1)):
        raise InheritedRerankTelemetryValidationError(
            f"{name} must be contiguous"
        )


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise InheritedRerankTelemetryValidationError(
            f"{name} must be a UUID"
        )


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise InheritedRerankTelemetryValidationError(
            f"{name} must be a string"
        )
    normalized = value.strip()
    if not normalized:
        raise InheritedRerankTelemetryValidationError(
            f"{name} must not be empty"
        )
    return normalized


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InheritedRerankTelemetryValidationError(
            f"{name} must be a finite number"
        )
    normalized = float(value)
    if not isfinite(normalized):
        raise InheritedRerankTelemetryValidationError(
            f"{name} must be a finite number"
        )
    return normalized


def _optional_finite_number(name: str, value: object) -> float | None:
    if value is None:
        return None
    return _finite_number(name, value)


def _nonnegative_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized < 0.0:
        raise InheritedRerankTelemetryValidationError(
            f"{name} must be non-negative"
        )
    return normalized


def _probability(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if not 0.0 <= normalized <= 1.0:
        raise InheritedRerankTelemetryValidationError(
            f"{name} must be between zero and one"
        )
    return normalized


def _optional_probability(name: str, value: object) -> float | None:
    if value is None:
        return None
    return _probability(name, value)


def _integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InheritedRerankTelemetryValidationError(
            f"{name} must be an integer"
        )
    return value


def _positive_integer(name: str, value: object) -> int:
    normalized = _integer(name, value)
    if normalized <= 0:
        raise InheritedRerankTelemetryValidationError(
            f"{name} must be a positive integer"
        )
    return normalized


def _nonnegative_integer(name: str, value: object) -> int:
    normalized = _integer(name, value)
    if normalized < 0:
        raise InheritedRerankTelemetryValidationError(
            f"{name} must be a non-negative integer"
        )
    return normalized


def _require_hash(name: str, value: object) -> None:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise InheritedRerankTelemetryValidationError(
            f"{name} must be a lowercase SHA-256 hex digest"
        )
