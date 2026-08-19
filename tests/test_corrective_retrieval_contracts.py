from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from math import inf, nan
from uuid import UUID

import pytest

from nextgen_memory.corrective_retrieval_contracts import (
    CorrectiveRetrievalValidationError,
    ProviderStatusClass,
    RetrievalAttemptOutcome,
    RetrievalAttemptResult,
    RetrievalCapabilityProfile,
    RetrievalExecutionPlan,
    RetrievalFailureClass,
    RetrievalMode,
    canonical_json_sha256,
)

H1 = "1" * 64
H2 = "2" * 64
H3 = "3" * 64
H4 = "4" * 64
H5 = "5" * 64
SPACE = UUID("11111111-1111-1111-1111-111111111111")
PROFILE_ID = UUID("22222222-2222-2222-2222-222222222222")


def make_profile(**overrides: object) -> RetrievalCapabilityProfile:
    values: dict[str, object] = {
        "profile_id": PROFILE_ID,
        "server_version": (8, 0, 12),
        "cluster_fingerprint": H1,
        "lexical_index_name": "rag_lexical_v2",
        "vector_index_name": "rag_autoembed_v1",
        "lexical_index_fingerprint": H2,
        "vector_index_fingerprint": H3,
        "lexical_ready": True,
        "vector_ready": True,
        "rank_fusion_supported": True,
        "score_fusion_supported": False,
        "native_rerank_supported": False,
        "native_rerank_enabled": False,
        "auto_embedding_enabled": True,
        "embedding_model": "voyage-4-lite",
        "embedding_query_rpm": 30,
        "embedding_query_tpm": 100_000,
        "capability_evidence_hash": H4,
    }
    values.update(overrides)
    return RetrievalCapabilityProfile(**values)  # type: ignore[arg-type]


def make_plan(**overrides: object) -> RetrievalExecutionPlan:
    values: dict[str, object] = {
        "space_id": SPACE,
        "mode": RetrievalMode.HYBRID_RANK_FUSION,
        "query_fingerprint": H1,
        "semantic_fingerprint": H2,
        "pipeline_hash": H3,
        "capability_profile_id": PROFILE_ID,
        "index_fingerprints": (H4, H5),
        "max_results": 8,
        "max_attempts": 3,
        "embedding_token_estimate": 120,
        "created_for_gap_key": "gap:missing-source",
    }
    values.update(overrides)
    return RetrievalExecutionPlan.create(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("member", "value"),
    [
        (RetrievalMode.LEXICAL, "lexical"),
        (RetrievalMode.VECTOR, "vector"),
        (RetrievalMode.HYBRID_RANK_FUSION, "hybrid_rank_fusion"),
        (RetrievalMode.HYBRID_SCORE_FUSION, "hybrid_score_fusion"),
        (RetrievalMode.NATIVE_RERANK, "native_rerank"),
    ],
)
def test_retrieval_mode_values_are_stable(member: RetrievalMode, value: str) -> None:
    assert member.value == value


@pytest.mark.parametrize(
    ("member", "value"),
    [
        (RetrievalFailureClass.SUCCESS, "success"),
        (RetrievalFailureClass.RATE_LIMITED, "rate_limited"),
        (RetrievalFailureClass.UNSUPPORTED_CAPABILITY, "unsupported_capability"),
        (RetrievalFailureClass.INDEX_UNAVAILABLE, "index_unavailable"),
        (RetrievalFailureClass.SCOPE_VIOLATION, "scope_violation"),
        (RetrievalFailureClass.INVALID_PIPELINE, "invalid_pipeline"),
        (RetrievalFailureClass.INVALID_QUERY, "invalid_query"),
        (RetrievalFailureClass.PROVIDER_TRANSIENT, "provider_transient"),
        (RetrievalFailureClass.PROVIDER_PERMANENT, "provider_permanent"),
        (RetrievalFailureClass.MATERIALIZATION_MISSING, "materialization_missing"),
        (
            RetrievalFailureClass.MATERIALIZATION_IDENTITY_MISMATCH,
            "materialization_identity_mismatch",
        ),
        (
            RetrievalFailureClass.MATERIALIZATION_SCOPE_MISMATCH,
            "materialization_scope_mismatch",
        ),
        (RetrievalFailureClass.MATERIALIZATION_INACTIVE, "materialization_inactive"),
        (
            RetrievalFailureClass.MATERIALIZATION_SOURCE_TYPE_MISMATCH,
            "materialization_source_type_mismatch",
        ),
    ],
)
def test_failure_taxonomy_values_are_stable(
    member: RetrievalFailureClass,
    value: str,
) -> None:
    assert member.value == value


