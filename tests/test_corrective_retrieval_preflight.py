from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest
from nextgen_memory.corrective_retrieval_preflight import (
    CapabilityProbeAuthorization,
    CorrectivePreflightPolicy,
    PreflightReason,
    RetrievalPipelinePreflight,
    pipeline_fingerprint,
)

from nextgen_memory.corrective_retrieval_contracts import (
    RetrievalCapabilityProfile,
    RetrievalFailureClass,
    RetrievalMode,
)

SPACE = UUID("11111111-1111-1111-1111-111111111111")
OTHER_SPACE = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PROFILE_ID = UUID("22222222-2222-2222-2222-222222222222")
OTHER_PROFILE_ID = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
H1, H2, H3, H4, H5 = (char * 64 for char in "12345")

LEX = RetrievalMode.LEXICAL
VEC = RetrievalMode.VECTOR
HYB = RetrievalMode.HYBRID_RANK_FUSION
SCORE = RetrievalMode.HYBRID_SCORE_FUSION
RERANK = RetrievalMode.NATIVE_RERANK
SUCCESS = RetrievalFailureClass.SUCCESS
INVALID = RetrievalFailureClass.INVALID_PIPELINE
SCOPE = RetrievalFailureClass.SCOPE_VIOLATION
UNSUPPORTED = RetrievalFailureClass.UNSUPPORTED_CAPABILITY
UNAVAILABLE = RetrievalFailureClass.INDEX_UNAVAILABLE


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


def make_policy(**overrides: object) -> CorrectivePreflightPolicy:
    values: dict[str, object] = {
        "lexical_index_name": "rag_lexical_v2",
        "vector_index_name": "rag_autoembed_v1",
        "vector_path": "rag_text",
        "max_branch_results": 20,
        "max_num_candidates": 200,
        "active_status": "active",
        "required_source_type": "paper",
    }
    values.update(overrides)
    return CorrectivePreflightPolicy(**values)  # type: ignore[arg-type]


def eq(path: str, value: object) -> dict[str, object]:
    return {"equals": {"path": path, "value": value}}


def lexical_pipeline(query: str = "bounded corrective query") -> list[dict[str, object]]:
    return [
        {
            "$search": {
                "index": "rag_lexical_v2",
                "compound": {
                    "must": [{"text": {"query": query, "path": ["rag_text", "title"]}}],
                    "filter": [
                        eq("space_id", str(SPACE)),
                        eq("status", "active"),
                        eq("source_type", "paper"),
                    ],
                },
            }
        },
        {"$limit": 8},
    ]


def vector_pipeline(query: str = "bounded corrective query") -> list[dict[str, object]]:
    return [
        {
            "$vectorSearch": {
                "index": "rag_autoembed_v1",
                "path": "rag_text",
                "query": {"text": query},
                "numCandidates": 32,
                "limit": 8,
                "filter": {
                    "space_id": str(SPACE),
                    "status": "active",
                    "source_type": "paper",
                },
            }
        }
    ]


def hybrid_pipeline(query: str = "bounded corrective query") -> list[dict[str, object]]:
    return [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "semantic": vector_pipeline(query),
                        "lexical": lexical_pipeline(query),
                    }
                },
                "combination": {"weights": {"semantic": 0.5, "lexical": 0.5}},
            }
        },
        {"$limit": 8},
    ]


def score_pipeline() -> list[dict[str, object]]:
    pipeline = hybrid_pipeline()
    pipeline[0] = {"$scoreFusion": pipeline[0]["$rankFusion"]}
    return pipeline


def rerank_pipeline() -> list[dict[str, object]]:
    return [{"$rerank": {"input": lexical_pipeline()}}, {"$limit": 8}]


def audit(
    pipeline: object,
    mode: RetrievalMode,
    *,
    profile: RetrievalCapabilityProfile | None = None,
    policy: CorrectivePreflightPolicy | None = None,
    authorization: CapabilityProbeAuthorization | None = None,
):
    return RetrievalPipelinePreflight.audit(
        pipeline,
        mode=mode,
        space_id=SPACE,
        profile=profile or make_profile(),
        policy=policy or make_policy(),
        probe_authorization=authorization,
    )


def lex_filters(pipeline: list[dict[str, object]]) -> list[object]:
    search = pipeline[0]["$search"]
    assert isinstance(search, dict)
    compound = search["compound"]
    assert isinstance(compound, dict)
    filters = compound["filter"]
    assert isinstance(filters, list)
    return filters


