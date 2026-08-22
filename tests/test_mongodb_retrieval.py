from __future__ import annotations

from math import inf, nan
from uuid import UUID

import pytest

from nextgen_memory.mongodb_retrieval import (
    MongoResearchIndexConfig,
    build_research_hybrid_pipeline,
)
from nextgen_memory.retrieval import ResearchRetrievalQuery

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")


def test_pipeline_uses_native_rank_fusion_with_scope_safe_search() -> None:
    query = ResearchRetrievalQuery(
        text="memory MoE utility router",
        space_id=SPACE_ID,
        limit=5,
    )

    pipeline = build_research_hybrid_pipeline(query, MongoResearchIndexConfig())

    rank_fusion = pipeline[0]["$rankFusion"]
    semantic_pipeline = rank_fusion["input"]["pipelines"]["semantic"]
    lexical_pipeline = rank_fusion["input"]["pipelines"]["lexical"]
    vector_search = semantic_pipeline[0]["$vectorSearch"]

    assert vector_search["index"] == "rag_autoembed_v1"
    assert vector_search["path"] == "rag_text"
    assert vector_search["query"] == {"text": query.text}
    assert vector_search["filter"] == {
        "space_id": str(query.space_id),
        "status": "active",
    }
    assert vector_search["limit"] == 10
    assert vector_search["numCandidates"] == 50

    lexical_search = lexical_pipeline[0]["$search"]
    assert lexical_search["index"] == "rag_lexical_v2"
    assert "text" not in lexical_search
    assert lexical_search["compound"]["must"] == [
        {
            "text": {
                "query": query.text,
                "path": ["rag_text", "title", "claims_text", "tags"],
            }
        }
    ]
    assert lexical_search["compound"]["filter"] == [
        {"equals": {"path": "space_id", "value": str(query.space_id)}},
        {"equals": {"path": "status", "value": "active"}},
    ]
    assert lexical_pipeline[1] == {"$limit": 10}
    assert len(lexical_pipeline) == 2
    assert rank_fusion["combination"]["weights"] == {
        "semantic": 0.65,
        "lexical": 0.35,
    }
    assert pipeline[1] == {"$limit": 5}
    assert "$project" in pipeline[2]


def test_pipeline_enables_score_details_only_when_requested() -> None:
    query = ResearchRetrievalQuery(
        text="latent memory",
        space_id=SPACE_ID,
        include_score_details=True,
    )

    pipeline = build_research_hybrid_pipeline(query, MongoResearchIndexConfig())

    assert pipeline[0]["$rankFusion"]["scoreDetails"] is True
    assert pipeline[2]["$project"]["score_details"] == {"$meta": "scoreDetails"}


@pytest.mark.parametrize("text", ["", "   "])
def test_query_rejects_blank_text(text: str) -> None:
    with pytest.raises(ValueError, match="text must not be empty"):
        ResearchRetrievalQuery(text=text, space_id=SPACE_ID)


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_query_rejects_invalid_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="limit must be between 1 and 100"):
        ResearchRetrievalQuery(text="memory", space_id=SPACE_ID, limit=limit)


def test_query_rejects_candidate_pool_smaller_than_limit() -> None:
    with pytest.raises(ValueError, match="num_candidates must be greater than or equal to limit"):
        ResearchRetrievalQuery(
            text="memory",
            space_id=SPACE_ID,
            limit=10,
            num_candidates=9,
        )


@pytest.mark.parametrize("weight", [nan, inf, -0.1])
def test_query_rejects_invalid_semantic_weight(weight: float) -> None:
    with pytest.raises(ValueError, match="semantic_weight"):
        ResearchRetrievalQuery(
            text="memory",
            space_id=SPACE_ID,
            semantic_weight=weight,
        )


def test_query_rejects_zero_total_weight() -> None:
    with pytest.raises(ValueError, match="at least one fusion weight must be positive"):
        ResearchRetrievalQuery(
            text="memory",
            space_id=SPACE_ID,
            semantic_weight=0.0,
            lexical_weight=0.0,
        )


class FakeCollection:
    def __init__(self, documents: list[dict[str, object]]) -> None:
        self.documents = documents
        self.pipelines: list[list[dict[str, object]]] = []

    def aggregate(self, pipeline: list[dict[str, object]]):
        self.pipelines.append(pipeline)
        return iter(self.documents)