@pytest.mark.parametrize(
    ("member", "value"),
    [
        (ProviderStatusClass.NOT_APPLICABLE, "not_applicable"),
        (ProviderStatusClass.SUCCESS, "success"),
        (ProviderStatusClass.RATE_LIMITED, "rate_limited"),
        (ProviderStatusClass.TRANSIENT_ERROR, "transient_error"),
        (ProviderStatusClass.PERMANENT_ERROR, "permanent_error"),
    ],
)
def test_provider_status_values_are_stable(member: ProviderStatusClass, value: str) -> None:
    assert member.value == value


def test_capability_profile_is_frozen_and_slotted() -> None:
    profile = make_profile()
    assert not hasattr(profile, "__dict__")
    with pytest.raises(FrozenInstanceError):
        profile.lexical_ready = False  # type: ignore[misc]


def test_capability_profile_accepts_current_atlas_shape() -> None:
    profile = make_profile()
    assert profile.server_version == (8, 0, 12)
    assert profile.embedding_model == "voyage-4-lite"
    assert profile.embedding_query_rpm == 30


@pytest.mark.parametrize(
    "field_name",
    [
        "lexical_ready",
        "vector_ready",
        "rank_fusion_supported",
        "score_fusion_supported",
        "native_rerank_supported",
        "native_rerank_enabled",
        "auto_embedding_enabled",
    ],
)
def test_capability_profile_rejects_non_bool_flags(field_name: str) -> None:
    with pytest.raises(CorrectiveRetrievalValidationError):
        make_profile(**{field_name: 1})


@pytest.mark.parametrize(
    "field_name",
    [
        "cluster_fingerprint",
        "lexical_index_fingerprint",
        "vector_index_fingerprint",
        "capability_evidence_hash",
    ],
)
def test_capability_profile_rejects_invalid_hashes(field_name: str) -> None:
    with pytest.raises(CorrectiveRetrievalValidationError):
        make_profile(**{field_name: "not-a-sha256"})


@pytest.mark.parametrize(
    "overrides",
    [
        {"auto_embedding_enabled": True, "embedding_model": None},
        {"auto_embedding_enabled": True, "embedding_query_rpm": None},
        {"auto_embedding_enabled": True, "embedding_query_tpm": None},
        {
            "auto_embedding_enabled": False,
            "embedding_model": "voyage-4-lite",
            "embedding_query_rpm": 30,
            "embedding_query_tpm": 100_000,
        },
    ],
)
def test_capability_profile_enforces_embedding_configuration_coherence(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(CorrectiveRetrievalValidationError):
        make_profile(**overrides)


def test_execution_plan_identity_is_deterministic() -> None:
    first = make_plan()
    second = make_plan()
    assert first == second
    assert first.plan_id == second.plan_id


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        ("space_id", UUID("33333333-3333-3333-3333-333333333333")),
        ("mode", RetrievalMode.LEXICAL),
        ("query_fingerprint", "a" * 64),
        ("semantic_fingerprint", "b" * 64),
        ("pipeline_hash", "c" * 64),
        ("capability_profile_id", UUID("44444444-4444-4444-4444-444444444444")),
        ("index_fingerprints", (H4, "d" * 64)),
        ("max_results", 9),
        ("created_for_gap_key", "gap:other"),
    ],
)
def test_execution_plan_identity_binds_policy_field(field_name: str, replacement: object) -> None:
    baseline = make_plan()
    changed = make_plan(**{field_name: replacement})
    assert changed.plan_id != baseline.plan_id


@pytest.mark.parametrize(
    "field_name",
    ["max_results", "max_attempts", "embedding_token_estimate"],
)
def test_execution_plan_rejects_bool_numeric_inputs(field_name: str) -> None:
    with pytest.raises(CorrectiveRetrievalValidationError):
        make_plan(**{field_name: True})


@pytest.mark.parametrize(
    "value",
    [
        [H4, H5],
        (H4,),
    ],
)
def test_execution_plan_requires_exact_two_fingerprint_tuple(value: object) -> None:
    with pytest.raises(CorrectiveRetrievalValidationError):
        make_plan(index_fingerprints=value)


