"""Deterministic persistence records for inherited provenance credit."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from types import MappingProxyType
from typing import Any, Protocol
from uuid import UUID, uuid5

from .provenance_credit import (
    BlockedPropagation,
    DirectCreditEvidence,
    PropagatedCreditContribution,
    PropagationConfig,
    PropagationMassLedger,
    ProvenanceCreditAbstention,
    ProvenanceCreditResult,
    ProvenanceRelationPolicy,
    TypedProvenanceGraph,
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_STATUSES = frozenset({"propagated", "abstained"})
_ALLOWED_OBSERVATION_KINDS = frozenset({"blocked", "abstention"})
_EVALUATION_NAMESPACE = "inherited-credit-evaluation-v0"


class ProvenanceCreditPersistenceValidationError(ValueError):
    """Persistence input violates the inherited-credit ledger contract."""


class ProvenanceCreditPersistenceConflictError(RuntimeError):
    """Stored inherited-credit evidence differs from its immutable payload."""


INHERITED_EVALUATION_INSERT_SQL = """
INSERT INTO ngm.provenance_credit_evaluations (
    id,
    space_id,
    direct_credit_id,
    evidence_group_id,
    root_node_id,
    source_kind,
    direct_value,
    direct_standard_error,
    trial_count,
    context_set_hash,
    continuation_set_hash,
    graph_fingerprint,
    policy_fingerprint,
    policy_version,
    status,
    result_hash,
    content_hash
) VALUES (
    %(id)s,
    %(space_id)s,
    %(direct_credit_id)s,
    %(evidence_group_id)s,
    %(root_node_id)s,
    %(source_kind)s,
    %(direct_value)s,
    %(direct_standard_error)s,
    %(trial_count)s,
    %(context_set_hash)s,
    %(continuation_set_hash)s,
    %(graph_fingerprint)s,
    %(policy_fingerprint)s,
    %(policy_version)s,
    %(status)s,
    %(result_hash)s,
    %(content_hash)s
)
ON CONFLICT (space_id, id) DO NOTHING
""".strip()

INHERITED_EVALUATION_SELECT_SQL = """
SELECT
    id,
    space_id,
    direct_credit_id,
    evidence_group_id,
    root_node_id,
    source_kind,
    direct_value,
    direct_standard_error,
    trial_count,
    context_set_hash,
    continuation_set_hash,
    graph_fingerprint,
    policy_fingerprint,
    policy_version,
    status,
    result_hash,
    content_hash
FROM ngm.provenance_credit_evaluations
WHERE space_id = %(space_id)s
  AND id = ANY(%(ids)s::uuid[])
ORDER BY id
""".strip()

INHERITED_CONTRIBUTION_INSERT_SQL = """
INSERT INTO ngm.inherited_credit_contributions (
    id,
    space_id,
    evaluation_id,
    target_node_id,
    propagated_value,
    propagated_standard_error,
    structural_confidence,
    minimum_edge_confidence,
    depth,
    relation_path,
    edge_path,
    path_fingerprint,
    content_hash
) VALUES (
    %(id)s,
    %(space_id)s,
    %(evaluation_id)s,
    %(target_node_id)s,
    %(propagated_value)s,
    %(propagated_standard_error)s,
    %(structural_confidence)s,
    %(minimum_edge_confidence)s,
    %(depth)s,
    %(relation_path)s,
    %(edge_path)s,
    %(path_fingerprint)s,
    %(content_hash)s
)
ON CONFLICT (space_id, id) DO NOTHING
""".strip()

INHERITED_CONTRIBUTION_SELECT_SQL = """
SELECT
    id,
    space_id,
    evaluation_id,
    target_node_id,
    propagated_value,
    propagated_standard_error,
    structural_confidence,
    minimum_edge_confidence,
    depth,
    relation_path,
    edge_path,
    path_fingerprint,
    content_hash
FROM ngm.inherited_credit_contributions
WHERE space_id = %(space_id)s
  AND id = ANY(%(ids)s::uuid[])
ORDER BY id
""".strip()

INHERITED_OBSERVATION_INSERT_SQL = """
INSERT INTO ngm.provenance_credit_observations (
    id,
    space_id,
    evaluation_id,
    kind,
    current_node_id,
    target_node_id,
    edge_id,
    relation,
    reason,
    depth,
    path_fingerprint,
    content_hash
) VALUES (
    %(id)s,
    %(space_id)s,
    %(evaluation_id)s,
    %(kind)s,
    %(current_node_id)s,
    %(target_node_id)s,
    %(edge_id)s,
    %(relation)s,
    %(reason)s,
    %(depth)s,
    %(path_fingerprint)s,
    %(content_hash)s
)
ON CONFLICT (space_id, id) DO NOTHING
""".strip()

INHERITED_OBSERVATION_SELECT_SQL = """
SELECT
    id,
    space_id,
    evaluation_id,
    kind,
    current_node_id,
    target_node_id,
    edge_id,
    relation,
    reason,
    depth,
    path_fingerprint,
    content_hash
FROM ngm.provenance_credit_observations
WHERE space_id = %(space_id)s
  AND id = ANY(%(ids)s::uuid[])
ORDER BY id
""".strip()

INHERITED_ACCOUNTING_INSERT_SQL = """
INSERT INTO ngm.provenance_credit_accounting (
    id,
    space_id,
    evaluation_id,
    direct_value,
    propagation_budget,
    propagated_value,
    dropped_value,
    unallocated_value,
    conservation_residual,
    content_hash
) VALUES (
    %(id)s,
    %(space_id)s,
    %(evaluation_id)s,
    %(direct_value)s,
    %(propagation_budget)s,
    %(propagated_value)s,
    %(dropped_value)s,
    %(unallocated_value)s,
    %(conservation_residual)s,
    %(content_hash)s
)
ON CONFLICT (space_id, id) DO NOTHING
""".strip()

INHERITED_ACCOUNTING_SELECT_SQL = """
SELECT
    id,
    space_id,
    evaluation_id,
    direct_value,
    propagation_budget,
    propagated_value,
    dropped_value,
    unallocated_value,
    conservation_residual,
    content_hash
