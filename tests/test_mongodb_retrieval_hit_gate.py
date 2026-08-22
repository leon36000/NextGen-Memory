from __future__ import annotations

from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest

from nextgen_memory.mongodb_retrieval import (
    MongoResearchIndexConfig,
    MongoResearchRetriever,
    build_research_hybrid_pipeline,
)
from nextgen_memory.retrieval import ResearchRetrievalQuery

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
MEMORY_A = UUID("4b84a18f-056f-5be9-bd27-a33ef835d29c")
MEMORY_B = UUID("2d6dc3f4-6fbb-51fb-b271-3ec5d70b70fa")


def query(*, limit: int = 2) -> ResearchRetrievalQuery:
    return ResearchRetrievalQuery(
        text="memory MoE utility router",
        space_id=SPACE_ID,
        limit=limit,
    )


def document(
    *,
    memory_id: UUID = MEMORY_A,
    backend_ref: str = "paper:arxiv:2605.21951",
    **overrides: object,
) -> dict[str, object]:
    values: dict[str, object] = {
        "_id": backend_ref,
        "memory_id": str(memory_id),
        "space_id": str(SPACE_ID),
        "status": "active",
        "source_type": "paper",
        "title": "Dynamic Mixture of Latent Memories",
        "source_uri": "https://arxiv.org/html/2605.21951v1",
        "tags": ["moe", "latent-memory"],
        "score": 0.0163,
    }
    values.update(overrides)
    return values


class FakeCollection:
    def __init__(self, documents: list[object]) -> None:
        self.documents = documents
        self.pipelines: list[list[dict[str, object]]] = []

    def aggregate(self, pipeline: list[dict[str, object]]):
        self.pipelines.append(pipeline)
        return iter(self.documents)


def test_config_declares_and_normalizes_required_research_source_type() -> None:
    config = MongoResearchIndexConfig()

    assert getattr(config, "source_type", None) == "paper"
    assert config.active_status == "active"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"active_status": ""},
        {"active_status": "   "},
        {"source_type": ""},
        {"source_type": "   "},
    ],
)
def test_config_rejects_blank_lifecycle_policy(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        MongoResearchIndexConfig(**kwargs)  # type: ignore[arg-type]


def test_pipeline_filters_and_projects_scope_lifecycle_and_source_type() -> None:
    config = MongoResearchIndexConfig()
    pipeline = build_research_hybrid_pipeline(query(), config)

    rank_fusion = pipeline[0]["$rankFusion"]
    semantic = rank_fusion["input"]["pipelines"]["semantic"]
    lexical = rank_fusion["input"]["pipelines"]["lexical"]

    assert semantic[0]["$vectorSearch"]["filter"] == {
        "space_id": str(SPACE_ID),
        "status": "active",
        "source_type": "paper",
    }
    assert lexical[0]["$search"]["compound"]["filter"] == [
        {"equals": {"path": "space_id", "value": str(SPACE_ID)}},
        {"equals": {"path": "status", "value": "active"}},
        {"equals": {"path": "source_type", "value": "paper"}},
    ]
    projection = pipeline[2]["$project"]
    assert projection["space_id"] == 1
    assert projection["status"] == 1
    assert projection["source_type"] == 1


def test_valid_document_passes_the_canonical_hit_gate() -> None:
    collection = FakeCollection(
        [
            document(),
            document(
                memory_id=MEMORY_B,
                backend_ref="paper:arxiv:2608.01739",
                title="CoEvo-Mem",
                score=0.0159,
            ),
        ]
    )

    hits = MongoResearchRetriever(collection).search(query())

    assert [hit.memory_id for hit in hits] == [MEMORY_A, MEMORY_B]
    assert [hit.backend_ref for hit in hits] == [
        "paper:arxiv:2605.21951",
        "paper:arxiv:2608.01739",
    ]
    assert [hit.rank for hit in hits] == [1, 2]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"space_id": None}, "space_id"),
        ({"space_id": "not-a-uuid"}, "space_id"),
        ({"space_id": str(uuid4())}, "space_id"),
        ({"status": None}, "status"),
        ({"status": "inactive"}, "status"),
        ({"source_type": None}, "source_type"),
        ({"source_type": "repository"}, "source_type"),
    ],
)
def test_scope_lifecycle_or_source_type_mismatch_fails_closed(
    overrides: dict[str, object],
    message: str,
) -> None:
    collection = FakeCollection([document(**overrides)])

    with pytest.raises(ValueError, match=message):
        MongoResearchRetriever(collection).search(query())


def test_non_mapping_backend_row_fails_closed() -> None:
    collection = FakeCollection([object()])

    with pytest.raises(ValueError, match="mapping"):
        MongoResearchRetriever(collection).search(query())


def test_backend_cannot_return_more_hits_than_query_limit() -> None:
    collection = FakeCollection(
        [
            document(),
            document(
                memory_id=MEMORY_B,
                backend_ref="paper:arxiv:2608.01739",
            ),
        ]
    )

    with pytest.raises(ValueError, match="exceeds query limit"):
        MongoResearchRetriever(collection).search(query(limit=1))


def test_duplicate_canonical_memory_identity_fails_closed() -> None:
    collection = FakeCollection(
        [
            document(),
            document(backend_ref="paper:duplicate-memory"),
        ]
    )

    with pytest.raises(ValueError, match="duplicate memory_id"):
        MongoResearchRetriever(collection).search(query())


def test_duplicate_backend_reference_fails_closed() -> None:
    collection = FakeCollection(
        [
            document(),
            document(memory_id=MEMORY_B),
        ]
    )

    with pytest.raises(ValueError, match="duplicate backend_ref"):
        MongoResearchRetriever(collection).search(query())


def test_gate_error_does_not_echo_raw_query_or_document_payload() -> None:
    sentinel_query = "private raw query with secret-token"
    sentinel_title = "private document body secret-token"
    collection = FakeCollection(
        [document(space_id=str(uuid4()), title=sentinel_title)]
    )

    with pytest.raises(ValueError) as exc_info:
        MongoResearchRetriever(collection).search(
            ResearchRetrievalQuery(
                text=sentinel_query,
                space_id=SPACE_ID,
                limit=1,
            )
        )

    message = str(exc_info.value)
    assert sentinel_query not in message
    assert sentinel_title not in message
    assert "secret-token" not in message


def test_public_hit_contract_does_not_expose_gate_fields() -> None:
    hit = MongoResearchRetriever(FakeCollection([document()])).search(query(limit=1))[0]

    assert isinstance(hit.__class__.__dataclass_fields__, Mapping)
    assert "space_id" not in hit.__class__.__dataclass_fields__
    assert "status" not in hit.__class__.__dataclass_fields__
    assert "source_type" not in hit.__class__.__dataclass_fields__