def test_retriever_maps_documents_to_ranked_immutable_hits() -> None:
    from nextgen_memory.mongodb_retrieval import MongoResearchRetriever

    collection = FakeCollection(
        [
            {
                "_id": "paper:arxiv:2605.21951",
                "memory_id": "4b84a18f-056f-5be9-bd27-a33ef835d29c",
                "title": "Dynamic Mixture of Latent Memories",
                "source_uri": "https://arxiv.org/html/2605.21951v1",
                "tags": ["moe", "latent-memory"],
                "score": 0.0163,
                "score_details": {"value": 0.0163},
            },
            {
                "_id": "paper:arxiv:2608.01739",
                "memory_id": "2d6dc3f4-6fbb-51fb-b271-3ec5d70b70fa",
                "title": "CoEvo-Mem",
                "source_uri": "https://arxiv.org/html/2608.01739",
                "tags": ["router", "utility"],
                "score": 0.0159,
            },
        ]
    )
    retriever = MongoResearchRetriever(collection)
    query = ResearchRetrievalQuery(
        text="memory MoE utility router",
        space_id=SPACE_ID,
        limit=2,
        include_score_details=True,
    )

    hits = retriever.search(query)

    assert len(collection.pipelines) == 1
    assert hits[0].rank == 1
    assert hits[0].memory_id == UUID("4b84a18f-056f-5be9-bd27-a33ef835d29c")
    assert hits[0].backend_ref == "paper:arxiv:2605.21951"
    assert hits[0].tags == ("moe", "latent-memory")
    assert dict(hits[0].score_details or {}) == {"value": 0.0163}
    assert hits[1].rank == 2
    assert hits[1].score_details is None


def test_retriever_rejects_document_without_canonical_uuid() -> None:
    from nextgen_memory.mongodb_retrieval import MongoResearchRetriever

    collection = FakeCollection(
        [
            {
                "_id": "paper:broken",
                "memory_id": "not-a-uuid",
                "title": "Broken",
                "source_uri": "https://example.invalid",
                "score": 0.1,
            }
        ]
    )

    with pytest.raises(ValueError, match="canonical memory_id"):
        MongoResearchRetriever(collection).search(
            ResearchRetrievalQuery(text="memory", space_id=SPACE_ID)
        )


def test_close_is_safe_for_dependency_injected_collection() -> None:
    from nextgen_memory.mongodb_retrieval import MongoResearchRetriever

    retriever = MongoResearchRetriever(FakeCollection([]))

    retriever.close()


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"limit": 5.5}, "limit must be an integer"),
        ({"limit": True}, "limit must be an integer"),
        ({"num_candidates": 50.5}, "num_candidates must be an integer"),
        ({"num_candidates": True}, "num_candidates must be an integer"),
    ],
)
def test_query_rejects_non_integer_atlas_limits(
    kwargs: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ResearchRetrievalQuery(text="memory", space_id=SPACE_ID, **kwargs)


def test_retriever_rejects_document_without_fusion_score() -> None:
    from nextgen_memory.mongodb_retrieval import MongoResearchRetriever

    collection = FakeCollection(
        [
            {
                "_id": "paper:arxiv:2605.21951",
                "memory_id": "4b84a18f-056f-5be9-bd27-a33ef835d29c",
                "title": "Dynamic Mixture of Latent Memories",
                "source_uri": "https://arxiv.org/html/2605.21951v1",
                "tags": ["moe"],
            }
        ]
    )

    with pytest.raises(ValueError, match="fusion score"):
        MongoResearchRetriever(collection).search(
            ResearchRetrievalQuery(text="memory", space_id=SPACE_ID)
        )


def test_retriever_rejects_non_array_tags() -> None:
    from nextgen_memory.mongodb_retrieval import MongoResearchRetriever

    collection = FakeCollection(
        [
            {
                "_id": "paper:arxiv:2605.21951",
                "memory_id": "4b84a18f-056f-5be9-bd27-a33ef835d29c",
                "title": "Dynamic Mixture of Latent Memories",
                "source_uri": "https://arxiv.org/html/2605.21951v1",
                "tags": {"moe": True},
                "score": 0.0163,
            }
        ]
    )

    with pytest.raises(ValueError, match="tags must be an array of strings"):
        MongoResearchRetriever(collection).search(
            ResearchRetrievalQuery(text="memory", space_id=SPACE_ID)
        )