FROM ngm.provenance_credit_accounting
WHERE space_id = %(space_id)s
  AND id = ANY(%(ids)s::uuid[])
ORDER BY id
""".strip()


@dataclass(frozen=True, slots=True)
class ProvenanceCreditEvaluationRecord:
    """One immutable direct-credit interpretation under a graph and policy."""

    id: UUID
    space_id: UUID
    direct_credit_id: UUID
    evidence_group_id: UUID
    root_node_id: UUID
    source_kind: str
    direct_value: float
    direct_standard_error: float
    trial_count: int
    context_set_hash: str
    continuation_set_hash: str
    graph_fingerprint: str
    policy_fingerprint: str
    policy_version: str
    status: str
    result_hash: str
    content_hash: str

    def __post_init__(self) -> None:
        for name in (
            "id",
            "space_id",
            "direct_credit_id",
            "evidence_group_id",
            "root_node_id",
        ):
            _require_uuid(name, getattr(self, name))
        source_kind = _required_text("source_kind", self.source_kind)
        direct_value = _finite_number("direct_value", self.direct_value)
        direct_standard_error = _nonnegative_number(
            "direct_standard_error",
            self.direct_standard_error,
        )
        _positive_integer("trial_count", self.trial_count)
        for name in (
            "context_set_hash",
            "continuation_set_hash",
            "graph_fingerprint",
            "policy_fingerprint",
            "result_hash",
            "content_hash",
        ):
            _require_hash(name, getattr(self, name))
        policy_version = _required_text("policy_version", self.policy_version)
        if self.status not in _ALLOWED_STATUSES:
            raise ProvenanceCreditPersistenceValidationError(
                "status is not supported for inherited credit"
            )
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "direct_value", direct_value)
        object.__setattr__(
            self,
            "direct_standard_error",
            direct_standard_error,
        )
        object.__setattr__(self, "policy_version", policy_version)

    def to_db_params(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "space_id": self.space_id,
            "direct_credit_id": self.direct_credit_id,
            "evidence_group_id": self.evidence_group_id,
            "root_node_id": self.root_node_id,
            "source_kind": self.source_kind,
            "direct_value": self.direct_value,
            "direct_standard_error": self.direct_standard_error,
            "trial_count": self.trial_count,
            "context_set_hash": self.context_set_hash,
            "continuation_set_hash": self.continuation_set_hash,
            "graph_fingerprint": self.graph_fingerprint,
            "policy_fingerprint": self.policy_fingerprint,
            "policy_version": self.policy_version,
            "status": self.status,
            "result_hash": self.result_hash,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class InheritedCreditContributionRecord:
    """One immutable path-specific inherited contribution."""

    id: UUID
    space_id: UUID
    evaluation_id: UUID
    target_node_id: UUID
    propagated_value: float
    propagated_standard_error: float
    structural_confidence: float
    minimum_edge_confidence: float
    depth: int
    relation_path: tuple[str, ...]
    edge_path: tuple[UUID, ...]
    path_fingerprint: str
    content_hash: str

    def __post_init__(self) -> None:
        for name in ("id", "space_id", "evaluation_id", "target_node_id"):
            _require_uuid(name, getattr(self, name))
        object.__setattr__(
            self,
            "propagated_value",
            _finite_number("propagated_value", self.propagated_value),
        )
        object.__setattr__(
            self,
            "propagated_standard_error",
            _nonnegative_number(
                "propagated_standard_error",
                self.propagated_standard_error,
            ),
        )
        object.__setattr__(
            self,
            "structural_confidence",
            _probability("structural_confidence", self.structural_confidence),
        )
        object.__setattr__(
            self,
            "minimum_edge_confidence",
            _probability(
                "minimum_edge_confidence",
                self.minimum_edge_confidence,
            ),
        )
        _positive_integer("depth", self.depth)
        relation_path = tuple(
            _required_text("relation_path item", item)
            for item in self.relation_path
        )
        edge_path = tuple(self.edge_path)
        if len(relation_path) != self.depth or len(edge_path) != self.depth:
            raise ProvenanceCreditPersistenceValidationError(
                "contribution path cardinality must equal depth"
            )
        if any(not isinstance(edge_id, UUID) for edge_id in edge_path):
            raise ProvenanceCreditPersistenceValidationError(
                "edge_path must contain UUID values"
            )
        _require_hash("path_fingerprint", self.path_fingerprint)
        _require_hash("content_hash", self.content_hash)
        object.__setattr__(self, "relation_path", relation_path)
        object.__setattr__(self, "edge_path", edge_path)

    def to_db_params(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "space_id": self.space_id,
            "evaluation_id": self.evaluation_id,
            "target_node_id": self.target_node_id,
            "propagated_value": self.propagated_value,
            "propagated_standard_error": self.propagated_standard_error,
            "structural_confidence": self.structural_confidence,
            "minimum_edge_confidence": self.minimum_edge_confidence,
            "depth": self.depth,
            "relation_path": list(self.relation_path),
            "edge_path": list(self.edge_path),
            "path_fingerprint": self.path_fingerprint,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ProvenanceCreditObservationRecord:
    """One immutable blocked-edge or root-abstention observation."""

    id: UUID
    space_id: UUID
    evaluation_id: UUID
    kind: str
    current_node_id: UUID | None
    target_node_id: UUID | None
    edge_id: UUID | None
    relation: str | None
    reason: str
    depth: int | None
    path_fingerprint: str | None
    content_hash: str

    def __post_init__(self) -> None:
        for name in ("id", "space_id", "evaluation_id"):
            _require_uuid(name, getattr(self, name))
        if self.kind not in _ALLOWED_OBSERVATION_KINDS:
            raise ProvenanceCreditPersistenceValidationError(
                "observation kind must be blocked or abstention"
            )
        reason = _required_text("reason", self.reason)
        if self.kind == "blocked":
            for name in ("current_node_id", "target_node_id", "edge_id"):
                _require_uuid(name, getattr(self, name))
            relation = _required_text("relation", self.relation)
            if self.depth is None:
                raise ProvenanceCreditPersistenceValidationError(
                    "blocked observation requires depth"
                )
            _nonnegative_integer("depth", self.depth)
            _require_hash("path_fingerprint", self.path_fingerprint)
            object.__setattr__(self, "relation", relation)
        else:
            if any(
                value is not None
                for value in (
                    self.current_node_id,
                    self.target_node_id,
                    self.edge_id,
                    self.relation,
                    self.depth,
                    self.path_fingerprint,
                )
            ):
                raise ProvenanceCreditPersistenceValidationError(
                    "abstention observation must not carry path fields"
                )
        _require_hash("content_hash", self.content_hash)
        object.__setattr__(self, "reason", reason)

    def to_db_params(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "space_id": self.space_id,
            "evaluation_id": self.evaluation_id,
            "kind": self.kind,
            "current_node_id": self.current_node_id,
            "target_node_id": self.target_node_id,
            "edge_id": self.edge_id,
            "relation": self.relation,
            "reason": self.reason,
            "depth": self.depth,
            "path_fingerprint": self.path_fingerprint,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ProvenanceCreditAccountingRecord:
    """One immutable mass-conservation row per evaluation."""

    id: UUID
    space_id: UUID
    evaluation_id: UUID
    direct_value: float
    propagation_budget: float
    propagated_value: float
    dropped_value: float
    unallocated_value: float
    conservation_residual: float
    content_hash: str

    def __post_init__(self) -> None:
        for name in ("id", "space_id", "evaluation_id"):
            _require_uuid(name, getattr(self, name))
        for name in (
            "direct_value",
            "propagation_budget",
            "propagated_value",
            "dropped_value",
            "unallocated_value",
            "conservation_residual",
        ):
            object.__setattr__(
                self,
                name,
                _finite_number(name, getattr(self, name)),
            )
        _require_hash("content_hash", self.content_hash)

    def to_db_params(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "space_id": self.space_id,
            "evaluation_id": self.evaluation_id,
            "direct_value": self.direct_value,
            "propagation_budget": self.propagation_budget,
            "propagated_value": self.propagated_value,
            "dropped_value": self.dropped_value,
            "unallocated_value": self.unallocated_value,
            "conservation_residual": self.conservation_residual,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class ProvenanceCreditBatch:
    """One complete deterministic inherited-credit persistence batch."""

    graph_fingerprint: str
    policy_fingerprint: str
    direct_credits: tuple[DirectCreditEvidence, ...]
    evaluations: tuple[ProvenanceCreditEvaluationRecord, ...]
    contributions: tuple[InheritedCreditContributionRecord, ...]
    observations: tuple[ProvenanceCreditObservationRecord, ...]
    accounting: tuple[ProvenanceCreditAccountingRecord, ...]

    def __post_init__(self) -> None:
        _require_hash("graph_fingerprint", self.graph_fingerprint)
        _require_hash("policy_fingerprint", self.policy_fingerprint)
        direct_credits = tuple(self.direct_credits)
        evaluations = tuple(self.evaluations)
        contributions = tuple(self.contributions)
        observations = tuple(self.observations)
        accounting = tuple(self.accounting)
        _require_instances(direct_credits, DirectCreditEvidence, "direct credits")
        _require_instances(
            evaluations,
            ProvenanceCreditEvaluationRecord,
            "evaluations",
        )
        _require_instances(
            contributions,
            InheritedCreditContributionRecord,
            "contributions",
        )
        _require_instances(
            observations,
            ProvenanceCreditObservationRecord,
            "observations",
        )
        _require_instances(
            accounting,
            ProvenanceCreditAccountingRecord,
            "accounting",
        )
        for name, records in (
            ("direct credits", direct_credits),
            ("evaluations", evaluations),
            ("contributions", contributions),
            ("observations", observations),
            ("accounting", accounting),
        ):
            identities = [
                record.direct_credit_id
                if isinstance(record, DirectCreditEvidence)
                else record.id
                for record in records
            ]
            if len(identities) != len(set(identities)):
                raise ProvenanceCreditPersistenceValidationError(
                    f"{name} contain duplicate identities"
                )

        spaces = {
            record.space_id
            for record in (*direct_credits, *evaluations, *contributions, *observations, *accounting)
        }
        if len(spaces) > 1:
            raise ProvenanceCreditPersistenceValidationError(
                "inherited credit batch must use one space"
            )
        evaluation_by_id = {record.id: record for record in evaluations}
        evaluation_by_direct = {
            record.direct_credit_id: record for record in evaluations
        }
        if set(evaluation_by_direct) != {
            record.direct_credit_id for record in direct_credits
        }:
            raise ProvenanceCreditPersistenceValidationError(
                "evaluations must cover every direct credit exactly once"
            )
        for record in (*contributions, *observations, *accounting):
            if record.evaluation_id not in evaluation_by_id:
                raise ProvenanceCreditPersistenceValidationError(
                    "child record references an unknown evaluation"
                )
        if {record.evaluation_id for record in accounting} != set(
            evaluation_by_id
        ):
            raise ProvenanceCreditPersistenceValidationError(
                "accounting must cover every evaluation exactly once"
            )
        object.__setattr__(
            self,
            "direct_credits",
            tuple(sorted(direct_credits, key=_direct_sort_key)),
        )
        object.__setattr__(
            self,
            "evaluations",
            tuple(sorted(evaluations, key=lambda item: str(item.id))),
        )
        object.__setattr__(
            self,
            "contributions",
            tuple(sorted(contributions, key=lambda item: str(item.id))),
        )
        object.__setattr__(
            self,
            "observations",
            tuple(sorted(observations, key=lambda item: str(item.id))),
        )
        object.__setattr__(
            self,
            "accounting",
            tuple(sorted(accounting, key=lambda item: str(item.id))),
        )

    @property
    def space_id(self) -> UUID | None:
        if self.evaluations:
            return self.evaluations[0].space_id
        if self.direct_credits:
            return self.direct_credits[0].space_id
        return None

    @property
    def evaluation_map(self) -> Mapping[UUID, ProvenanceCreditEvaluationRecord]:
        return MappingProxyType({record.id: record for record in self.evaluations})


class ProvenanceCreditPersistenceCursor(Protocol):
    """Minimal mapping cursor used by the insert-then-readback writer."""

    def executemany(
        self,
        sql: str,
        rows: list[Mapping[str, Any]],
    ) -> Any: ...

    def execute(self, sql: str, params: Mapping[str, Any]) -> Any: ...

    def fetchall(self) -> Iterable[Mapping[str, Any]]: ...


class ProvenanceCreditPersistenceWriter:
    """Insert a complete batch and verify every immutable stored row."""

    def write(
        self,
        cursor: ProvenanceCreditPersistenceCursor,
        batch: ProvenanceCreditBatch,
    ) -> int:
        if not isinstance(batch, ProvenanceCreditBatch):
            raise ProvenanceCreditPersistenceValidationError(
                "batch must be a ProvenanceCreditBatch"
            )
        if batch.space_id is None:
            return 0
        phases: tuple[
            tuple[
                str,
                str,
                Sequence[Any],
                Any,
            ],
            ...,
        ] = (
            (
                INHERITED_EVALUATION_INSERT_SQL,
                INHERITED_EVALUATION_SELECT_SQL,
                batch.evaluations,
                _normalize_evaluation_row,
            ),
            (
                INHERITED_CONTRIBUTION_INSERT_SQL,
                INHERITED_CONTRIBUTION_SELECT_SQL,
                batch.contributions,
                _normalize_contribution_row,
            ),
            (
                INHERITED_OBSERVATION_INSERT_SQL,
                INHERITED_OBSERVATION_SELECT_SQL,
                batch.observations,
                _normalize_observation_row,
            ),
            (
                INHERITED_ACCOUNTING_INSERT_SQL,
                INHERITED_ACCOUNTING_SELECT_SQL,
                batch.accounting,
                _normalize_accounting_row,
            ),
        )
        written = 0
        for insert_sql, select_sql, records, normalizer in phases:
            if not records:
                continue
            expected = {record.id: record.to_db_params() for record in records}
            cursor.executemany(
                insert_sql,
                [record.to_db_params() for record in records],
            )
            cursor.execute(
                select_sql,
                {
                    "space_id": batch.space_id,
                    "ids": sorted(expected, key=str),
                },
            )
            stored: dict[UUID, dict[str, Any]] = {}
            for raw_row in cursor.fetchall():
                if not isinstance(raw_row, Mapping):
                    raise ProvenanceCreditPersistenceConflictError(
                        "stored inherited credit row is not a mapping"
                    )
                normalized = normalizer(raw_row)
                record_id = normalized["id"]
                if record_id not in expected:
                    raise ProvenanceCreditPersistenceConflictError(
                        "stored inherited credit returned an unexpected ID"
                    )
                if record_id in stored:
                    raise ProvenanceCreditPersistenceConflictError(
                        "stored inherited credit returned a duplicate ID"
                    )
                stored[record_id] = normalized
            missing = set(expected).difference(stored)
            if missing:
                raise ProvenanceCreditPersistenceConflictError(
                    "stored inherited credit is missing deterministic rows"
                )
            for record_id, expected_payload in expected.items():
                if stored[record_id] != expected_payload:
                    raise ProvenanceCreditPersistenceConflictError(
                        "stored inherited credit immutable payload differs"
                    )
            written += len(records)
        return written


def fingerprint_provenance_graph(graph: TypedProvenanceGraph) -> str:
    """Hash the canonical control-plane graph without memory content."""

    if not isinstance(graph, TypedProvenanceGraph):
        raise ProvenanceCreditPersistenceValidationError(
            "graph must be a TypedProvenanceGraph"
        )
    payload = {
        "space_id": str(graph.space_id),
        "nodes": [
            {
                "memory_id": str(node.memory_id),
                "space_id": str(node.space_id),
                "authorized": node.authorized,
                "currently_valid": node.currently_valid,
            }
            for node in graph.nodes
        ],
        "edges": [
            {
                "edge_id": str(edge.edge_id),
                "space_id": str(edge.space_id),
                "from_node_id": str(edge.from_node_id),
                "to_node_id": str(edge.to_node_id),
                "relation": edge.relation,
                "confidence": edge.confidence,
                "local_attribution": edge.local_attribution,
                "evidence_id": (
                    str(edge.evidence_id) if edge.evidence_id is not None else None
                ),
            }
            for edge in graph.edges
        ],
    }
    return _hash_payload(payload)


def fingerprint_provenance_policy(
    policies: Sequence[ProvenanceRelationPolicy],
    config: PropagationConfig,
) -> str:
    """Hash reviewed relation policies plus allocation-changing config."""

    if not isinstance(config, PropagationConfig):
        raise ProvenanceCreditPersistenceValidationError(
            "config must be a PropagationConfig"
        )
    normalized = tuple(policies)
    _require_instances(
        normalized,
        ProvenanceRelationPolicy,
        "policies",
    )
    by_relation: dict[str, ProvenanceRelationPolicy] = {}
    for policy in normalized:
        existing = by_relation.get(policy.relation)
        if existing is not None and existing != policy:
            raise ProvenanceCreditPersistenceValidationError(
                "conflicting policies for one relation"
            )
        by_relation[policy.relation] = policy
    payload = {
        "policies": [
            {
                "relation": policy.relation,
                "direction": policy.direction.value,
                "allow_positive": policy.allow_positive,
                "allow_negative": policy.allow_negative,
                "relation_weight": policy.relation_weight,
                "requires_local_attribution": (
                    policy.requires_local_attribution
                ),
                "maximum_depth": policy.maximum_depth,
            }
            for policy in sorted(
                by_relation.values(),
                key=lambda item: item.relation,
            )
        ],
        "config": {
            "positive_budget_fraction": config.positive_budget_fraction,
            "negative_budget_fraction": config.negative_budget_fraction,
            "transmission_fraction": config.transmission_fraction,
            "maximum_depth": config.maximum_depth,
            "minimum_absolute_mass": config.minimum_absolute_mass,
            "conservation_tolerance": config.conservation_tolerance,
            "policy_version": config.policy_version,
        },
    }
    return _hash_payload(payload)


def build_provenance_credit_batch(
    *,
    graph: TypedProvenanceGraph,
    policies: Sequence[ProvenanceRelationPolicy],
    config: PropagationConfig,
    result: ProvenanceCreditResult,
) -> ProvenanceCreditBatch:
    """Build a complete deterministic persistence batch from a propagation result."""

    if not isinstance(result, ProvenanceCreditResult):
        raise ProvenanceCreditPersistenceValidationError(
            "result must be a ProvenanceCreditResult"
        )
    if not isinstance(config, PropagationConfig):
        raise ProvenanceCreditPersistenceValidationError(
            "config must be a PropagationConfig"
        )
    if result.policy_version != config.policy_version:
        raise ProvenanceCreditPersistenceValidationError(
            "result policy_version does not match propagation config"
        )
    graph_fingerprint = fingerprint_provenance_graph(graph)
    policy_fingerprint = fingerprint_provenance_policy(policies, config)
    node_ids = {node.memory_id for node in graph.nodes}
    edge_ids = {edge.edge_id for edge in graph.edges}

    evaluations: list[ProvenanceCreditEvaluationRecord] = []
    contributions: list[InheritedCreditContributionRecord] = []
    observations: list[ProvenanceCreditObservationRecord] = []
    accounting: list[ProvenanceCreditAccountingRecord] = []

    mass_by_direct = _unique_by_direct(result.mass_ledgers, "mass ledger")
    for direct in result.direct_credits:
        if direct.space_id != graph.space_id:
            raise ProvenanceCreditPersistenceValidationError(
                "direct credit space does not match graph space"
            )
        if direct.root_memory_id not in node_ids:
            raise ProvenanceCreditPersistenceValidationError(
                "direct credit root is absent from graph"
            )
        ledger = mass_by_direct.get(direct.direct_credit_id)
        if ledger is None:
            raise ProvenanceCreditPersistenceValidationError(
                "direct credit is missing mass accounting"
            )
        _validate_mass_ledger(direct, ledger)
        evaluation_id = uuid5(
            direct.direct_credit_id,
            (
                f"{_EVALUATION_NAMESPACE}:"
                f"{graph_fingerprint}:{policy_fingerprint}"
            ),
        )
        direct_contributions = tuple(
            item
            for item in result.contributions
            if item.direct_credit_id == direct.direct_credit_id
        )
        direct_blocks = tuple(
            item
            for item in result.blocked
            if item.direct_credit_id == direct.direct_credit_id
        )
        direct_abstentions = tuple(
            item
            for item in result.abstentions
            if item.direct_credit_id == direct.direct_credit_id
        )
        contribution_records = tuple(
            _build_contribution_record(
                graph.space_id,
                evaluation_id,
                direct,
                item,
                node_ids,
                edge_ids,
            )
            for item in direct_contributions
        )
        observation_records = (
            *(
                _build_block_record(
                    graph.space_id,
                    evaluation_id,
                    direct,
                    item,
                    node_ids,
                    edge_ids,
                )
                for item in direct_blocks
            ),
            *(
                _build_abstention_record(
                    graph.space_id,
                    evaluation_id,
                    direct,
                    item,
                )
                for item in direct_abstentions
            ),
        )
        accounting_record = _build_accounting_record(
            graph.space_id,
            evaluation_id,
            direct,
            ledger,
        )
        evaluation_base = {
            "id": str(evaluation_id),
            "space_id": str(graph.space_id),
            "direct_credit_id": str(direct.direct_credit_id),
            "evidence_group_id": str(direct.evidence_group_id),
            "root_node_id": str(direct.root_memory_id),
            "source_kind": direct.source_kind.value,
            "direct_value": direct.value,
            "direct_standard_error": direct.standard_error,
            "trial_count": direct.trial_count,
            "context_set_hash": direct.context_set_hash,
            "continuation_set_hash": direct.continuation_set_hash,
            "graph_fingerprint": graph_fingerprint,
            "policy_fingerprint": policy_fingerprint,
            "policy_version": config.policy_version,
            "status": "propagated" if contribution_records else "abstained",
        }
        result_hash = _hash_payload(
            {
                "evaluation": evaluation_base,
                "contribution_hashes": sorted(
                    item.content_hash for item in contribution_records
                ),
                "observation_hashes": sorted(
                    item.content_hash for item in observation_records
                ),
                "accounting_hash": accounting_record.content_hash,
            }
        )
        evaluation_payload = {
            **evaluation_base,
            "result_hash": result_hash,
        }
        evaluations.append(
            ProvenanceCreditEvaluationRecord(
                id=evaluation_id,
                space_id=graph.space_id,
                direct_credit_id=direct.direct_credit_id,
                evidence_group_id=direct.evidence_group_id,
                root_node_id=direct.root_memory_id,
                source_kind=direct.source_kind.value,
                direct_value=direct.value,
                direct_standard_error=direct.standard_error,
                trial_count=direct.trial_count,
                context_set_hash=direct.context_set_hash,
                continuation_set_hash=direct.continuation_set_hash,
                graph_fingerprint=graph_fingerprint,
                policy_fingerprint=policy_fingerprint,
                policy_version=config.policy_version,
                status=evaluation_base["status"],
                result_hash=result_hash,
                content_hash=_hash_payload(evaluation_payload),
            )
        )
        contributions.extend(contribution_records)
        observations.extend(observation_records)
        accounting.append(accounting_record)

    known_direct_ids = {
        direct.direct_credit_id for direct in result.direct_credits
    }
    for collection_name, items in (
        ("contribution", result.contributions),
        ("blocked observation", result.blocked),
        ("abstention", result.abstentions),
        ("mass ledger", result.mass_ledgers),
    ):
        unknown = {
            item.direct_credit_id for item in items
        }.difference(known_direct_ids)
        if unknown:
            raise ProvenanceCreditPersistenceValidationError(
                f"result contains {collection_name} for an unknown direct credit"
            )

    return ProvenanceCreditBatch(
        graph_fingerprint=graph_fingerprint,
        policy_fingerprint=policy_fingerprint,
        direct_credits=result.direct_credits,
        evaluations=tuple(evaluations),
        contributions=tuple(contributions),
        observations=tuple(observations),
        accounting=tuple(accounting),
    )


def _build_contribution_record(
    space_id: UUID,
    evaluation_id: UUID,
    direct: DirectCreditEvidence,
    contribution: PropagatedCreditContribution,
    node_ids: set[UUID],
    edge_ids: set[UUID],
) -> InheritedCreditContributionRecord:
    if contribution.root_memory_id != direct.root_memory_id:
        raise ProvenanceCreditPersistenceValidationError(
            "contribution root does not match direct credit"
        )
    if contribution.target_memory_id not in node_ids:
        raise ProvenanceCreditPersistenceValidationError(
            "contribution target is absent from graph"
        )
    if any(edge_id not in edge_ids for edge_id in contribution.edge_path):
        raise ProvenanceCreditPersistenceValidationError(
            "contribution edge path references an unknown graph edge"
        )
    record_id = uuid5(
        evaluation_id,
        f"contribution:{contribution.path_fingerprint}",
    )
    payload = {
        "id": str(record_id),
        "space_id": str(space_id),
        "evaluation_id": str(evaluation_id),
        "target_node_id": str(contribution.target_memory_id),
        "propagated_value": contribution.propagated_value,
        "propagated_standard_error": (
            contribution.propagated_standard_error
        ),
        "structural_confidence": contribution.structural_confidence,
        "minimum_edge_confidence": (
            contribution.minimum_edge_confidence
        ),
        "depth": contribution.depth,
        "relation_path": list(contribution.relation_path),
        "edge_path": [str(edge_id) for edge_id in contribution.edge_path],
        "path_fingerprint": contribution.path_fingerprint,
    }
    return InheritedCreditContributionRecord(
        id=record_id,
        space_id=space_id,
        evaluation_id=evaluation_id,
        target_node_id=contribution.target_memory_id,
        propagated_value=contribution.propagated_value,
        propagated_standard_error=(
            contribution.propagated_standard_error
        ),
        structural_confidence=contribution.structural_confidence,
        minimum_edge_confidence=contribution.minimum_edge_confidence,
        depth=contribution.depth,
        relation_path=contribution.relation_path,
        edge_path=contribution.edge_path,
        path_fingerprint=contribution.path_fingerprint,
        content_hash=_hash_payload(payload),
    )


def _build_block_record(
    space_id: UUID,
    evaluation_id: UUID,
    direct: DirectCreditEvidence,
    blocked: BlockedPropagation,
    node_ids: set[UUID],
    edge_ids: set[UUID],
) -> ProvenanceCreditObservationRecord:
    if blocked.root_memory_id != direct.root_memory_id:
        raise ProvenanceCreditPersistenceValidationError(
            "blocked observation root does not match direct credit"
        )
    if blocked.current_memory_id not in node_ids or blocked.target_memory_id not in node_ids:
        raise ProvenanceCreditPersistenceValidationError(
            "blocked observation node is absent from graph"
        )
    if blocked.edge_id not in edge_ids:
        raise ProvenanceCreditPersistenceValidationError(
            "blocked observation edge is absent from graph"
        )
    record_id = uuid5(
        evaluation_id,
        f"blocked:{blocked.path_fingerprint}:{blocked.reason.value}",
    )
    payload = {
        "id": str(record_id),
        "space_id": str(space_id),
        "evaluation_id": str(evaluation_id),
        "kind": "blocked",
        "current_node_id": str(blocked.current_memory_id),
        "target_node_id": str(blocked.target_memory_id),
        "edge_id": str(blocked.edge_id),
        "relation": blocked.relation,
        "reason": blocked.reason.value,
        "depth": blocked.depth,
        "path_fingerprint": blocked.path_fingerprint,
    }
    return ProvenanceCreditObservationRecord(
        id=record_id,
        space_id=space_id,
        evaluation_id=evaluation_id,
        kind="blocked",
        current_node_id=blocked.current_memory_id,
        target_node_id=blocked.target_memory_id,
        edge_id=blocked.edge_id,
        relation=blocked.relation,
        reason=blocked.reason.value,
        depth=blocked.depth,
        path_fingerprint=blocked.path_fingerprint,
        content_hash=_hash_payload(payload),
    )


def _build_abstention_record(
    space_id: UUID,
    evaluation_id: UUID,
    direct: DirectCreditEvidence,
    abstention: ProvenanceCreditAbstention,
) -> ProvenanceCreditObservationRecord:
    if abstention.root_memory_id != direct.root_memory_id:
        raise ProvenanceCreditPersistenceValidationError(
            "abstention root does not match direct credit"
        )
    record_id = uuid5(
        evaluation_id,
        f"abstention:{abstention.reason.value}",
    )
    payload = {
        "id": str(record_id),
        "space_id": str(space_id),
        "evaluation_id": str(evaluation_id),
        "kind": "abstention",
        "reason": abstention.reason.value,
    }
    return ProvenanceCreditObservationRecord(
        id=record_id,
        space_id=space_id,
        evaluation_id=evaluation_id,
        kind="abstention",
        current_node_id=None,
        target_node_id=None,
        edge_id=None,
        relation=None,
        reason=abstention.reason.value,
        depth=None,
        path_fingerprint=None,
        content_hash=_hash_payload(payload),
    )


def _build_accounting_record(
    space_id: UUID,
    evaluation_id: UUID,
    direct: DirectCreditEvidence,
    ledger: PropagationMassLedger,
) -> ProvenanceCreditAccountingRecord:
    record_id = uuid5(evaluation_id, "mass-ledger")
    payload = {
        "id": str(record_id),
        "space_id": str(space_id),
        "evaluation_id": str(evaluation_id),
        "direct_value": ledger.direct_value,
        "propagation_budget": ledger.propagation_budget,
        "propagated_value": ledger.propagated_value,
        "dropped_value": ledger.dropped_value,
        "unallocated_value": ledger.unallocated_value,
        "conservation_residual": ledger.conservation_residual,
    }
    if ledger.direct_credit_id != direct.direct_credit_id:
        raise ProvenanceCreditPersistenceValidationError(
            "mass ledger direct credit does not match evaluation"
        )
    return ProvenanceCreditAccountingRecord(
        id=record_id,
        space_id=space_id,
        evaluation_id=evaluation_id,
        direct_value=ledger.direct_value,
        propagation_budget=ledger.propagation_budget,
        propagated_value=ledger.propagated_value,
        dropped_value=ledger.dropped_value,
        unallocated_value=ledger.unallocated_value,
        conservation_residual=ledger.conservation_residual,
        content_hash=_hash_payload(payload),
    )


def _validate_mass_ledger(
    direct: DirectCreditEvidence,
    ledger: PropagationMassLedger,
) -> None:
    if ledger.root_memory_id != direct.root_memory_id:
        raise ProvenanceCreditPersistenceValidationError(
            "mass ledger root does not match direct credit"
        )
    if ledger.direct_value != direct.value:
        raise ProvenanceCreditPersistenceValidationError(
            "mass ledger direct value does not match direct credit"
        )


def _unique_by_direct(
    items: Sequence[Any],
    description: str,
) -> dict[UUID, Any]:
    result: dict[UUID, Any] = {}
    for item in items:
        direct_credit_id = item.direct_credit_id
        if direct_credit_id in result:
            raise ProvenanceCreditPersistenceValidationError(
                f"duplicate {description} for one direct credit"
            )
        result[direct_credit_id] = item
    return result


def _normalize_evaluation_row(row: Mapping[str, Any]) -> dict[str, Any]:
    required = tuple(ProvenanceCreditEvaluationRecord.__dataclass_fields__)
    _require_columns(row, required)
    return {
        "id": _parse_uuid("id", row["id"]),
        "space_id": _parse_uuid("space_id", row["space_id"]),
        "direct_credit_id": _parse_uuid(
            "direct_credit_id", row["direct_credit_id"]
        ),
        "evidence_group_id": _parse_uuid(
            "evidence_group_id", row["evidence_group_id"]
        ),
        "root_node_id": _parse_uuid("root_node_id", row["root_node_id"]),
        "source_kind": str(row["source_kind"]),
        "direct_value": float(row["direct_value"]),
        "direct_standard_error": float(row["direct_standard_error"]),
        "trial_count": _parse_int("trial_count", row["trial_count"]),
        "context_set_hash": str(row["context_set_hash"]),
        "continuation_set_hash": str(row["continuation_set_hash"]),
        "graph_fingerprint": str(row["graph_fingerprint"]),
        "policy_fingerprint": str(row["policy_fingerprint"]),
        "policy_version": str(row["policy_version"]),
        "status": str(row["status"]),
        "result_hash": str(row["result_hash"]),
        "content_hash": str(row["content_hash"]),
    }


def _normalize_contribution_row(row: Mapping[str, Any]) -> dict[str, Any]:
    required = tuple(InheritedCreditContributionRecord.__dataclass_fields__)
    _require_columns(row, required)
    return {
        "id": _parse_uuid("id", row["id"]),
        "space_id": _parse_uuid("space_id", row["space_id"]),
        "evaluation_id": _parse_uuid("evaluation_id", row["evaluation_id"]),
        "target_node_id": _parse_uuid("target_node_id", row["target_node_id"]),
        "propagated_value": float(row["propagated_value"]),
        "propagated_standard_error": float(
            row["propagated_standard_error"]
        ),
        "structural_confidence": float(row["structural_confidence"]),
        "minimum_edge_confidence": float(row["minimum_edge_confidence"]),
        "depth": _parse_int("depth", row["depth"]),
        "relation_path": [str(item) for item in row["relation_path"]],
        "edge_path": [
            _parse_uuid("edge_path item", item) for item in row["edge_path"]
        ],
        "path_fingerprint": str(row["path_fingerprint"]),
        "content_hash": str(row["content_hash"]),
    }


def _normalize_observation_row(row: Mapping[str, Any]) -> dict[str, Any]:
    required = tuple(ProvenanceCreditObservationRecord.__dataclass_fields__)
    _require_columns(row, required)
    return {
        "id": _parse_uuid("id", row["id"]),
        "space_id": _parse_uuid("space_id", row["space_id"]),
        "evaluation_id": _parse_uuid("evaluation_id", row["evaluation_id"]),
        "kind": str(row["kind"]),
        "current_node_id": _parse_optional_uuid(
            "current_node_id", row["current_node_id"]
        ),
        "target_node_id": _parse_optional_uuid(
            "target_node_id", row["target_node_id"]
        ),
        "edge_id": _parse_optional_uuid("edge_id", row["edge_id"]),
        "relation": None if row["relation"] is None else str(row["relation"]),
        "reason": str(row["reason"]),
        "depth": (
            None if row["depth"] is None else _parse_int("depth", row["depth"])
        ),
        "path_fingerprint": (
            None
            if row["path_fingerprint"] is None
            else str(row["path_fingerprint"])
        ),
        "content_hash": str(row["content_hash"]),
    }


def _normalize_accounting_row(row: Mapping[str, Any]) -> dict[str, Any]:
    required = tuple(ProvenanceCreditAccountingRecord.__dataclass_fields__)
    _require_columns(row, required)
    return {
        "id": _parse_uuid("id", row["id"]),
        "space_id": _parse_uuid("space_id", row["space_id"]),
        "evaluation_id": _parse_uuid("evaluation_id", row["evaluation_id"]),
        "direct_value": float(row["direct_value"]),
        "propagation_budget": float(row["propagation_budget"]),
        "propagated_value": float(row["propagated_value"]),
        "dropped_value": float(row["dropped_value"]),
        "unallocated_value": float(row["unallocated_value"]),
        "conservation_residual": float(row["conservation_residual"]),
        "content_hash": str(row["content_hash"]),
    }


def _require_columns(row: Mapping[str, Any], columns: Sequence[str]) -> None:
    missing = set(columns).difference(row)
    if missing:
        raise ProvenanceCreditPersistenceConflictError(
            "stored inherited credit row is missing immutable fields"
        )


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _direct_sort_key(item: DirectCreditEvidence) -> tuple[str, str, str]:
    return (
        str(item.evidence_group_id),
        str(item.root_memory_id),
        str(item.direct_credit_id),
    )


def _require_instances(
    values: Sequence[Any],
    expected_type: type[Any],
    description: str,
) -> None:
    if any(not isinstance(item, expected_type) for item in values):
        raise ProvenanceCreditPersistenceValidationError(
            f"{description} contain an unsupported value"
        )


def _require_uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise ProvenanceCreditPersistenceValidationError(
            f"{name} must be a UUID"
        )


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ProvenanceCreditPersistenceValidationError(
            f"{name} must be a string"
        )
    normalized = value.strip()
    if not normalized:
        raise ProvenanceCreditPersistenceValidationError(
            f"{name} must not be empty"
        )
    return normalized


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProvenanceCreditPersistenceValidationError(
            f"{name} must be a finite number"
        )
    normalized = float(value)
    if not isfinite(normalized):
        raise ProvenanceCreditPersistenceValidationError(
            f"{name} must be a finite number"
        )
    return normalized


def _nonnegative_number(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if normalized < 0:
        raise ProvenanceCreditPersistenceValidationError(
            f"{name} must be non-negative"
        )
    return normalized


def _probability(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if not 0.0 <= normalized <= 1.0:
        raise ProvenanceCreditPersistenceValidationError(
            f"{name} must be between zero and one"
        )
    return normalized


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProvenanceCreditPersistenceValidationError(
            f"{name} must be a positive integer"
        )
    return value


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProvenanceCreditPersistenceValidationError(
            f"{name} must be a non-negative integer"
        )
    return value


def _require_hash(name: str, value: object) -> None:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ProvenanceCreditPersistenceValidationError(
            f"{name} must be lowercase SHA-256 hex"
        )


def _parse_uuid(name: str, value: object) -> UUID:
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError, AttributeError) as error:
        raise ProvenanceCreditPersistenceConflictError(
            f"stored {name} must be a UUID"
        ) from error


def _parse_optional_uuid(name: str, value: object) -> UUID | None:
    if value is None:
        return None
    return _parse_uuid(name, value)


def _parse_int(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProvenanceCreditPersistenceConflictError(
            f"stored {name} must be an integer"
        )
    return value