def test_attempt_result_accepts_consistent_success() -> None:
    plan = make_plan()
    result = RetrievalAttemptResult(
        plan_id=plan.plan_id,
        attempt_number=1,
        mode=plan.mode,
        outcome=RetrievalAttemptOutcome.SUCCESS,
        failure_class=RetrievalFailureClass.SUCCESS,
        query_fingerprint=plan.query_fingerprint,
        pipeline_hash=plan.pipeline_hash,
        capability_profile_id=plan.capability_profile_id,
        index_fingerprints=plan.index_fingerprints,
        returned_count=2,
        admitted_count=1,
        duration_bucket="lt_250ms",
        retry_after_seconds=None,
        provider_status_class=ProviderStatusClass.SUCCESS,
    )
    assert result.failure_class is RetrievalFailureClass.SUCCESS


@pytest.mark.parametrize(
    ("outcome", "failure_class", "provider_status_class", "retry_after_seconds"),
    [
        (
            RetrievalAttemptOutcome.SUCCESS,
            RetrievalFailureClass.PROVIDER_TRANSIENT,
            ProviderStatusClass.TRANSIENT_ERROR,
            None,
        ),
        (
            RetrievalAttemptOutcome.FAILURE,
            RetrievalFailureClass.SUCCESS,
            ProviderStatusClass.SUCCESS,
            None,
        ),
        (
            RetrievalAttemptOutcome.FAILURE,
            RetrievalFailureClass.PROVIDER_TRANSIENT,
            ProviderStatusClass.SUCCESS,
            None,
        ),
        (
            RetrievalAttemptOutcome.FAILURE,
            RetrievalFailureClass.RATE_LIMITED,
            ProviderStatusClass.RATE_LIMITED,
            -1,
        ),
    ],
)
def test_attempt_result_rejects_inconsistent_state(
    outcome: RetrievalAttemptOutcome,
    failure_class: RetrievalFailureClass,
    provider_status_class: ProviderStatusClass,
    retry_after_seconds: int | None,
) -> None:
    plan = make_plan()
    with pytest.raises(CorrectiveRetrievalValidationError):
        RetrievalAttemptResult(
            plan_id=plan.plan_id,
            attempt_number=1,
            mode=plan.mode,
            outcome=outcome,
            failure_class=failure_class,
            query_fingerprint=plan.query_fingerprint,
            pipeline_hash=plan.pipeline_hash,
            capability_profile_id=plan.capability_profile_id,
            index_fingerprints=plan.index_fingerprints,
            returned_count=0,
            admitted_count=0,
            duration_bucket="lt_250ms",
            retry_after_seconds=retry_after_seconds,
            provider_status_class=provider_status_class,
        )


def test_attempt_result_rejects_more_admitted_than_returned() -> None:
    plan = make_plan()
    with pytest.raises(CorrectiveRetrievalValidationError):
        RetrievalAttemptResult(
            plan_id=plan.plan_id,
            attempt_number=1,
            mode=plan.mode,
            outcome=RetrievalAttemptOutcome.FAILURE,
            failure_class=RetrievalFailureClass.INVALID_QUERY,
            query_fingerprint=plan.query_fingerprint,
            pipeline_hash=plan.pipeline_hash,
            capability_profile_id=plan.capability_profile_id,
            index_fingerprints=plan.index_fingerprints,
            returned_count=1,
            admitted_count=2,
            duration_bucket="lt_250ms",
            retry_after_seconds=None,
            provider_status_class=ProviderStatusClass.NOT_APPLICABLE,
        )


def test_privacy_safe_contracts_have_no_raw_payload_fields() -> None:
    forbidden = {
        "query",
        "raw_query",
        "vector",
        "prompt",
        "answer",
        "content",
        "title",
        "source_uri",
        "provider_error_body",
        "score_details",
        "connection_string",
        "hostname",
        "credentials",
    }
    declared = {
        item.name
        for cls in (RetrievalExecutionPlan, RetrievalAttemptResult)
        for item in fields(cls)
    }
    assert declared.isdisjoint(forbidden)


def test_canonical_json_rejects_nonfinite_numbers() -> None:
    for value in (nan, inf, -inf):
        with pytest.raises(CorrectiveRetrievalValidationError):
            canonical_json_sha256({"unsafe": value})


def test_execution_plan_is_frozen_and_slotted() -> None:
    plan = make_plan()
    assert not hasattr(plan, "__dict__")
    with pytest.raises(FrozenInstanceError):
        plan.max_results = 99  # type: ignore[misc]
