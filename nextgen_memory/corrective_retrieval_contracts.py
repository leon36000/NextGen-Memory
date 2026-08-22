"""Immutable, privacy-safe contracts for corrective retrieval preproduction."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from math import isfinite
from typing import Any, Self
from uuid import UUID, uuid5

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_PLAN_NAMESPACE = UUID("9d0d4f64-77eb-5cc0-8bc1-b1c6ef8f8a3d")


class CorrectiveRetrievalValidationError(ValueError):
    """Raised when a corrective-retrieval contract fails closed."""


class RetrievalMode(StrEnum):
    """Retrieval semantics that must never be changed implicitly."""

    LEXICAL = "lexical"
    VECTOR = "vector"
    HYBRID_RANK_FUSION = "hybrid_rank_fusion"
    HYBRID_SCORE_FUSION = "hybrid_score_fusion"
    NATIVE_RERANK = "native_rerank"


class RetrievalFailureClass(StrEnum):
    """Bounded failure taxonomy allowed outside a provider adapter."""

    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    INDEX_UNAVAILABLE = "index_unavailable"
    SCOPE_VIOLATION = "scope_violation"
    INVALID_PIPELINE = "invalid_pipeline"
    INVALID_QUERY = "invalid_query"
    PROVIDER_TRANSIENT = "provider_transient"
    PROVIDER_PERMANENT = "provider_permanent"
    MATERIALIZATION_MISSING = "materialization_missing"
    MATERIALIZATION_IDENTITY_MISMATCH = "materialization_identity_mismatch"
    MATERIALIZATION_SCOPE_MISMATCH = "materialization_scope_mismatch"
    MATERIALIZATION_INACTIVE = "materialization_inactive"
    MATERIALIZATION_SOURCE_TYPE_MISMATCH = "materialization_source_type_mismatch"


class ProviderStatusClass(StrEnum):
    """Privacy-safe provider status classes retained after adapter redaction."""

    NOT_APPLICABLE = "not_applicable"
    SUCCESS = "success"
    RATE_LIMITED = "rate_limited"
    TRANSIENT_ERROR = "transient_error"
    PERMANENT_ERROR = "permanent_error"


class RetrievalAttemptOutcome(StrEnum):
    """High-level outcome of one bounded retrieval attempt."""

    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class RetrievalCapabilityProfile:
    """Immutable, privacy-safe snapshot of retrieval capabilities."""

    profile_id: UUID
    server_version: tuple[int, int, int]
    cluster_fingerprint: str
    lexical_index_name: str
    vector_index_name: str
    lexical_index_fingerprint: str
    vector_index_fingerprint: str
    lexical_ready: bool
    vector_ready: bool
    rank_fusion_supported: bool
    score_fusion_supported: bool
    native_rerank_supported: bool
    native_rerank_enabled: bool
    auto_embedding_enabled: bool
    embedding_model: str | None
    embedding_query_rpm: int | None
    embedding_query_tpm: int | None
    capability_evidence_hash: str

    def __post_init__(self) -> None:
        _require_uuid("profile_id", self.profile_id)
        object.__setattr__(
            self,
            "server_version",
            _require_server_version(self.server_version),
        )
        for name in (
            "cluster_fingerprint",
            "lexical_index_fingerprint",
            "vector_index_fingerprint",
            "capability_evidence_hash",
        ):
            _require_hash(name, getattr(self, name))
        for name in ("lexical_index_name", "vector_index_name"):
            object.__setattr__(self, name, _require_text(name, getattr(self, name)))
        for name in (
            "lexical_ready",
            "vector_ready",
            "rank_fusion_supported",
            "score_fusion_supported",
            "native_rerank_supported",
            "native_rerank_enabled",
            "auto_embedding_enabled",
        ):
            _require_bool(name, getattr(self, name))
        if self.native_rerank_enabled and not self.native_rerank_supported:
            raise CorrectiveRetrievalValidationError(
                "native_rerank_enabled requires native_rerank_supported"
            )
        if self.auto_embedding_enabled:
            object.__setattr__(
                self,
                "embedding_model",
                _require_text("embedding_model", self.embedding_model),
            )
            object.__setattr__(
                self,
                "embedding_query_rpm",
                _require_positive_int("embedding_query_rpm", self.embedding_query_rpm),
            )
            object.__setattr__(
                self,
                "embedding_query_tpm",
                _require_positive_int("embedding_query_tpm", self.embedding_query_tpm),
            )
        elif any(
            value is not None
            for value in (
                self.embedding_model,
                self.embedding_query_rpm,
                self.embedding_query_tpm,
            )
        ):
            raise CorrectiveRetrievalValidationError(
                "embedding configuration must be absent when auto embedding is disabled"
            )


@dataclass(frozen=True, slots=True)
class RetrievalExecutionPlan:
    """Privacy-safe immutable executable policy for one corrective retrieval."""

    plan_id: UUID
    space_id: UUID
    mode: RetrievalMode
    query_fingerprint: str
    semantic_fingerprint: str
    pipeline_hash: str
    capability_profile_id: UUID
    index_fingerprints: tuple[str, str]
    max_results: int
    max_attempts: int
    embedding_token_estimate: int
    created_for_gap_key: str

    def __post_init__(self) -> None:
        _require_uuid("plan_id", self.plan_id)
        _require_uuid("space_id", self.space_id)
        if not isinstance(self.mode, RetrievalMode):
            raise CorrectiveRetrievalValidationError("mode must be a RetrievalMode")
        for name in ("query_fingerprint", "semantic_fingerprint", "pipeline_hash"):
            _require_hash(name, getattr(self, name))
        _require_uuid("capability_profile_id", self.capability_profile_id)
        object.__setattr__(
            self,
            "index_fingerprints",
            _require_index_fingerprints(self.index_fingerprints),
        )
        object.__setattr__(
            self,
            "max_results",
            _require_positive_int("max_results", self.max_results),
        )
        object.__setattr__(
            self,
            "max_attempts",
            _require_positive_int("max_attempts", self.max_attempts),
        )
        object.__setattr__(
            self,
            "embedding_token_estimate",
            _require_nonnegative_int(
                "embedding_token_estimate",
                self.embedding_token_estimate,
            ),
        )
        object.__setattr__(
            self,
            "created_for_gap_key",
            _require_text("created_for_gap_key", self.created_for_gap_key),
        )
        expected = self._expected_plan_id()
        if self.plan_id != expected:
            raise CorrectiveRetrievalValidationError(
                "plan_id does not match the canonical privacy-safe plan payload"
            )

    @classmethod
    def create(
        cls,
        *,
        space_id: UUID,
        mode: RetrievalMode,
        query_fingerprint: str,
        semantic_fingerprint: str,
        pipeline_hash: str,
        capability_profile_id: UUID,
        index_fingerprints: tuple[str, str],
        max_results: int,
        max_attempts: int,
        embedding_token_estimate: int,
        created_for_gap_key: str,
    ) -> Self:
        """Construct a plan with a deterministic UUID5 identity."""

        payload = _plan_identity_payload(
            space_id=space_id,
            mode=mode,
            query_fingerprint=query_fingerprint,
            semantic_fingerprint=semantic_fingerprint,
            pipeline_hash=pipeline_hash,
            capability_profile_id=capability_profile_id,
            index_fingerprints=index_fingerprints,
            max_results=max_results,
            max_attempts=max_attempts,
            embedding_token_estimate=embedding_token_estimate,
            created_for_gap_key=created_for_gap_key,
        )
        plan_id = uuid5(_PLAN_NAMESPACE, _canonical_json_text(payload))
        return cls(
            plan_id=plan_id,
            space_id=space_id,
            mode=mode,
            query_fingerprint=query_fingerprint,
            semantic_fingerprint=semantic_fingerprint,
            pipeline_hash=pipeline_hash,
            capability_profile_id=capability_profile_id,
            index_fingerprints=index_fingerprints,
            max_results=max_results,
            max_attempts=max_attempts,
            embedding_token_estimate=embedding_token_estimate,
            created_for_gap_key=created_for_gap_key,
        )

    def _expected_plan_id(self) -> UUID:
        payload = _plan_identity_payload(
            space_id=self.space_id,
            mode=self.mode,
            query_fingerprint=self.query_fingerprint,
            semantic_fingerprint=self.semantic_fingerprint,
            pipeline_hash=self.pipeline_hash,
            capability_profile_id=self.capability_profile_id,
            index_fingerprints=self.index_fingerprints,
            max_results=self.max_results,
            max_attempts=self.max_attempts,
            embedding_token_estimate=self.embedding_token_estimate,
            created_for_gap_key=self.created_for_gap_key,
        )
        return uuid5(_PLAN_NAMESPACE, _canonical_json_text(payload))


@dataclass(frozen=True, slots=True)
class RetrievalAttemptResult:
    """Privacy-safe result envelope for one bounded retrieval attempt."""

    plan_id: UUID
    attempt_number: int
    mode: RetrievalMode
    outcome: RetrievalAttemptOutcome
    failure_class: RetrievalFailureClass
    query_fingerprint: str
    pipeline_hash: str
    capability_profile_id: UUID
    index_fingerprints: tuple[str, str]
    returned_count: int
    admitted_count: int
    duration_bucket: str
    retry_after_seconds: int | None
    provider_status_class: ProviderStatusClass

    def __post_init__(self) -> None:
        _require_uuid("plan_id", self.plan_id)
        object.__setattr__(
            self,
            "attempt_number",
            _require_positive_int("attempt_number", self.attempt_number),
        )
        if not isinstance(self.mode, RetrievalMode):
            raise CorrectiveRetrievalValidationError("mode must be a RetrievalMode")
        if not isinstance(self.outcome, RetrievalAttemptOutcome):
            raise CorrectiveRetrievalValidationError(
                "outcome must be a RetrievalAttemptOutcome"
            )
        if not isinstance(self.failure_class, RetrievalFailureClass):
            raise CorrectiveRetrievalValidationError(
                "failure_class must be a RetrievalFailureClass"
            )
        _require_hash("query_fingerprint", self.query_fingerprint)
        _require_hash("pipeline_hash", self.pipeline_hash)
        _require_uuid("capability_profile_id", self.capability_profile_id)
        object.__setattr__(
            self,
            "index_fingerprints",
            _require_index_fingerprints(self.index_fingerprints),
        )
        object.__setattr__(
            self,
            "returned_count",
            _require_nonnegative_int("returned_count", self.returned_count),
        )
        object.__setattr__(
            self,
            "admitted_count",
            _require_nonnegative_int("admitted_count", self.admitted_count),
        )
        if self.admitted_count > self.returned_count:
            raise CorrectiveRetrievalValidationError(
                "admitted_count cannot exceed returned_count"
            )
        object.__setattr__(
            self,
            "duration_bucket",
            _require_text("duration_bucket", self.duration_bucket),
        )
        if self.retry_after_seconds is not None:
            object.__setattr__(
                self,
                "retry_after_seconds",
                _require_nonnegative_int(
                    "retry_after_seconds",
                    self.retry_after_seconds,
                ),
            )
        if not isinstance(self.provider_status_class, ProviderStatusClass):
            raise CorrectiveRetrievalValidationError(
                "provider_status_class must be a ProviderStatusClass"
            )
        self._validate_consistency()

    def _validate_consistency(self) -> None:
        success = self.failure_class is RetrievalFailureClass.SUCCESS
        if success != (self.outcome is RetrievalAttemptOutcome.SUCCESS):
            raise CorrectiveRetrievalValidationError(
                "outcome is inconsistent with failure_class"
            )
        expected_status = _expected_provider_status(self.failure_class)
        if self.provider_status_class is not expected_status:
            raise CorrectiveRetrievalValidationError(
                "provider_status_class is inconsistent with failure_class"
            )
        if (
            self.failure_class is not RetrievalFailureClass.RATE_LIMITED
            and self.retry_after_seconds is not None
        ):
            raise CorrectiveRetrievalValidationError(
                "retry_after_seconds is only valid for rate limiting"
            )


def canonical_json_sha256(value: object) -> str:
    """Hash a strict JSON-like value without arbitrary-string fallbacks."""

    return hashlib.sha256(_canonical_json_text(value).encode("utf-8")).hexdigest()


def _canonical_json_text(value: object) -> str:
    normalized = _normalize_json_value(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _normalize_json_value(value: object) -> Any:
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise CorrectiveRetrievalValidationError(
                "canonical JSON numbers must be finite"
            )
        return value
    if type(value) is list:
        return [_normalize_json_value(item) for item in value]
    if type(value) is tuple:
        return [_normalize_json_value(item) for item in value]
    if type(value) is dict:
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise CorrectiveRetrievalValidationError(
                    "canonical JSON object keys must be strings"
                )
            normalized[key] = _normalize_json_value(item)
        return normalized
    raise CorrectiveRetrievalValidationError(
        "value is not supported by the canonical JSON contract"
    )


def _plan_identity_payload(
    *,
    space_id: UUID,
    mode: RetrievalMode,
    query_fingerprint: str,
    semantic_fingerprint: str,
    pipeline_hash: str,
    capability_profile_id: UUID,
    index_fingerprints: tuple[str, str],
    max_results: int,
    max_attempts: int,
    embedding_token_estimate: int,
    created_for_gap_key: str,
) -> dict[str, object]:
    _require_uuid("space_id", space_id)
    if not isinstance(mode, RetrievalMode):
        raise CorrectiveRetrievalValidationError("mode must be a RetrievalMode")
    for name, value in (
        ("query_fingerprint", query_fingerprint),
        ("semantic_fingerprint", semantic_fingerprint),
        ("pipeline_hash", pipeline_hash),
    ):
        _require_hash(name, value)
    _require_uuid("capability_profile_id", capability_profile_id)
    fingerprints = _require_index_fingerprints(index_fingerprints)
    max_results = _require_positive_int("max_results", max_results)
    max_attempts = _require_positive_int("max_attempts", max_attempts)
    embedding_token_estimate = _require_nonnegative_int(
        "embedding_token_estimate",
        embedding_token_estimate,
    )
    created_for_gap_key = _require_text("created_for_gap_key", created_for_gap_key)
    return {
        "space_id": str(space_id),
        "mode": mode.value,
        "query_fingerprint": query_fingerprint,
        "semantic_fingerprint": semantic_fingerprint,
        "pipeline_hash": pipeline_hash,
        "capability_profile_id": str(capability_profile_id),
        "index_fingerprints": fingerprints,
        "max_results": max_results,
        "max_attempts": max_attempts,
        "embedding_token_estimate": embedding_token_estimate,
        "created_for_gap_key": created_for_gap_key,
    }


def _expected_provider_status(failure_class: RetrievalFailureClass) -> ProviderStatusClass:
    if failure_class is RetrievalFailureClass.SUCCESS:
        return ProviderStatusClass.SUCCESS
    if failure_class is RetrievalFailureClass.RATE_LIMITED:
        return ProviderStatusClass.RATE_LIMITED
    if failure_class is RetrievalFailureClass.PROVIDER_TRANSIENT:
        return ProviderStatusClass.TRANSIENT_ERROR
    if failure_class is RetrievalFailureClass.PROVIDER_PERMANENT:
        return ProviderStatusClass.PERMANENT_ERROR
    return ProviderStatusClass.NOT_APPLICABLE


def _require_uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise CorrectiveRetrievalValidationError(f"{name} must be a UUID")
    return value


def _require_hash(name: str, value: object) -> str:
    if type(value) is not str or not _HASH_RE.fullmatch(value):
        raise CorrectiveRetrievalValidationError(
            f"{name} must be a lowercase SHA-256 hex digest"
        )
    return value


def _require_text(name: str, value: object) -> str:
    if type(value) is not str or not value.strip():
        raise CorrectiveRetrievalValidationError(f"{name} must be non-empty text")
    return value.strip()


def _require_bool(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise CorrectiveRetrievalValidationError(f"{name} must be a bool")
    return value


def _require_positive_int(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise CorrectiveRetrievalValidationError(f"{name} must be a positive integer")
    return value


def _require_nonnegative_int(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise CorrectiveRetrievalValidationError(
            f"{name} must be a non-negative integer"
        )
    return value


def _require_server_version(value: object) -> tuple[int, int, int]:
    if type(value) is not tuple or len(value) != 3:
        raise CorrectiveRetrievalValidationError(
            "server_version must be an exact three-integer tuple"
        )
    resolved: list[int] = []
    for item in value:
        if type(item) is not int or item < 0:
            raise CorrectiveRetrievalValidationError(
                "server_version must be an exact three-integer tuple"
            )
        resolved.append(item)
    return resolved[0], resolved[1], resolved[2]


def _require_index_fingerprints(value: object) -> tuple[str, str]:
    if type(value) is not tuple or len(value) != 2:
        raise CorrectiveRetrievalValidationError(
            "index_fingerprints must be an exact two-item tuple"
        )
    left, right = value
    return _require_hash("index_fingerprints[0]", left), _require_hash(
        "index_fingerprints[1]", right
    )
