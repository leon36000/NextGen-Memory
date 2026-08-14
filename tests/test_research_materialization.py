from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any
from uuid import UUID

import pytest

from nextgen_memory.context_compiler import ContextCompileRequest
from nextgen_memory.domain import (
    EvidenceNeed,
    RoutingRequest,
    RoutingScope,
    TaskKind,
)
from nextgen_memory.research_read_pipeline import (
    RESEARCH_METADATA_SELECT_SQL,
    CrossStoreResearchMaterializer,
    MongoResearchDocumentReader,
    NeonResearchMetadataReader,
    ResearchMaterializationError,
    ResearchMemoryMetadata,
    ResearchReadRequest,
    ResearchReadValidationError,
    ResearchSourceDocument,
)
from nextgen_memory.retrieval import ResearchRetrievalHit, ResearchRetrievalQuery
from nextgen_memory.utility_reranker import (
    RerankedMemory,
    UtilityEvidence,
    UtilityScoreBreakdown,
)

SPACE = UUID("11111111-1111-1111-1111-111111111111")
OTHER_SPACE = UUID("22222222-2222-2222-2222-222222222222")
MEMORY_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
MEMORY_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
NOW = datetime(2026, 8, 14, 18, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64


def read_request(**overrides: object) -> ResearchReadRequest:
    values: dict[str, object] = {
        "routing_request": RoutingRequest(
            query="compare memory routing architectures",
            scope=RoutingScope(
                space_id=SPACE,
                project_key="nextgen-memory",
                permissions=frozenset({"memory:read"}),
            ),
            task_kind=TaskKind.RESEARCH,
            needs=frozenset({EvidenceNeed.RESEARCH}),
            token_budget=1500,
        ),
        "retrieval_query": ResearchRetrievalQuery(
            text="compare memory routing architectures",
            space_id=SPACE,
            limit=5,
        ),
        "compile_request": ContextCompileRequest(
            space_id=SPACE,
            token_budget=700,
            envelope_tokens=100,
            required_coverage_keys=("router",),
        ),
        "mandatory_memory_ids": (),
        "coverage_aliases": {"hybrid-retrieval": ("router",)},
        "active_status": "active",
    }
    values.update(overrides)
    return ResearchReadRequest(**values)


def hit(
    memory_id: UUID = MEMORY_A,
    *,
    backend_ref: str = "paper:a",
    title: str = "Paper A",
    source_uri: str = "https://example.invalid/a",
    tags: tuple[str, ...] = ("hybrid-retrieval", "memory"),
    rank: int = 1,
    score: float = 0.9,
) -> ResearchRetrievalHit:
    return ResearchRetrievalHit(
        memory_id=memory_id,
        backend_ref=backend_ref,
        title=title,
        source_uri=source_uri,
        source_type="paper",
        year=2026,
        tags=tags,
        score=score,
        rank=rank,
    )


def reranked(item: ResearchRetrievalHit | None = None) -> RerankedMemory:
    item = item or hit()
    return RerankedMemory(
        hit=item,
        final_rank=item.rank,
        final_score=0.8 if item.rank == 1 else 0.7,
        score_breakdown=UtilityScoreBreakdown(
            relevance_component=0.7,
            reward_component=0.1,
            verdict_component=0.05,
            harm_penalty=0.0,
            token_penalty=0.01,
            latency_penalty=0.01,
            final_score=0.8 if item.rank == 1 else 0.7,
        ),
        utility_evidence=UtilityEvidence(
            memory_id=item.memory_id,
            feedback_count=3,
            avg_reward=0.4,
            positive_count=2,
            negative_count=0,
            last_feedback_at=NOW,
        ),
    )


def metadata_row(memory_id: UUID = MEMORY_A, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "memory_id": memory_id,
        "space_id": SPACE,
        "subject_key": "research.memory-routing",
        "expert_keys": ["research", "semantic"],
        "confidence": 0.85,
        "authority": 0.9,
        "content_hash": HASH_A if memory_id == MEMORY_A else HASH_B,
        "sensitivity": "public",
        "valid_from": None,
        "valid_to": None,
    }
    values.update(overrides)
    return values


def document_row(memory_id: UUID = MEMORY_A, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "_id": "paper:a" if memory_id == MEMORY_A else "paper:b",
        "memory_id": str(memory_id),
        "space_id": str(SPACE),
        "status": "active",
        "source_type": "paper",
        "title": "Paper A" if memory_id == MEMORY_A else "Paper B",
        "source_uri": (
            "https://example.invalid/a"
            if memory_id == MEMORY_A
            else "https://example.invalid/b"
        ),
        "authors": ["Researcher"],
        "claims": [{"text": "Claim one."}],
        "claims_text": "Claim one.",
        "tags": ["hybrid-retrieval", "memory"],
        "rag_text": "Paper A\nClaim one.\nTags: hybrid-retrieval, memory",
        "provenance": {"retriever": "Exa", "canonical_source": "arXiv"},
    }
    values.update(overrides)
    return values


class FakeCursor:
    def __init__(self, rows: Iterable[Mapping[str, Any]]) -> None:
        self.rows = list(rows)
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def execute(self, sql: str, params: Mapping[str, Any]) -> None:
        self.calls.append((sql, params))

    def fetchall(self) -> Iterable[Mapping[str, Any]]:
        return list(self.rows)


class FakeCollection:
    def __init__(self, documents: Iterable[Mapping[str, Any]]) -> None:
        self.documents = list(documents)
        self.calls: list[tuple[Mapping[str, Any], Mapping[str, int]]] = []

    def find(
        self,
        filter: Mapping[str, Any],
        projection: Mapping[str, int],
    ) -> Iterable[Mapping[str, Any]]:
        self.calls.append((filter, projection))
        return list(self.documents)


class FakeMetadataProvider:
    def __init__(self, rows: Mapping[UUID, ResearchMemoryMetadata]) -> None:
        self.rows = rows
        self.calls: list[tuple[UUID, tuple[UUID, ...]]] = []

    def fetch(
        self,
        *,
        space_id: UUID,
        memory_ids: Sequence[UUID],
    ) -> Mapping[UUID, ResearchMemoryMetadata]:
        self.calls.append((space_id, tuple(memory_ids)))
        return self.rows


class FakeDocumentProvider:
    def __init__(self, rows: Mapping[UUID, ResearchSourceDocument]) -> None:
        self.rows = rows
        self.calls: list[
            tuple[UUID, tuple[str, ...], tuple[UUID, ...], str]
        ] = []

    def fetch(
        self,
        *,
        space_id: UUID,
        backend_refs: Sequence[str],
        memory_ids: Sequence[UUID],
        active_status: str,
    ) -> Mapping[UUID, ResearchSourceDocument]:
        self.calls.append(
            (
                space_id,
                tuple(backend_refs),
                tuple(memory_ids),
                active_status,
            )
        )
        return self.rows


class FixedEstimator:
    def __init__(self, tokens: int = 120) -> None:
        self.tokens = tokens
        self.calls: list[str] = []

    def estimate(self, content: str) -> int:
        self.calls.append(content)
        return self.tokens


def metadata(memory_id: UUID = MEMORY_A, **overrides: object) -> ResearchMemoryMetadata:
    values: dict[str, object] = {
        "memory_id": memory_id,
        "space_id": SPACE,
        "subject_key": "research.memory-routing",
        "expert_keys": ("research", "semantic"),
        "confidence": 0.85,
        "authority": 0.9,
        "canonical_content_hash": HASH_A if memory_id == MEMORY_A else HASH_B,
        "sensitivity": "public",
        "valid_from": None,
        "valid_to": None,
    }
    values.update(overrides)
    return ResearchMemoryMetadata(**values)


def document(memory_id: UUID = MEMORY_A, **overrides: object) -> ResearchSourceDocument:
    row = document_row(memory_id)
    row.update(overrides)
    return ResearchSourceDocument.from_mapping(row)


def test_metadata_contract_normalizes_and_validates_canonical_fields() -> None:
    item = metadata(
        subject_key=" research.memory-routing ",
        expert_keys=(" semantic ", "research", "research"),
        sensitivity=" PUBLIC ",
    )

    assert item.subject_key == "research.memory-routing"
    assert item.expert_keys == ("research", "semantic")
    assert item.sensitivity == "public"
    assert item.is_valid_at(NOW)


@pytest.mark.parametrize(
    "overrides",
    [
        {"subject_key": " "},
        {"expert_keys": ("semantic",)},
        {"confidence": -0.1},
        {"confidence": 1.1},
        {"authority": float("nan")},
        {"canonical_content_hash": "bad"},
        {"sensitivity": "unknown"},
        {"valid_from": datetime(2026, 8, 14)},
        {"valid_from": NOW, "valid_to": NOW - timedelta(seconds=1)},
    ],
)
def test_metadata_contract_rejects_malformed_rows(overrides: dict[str, object]) -> None:
    with pytest.raises(ResearchReadValidationError):
        metadata(**overrides)


def test_document_contract_maps_live_atlas_shape_and_freezes_provenance() -> None:
    item = ResearchSourceDocument.from_mapping(document_row())

    assert item.backend_ref == "paper:a"
    assert item.memory_id == MEMORY_A
    assert item.tags == ("hybrid-retrieval", "memory")
    assert item.claims == ("Claim one.",)
    assert item.rag_text.startswith("Paper A")
    assert isinstance(item.provenance, MappingProxyType)
    with pytest.raises(TypeError):
        item.provenance["x"] = "y"  # type: ignore[index]


@pytest.mark.parametrize(
    "overrides",
    [
        {"_id": " "},
        {"memory_id": "bad"},
        {"space_id": "bad"},
        {"status": " "},
        {"source_type": " "},
        {"title": " "},
        {"source_uri": " "},
        {"authors": [1]},
        {"claims": [{"missing": "text"}]},
        {"tags": ["memory", " "]},
        {"rag_text": " "},
        {"provenance": []},
    ],
)
def test_document_contract_rejects_malformed_atlas_shape(
    overrides: dict[str, object],
) -> None:
    row = document_row()
    row.update(overrides)
    with pytest.raises(ResearchReadValidationError):
        ResearchSourceDocument.from_mapping(row)


def test_neon_metadata_reader_is_scoped_parameterized_and_order_independent() -> None:
    cursor = FakeCursor([metadata_row(MEMORY_B), metadata_row(MEMORY_A)])
    reader = NeonResearchMetadataReader(cursor)

    rows = reader.fetch(
        space_id=SPACE,
        memory_ids=(MEMORY_B, MEMORY_A, MEMORY_A),
    )

    assert set(rows) == {MEMORY_A, MEMORY_B}
    assert isinstance(rows, MappingProxyType)
    assert len(cursor.calls) == 1
    sql, params = cursor.calls[0]
    assert sql == RESEARCH_METADATA_SELECT_SQL
    assert "WHERE space_id = %(space_id)s" in sql
    assert "ANY(%(memory_ids)s::uuid[])" in sql
    assert params == {
        "space_id": SPACE,
        "memory_ids": [MEMORY_A, MEMORY_B],
    }


def test_neon_metadata_reader_skips_query_for_empty_ids() -> None:
    cursor = FakeCursor([])
    rows = NeonResearchMetadataReader(cursor).fetch(
        space_id=SPACE,
        memory_ids=(),
    )

    assert rows == {}
    assert cursor.calls == []


@pytest.mark.parametrize(
    "rows",
    [
        [metadata_row(MEMORY_A, space_id=OTHER_SPACE)],
        [metadata_row(MEMORY_B)],
        [metadata_row(MEMORY_A), metadata_row(MEMORY_A)],
        [{"memory_id": MEMORY_A}],
        ["not-a-mapping"],
    ],
)
def test_neon_metadata_reader_rejects_unexpected_duplicate_or_malformed_rows(
    rows: list[object],
) -> None:
    cursor = FakeCursor(rows)  # type: ignore[arg-type]
    with pytest.raises((ResearchReadValidationError, ResearchMaterializationError)):
        NeonResearchMetadataReader(cursor).fetch(
            space_id=SPACE,
            memory_ids=(MEMORY_A,),
        )


def test_mongo_reader_uses_exact_scope_status_uuid_and_backend_filter() -> None:
    collection = FakeCollection([document_row()])
    reader = MongoResearchDocumentReader(collection)

    rows = reader.fetch(
        space_id=SPACE,
        backend_refs=("paper:a",),
        memory_ids=(MEMORY_A,),
        active_status="active",
    )

    assert rows[MEMORY_A].backend_ref == "paper:a"
    assert len(collection.calls) == 1
    filter_doc, projection = collection.calls[0]
    assert filter_doc == {
        "_id": {"$in": ["paper:a"]},
        "memory_id": {"$in": [str(MEMORY_A)]},
        "space_id": str(SPACE),
        "status": "active",
    }
    assert projection["rag_text"] == 1
    assert projection["provenance"] == 1
    assert "embedding" not in projection


@pytest.mark.parametrize(
    "documents",
    [
        [],
        [document_row(MEMORY_B)],
        [document_row(space_id=str(OTHER_SPACE))],
        [document_row(status="inactive")],
        [document_row(), document_row()],
        [document_row(_id="paper:unexpected")],
        ["not-a-mapping"],
    ],
)
def test_mongo_reader_rejects_missing_unexpected_inactive_or_duplicate_documents(
    documents: list[object],
) -> None:
    collection = FakeCollection(documents)  # type: ignore[arg-type]
    with pytest.raises((ResearchReadValidationError, ResearchMaterializationError)):
        MongoResearchDocumentReader(collection).fetch(
            space_id=SPACE,
            backend_refs=("paper:a",),
            memory_ids=(MEMORY_A,),
            active_status="active",
        )


def test_cross_store_materializer_joins_exactly_and_preserves_two_hashes() -> None:
    ranked = reranked()
    metadata_provider = FakeMetadataProvider({MEMORY_A: metadata()})
    document_provider = FakeDocumentProvider({MEMORY_A: document()})
    estimator = FixedEstimator(123)
    materializer = CrossStoreResearchMaterializer(
        metadata_provider=metadata_provider,
        document_provider=document_provider,
        token_estimator=estimator,
        now=lambda: NOW,
    )

    result = materializer.materialize(read_request(), (ranked,))

    assert len(result) == 1
    item = result[0]
    assert item.metadata.canonical_content_hash == HASH_A
    assert item.materialized_content_hash != HASH_A
    assert item.materialized_content_hash == __import__("hashlib").sha256(
        item.document.rag_text.encode("utf-8")
    ).hexdigest()
    assert item.estimated_tokens == 123
    assert item.coverage_keys == ("hybrid-retrieval", "memory", "router")
    assert item.mandatory is False
    context = item.to_context_evidence()
    assert context.content_hash == item.materialized_content_hash
    assert context.authority == 0.9
    assert context.confidence == 0.85
    assert context.subject_key == "research.memory-routing"
    assert context.original_rank == 1
    assert estimator.calls == [item.document.rag_text]


def test_materializer_propagates_mandatory_memory_and_reranker_order() -> None:
    first = reranked()
    second_hit = hit(
        MEMORY_B,
        backend_ref="paper:b",
        title="Paper B",
        source_uri="https://example.invalid/b",
        rank=2,
    )
    second = reranked(second_hit)
    materializer = CrossStoreResearchMaterializer(
        metadata_provider=FakeMetadataProvider(
            {MEMORY_B: metadata(MEMORY_B), MEMORY_A: metadata()}
        ),
        document_provider=FakeDocumentProvider(
            {MEMORY_B: document(MEMORY_B), MEMORY_A: document()}
        ),
        token_estimator=FixedEstimator(50),
        now=lambda: NOW,
    )

    result = materializer.materialize(
        read_request(mandatory_memory_ids=(MEMORY_B,)),
        (first, second),
    )

    assert [item.reranked.hit.memory_id for item in result] == [
        MEMORY_A,
        MEMORY_B,
    ]
    assert result[0].mandatory is False
    assert result[1].mandatory is True


@pytest.mark.parametrize(
    ("metadata_rows", "document_rows", "error"),
    [
        ({}, {MEMORY_A: document()}, "missing Neon"),
        ({MEMORY_A: metadata()}, {}, "missing Atlas"),
        (
            {MEMORY_A: metadata(), MEMORY_B: metadata(MEMORY_B)},
            {MEMORY_A: document()},
            "unexpected Neon",
        ),
        (
            {MEMORY_A: metadata()},
            {MEMORY_A: document(), MEMORY_B: document(MEMORY_B)},
            "unexpected Atlas",
        ),
    ],
)
def test_materializer_rejects_missing_or_extra_cross_store_rows(
    metadata_rows: Mapping[UUID, ResearchMemoryMetadata],
    document_rows: Mapping[UUID, ResearchSourceDocument],
    error: str,
) -> None:
    materializer = CrossStoreResearchMaterializer(
        metadata_provider=FakeMetadataProvider(metadata_rows),
        document_provider=FakeDocumentProvider(document_rows),
        token_estimator=FixedEstimator(),
        now=lambda: NOW,
    )

    with pytest.raises(ResearchMaterializationError, match=error):
        materializer.materialize(read_request(), (reranked(),))


@pytest.mark.parametrize(
    "changed_document",
    [
        document(backend_ref="paper:other"),
        document(title="Changed title"),
        document(source_uri="https://example.invalid/changed"),
        document(tags=("changed",)),
        document(status="inactive"),
        document(space_id=OTHER_SPACE),
    ],
)
def test_materializer_rejects_time_of_check_time_of_use_drift(
    changed_document: ResearchSourceDocument,
) -> None:
    materializer = CrossStoreResearchMaterializer(
        metadata_provider=FakeMetadataProvider({MEMORY_A: metadata()}),
        document_provider=FakeDocumentProvider({MEMORY_A: changed_document}),
        token_estimator=FixedEstimator(),
        now=lambda: NOW,
    )

    with pytest.raises(ResearchMaterializationError, match="drift|status|space"):
        materializer.materialize(read_request(), (reranked(),))


def test_materializer_rejects_invalid_validity_nonpositive_tokens_and_duplicates() -> None:
    expired = metadata(valid_to=NOW - timedelta(seconds=1))
    materializer = CrossStoreResearchMaterializer(
        metadata_provider=FakeMetadataProvider({MEMORY_A: expired}),
        document_provider=FakeDocumentProvider({MEMORY_A: document()}),
        token_estimator=FixedEstimator(),
        now=lambda: NOW,
    )
    with pytest.raises(ResearchMaterializationError, match="valid"):
        materializer.materialize(read_request(), (reranked(),))

    nonpositive = CrossStoreResearchMaterializer(
        metadata_provider=FakeMetadataProvider({MEMORY_A: metadata()}),
        document_provider=FakeDocumentProvider({MEMORY_A: document()}),
        token_estimator=FixedEstimator(0),
        now=lambda: NOW,
    )
    with pytest.raises(ResearchMaterializationError, match="token"):
        nonpositive.materialize(read_request(), (reranked(),))

    duplicate = reranked()
    valid = CrossStoreResearchMaterializer(
        metadata_provider=FakeMetadataProvider({MEMORY_A: metadata()}),
        document_provider=FakeDocumentProvider({MEMORY_A: document()}),
        token_estimator=FixedEstimator(),
        now=lambda: NOW,
    )
    with pytest.raises(ResearchMaterializationError, match="duplicate"):
        valid.materialize(read_request(), (duplicate, duplicate))


def test_materializer_rejects_mandatory_memory_not_retrieved() -> None:
    materializer = CrossStoreResearchMaterializer(
        metadata_provider=FakeMetadataProvider({MEMORY_A: metadata()}),
        document_provider=FakeDocumentProvider({MEMORY_A: document()}),
        token_estimator=FixedEstimator(),
        now=lambda: NOW,
    )

    with pytest.raises(ResearchMaterializationError, match="mandatory"):
        materializer.materialize(
            read_request(mandatory_memory_ids=(MEMORY_B,)),
            (reranked(),),
        )