def vec_body(pipeline: list[dict[str, object]]) -> dict[str, object]:
    body = pipeline[0]["$vectorSearch"]
    assert isinstance(body, dict)
    return body


def branches(pipeline: list[dict[str, object]]) -> dict[str, object]:
    fusion = pipeline[0]["$rankFusion"]
    assert isinstance(fusion, dict)
    fusion_input = fusion["input"]
    assert isinstance(fusion_input, dict)
    value = fusion_input["pipelines"]
    assert isinstance(value, dict)
    return value


def remove_lex_filter(pipeline: list[dict[str, object]], field: str) -> None:
    filters = lex_filters(pipeline)
    filters[:] = [
        item
        for item in filters
        if not (
            isinstance(item, dict)
            and isinstance(item.get("equals"), dict)
            and item["equals"].get("path") == field
        )
    ]


def set_lex_filter(pipeline: list[dict[str, object]], field: str, value: object) -> None:
    for item in lex_filters(pipeline):
        if (
            isinstance(item, dict)
            and isinstance(item.get("equals"), dict)
            and item["equals"].get("path") == field
        ):
            item["equals"]["value"] = value
            return
    raise AssertionError(field)


def bad_scope_value(field: str) -> object:
    return {
        "space_id": str(OTHER_SPACE),
        "status": "inactive",
        "source_type": "other",
    }[field]


def authorization(**overrides: object) -> CapabilityProbeAuthorization:
    values: dict[str, object] = {
        "profile_id": PROFILE_ID,
        "mode": HYB,
        "cluster_fingerprint": H1,
        "lexical_index_fingerprint": H2,
        "vector_index_fingerprint": H3,
        "pipeline_hash": pipeline_fingerprint(hybrid_pipeline()),
    }
    values.update(overrides)
    return CapabilityProbeAuthorization(**values)  # type: ignore[arg-type]


# Ten contract/validity tests.
def test_policy_is_frozen_and_slotted() -> None:
    policy = make_policy()
    assert not hasattr(policy, "__dict__")
    with pytest.raises(FrozenInstanceError):
        policy.max_branch_results = 99  # type: ignore[misc]


def test_authorization_is_frozen_and_slotted() -> None:
    value = authorization()
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.pipeline_hash = H5  # type: ignore[misc]


def test_decision_is_frozen_and_slotted() -> None:
    decision = audit(lexical_pipeline(), LEX)
    assert not hasattr(decision, "__dict__")
    with pytest.raises(FrozenInstanceError):
        decision.allowed = False  # type: ignore[misc]


def test_valid_lexical_allowed() -> None:
    decision = audit(lexical_pipeline(), LEX)
    assert decision.allowed
    assert decision.failure_class is SUCCESS
    assert decision.reason is PreflightReason.ALLOWED
    assert not decision.embedding_bearing


def test_valid_vector_allowed() -> None:
    decision = audit(vector_pipeline(), VEC)
    assert decision.allowed
    assert decision.failure_class is SUCCESS
    assert decision.embedding_bearing


def test_valid_hybrid_allowed() -> None:
    decision = audit(hybrid_pipeline(), HYB)
    assert decision.allowed
    assert decision.failure_class is SUCCESS
    assert decision.embedding_bearing


def test_pipeline_fingerprint_is_deterministic() -> None:
    pipeline = hybrid_pipeline()
    assert pipeline_fingerprint(pipeline) == pipeline_fingerprint(deepcopy(pipeline))


def test_audit_does_not_mutate_input() -> None:
    pipeline = hybrid_pipeline()
    before = deepcopy(pipeline)
    audit(pipeline, HYB)
    assert pipeline == before


def test_decision_repr_excludes_raw_query() -> None:
    sentinel = "secret-query-never-in-decision"
    assert sentinel not in repr(audit(hybrid_pipeline(sentinel), HYB))


def test_failure_reason_is_bounded_enum() -> None:
    pipeline = lexical_pipeline()
    remove_lex_filter(pipeline, "space_id")
    assert isinstance(audit(pipeline, LEX).reason, PreflightReason)


