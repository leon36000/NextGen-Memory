"""Pure static admission checks for corrective-retrieval pipelines."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from .corrective_retrieval_contracts import (
    CorrectiveRetrievalValidationError,
    RetrievalCapabilityProfile,
    RetrievalFailureClass,
    RetrievalMode,
    canonical_json_sha256,
)

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_INVALID_PIPELINE_HASH = canonical_json_sha256({"invalid_pipeline": True})


class PreflightReason(StrEnum):
    """Bounded, privacy-safe reasons returned by static admission."""

    ALLOWED = "allowed"
    INVALID_PIPELINE = "invalid_pipeline"
    SCOPE_VIOLATION = "scope_violation"
    INDEX_UNAVAILABLE = "index_unavailable"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    PROBE_AUTHORIZATION_MISMATCH = "probe_authorization_mismatch"


@dataclass(frozen=True, slots=True)
class CorrectivePreflightPolicy:
    """Immutable structural policy for a corrective retrieval pipeline."""

    lexical_index_name: str
    vector_index_name: str
    vector_path: str
    max_branch_results: int
    max_num_candidates: int
    active_status: str = "active"
    required_source_type: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "lexical_index_name",
            "vector_index_name",
            "vector_path",
            "active_status",
        ):
            object.__setattr__(self, name, _require_text(name, getattr(self, name)))
        object.__setattr__(
            self,
            "max_branch_results",
            _require_positive_int("max_branch_results", self.max_branch_results),
        )
        object.__setattr__(
            self,
            "max_num_candidates",
            _require_positive_int("max_num_candidates", self.max_num_candidates),
        )
        if self.max_num_candidates < self.max_branch_results:
            raise CorrectiveRetrievalValidationError(
                "max_num_candidates cannot be below max_branch_results"
            )
        if self.required_source_type is not None:
            object.__setattr__(
                self,
                "required_source_type",
                _require_text("required_source_type", self.required_source_type),
            )


@dataclass(frozen=True, slots=True)
class CapabilityProbeAuthorization:
    """Exact fingerprint-bound authorization from a successful live probe."""

    profile_id: UUID
    mode: RetrievalMode
    cluster_fingerprint: str
    lexical_index_fingerprint: str
    vector_index_fingerprint: str
    pipeline_hash: str

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, UUID):
            raise CorrectiveRetrievalValidationError("profile_id must be a UUID")
        if not isinstance(self.mode, RetrievalMode):
            raise CorrectiveRetrievalValidationError("mode must be a RetrievalMode")
        for name in (
            "cluster_fingerprint",
            "lexical_index_fingerprint",
            "vector_index_fingerprint",
            "pipeline_hash",
        ):
            _require_hash(name, getattr(self, name))


@dataclass(frozen=True, slots=True)
class RetrievalPreflightDecision:
    """Privacy-safe result of one pure static pipeline audit."""

    allowed: bool
    failure_class: RetrievalFailureClass
    reason: PreflightReason
    mode: RetrievalMode
    pipeline_hash: str
    embedding_bearing: bool
    capability_profile_id: UUID
    index_fingerprints: tuple[str, str]

    def __post_init__(self) -> None:
        if type(self.allowed) is not bool:
            raise CorrectiveRetrievalValidationError("allowed must be a bool")
        if not isinstance(self.failure_class, RetrievalFailureClass):
            raise CorrectiveRetrievalValidationError(
                "failure_class must be a RetrievalFailureClass"
            )
        if not isinstance(self.reason, PreflightReason):
            raise CorrectiveRetrievalValidationError("reason must be a PreflightReason")
        if not isinstance(self.mode, RetrievalMode):
            raise CorrectiveRetrievalValidationError("mode must be a RetrievalMode")
        _require_hash("pipeline_hash", self.pipeline_hash)
        if type(self.embedding_bearing) is not bool:
            raise CorrectiveRetrievalValidationError("embedding_bearing must be a bool")
        if not isinstance(self.capability_profile_id, UUID):
            raise CorrectiveRetrievalValidationError(
                "capability_profile_id must be a UUID"
            )
        if type(self.index_fingerprints) is not tuple or len(self.index_fingerprints) != 2:
            raise CorrectiveRetrievalValidationError(
                "index_fingerprints must be an exact two-item tuple"
            )
        for value in self.index_fingerprints:
            _require_hash("index_fingerprint", value)
        if self.allowed:
            if self.failure_class is not RetrievalFailureClass.SUCCESS:
                raise CorrectiveRetrievalValidationError(
                    "allowed decisions must use the success failure class"
                )
            if self.reason is not PreflightReason.ALLOWED:
                raise CorrectiveRetrievalValidationError(
                    "allowed decisions must use the allowed reason"
                )
        elif self.failure_class is RetrievalFailureClass.SUCCESS:
            raise CorrectiveRetrievalValidationError(
                "denied decisions cannot use the success failure class"
            )


def pipeline_fingerprint(pipeline: object) -> str:
    """Return a deterministic hash without retaining raw pipeline content."""

    return canonical_json_sha256(pipeline)


class RetrievalPipelinePreflight:
    """Pure static auditor for lexical, vector, and fusion pipeline shapes."""

    @staticmethod
    def audit(
        pipeline: object,
        *,
        mode: RetrievalMode,
        space_id: UUID,
        profile: RetrievalCapabilityProfile,
        policy: CorrectivePreflightPolicy,
        probe_authorization: CapabilityProbeAuthorization | None = None,
    ) -> RetrievalPreflightDecision:
        if not isinstance(mode, RetrievalMode):
            raise CorrectiveRetrievalValidationError("mode must be a RetrievalMode")
        if not isinstance(space_id, UUID):
            raise CorrectiveRetrievalValidationError("space_id must be a UUID")
        if not isinstance(profile, RetrievalCapabilityProfile):
            raise CorrectiveRetrievalValidationError(
                "profile must be a RetrievalCapabilityProfile"
            )
        if not isinstance(policy, CorrectivePreflightPolicy):
            raise CorrectiveRetrievalValidationError(
                "policy must be a CorrectivePreflightPolicy"
            )
        if probe_authorization is not None and not isinstance(
            probe_authorization,
            CapabilityProbeAuthorization,
        ):
            raise CorrectiveRetrievalValidationError(
                "probe_authorization must be a CapabilityProbeAuthorization"
            )

        try:
            digest = pipeline_fingerprint(pipeline)
        except CorrectiveRetrievalValidationError:
            digest = _INVALID_PIPELINE_HASH

        embedding_bearing = mode in {
            RetrievalMode.VECTOR,
            RetrievalMode.HYBRID_RANK_FUSION,
            RetrievalMode.HYBRID_SCORE_FUSION,
        }

        capability_failure = _capability_failure(
            mode=mode,
            profile=profile,
            policy=policy,
            pipeline_hash=digest,
            authorization=probe_authorization,
        )
        if capability_failure is not None:
            return _decision(
                profile=profile,
                mode=mode,
                pipeline_hash=digest,
                embedding_bearing=embedding_bearing,
                failure_class=capability_failure[0],
                reason=capability_failure[1],
            )

        if type(pipeline) is not list or not pipeline:
            return _invalid(profile, mode, digest, embedding_bearing)

        if mode is RetrievalMode.LEXICAL:
            failure = _audit_lexical_pipeline(pipeline, space_id, policy)
        elif mode is RetrievalMode.VECTOR:
            failure = _audit_vector_pipeline(pipeline, space_id, policy)
        elif mode is RetrievalMode.HYBRID_RANK_FUSION:
            failure = _audit_fusion_pipeline(
                pipeline,
                fusion_stage="$rankFusion",
                space_id=space_id,
                policy=policy,
            )
        elif mode is RetrievalMode.HYBRID_SCORE_FUSION:
            failure = _audit_fusion_pipeline(
                pipeline,
                fusion_stage="$scoreFusion",
                space_id=space_id,
                policy=policy,
            )
        else:
            failure = _audit_rerank_pipeline(pipeline, policy)

        if failure is not None:
            return _decision(
                profile=profile,
                mode=mode,
                pipeline_hash=digest,
                embedding_bearing=embedding_bearing,
                failure_class=failure[0],
                reason=failure[1],
            )
        return _decision(
            profile=profile,
            mode=mode,
            pipeline_hash=digest,
            embedding_bearing=embedding_bearing,
            failure_class=RetrievalFailureClass.SUCCESS,
            reason=PreflightReason.ALLOWED,
        )


def _capability_failure(
    *,
    mode: RetrievalMode,
    profile: RetrievalCapabilityProfile,
    policy: CorrectivePreflightPolicy,
    pipeline_hash: str,
    authorization: CapabilityProbeAuthorization | None,
) -> tuple[RetrievalFailureClass, PreflightReason] | None:
    uses_lexical = mode in {
        RetrievalMode.LEXICAL,
        RetrievalMode.HYBRID_RANK_FUSION,
        RetrievalMode.HYBRID_SCORE_FUSION,
    }
    uses_vector = mode in {
        RetrievalMode.VECTOR,
        RetrievalMode.HYBRID_RANK_FUSION,
        RetrievalMode.HYBRID_SCORE_FUSION,
    }
    if uses_lexical and (
        not profile.lexical_ready or profile.lexical_index_name != policy.lexical_index_name
    ):
        return RetrievalFailureClass.INDEX_UNAVAILABLE, PreflightReason.INDEX_UNAVAILABLE
    if uses_vector and (
        not profile.vector_ready or profile.vector_index_name != policy.vector_index_name
    ):
        return RetrievalFailureClass.INDEX_UNAVAILABLE, PreflightReason.INDEX_UNAVAILABLE
    if uses_vector and not profile.auto_embedding_enabled:
        return (
            RetrievalFailureClass.UNSUPPORTED_CAPABILITY,
            PreflightReason.UNSUPPORTED_CAPABILITY,
        )
    if (
        mode is RetrievalMode.HYBRID_RANK_FUSION
        and not profile.rank_fusion_supported
        and not _probe_authorizes_rank_fusion(
            profile=profile,
            pipeline_hash=pipeline_hash,
            authorization=authorization,
        )
    ):
        return (
            RetrievalFailureClass.UNSUPPORTED_CAPABILITY,
            PreflightReason.PROBE_AUTHORIZATION_MISMATCH,
        )
    if mode is RetrievalMode.HYBRID_SCORE_FUSION and not profile.score_fusion_supported:
        return (
            RetrievalFailureClass.UNSUPPORTED_CAPABILITY,
            PreflightReason.UNSUPPORTED_CAPABILITY,
        )
    if mode is RetrievalMode.NATIVE_RERANK and (
        not profile.native_rerank_supported or not profile.native_rerank_enabled
    ):
        return (
            RetrievalFailureClass.UNSUPPORTED_CAPABILITY,
            PreflightReason.UNSUPPORTED_CAPABILITY,
        )
    return None


def _probe_authorizes_rank_fusion(
    *,
    profile: RetrievalCapabilityProfile,
    pipeline_hash: str,
    authorization: CapabilityProbeAuthorization | None,
) -> bool:
    return bool(
        authorization is not None
        and authorization.mode is RetrievalMode.HYBRID_RANK_FUSION
        and authorization.profile_id == profile.profile_id
        and authorization.cluster_fingerprint == profile.cluster_fingerprint
        and authorization.lexical_index_fingerprint == profile.lexical_index_fingerprint
        and authorization.vector_index_fingerprint == profile.vector_index_fingerprint
        and authorization.pipeline_hash == pipeline_hash
    )


def _audit_lexical_pipeline(
    pipeline: object,
    space_id: UUID,
    policy: CorrectivePreflightPolicy,
) -> tuple[RetrievalFailureClass, PreflightReason] | None:
    if type(pipeline) is not list or len(pipeline) < 2:
        return _invalid_failure()
    first = _single_stage(pipeline[0], "$search")
    if first is None or type(first) is not dict:
        return _invalid_failure()
    if first.get("index") != policy.lexical_index_name:
        return _invalid_failure()
    compound = first.get("compound")
    if type(compound) is not dict:
        return _invalid_failure()
    filters = compound.get("filter")
    if type(filters) is not list:
        return _invalid_failure()
    parsed = _parse_lexical_filters(filters)
    if parsed is None:
        return _invalid_failure()
    scope_failure = _scope_failure(parsed, space_id, policy)
    if scope_failure is not None:
        return scope_failure
    limit = _single_stage(pipeline[1], "$limit")
    if not _bounded_positive_int(limit, policy.max_branch_results):
        return _invalid_failure()
    for stage in pipeline[2:]:
        if _single_stage(stage, "$project") is None:
            return _invalid_failure()
    return None


def _parse_lexical_filters(filters: list[object]) -> dict[str, list[object]] | None:
    parsed: dict[str, list[object]] = {}
    for item in filters:
        if type(item) is not dict or set(item) != {"equals"}:
            return None
        equals = item.get("equals")
        if type(equals) is not dict or set(equals) != {"path", "value"}:
            return None
        path = equals.get("path")
        if type(path) is not str:
            return None
        parsed.setdefault(path, []).append(equals.get("value"))
    return parsed


def _scope_failure(
    values: dict[str, list[object]],
    space_id: UUID,
    policy: CorrectivePreflightPolicy,
) -> tuple[RetrievalFailureClass, PreflightReason] | None:
    required: dict[str, object] = {
        "space_id": str(space_id),
        "status": policy.active_status,
    }
    if policy.required_source_type is not None:
        required["source_type"] = policy.required_source_type
    for field, expected in required.items():
        observed = values.get(field)
        if observed is None or len(observed) != 1 or observed[0] != expected:
            return RetrievalFailureClass.SCOPE_VIOLATION, PreflightReason.SCOPE_VIOLATION
    return None


def _audit_vector_pipeline(
    pipeline: object,
    space_id: UUID,
    policy: CorrectivePreflightPolicy,
) -> tuple[RetrievalFailureClass, PreflightReason] | None:
    if type(pipeline) is not list or not pipeline:
        return _invalid_failure()
    first = _single_stage(pipeline[0], "$vectorSearch")
    if first is None or type(first) is not dict:
        return _invalid_failure()
    if first.get("index") != policy.vector_index_name:
        return _invalid_failure()
    if first.get("path") != policy.vector_path:
        return _invalid_failure()
    limit = first.get("limit")
    candidates = first.get("numCandidates")
    if not _bounded_positive_int(limit, policy.max_branch_results):
        return _invalid_failure()
    if not _bounded_positive_int(candidates, policy.max_num_candidates):
        return _invalid_failure()
    if candidates < limit:
        return _invalid_failure()
    scope = first.get("filter")
    if type(scope) is not dict:
        return _invalid_failure()
    required: dict[str, object] = {
        "space_id": str(space_id),
        "status": policy.active_status,
    }
    if policy.required_source_type is not None:
        required["source_type"] = policy.required_source_type
    for field, expected in required.items():
        if field not in scope or scope[field] != expected:
            return RetrievalFailureClass.SCOPE_VIOLATION, PreflightReason.SCOPE_VIOLATION
    for stage in pipeline[1:]:
        if _single_stage(stage, "$project") is None:
            return _invalid_failure()
    return None


def _audit_fusion_pipeline(
    pipeline: object,
    *,
    fusion_stage: str,
    space_id: UUID,
    policy: CorrectivePreflightPolicy,
) -> tuple[RetrievalFailureClass, PreflightReason] | None:
    if type(pipeline) is not list or len(pipeline) < 2:
        return _invalid_failure()
    fusion = _single_stage(pipeline[0], fusion_stage)
    if fusion is None or type(fusion) is not dict:
        return _invalid_failure()
    fusion_input = fusion.get("input")
    if type(fusion_input) is not dict:
        return _invalid_failure()
    pipelines = fusion_input.get("pipelines")
    if type(pipelines) is not dict or set(pipelines) != {"semantic", "lexical"}:
        return _invalid_failure()
    lexical = pipelines.get("lexical")
    semantic = pipelines.get("semantic")
    if type(lexical) is not list or type(semantic) is not list:
        return _invalid_failure()
    lexical_failure = _audit_lexical_pipeline(lexical, space_id, policy)
    if lexical_failure is not None:
        return lexical_failure
    vector_failure = _audit_vector_pipeline(semantic, space_id, policy)
    if vector_failure is not None:
        return vector_failure
    limit = _single_stage(pipeline[1], "$limit")
    if not _bounded_positive_int(limit, policy.max_branch_results):
        return _invalid_failure()
    for stage in pipeline[2:]:
        if _single_stage(stage, "$project") is None:
            return _invalid_failure()
    return None


def _audit_rerank_pipeline(
    pipeline: object,
    policy: CorrectivePreflightPolicy,
) -> tuple[RetrievalFailureClass, PreflightReason] | None:
    if type(pipeline) is not list or len(pipeline) < 2:
        return _invalid_failure()
    rerank = _single_stage(pipeline[0], "$rerank")
    if rerank is None or type(rerank) is not dict:
        return _invalid_failure()
    limit = _single_stage(pipeline[1], "$limit")
    if not _bounded_positive_int(limit, policy.max_branch_results):
        return _invalid_failure()
    for stage in pipeline[2:]:
        if _single_stage(stage, "$project") is None:
            return _invalid_failure()
    return None


def _single_stage(stage: object, expected: str) -> object | None:
    if type(stage) is not dict or set(stage) != {expected}:
        return None
    return stage.get(expected)


def _bounded_positive_int(value: object, maximum: int) -> bool:
    return type(value) is int and 0 < value <= maximum


def _invalid_failure() -> tuple[RetrievalFailureClass, PreflightReason]:
    return RetrievalFailureClass.INVALID_PIPELINE, PreflightReason.INVALID_PIPELINE


def _invalid(
    profile: RetrievalCapabilityProfile,
    mode: RetrievalMode,
    pipeline_hash: str,
    embedding_bearing: bool,
) -> RetrievalPreflightDecision:
    return _decision(
        profile=profile,
        mode=mode,
        pipeline_hash=pipeline_hash,
        embedding_bearing=embedding_bearing,
        failure_class=RetrievalFailureClass.INVALID_PIPELINE,
        reason=PreflightReason.INVALID_PIPELINE,
    )


def _decision(
    *,
    profile: RetrievalCapabilityProfile,
    mode: RetrievalMode,
    pipeline_hash: str,
    embedding_bearing: bool,
    failure_class: RetrievalFailureClass,
    reason: PreflightReason,
) -> RetrievalPreflightDecision:
    return RetrievalPreflightDecision(
        allowed=failure_class is RetrievalFailureClass.SUCCESS,
        failure_class=failure_class,
        reason=reason,
        mode=mode,
        pipeline_hash=pipeline_hash,
        embedding_bearing=embedding_bearing,
        capability_profile_id=profile.profile_id,
        index_fingerprints=(
            profile.lexical_index_fingerprint,
            profile.vector_index_fingerprint,
        ),
    )


def _require_text(name: str, value: object) -> str:
    if type(value) is not str or not value.strip():
        raise CorrectiveRetrievalValidationError(f"{name} must be non-empty text")
    return value.strip()


def _require_positive_int(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise CorrectiveRetrievalValidationError(f"{name} must be a positive integer")
    return value


def _require_hash(name: str, value: object) -> str:
    if type(value) is not str or not _HASH_RE.fullmatch(value):
        raise CorrectiveRetrievalValidationError(
            f"{name} must be a lowercase SHA-256 hex digest"
        )
    return value
