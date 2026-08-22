"""Typed, mass-conserving propagation of intervention-grounded memory credit."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from types import MappingProxyType
from typing import Any
from uuid import UUID

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_RELATION_RE = re.compile(r"^[a-z][a-z0-9_:-]*$")
_SCHEMA = "nextgen-memory-provenance-credit-v0"


class ProvenanceCreditValidationError(ValueError):
    """Raised when provenance-credit inputs violate a fail-closed contract."""


class CreditSourceKind(StrEnum):
    """Source of a direct, intervention-grounded memory value."""

    CAUSAL = "causal"
    INTERACTION = "interaction"


class PropagationDirection(StrEnum):
    """How a typed relation is traversed from a credited memory."""

    FORWARD = "forward"
    REVERSE = "reverse"
    BLOCKED = "blocked"


class PropagationBlockReason(StrEnum):
    """Why one graph edge was excluded from propagation."""

    POLICY_MISSING = "policy_missing"
    RELATION_BLOCKED = "relation_blocked"
    SIGN_NOT_ALLOWED = "sign_not_allowed"
    LOCAL_ATTRIBUTION_REQUIRED = "local_attribution_required"
    TARGET_UNAUTHORIZED = "target_unauthorized"
    TARGET_INVALID = "target_invalid"
    DEPTH_LIMIT = "depth_limit"
    NON_POSITIVE_WEIGHT = "non_positive_weight"


class ProvenanceCreditAbstentionReason(StrEnum):
    """Why one direct credit produced no inherited contribution."""

    ZERO_DIRECT_CREDIT = "zero_direct_credit"
    NEGATIVE_PROPAGATION_DISABLED = "negative_propagation_disabled"
    NO_ADMISSIBLE_PATH = "no_admissible_path"
    BELOW_MASS_FLOOR = "below_mass_floor"


@dataclass(frozen=True, slots=True)
class ProvenanceNode:
    """Canonical memory identity plus hard authorization and validity gates."""

    memory_id: UUID
    space_id: UUID
    authorized: bool = True
    currently_valid: bool = True

    def __post_init__(self) -> None:
        _require_uuid("memory_id", self.memory_id)
        _require_uuid("space_id", self.space_id)
        _require_bool("authorized", self.authorized)
        _require_bool("currently_valid", self.currently_valid)


@dataclass(frozen=True, slots=True)
class ProvenanceEdge:
    """One immutable typed provenance edge without raw evidence payloads."""

    edge_id: UUID
    space_id: UUID
    from_node_id: UUID
    to_node_id: UUID
    relation: str
    confidence: float = 1.0
    local_attribution: float | None = None
    evidence_id: UUID | None = None

    def __post_init__(self) -> None:
        for name in ("edge_id", "space_id", "from_node_id", "to_node_id"):
            _require_uuid(name, getattr(self, name))
        relation = _normalize_relation(self.relation)
        confidence = _probability("confidence", self.confidence)
        local_attribution = self.local_attribution
        if local_attribution is not None:
            local_attribution = _probability("local_attribution", local_attribution)
            if self.evidence_id is None:
                raise ProvenanceCreditValidationError("local_attribution requires an evidence_id")
        elif self.evidence_id is not None:
            raise ProvenanceCreditValidationError("evidence_id requires local_attribution")
        if self.evidence_id is not None:
            _require_uuid("evidence_id", self.evidence_id)
        object.__setattr__(self, "relation", relation)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "local_attribution", local_attribution)


@dataclass(frozen=True, slots=True)
class ProvenanceRelationPolicy:
    """Explicit propagation semantics for one normalized relation."""

    relation: str
    direction: PropagationDirection
    allow_positive: bool
    allow_negative: bool
    relation_weight: float = 1.0
    requires_local_attribution: bool = False
    maximum_depth: int | None = None

    def __post_init__(self) -> None:
        relation = _normalize_relation(self.relation)
        if not isinstance(self.direction, PropagationDirection):
            raise ProvenanceCreditValidationError("direction must be a PropagationDirection")
        _require_bool("allow_positive", self.allow_positive)
        _require_bool("allow_negative", self.allow_negative)
        relation_weight = _probability("relation_weight", self.relation_weight)
        _require_bool("requires_local_attribution", self.requires_local_attribution)
        if self.maximum_depth is not None:
            _positive_integer("maximum_depth", self.maximum_depth)
        if self.direction is PropagationDirection.BLOCKED and (
            self.allow_positive or self.allow_negative
        ):
            raise ProvenanceCreditValidationError("blocked relation policy cannot allow credit")
        if self.allow_negative and not self.requires_local_attribution:
            raise ProvenanceCreditValidationError(
                "negative-credit policies require local attribution"
            )
        object.__setattr__(self, "relation", relation)
        object.__setattr__(self, "relation_weight", relation_weight)


@dataclass(frozen=True, slots=True)
class DirectCreditEvidence:
    """One direct memory value from a matched causal or interaction experiment."""

    direct_credit_id: UUID
    evidence_group_id: UUID
    space_id: UUID
    root_memory_id: UUID
    source_kind: CreditSourceKind
    value: float
    standard_error: float
    trial_count: int
    context_set_hash: str
    continuation_set_hash: str

    def __post_init__(self) -> None:
        for name in (
            "direct_credit_id",
            "evidence_group_id",
            "space_id",
            "root_memory_id",
        ):
            _require_uuid(name, getattr(self, name))
        if not isinstance(self.source_kind, CreditSourceKind):
            raise ProvenanceCreditValidationError("source_kind must be a CreditSourceKind")
        value = _finite_number("value", self.value)
        standard_error = _finite_number("standard_error", self.standard_error)
        if standard_error < 0:
            raise ProvenanceCreditValidationError("standard_error must be non-negative")
        _positive_integer("trial_count", self.trial_count)
        _require_hash("context_set_hash", self.context_set_hash)
        _require_hash("continuation_set_hash", self.continuation_set_hash)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "standard_error", standard_error)


@dataclass(frozen=True, slots=True)
class PropagationConfig:
    """Conservative global controls for inherited utility propagation."""

    positive_budget_fraction: float = 0.50
    negative_budget_fraction: float = 0.00
    transmission_fraction: float = 0.50
    maximum_depth: int = 4
    minimum_absolute_mass: float = 0.0001
    conservation_tolerance: float = 1e-12
    policy_version: str = "provenance-credit-v0"

    def __post_init__(self) -> None:
        for name in (
            "positive_budget_fraction",
            "negative_budget_fraction",
            "transmission_fraction",
        ):
            object.__setattr__(self, name, _probability(name, getattr(self, name)))
        _positive_integer("maximum_depth", self.maximum_depth)
        minimum_absolute_mass = _finite_number("minimum_absolute_mass", self.minimum_absolute_mass)
        conservation_tolerance = _finite_number(
            "conservation_tolerance", self.conservation_tolerance
        )
        if minimum_absolute_mass < 0:
            raise ProvenanceCreditValidationError("minimum_absolute_mass must be non-negative")
        if conservation_tolerance < 0:
            raise ProvenanceCreditValidationError("conservation_tolerance must be non-negative")
        policy_version = _required_text("policy_version", self.policy_version)
        object.__setattr__(self, "minimum_absolute_mass", minimum_absolute_mass)
        object.__setattr__(self, "conservation_tolerance", conservation_tolerance)
        object.__setattr__(self, "policy_version", policy_version)


@dataclass(frozen=True, slots=True)
class PropagatedCreditContribution:
    """One path-specific inherited contribution retained at a target memory."""

    direct_credit_id: UUID
    root_memory_id: UUID
    target_memory_id: UUID
    propagated_value: float
    propagated_standard_error: float
    structural_confidence: float
    minimum_edge_confidence: float
    depth: int
    relation_path: tuple[str, ...]
    edge_path: tuple[UUID, ...]
    path_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "direct_credit_id",
            "root_memory_id",
            "target_memory_id",
        ):
            _require_uuid(name, getattr(self, name))
        for name in (
            "propagated_value",
            "propagated_standard_error",
            "structural_confidence",
            "minimum_edge_confidence",
        ):
            _finite_number(name, getattr(self, name))
        if self.propagated_standard_error < 0:
            raise ProvenanceCreditValidationError("propagated_standard_error must be non-negative")
        _probability("structural_confidence", self.structural_confidence)
        _probability("minimum_edge_confidence", self.minimum_edge_confidence)
        _positive_integer("depth", self.depth)
        if len(self.relation_path) != self.depth:
            raise ProvenanceCreditValidationError("relation_path length must equal depth")
        if len(self.edge_path) != self.depth:
            raise ProvenanceCreditValidationError("edge_path length must equal depth")
        if any(_normalize_relation(item) != item for item in self.relation_path):
            raise ProvenanceCreditValidationError("relation_path must contain normalized relations")
        if any(not isinstance(edge_id, UUID) for edge_id in self.edge_path):
            raise ProvenanceCreditValidationError("edge_path must contain UUID values")
        _require_hash("path_fingerprint", self.path_fingerprint)


@dataclass(frozen=True, slots=True)
class PropagatedTargetCredit:
    """Conservative aggregation of paths for one direct-credit target pair."""

    direct_credit_id: UUID
    root_memory_id: UUID
    target_memory_id: UUID
    propagated_value: float
    propagated_standard_error: float
    path_count: int

    def __post_init__(self) -> None:
        for name in (
            "direct_credit_id",
            "root_memory_id",
            "target_memory_id",
        ):
            _require_uuid(name, getattr(self, name))
        _finite_number("propagated_value", self.propagated_value)
        standard_error = _finite_number("propagated_standard_error", self.propagated_standard_error)
        if standard_error < 0:
            raise ProvenanceCreditValidationError("propagated_standard_error must be non-negative")
        _positive_integer("path_count", self.path_count)


@dataclass(frozen=True, slots=True)
class BlockedPropagation:
    """One policy or hard-gate exclusion encountered during traversal."""

    direct_credit_id: UUID
    root_memory_id: UUID
    current_memory_id: UUID
    target_memory_id: UUID
    edge_id: UUID
    relation: str
    reason: PropagationBlockReason
    depth: int
    path_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "direct_credit_id",
            "root_memory_id",
            "current_memory_id",
            "target_memory_id",
            "edge_id",
        ):
            _require_uuid(name, getattr(self, name))
        if not isinstance(self.reason, PropagationBlockReason):
            raise ProvenanceCreditValidationError("reason must be a PropagationBlockReason")
        relation = _normalize_relation(self.relation)
        _nonnegative_integer("depth", self.depth)
        _require_hash("path_fingerprint", self.path_fingerprint)
        object.__setattr__(self, "relation", relation)


@dataclass(frozen=True, slots=True)
class ProvenanceCreditAbstention:
    """Explicit reason one direct signal produced no inherited contribution."""

    direct_credit_id: UUID
    root_memory_id: UUID
    reason: ProvenanceCreditAbstentionReason

    def __post_init__(self) -> None:
        _require_uuid("direct_credit_id", self.direct_credit_id)
        _require_uuid("root_memory_id", self.root_memory_id)
        if not isinstance(self.reason, ProvenanceCreditAbstentionReason):
            raise ProvenanceCreditValidationError(
                "reason must be a ProvenanceCreditAbstentionReason"
            )


@dataclass(frozen=True, slots=True)
class PropagationMassLedger:
    """Signed conservation accounting for one direct credit."""

    direct_credit_id: UUID
    root_memory_id: UUID
    direct_value: float
    propagation_budget: float
    propagated_value: float
    dropped_value: float
    unallocated_value: float
    conservation_residual: float

    def __post_init__(self) -> None:
        _require_uuid("direct_credit_id", self.direct_credit_id)
        _require_uuid("root_memory_id", self.root_memory_id)
        for name in (
            "direct_value",
            "propagation_budget",
            "propagated_value",
            "dropped_value",
            "unallocated_value",
            "conservation_residual",
        ):
            _finite_number(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class TypedProvenanceGraph:
    """Canonical typed graph; relation policies are supplied separately."""

    nodes: tuple[ProvenanceNode, ...]
    edges: tuple[ProvenanceEdge, ...]

    def __post_init__(self) -> None:
        nodes = tuple(self.nodes)
        edges = tuple(self.edges)
        if not nodes:
            raise ProvenanceCreditValidationError("provenance graph requires at least one node")
        if any(not isinstance(item, ProvenanceNode) for item in nodes):
            raise ProvenanceCreditValidationError("nodes must contain ProvenanceNode instances")
        if any(not isinstance(item, ProvenanceEdge) for item in edges):
            raise ProvenanceCreditValidationError("edges must contain ProvenanceEdge instances")

        node_ids = [item.memory_id for item in nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ProvenanceCreditValidationError("duplicate provenance node memory_id")
        spaces = {item.space_id for item in nodes}
        if len(spaces) != 1:
            raise ProvenanceCreditValidationError("provenance nodes must share one space")
        space_id = next(iter(spaces))
        known = set(node_ids)

        edge_ids = [item.edge_id for item in edges]
        if len(edge_ids) != len(set(edge_ids)):
            raise ProvenanceCreditValidationError("duplicate provenance edge_id")
        for item in edges:
            if item.space_id != space_id:
                raise ProvenanceCreditValidationError(
                    "provenance edge space does not match graph space"
                )
            if item.from_node_id not in known or item.to_node_id not in known:
                raise ProvenanceCreditValidationError("provenance edge references an unknown node")
            if item.from_node_id == item.to_node_id:
                raise ProvenanceCreditValidationError("provenance self-edge is not allowed")

        object.__setattr__(
            self,
            "nodes",
            tuple(sorted(nodes, key=lambda item: str(item.memory_id))),
        )
        object.__setattr__(
            self,
            "edges",
            tuple(sorted(edges, key=_edge_sort_key)),
        )

    @property
    def space_id(self) -> UUID:
        return self.nodes[0].space_id

    @property
    def node_map(self) -> Mapping[UUID, ProvenanceNode]:
        return MappingProxyType({item.memory_id: item for item in self.nodes})


@dataclass(frozen=True, slots=True)
class ProvenanceCreditResult:
    """Direct evidence, inherited paths, exclusions, and conservation evidence."""

    policy_version: str
    direct_credits: tuple[DirectCreditEvidence, ...]
    contributions: tuple[PropagatedCreditContribution, ...]
    target_credits: tuple[PropagatedTargetCredit, ...]
    blocked: tuple[BlockedPropagation, ...]
    abstentions: tuple[ProvenanceCreditAbstention, ...]
    mass_ledgers: tuple[PropagationMassLedger, ...]

    def __post_init__(self) -> None:
        policy_version = _required_text("policy_version", self.policy_version)
        direct_credits = tuple(self.direct_credits)
        contributions = tuple(self.contributions)
        target_credits = tuple(self.target_credits)
        blocked = tuple(self.blocked)
        abstentions = tuple(self.abstentions)
        mass_ledgers = tuple(self.mass_ledgers)
        direct_ids = [item.direct_credit_id for item in direct_credits]
        if len(direct_ids) != len(set(direct_ids)):
            raise ProvenanceCreditValidationError("result direct credits must have unique IDs")
        if {item.direct_credit_id for item in mass_ledgers} != set(direct_ids):
            raise ProvenanceCreditValidationError(
                "mass ledgers must cover every direct credit exactly once"
            )
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "direct_credits", direct_credits)
        object.__setattr__(self, "contributions", contributions)
        object.__setattr__(self, "target_credits", target_credits)
        object.__setattr__(self, "blocked", blocked)
        object.__setattr__(self, "abstentions", abstentions)
        object.__setattr__(self, "mass_ledgers", mass_ledgers)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _SCHEMA,
            "policy_version": self.policy_version,
            "direct_credits": [
                {
                    "direct_credit_id": str(item.direct_credit_id),
                    "evidence_group_id": str(item.evidence_group_id),
                    "space_id": str(item.space_id),
                    "root_memory_id": str(item.root_memory_id),
                    "source_kind": item.source_kind.value,
                    "value": item.value,
                    "standard_error": item.standard_error,
                    "trial_count": item.trial_count,
                    "context_set_hash": item.context_set_hash,
                    "continuation_set_hash": item.continuation_set_hash,
                }
                for item in self.direct_credits
            ],
            "contributions": [
                {
                    "direct_credit_id": str(item.direct_credit_id),
                    "root_memory_id": str(item.root_memory_id),
                    "target_memory_id": str(item.target_memory_id),
                    "propagated_value": item.propagated_value,
                    "propagated_standard_error": (item.propagated_standard_error),
                    "structural_confidence": item.structural_confidence,
                    "minimum_edge_confidence": (item.minimum_edge_confidence),
                    "depth": item.depth,
                    "relation_path": list(item.relation_path),
                    "edge_path": [str(edge_id) for edge_id in item.edge_path],
                    "path_fingerprint": item.path_fingerprint,
                }
                for item in self.contributions
            ],
            "target_credits": [
                {
                    "direct_credit_id": str(item.direct_credit_id),
                    "root_memory_id": str(item.root_memory_id),
                    "target_memory_id": str(item.target_memory_id),
                    "propagated_value": item.propagated_value,
                    "propagated_standard_error": (item.propagated_standard_error),
                    "path_count": item.path_count,
                }
                for item in self.target_credits
            ],
            "blocked": [
                {
                    "direct_credit_id": str(item.direct_credit_id),
                    "root_memory_id": str(item.root_memory_id),
                    "current_memory_id": str(item.current_memory_id),
                    "target_memory_id": str(item.target_memory_id),
                    "edge_id": str(item.edge_id),
                    "relation": item.relation,
                    "reason": item.reason.value,
                    "depth": item.depth,
                    "path_fingerprint": item.path_fingerprint,
                }
                for item in self.blocked
            ],
            "abstentions": [
                {
                    "direct_credit_id": str(item.direct_credit_id),
                    "root_memory_id": str(item.root_memory_id),
                    "reason": item.reason.value,
                }
                for item in self.abstentions
            ],
            "mass_ledgers": [
                {
                    "direct_credit_id": str(item.direct_credit_id),
                    "root_memory_id": str(item.root_memory_id),
                    "direct_value": item.direct_value,
                    "propagation_budget": item.propagation_budget,
                    "propagated_value": item.propagated_value,
                    "dropped_value": item.dropped_value,
                    "unallocated_value": item.unallocated_value,
                    "conservation_residual": item.conservation_residual,
                }
                for item in self.mass_ledgers
            ],
        }

    def render_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class _PathState:
    current_memory_id: UUID
    mass: float
    depth: int
    relation_path: tuple[str, ...]
    edge_path: tuple[UUID, ...]
    structural_confidence: float
    minimum_edge_confidence: float


@dataclass(frozen=True, slots=True)
class _TraversalEdge:
    edge: ProvenanceEdge
    target_memory_id: UUID
    policy: ProvenanceRelationPolicy
    weight: float


class ConservativeProvenancePropagator:
    """Propagate direct credit through explicit typed policies without creating mass."""

    def __init__(self, config: PropagationConfig | None = None) -> None:
        self.config = config or PropagationConfig()

    def propagate(
        self,
        graph: TypedProvenanceGraph,
        direct_credits: Sequence[DirectCreditEvidence],
        policies: Sequence[ProvenanceRelationPolicy],
    ) -> ProvenanceCreditResult:
        if not isinstance(graph, TypedProvenanceGraph):
            raise ProvenanceCreditValidationError("graph must be a TypedProvenanceGraph")
        selected = select_preferred_direct_credits(direct_credits)
        policy_map = _normalize_policies(policies)
        node_map = graph.node_map

        contributions: list[PropagatedCreditContribution] = []
        blocked: list[BlockedPropagation] = []
        abstentions: list[ProvenanceCreditAbstention] = []
        ledgers: list[PropagationMassLedger] = []

        for direct in selected:
            if direct.space_id != graph.space_id:
                raise ProvenanceCreditValidationError(
                    "direct credit space does not match provenance graph space"
                )
            root = node_map.get(direct.root_memory_id)
            if root is None:
                raise ProvenanceCreditValidationError(
                    "direct credit root is absent from provenance graph"
                )
            if not root.authorized or not root.currently_valid:
                raise ProvenanceCreditValidationError(
                    "direct credit root must be authorized and currently valid"
                )

            positive = direct.value > 0
            _validate_oriented_acyclic_graph(
                graph,
                policy_map,
                positive=positive,
            )
            result = self._propagate_one(
                graph,
                node_map,
                policy_map,
                direct,
            )
            contributions.extend(result[0])
            blocked.extend(result[1])
            abstentions.extend(result[2])
            ledgers.append(result[3])

        contributions_tuple = tuple(sorted(contributions, key=_contribution_sort_key))
        target_credits = _summarize_targets(contributions_tuple)
        return ProvenanceCreditResult(
            policy_version=self.config.policy_version,
            direct_credits=selected,
            contributions=contributions_tuple,
            target_credits=target_credits,
            blocked=tuple(sorted(blocked, key=_blocked_sort_key)),
            abstentions=tuple(sorted(abstentions, key=_abstention_sort_key)),
            mass_ledgers=tuple(sorted(ledgers, key=_ledger_sort_key)),
        )

    def _propagate_one(
        self,
        graph: TypedProvenanceGraph,
        node_map: Mapping[UUID, ProvenanceNode],
        policy_map: Mapping[str, ProvenanceRelationPolicy],
        direct: DirectCreditEvidence,
    ) -> tuple[
        list[PropagatedCreditContribution],
        list[BlockedPropagation],
        list[ProvenanceCreditAbstention],
        PropagationMassLedger,
    ]:
        if direct.value > 0:
            budget = direct.value * self.config.positive_budget_fraction
        elif direct.value < 0:
            budget = direct.value * self.config.negative_budget_fraction
        else:
            budget = 0.0

        contributions: list[PropagatedCreditContribution] = []
        blocked: list[BlockedPropagation] = []
        abstentions: list[ProvenanceCreditAbstention] = []
        dropped = 0.0
        unallocated = 0.0

        if direct.value == 0.0:
            abstentions.append(
                ProvenanceCreditAbstention(
                    direct_credit_id=direct.direct_credit_id,
                    root_memory_id=direct.root_memory_id,
                    reason=(ProvenanceCreditAbstentionReason.ZERO_DIRECT_CREDIT),
                )
            )
        elif direct.value < 0 and self.config.negative_budget_fraction == 0.0:
            abstentions.append(
                ProvenanceCreditAbstention(
                    direct_credit_id=direct.direct_credit_id,
                    root_memory_id=direct.root_memory_id,
                    reason=(ProvenanceCreditAbstentionReason.NEGATIVE_PROPAGATION_DISABLED),
                )
            )
        elif budget != 0.0:
            state = _PathState(
                current_memory_id=direct.root_memory_id,
                mass=budget,
                depth=0,
                relation_path=(),
                edge_path=(),
                structural_confidence=1.0,
                minimum_edge_confidence=1.0,
            )

            def retain(current: _PathState, value: float) -> None:
                nonlocal dropped
                if value == 0.0:
                    return
                if abs(value) < self.config.minimum_absolute_mass:
                    dropped += value
                    return
                contributions.append(_contribution(direct, current, value))

            def visit(current: _PathState) -> None:
                nonlocal dropped, unallocated
                if current.depth >= self.config.maximum_depth:
                    if current.depth == 0:
                        unallocated += current.mass
                    else:
                        retain(current, current.mass)
                    return

                outgoing, exclusions = _outgoing_edges(
                    graph,
                    node_map,
                    policy_map,
                    direct,
                    current,
                    self.config,
                )
                blocked.extend(exclusions)
                if not outgoing:
                    if current.depth == 0:
                        unallocated += current.mass
                    else:
                        retain(current, current.mass)
                    return

                if current.depth == 0:
                    retained = 0.0
                    transmitted = current.mass
                else:
                    transmitted = current.mass * self.config.transmission_fraction
                    retained = current.mass - transmitted
                retain(current, retained)

                total_weight = sum(item.weight for item in outgoing)
                if total_weight <= 0:
                    if current.depth == 0:
                        unallocated += transmitted
                    else:
                        retain(current, transmitted)
                    return
                for traversal in outgoing:
                    share = transmitted * traversal.weight / total_weight
                    if share == 0.0:
                        continue
                    if abs(share) < self.config.minimum_absolute_mass:
                        dropped += share
                        continue
                    edge = traversal.edge
                    visit(
                        _PathState(
                            current_memory_id=traversal.target_memory_id,
                            mass=share,
                            depth=current.depth + 1,
                            relation_path=(
                                *current.relation_path,
                                edge.relation,
                            ),
                            edge_path=(*current.edge_path, edge.edge_id),
                            structural_confidence=(current.structural_confidence * edge.confidence),
                            minimum_edge_confidence=min(
                                current.minimum_edge_confidence,
                                edge.confidence,
                            ),
                        )
                    )

            visit(state)

        propagated = sum(item.propagated_value for item in contributions)
        residual = budget - propagated - dropped - unallocated
        if abs(residual) > self.config.conservation_tolerance:
            raise ProvenanceCreditValidationError(
                "propagation mass conservation residual exceeds tolerance"
            )
        if not contributions and not abstentions:
            reason = (
                ProvenanceCreditAbstentionReason.BELOW_MASS_FLOOR
                if dropped != 0.0 and unallocated == 0.0
                else ProvenanceCreditAbstentionReason.NO_ADMISSIBLE_PATH
            )
            abstentions.append(
                ProvenanceCreditAbstention(
                    direct_credit_id=direct.direct_credit_id,
                    root_memory_id=direct.root_memory_id,
                    reason=reason,
                )
            )

        ledger = PropagationMassLedger(
            direct_credit_id=direct.direct_credit_id,
            root_memory_id=direct.root_memory_id,
            direct_value=direct.value,
            propagation_budget=budget,
            propagated_value=propagated,
            dropped_value=dropped,
            unallocated_value=unallocated,
            conservation_residual=residual,
        )
        return contributions, blocked, abstentions, ledger


def select_preferred_direct_credits(
    candidates: Sequence[DirectCreditEvidence],
) -> tuple[DirectCreditEvidence, ...]:
    """Choose interaction over causal evidence per experiment without summing values."""

    normalized = tuple(candidates)
    if any(not isinstance(item, DirectCreditEvidence) for item in normalized):
        raise ProvenanceCreditValidationError(
            "direct credits must contain DirectCreditEvidence instances"
        )
    groups: dict[
        tuple[UUID, UUID, UUID],
        list[DirectCreditEvidence],
    ] = {}
    for item in normalized:
        key = (item.space_id, item.root_memory_id, item.evidence_group_id)
        groups.setdefault(key, []).append(item)

    selected: list[DirectCreditEvidence] = []
    for key in sorted(groups, key=_direct_group_sort_key):
        group = groups[key]
        context_hashes = {item.context_set_hash for item in group}
        continuation_hashes = {item.continuation_set_hash for item in group}
        if len(context_hashes) != 1 or len(continuation_hashes) != 1:
            raise ProvenanceCreditValidationError(
                "direct evidence group has conflicting matched fingerprints"
            )

        unique: list[DirectCreditEvidence] = []
        for item in group:
            if item not in unique:
                unique.append(item)
        preferred_kind = (
            CreditSourceKind.INTERACTION
            if any(item.source_kind is CreditSourceKind.INTERACTION for item in unique)
            else CreditSourceKind.CAUSAL
        )
        preferred = [item for item in unique if item.source_kind is preferred_kind]
        if len(preferred) != 1:
            raise ProvenanceCreditValidationError(
                "conflicting direct credit evidence at the same priority"
            )
        selected.append(preferred[0])

    return tuple(sorted(selected, key=_direct_credit_sort_key))


def project_relation_policies_v0() -> tuple[ProvenanceRelationPolicy, ...]:
    """Explicit initial policies for the heterogeneous live project graph."""

    blocked_relations = (
        "authorizes",
        "constrained_by",
        "explains",
        "followed_by",
        "implements",
        "motivates",
        "superseded_by",
    )
    values = [
        ProvenanceRelationPolicy(
            relation="supported_by",
            direction=PropagationDirection.FORWARD,
            allow_positive=True,
            allow_negative=False,
            relation_weight=1.0,
            requires_local_attribution=False,
        )
    ]
    values.extend(
        ProvenanceRelationPolicy(
            relation=relation,
            direction=PropagationDirection.BLOCKED,
            allow_positive=False,
            allow_negative=False,
            relation_weight=0.0,
            requires_local_attribution=False,
        )
        for relation in blocked_relations
    )
    return tuple(sorted(values, key=lambda item: item.relation))


def _normalize_policies(
    policies: Sequence[ProvenanceRelationPolicy],
) -> Mapping[str, ProvenanceRelationPolicy]:
    normalized = tuple(policies)
    if any(not isinstance(item, ProvenanceRelationPolicy) for item in normalized):
        raise ProvenanceCreditValidationError(
            "policies must contain ProvenanceRelationPolicy instances"
        )
    result: dict[str, ProvenanceRelationPolicy] = {}
    for item in normalized:
        existing = result.get(item.relation)
        if existing is not None and existing != item:
            raise ProvenanceCreditValidationError("conflicting policies for one relation")
        result[item.relation] = item
    return MappingProxyType(dict(sorted(result.items())))


def _outgoing_edges(
    graph: TypedProvenanceGraph,
    node_map: Mapping[UUID, ProvenanceNode],
    policy_map: Mapping[str, ProvenanceRelationPolicy],
    direct: DirectCreditEvidence,
    state: _PathState,
    config: PropagationConfig,
) -> tuple[tuple[_TraversalEdge, ...], tuple[BlockedPropagation, ...]]:
    outgoing: list[_TraversalEdge] = []
    blocked: list[BlockedPropagation] = []
    positive = direct.value > 0

    for edge in graph.edges:
        policy = policy_map.get(edge.relation)
        if policy is None:
            if edge.from_node_id == state.current_memory_id:
                blocked.append(
                    _blocked(
                        direct,
                        state,
                        edge,
                        edge.to_node_id,
                        PropagationBlockReason.POLICY_MISSING,
                    )
                )
            continue
        if policy.direction is PropagationDirection.BLOCKED:
            if edge.from_node_id == state.current_memory_id:
                blocked.append(
                    _blocked(
                        direct,
                        state,
                        edge,
                        edge.to_node_id,
                        PropagationBlockReason.RELATION_BLOCKED,
                    )
                )
            continue

        source, target = _oriented_endpoints(edge, policy.direction)
        if source != state.current_memory_id:
            continue
        next_depth = state.depth + 1
        if next_depth > config.maximum_depth or (
            policy.maximum_depth is not None and next_depth > policy.maximum_depth
        ):
            blocked.append(
                _blocked(
                    direct,
                    state,
                    edge,
                    target,
                    PropagationBlockReason.DEPTH_LIMIT,
                )
            )
            continue
        if (positive and not policy.allow_positive) or (not positive and not policy.allow_negative):
            blocked.append(
                _blocked(
                    direct,
                    state,
                    edge,
                    target,
                    PropagationBlockReason.SIGN_NOT_ALLOWED,
                )
            )
            continue
        if policy.requires_local_attribution and (
            edge.local_attribution is None or edge.evidence_id is None
        ):
            blocked.append(
                _blocked(
                    direct,
                    state,
                    edge,
                    target,
                    PropagationBlockReason.LOCAL_ATTRIBUTION_REQUIRED,
                )
            )
            continue
        target_node = node_map[target]
        if not target_node.authorized:
            blocked.append(
                _blocked(
                    direct,
                    state,
                    edge,
                    target,
                    PropagationBlockReason.TARGET_UNAUTHORIZED,
                )
            )
            continue
        if not target_node.currently_valid:
            blocked.append(
                _blocked(
                    direct,
                    state,
                    edge,
                    target,
                    PropagationBlockReason.TARGET_INVALID,
                )
            )
            continue
        attribution = edge.local_attribution if edge.local_attribution is not None else 1.0
        weight = policy.relation_weight * edge.confidence * attribution
        if weight <= 0:
            blocked.append(
                _blocked(
                    direct,
                    state,
                    edge,
                    target,
                    PropagationBlockReason.NON_POSITIVE_WEIGHT,
                )
            )
            continue
        outgoing.append(
            _TraversalEdge(
                edge=edge,
                target_memory_id=target,
                policy=policy,
                weight=weight,
            )
        )

    return (
        tuple(
            sorted(
                outgoing,
                key=lambda item: (
                    str(item.target_memory_id),
                    item.edge.relation,
                    str(item.edge.edge_id),
                ),
            )
        ),
        tuple(sorted(blocked, key=_blocked_sort_key)),
    )


def _validate_oriented_acyclic_graph(
    graph: TypedProvenanceGraph,
    policies: Mapping[str, ProvenanceRelationPolicy],
    *,
    positive: bool,
) -> None:
    node_map = graph.node_map
    adjacency: dict[UUID, set[UUID]] = {item.memory_id: set() for item in graph.nodes}
    for edge in graph.edges:
        policy = policies.get(edge.relation)
        if policy is None or policy.direction is PropagationDirection.BLOCKED:
            continue
        if (positive and not policy.allow_positive) or (not positive and not policy.allow_negative):
            continue
        if policy.requires_local_attribution and (
            edge.local_attribution is None or edge.evidence_id is None
        ):
            continue
        source, target = _oriented_endpoints(edge, policy.direction)
        if not node_map[source].authorized or not node_map[source].currently_valid:
            continue
        if not node_map[target].authorized or not node_map[target].currently_valid:
            continue
        attribution = edge.local_attribution if edge.local_attribution is not None else 1.0
        if policy.relation_weight * edge.confidence * attribution <= 0:
            continue
        adjacency[source].add(target)

    visiting: set[UUID] = set()
    visited: set[UUID] = set()

    def visit(memory_id: UUID) -> None:
        if memory_id in visiting:
            raise ProvenanceCreditValidationError(
                "policy-oriented provenance graph contains a cycle"
            )
        if memory_id in visited:
            return
        visiting.add(memory_id)
        for target in sorted(adjacency[memory_id], key=str):
            visit(target)
        visiting.remove(memory_id)
        visited.add(memory_id)

    for memory_id in sorted(adjacency, key=str):
        visit(memory_id)


def _summarize_targets(
    contributions: Sequence[PropagatedCreditContribution],
) -> tuple[PropagatedTargetCredit, ...]:
    grouped: dict[
        tuple[UUID, UUID, UUID],
        list[PropagatedCreditContribution],
    ] = {}
    for item in contributions:
        key = (
            item.direct_credit_id,
            item.root_memory_id,
            item.target_memory_id,
        )
        grouped.setdefault(key, []).append(item)

    values: list[PropagatedTargetCredit] = []
    for key in sorted(grouped, key=_target_group_sort_key):
        direct_credit_id, root_memory_id, target_memory_id = key
        paths = grouped[key]
        values.append(
            PropagatedTargetCredit(
                direct_credit_id=direct_credit_id,
                root_memory_id=root_memory_id,
                target_memory_id=target_memory_id,
                propagated_value=sum(item.propagated_value for item in paths),
                propagated_standard_error=sum(item.propagated_standard_error for item in paths),
                path_count=len(paths),
            )
        )
    return tuple(values)


def _contribution(
    direct: DirectCreditEvidence,
    state: _PathState,
    value: float,
) -> PropagatedCreditContribution:
    multiplier = value / direct.value
    return PropagatedCreditContribution(
        direct_credit_id=direct.direct_credit_id,
        root_memory_id=direct.root_memory_id,
        target_memory_id=state.current_memory_id,
        propagated_value=value,
        propagated_standard_error=(abs(multiplier) * direct.standard_error),
        structural_confidence=state.structural_confidence,
        minimum_edge_confidence=state.minimum_edge_confidence,
        depth=state.depth,
        relation_path=state.relation_path,
        edge_path=state.edge_path,
        path_fingerprint=_path_fingerprint(
            direct.direct_credit_id,
            direct.root_memory_id,
            state.current_memory_id,
            state.relation_path,
            state.edge_path,
        ),
    )


def _blocked(
    direct: DirectCreditEvidence,
    state: _PathState,
    edge: ProvenanceEdge,
    target_memory_id: UUID,
    reason: PropagationBlockReason,
) -> BlockedPropagation:
    relation_path = (*state.relation_path, edge.relation)
    edge_path = (*state.edge_path, edge.edge_id)
    return BlockedPropagation(
        direct_credit_id=direct.direct_credit_id,
        root_memory_id=direct.root_memory_id,
        current_memory_id=state.current_memory_id,
        target_memory_id=target_memory_id,
        edge_id=edge.edge_id,
        relation=edge.relation,
        reason=reason,
        depth=state.depth,
        path_fingerprint=_path_fingerprint(
            direct.direct_credit_id,
            direct.root_memory_id,
            target_memory_id,
            relation_path,
            edge_path,
        ),
    )


def _path_fingerprint(
    direct_credit_id: UUID,
    root_memory_id: UUID,
    target_memory_id: UUID,
    relation_path: Sequence[str],
    edge_path: Sequence[UUID],
) -> str:
    payload = {
        "direct_credit_id": str(direct_credit_id),
        "root_memory_id": str(root_memory_id),
        "target_memory_id": str(target_memory_id),
        "relation_path": list(relation_path),
        "edge_path": [str(edge_id) for edge_id in edge_path],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _oriented_endpoints(
    edge: ProvenanceEdge,
    direction: PropagationDirection,
) -> tuple[UUID, UUID]:
    if direction is PropagationDirection.FORWARD:
        return edge.from_node_id, edge.to_node_id
    if direction is PropagationDirection.REVERSE:
        return edge.to_node_id, edge.from_node_id
    raise ProvenanceCreditValidationError("blocked relation does not have traversable endpoints")


def _edge_sort_key(edge: ProvenanceEdge) -> tuple[str, str, str, str]:
    return (
        edge.relation,
        str(edge.from_node_id),
        str(edge.to_node_id),
        str(edge.edge_id),
    )


def _contribution_sort_key(
    item: PropagatedCreditContribution,
) -> tuple[str, int, str, str]:
    return (
        str(item.direct_credit_id),
        item.depth,
        str(item.target_memory_id),
        item.path_fingerprint,
    )


def _blocked_sort_key(item: BlockedPropagation) -> tuple[str, int, str, str, str]:
    return (
        str(item.direct_credit_id),
        item.depth,
        str(item.current_memory_id),
        str(item.edge_id),
        item.reason.value,
    )


def _abstention_sort_key(
    item: ProvenanceCreditAbstention,
) -> tuple[str, str]:
    return str(item.direct_credit_id), item.reason.value


def _ledger_sort_key(item: PropagationMassLedger) -> str:
    return str(item.direct_credit_id)


def _direct_group_sort_key(key: tuple[UUID, UUID, UUID]) -> tuple[str, str, str]:
    space_id, root_memory_id, evidence_group_id = key
    return str(space_id), str(evidence_group_id), str(root_memory_id)


def _direct_credit_sort_key(
    item: DirectCreditEvidence,
) -> tuple[str, str, str, str]:
    return (
        str(item.space_id),
        str(item.evidence_group_id),
        str(item.root_memory_id),
        str(item.direct_credit_id),
    )


def _target_group_sort_key(
    key: tuple[UUID, UUID, UUID],
) -> tuple[str, str, str]:
    return tuple(str(item) for item in key)


def _normalize_relation(value: object) -> str:
    relation = _required_text("relation", value).lower()
    if _RELATION_RE.fullmatch(relation) is None:
        raise ProvenanceCreditValidationError("relation must use lowercase typed-relation syntax")
    return relation


def _required_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ProvenanceCreditValidationError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ProvenanceCreditValidationError(f"{name} must not be empty")
    return normalized


def _require_uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise ProvenanceCreditValidationError(f"{name} must be a UUID")


def _require_bool(name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise ProvenanceCreditValidationError(f"{name} must be a boolean")


def _finite_number(name: str, value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProvenanceCreditValidationError(f"{name} must be a finite number")
    normalized = float(value)
    if not isfinite(normalized):
        raise ProvenanceCreditValidationError(f"{name} must be a finite number")
    return normalized


def _probability(name: str, value: object) -> float:
    normalized = _finite_number(name, value)
    if not 0.0 <= normalized <= 1.0:
        raise ProvenanceCreditValidationError(f"{name} must be between zero and one")
    return normalized


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ProvenanceCreditValidationError(f"{name} must be a positive integer")
    return value


def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProvenanceCreditValidationError(f"{name} must be a non-negative integer")
    return value


def _require_hash(name: str, value: object) -> None:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ProvenanceCreditValidationError(f"{name} must be a lowercase SHA-256 hex digest")