# Twelve policy validation tests.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_branch_results", True),
        ("max_branch_results", 0),
        ("max_branch_results", -1),
        ("max_num_candidates", True),
        ("max_num_candidates", 0),
        ("max_num_candidates", -1),
        ("lexical_index_name", ""),
        ("vector_index_name", " "),
        ("vector_path", ""),
        ("active_status", ""),
        ("required_source_type", ""),
        ("lexical_index_name", 1),
    ],
)
def test_policy_rejects_invalid_values(field: str, value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        make_policy(**{field: value})


# Ten capability-gate tests.
@pytest.mark.parametrize(
    ("mode", "pipeline", "profile", "failure"),
    [
        (LEX, lexical_pipeline(), make_profile(lexical_ready=False), UNAVAILABLE),
        (VEC, vector_pipeline(), make_profile(vector_ready=False), UNAVAILABLE),
        (HYB, hybrid_pipeline(), make_profile(lexical_ready=False), UNAVAILABLE),
        (HYB, hybrid_pipeline(), make_profile(vector_ready=False), UNAVAILABLE),
        (
            VEC,
            vector_pipeline(),
            make_profile(
                auto_embedding_enabled=False,
                embedding_model=None,
                embedding_query_rpm=None,
                embedding_query_tpm=None,
            ),
            UNSUPPORTED,
        ),
        (
            HYB,
            hybrid_pipeline(),
            make_profile(
                auto_embedding_enabled=False,
                embedding_model=None,
                embedding_query_rpm=None,
                embedding_query_tpm=None,
            ),
            UNSUPPORTED,
        ),
        (HYB, hybrid_pipeline(), make_profile(rank_fusion_supported=False), UNSUPPORTED),
        (SCORE, score_pipeline(), make_profile(score_fusion_supported=False), UNSUPPORTED),
        (RERANK, rerank_pipeline(), make_profile(native_rerank_supported=False), UNSUPPORTED),
        (
            RERANK,
            rerank_pipeline(),
            make_profile(native_rerank_supported=True, native_rerank_enabled=False),
            UNSUPPORTED,
        ),
    ],
)
def test_capability_gates_fail_closed(
    mode: RetrievalMode,
    pipeline: object,
    profile: RetrievalCapabilityProfile,
    failure: RetrievalFailureClass,
) -> None:
    decision = audit(pipeline, mode, profile=profile)
    assert not decision.allowed
    assert decision.failure_class is failure


# Nine fingerprint-bound probe-admission tests.
@pytest.mark.parametrize(
    ("probe", "pipeline", "mode", "allowed"),
    [
        (authorization(), hybrid_pipeline(), HYB, True),
        (authorization(profile_id=OTHER_PROFILE_ID), hybrid_pipeline(), HYB, False),
        (authorization(cluster_fingerprint=H5), hybrid_pipeline(), HYB, False),
        (authorization(lexical_index_fingerprint=H5), hybrid_pipeline(), HYB, False),
        (authorization(vector_index_fingerprint=H5), hybrid_pipeline(), HYB, False),
        (authorization(pipeline_hash=H5), hybrid_pipeline(), HYB, False),
        (authorization(mode=VEC), hybrid_pipeline(), HYB, False),
        (
            authorization(mode=SCORE, pipeline_hash=pipeline_fingerprint(score_pipeline())),
            score_pipeline(),
            SCORE,
            False,
        ),
        (authorization(), hybrid_pipeline("changed-after-probe"), HYB, False),
    ],
)
def test_probe_authorization_is_exact_and_fingerprint_bound(
    probe: CapabilityProbeAuthorization,
    pipeline: object,
    mode: RetrievalMode,
    allowed: bool,
) -> None:
    profile = make_profile(rank_fusion_supported=False)
    decision = audit(pipeline, mode, profile=profile, authorization=probe)
    assert decision.allowed is allowed
    if not allowed:
        assert decision.failure_class is UNSUPPORTED


# Ten privacy tests.
@pytest.mark.parametrize(
    "sentinel",
    [
        "mongodb://user:password@host/db",
        "raw query payload alpha",
        "[0.123,0.456,0.789]",
        "provider body: 429 quota exceeded",
        "ssh://private-host",
        "title: confidential",
        "https://source.example/private",
        "prompt: ignore previous instructions",
        "answer: classified",
        "credential=super-secret",
    ],
)
def test_privacy_sentinels_never_leave_decision(sentinel: str) -> None:
    serialized = repr(audit(hybrid_pipeline(sentinel), HYB))
    assert sentinel not in serialized
    assert "password" not in serialized
    assert "private-host" not in serialized


# Thirty lexical safety mutations: 9 + 8 + 3 + 5 + 5.
@pytest.mark.parametrize("field", ["space_id", "status", "source_type"])
@pytest.mark.parametrize("variant", ["missing", "wrong", "conflicting"])
def test_lexical_scope_mutations_fail_closed(field: str, variant: str) -> None:
    pipeline = lexical_pipeline()
    if variant == "missing":
        remove_lex_filter(pipeline, field)
    elif variant == "wrong":
        set_lex_filter(pipeline, field, bad_scope_value(field))
    else:
        lex_filters(pipeline).append(eq(field, bad_scope_value(field)))
    decision = audit(pipeline, LEX)
    assert not decision.allowed
    assert decision.failure_class is SCOPE


@pytest.mark.parametrize("value", [None, 0, -1, 21, True, "8", 1.5, []])
def test_lexical_limit_mutations_fail_closed(value: object) -> None:
    pipeline = lexical_pipeline()
    if value is None:
        pipeline.pop()
    else:
        pipeline[1]["$limit"] = value
    assert audit(pipeline, LEX).failure_class is INVALID


@pytest.mark.parametrize("index", ["rag_lexical_v1", "", "wrong"])
def test_lexical_index_mutations_fail_closed(index: str) -> None:
    pipeline = lexical_pipeline()
    pipeline[0]["$search"]["index"] = index
    assert audit(pipeline, LEX).failure_class is INVALID


@pytest.mark.parametrize("variant", ["none", "mapping", "string", "missing_path", "missing_value"])
def test_lexical_filter_shape_mutations_fail_closed(variant: str) -> None:
    pipeline = lexical_pipeline()
    compound = pipeline[0]["$search"]["compound"]
    if variant == "none":
        compound["filter"] = None
    elif variant == "mapping":
        compound["filter"] = {}
    elif variant == "string":
        lex_filters(pipeline).append("bad")
    elif variant == "missing_path":
        lex_filters(pipeline).append({"equals": {"value": "x"}})
    else:
        lex_filters(pipeline).append({"equals": {"path": "x"}})
    assert audit(pipeline, LEX).failure_class is INVALID


@pytest.mark.parametrize(
    "variant",
    ["ranking_not_first", "unknown", "multi_key", "bad_body", "bad_compound"],
)
def test_lexical_stage_shape_mutations_fail_closed(variant: str) -> None:
    pipeline = lexical_pipeline()
    if variant == "ranking_not_first":
        pipeline.insert(0, {"$match": {"space_id": str(SPACE)}})
    elif variant == "unknown":
        pipeline.insert(1, {"$unknown": {}})
    elif variant == "multi_key":
        pipeline[0]["$limit"] = 8
    elif variant == "bad_body":
        pipeline[0]["$search"] = "bad"
    else:
        pipeline[0]["$search"]["compound"] = "bad"
    assert audit(pipeline, LEX).failure_class is INVALID


# Thirty vector safety mutations: 6 + 7 + 7 + 4 + 3 + 3.
@pytest.mark.parametrize("field", ["space_id", "status", "source_type"])
@pytest.mark.parametrize("variant", ["missing", "wrong"])
def test_vector_scope_mutations_fail_closed(field: str, variant: str) -> None:
    pipeline = vector_pipeline()
    scope = vec_body(pipeline)["filter"]
    assert isinstance(scope, dict)
    if variant == "missing":
        del scope[field]
    else:
        scope[field] = bad_scope_value(field)
    assert audit(pipeline, VEC).failure_class is SCOPE


@pytest.mark.parametrize("value", [None, 0, -1, 21, True, "8", 1.5])
def test_vector_limit_mutations_fail_closed(value: object) -> None:
    pipeline = vector_pipeline()
    body = vec_body(pipeline)
    if value is None:
        del body["limit"]
    else:
        body["limit"] = value
    assert audit(pipeline, VEC).failure_class is INVALID


@pytest.mark.parametrize("value", [None, 0, -1, 201, True, "32", 1.5])
def test_vector_candidate_mutations_fail_closed(value: object) -> None:
    pipeline = vector_pipeline()
    body = vec_body(pipeline)
    if value is None:
        del body["numCandidates"]
    else:
        body["numCandidates"] = value
    assert audit(pipeline, VEC).failure_class is INVALID


@pytest.mark.parametrize(
    ("field", "value"),
    [("index", "wrong"), ("index", ""), ("path", "wrong"), ("path", "")],
)
def test_vector_index_path_mutations_fail_closed(field: str, value: str) -> None:
    pipeline = vector_pipeline()
    vec_body(pipeline)[field] = value
    assert audit(pipeline, VEC).failure_class is INVALID


@pytest.mark.parametrize("value", [None, [], "bad"])
def test_vector_filter_shape_mutations_fail_closed(value: object) -> None:
    pipeline = vector_pipeline()
    vec_body(pipeline)["filter"] = value
    assert audit(pipeline, VEC).failure_class is INVALID


@pytest.mark.parametrize("variant", ["ranking_not_first", "multi_key", "bad_body"])
def test_vector_stage_shape_mutations_fail_closed(variant: str) -> None:
    pipeline = vector_pipeline()
    if variant == "ranking_not_first":
        pipeline.insert(0, {"$match": {"space_id": str(SPACE)}})
    elif variant == "multi_key":
        pipeline[0]["$limit"] = 8
    else:
        pipeline[0]["$vectorSearch"] = "bad"
    assert audit(pipeline, VEC).failure_class is INVALID


# Thirty hybrid safety mutations: 12 + 8 + 5 + 5.
@pytest.mark.parametrize("branch", ["lexical", "semantic"])
@pytest.mark.parametrize("field", ["space_id", "status", "source_type"])
@pytest.mark.parametrize("variant", ["missing", "wrong"])
def test_hybrid_branch_scope_mutations_fail_closed(
    branch: str,
    field: str,
    variant: str,
) -> None:
    pipeline = hybrid_pipeline()
    branch_pipeline = branches(pipeline)[branch]
    assert isinstance(branch_pipeline, list)
    if branch == "lexical":
        if variant == "missing":
            remove_lex_filter(branch_pipeline, field)
        else:
            set_lex_filter(branch_pipeline, field, bad_scope_value(field))
    else:
        scope = vec_body(branch_pipeline)["filter"]
        assert isinstance(scope, dict)
        if variant == "missing":
            del scope[field]
        else:
            scope[field] = bad_scope_value(field)
    assert audit(pipeline, HYB).failure_class is SCOPE


@pytest.mark.parametrize(
    "variant",
    [
        "missing_lexical",
        "missing_semantic",
        "extra_branch",
        "pipelines_type",
        "missing_input",
        "input_type",
        "lexical_type",
        "semantic_type",
    ],
)
def test_hybrid_branch_structure_mutations_fail_closed(variant: str) -> None:
    pipeline = hybrid_pipeline()
    if variant == "missing_input":
        del pipeline[0]["$rankFusion"]["input"]
    elif variant == "input_type":
        pipeline[0]["$rankFusion"]["input"] = "bad"
    elif variant == "pipelines_type":
        pipeline[0]["$rankFusion"]["input"]["pipelines"] = []
    else:
        value = branches(pipeline)
        if variant == "missing_lexical":
            del value["lexical"]
        elif variant == "missing_semantic":
            del value["semantic"]
        elif variant == "extra_branch":
            value["extra"] = lexical_pipeline()
        elif variant == "lexical_type":
            value["lexical"] = {}
        else:
            value["semantic"] = {}
    assert audit(pipeline, HYB).failure_class is INVALID


@pytest.mark.parametrize(
    "variant",
    ["lexical_index", "vector_index", "vector_path", "lexical_limit", "vector_limit"],
)
def test_hybrid_branch_contract_mutations_fail_closed(variant: str) -> None:
    pipeline = hybrid_pipeline()
    value = branches(pipeline)
    lexical = value["lexical"]
    semantic = value["semantic"]
    assert isinstance(lexical, list)
    assert isinstance(semantic, list)
    if variant == "lexical_index":
        lexical[0]["$search"]["index"] = "rag_lexical_v1"
    elif variant == "vector_index":
        vec_body(semantic)["index"] = "wrong"
    elif variant == "vector_path":
        vec_body(semantic)["path"] = "wrong"
    elif variant == "lexical_limit":
        lexical.pop()
    else:
        del vec_body(semantic)["limit"]
    assert audit(pipeline, HYB).failure_class is INVALID


@pytest.mark.parametrize(
    "variant",
    ["missing_limit", "zero_limit", "unknown", "multi_key", "bad_fusion_body"],
)
def test_hybrid_top_level_mutations_fail_closed(variant: str) -> None:
    pipeline = hybrid_pipeline()
    if variant == "missing_limit":
        pipeline.pop()
    elif variant == "zero_limit":
        pipeline[1]["$limit"] = 0
    elif variant == "unknown":
        pipeline.append({"$unknown": {}})
    elif variant == "multi_key":
        pipeline[0]["$limit"] = 8
    else:
        pipeline[0]["$rankFusion"] = "bad"
    assert audit(pipeline, HYB).failure_class is INVALID
