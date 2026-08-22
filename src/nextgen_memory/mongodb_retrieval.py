"""MongoDB Atlas retrieval pipeline construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, Self
from uuid import UUID

from .retrieval import ResearchRetrievalHit, ResearchRetrievalQuery


@dataclass(frozen=True, slots=True)
class MongoResearchIndexConfig:
    database: str = "nextgen_memory"
    collection: str = "research_sources"
    lexical_index: str = "rag_lexical_v2"
    vector_index: str = "rag_autoembed_v1"
    vector_path: str = "rag_text"
    lexical_paths: tuple[str, ...] = (
        "rag_text",
        "title",
        "claims_text",
        "tags",
    )
    active_status: str = "active"
    source_type: str = "paper"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "active_status",
            _normalize_policy_text("active_status", self.active_status),
        )
        object.__setattr__(
            self,
            "source_type",
            _normalize_policy_text("source_type", self.source_type),
        )


def build_research_hybrid_pipeline(
    query: ResearchRetrievalQuery,
    config: MongoResearchIndexConfig,
) -> list[dict[str, Any]]:
    """Build a MongoDB 8.0 native RRF pipeline for scoped research retrieval."""

    branch_limit = min(query.limit * 2, 100)
    scope_filter = {
        "space_id": str(query.space_id),
        "status": config.active_status,
        "source_type": config.source_type,
    }
    project: dict[str, Any] = {
        "_id": 1,
        "memory_id": 1,
        "space_id": 1,
        "status": 1,
        "source_type": 1,
        "title": 1,
        "source_uri": 1,
        "tags": 1,
        "score": {"$meta": "score"},
    }
    if query.include_score_details:
        project["score_details"] = {"$meta": "scoreDetails"}

    return [
        {
            "$rankFusion": {
                "input": {
                    "pipelines": {
                        "semantic": [
                            {
                                "$vectorSearch": {
                                    "index": config.vector_index,
                                    "path": config.vector_path,
                                    "query": {"text": query.text},
                                    "numCandidates": query.num_candidates,
                                    "limit": branch_limit,
                                    "filter": scope_filter,
                                }
                            }
                        ],
                        "lexical": [
                            {
                                "$search": {
                                    "index": config.lexical_index,
                                    "compound": {
                                        "must": [
                                            {
                                                "text": {
                                                    "query": query.text,
                                                    "path": list(config.lexical_paths),
                                                }
                                            }
                                        ],
                                        "filter": [
                                            {
                                                "equals": {
                                                    "path": "space_id",
                                                    "value": str(query.space_id),
                                                }
                                            },
                                            {
                                                "equals": {
                                                    "path": "status",
                                                    "value": config.active_status,
                                                }
                                            },
                                            {
                                                "equals": {
                                                    "path": "source_type",
                                                    "value": config.source_type,
                                                }
                                            },
                                        ],
                                    },
                                }
                            },
                            {"$limit": branch_limit},
                        ],
                    }
                },
                "combination": {
                    "weights": {
                        "semantic": query.semantic_weight,
                        "lexical": query.lexical_weight,
                    }
                },
                "scoreDetails": query.include_score_details,
            }
        },
        {"$limit": query.limit},
        {"$project": project},
    ]


class AggregateCollection(Protocol):
    def aggregate(self, pipeline: list[dict[str, Any]]) -> Iterable[Mapping[str, Any]]:
        """Execute an aggregation pipeline and yield result documents."""
        ...


class CloseableClient(Protocol):
    def close(self) -> None:
        """Release the underlying database client."""
        ...


class MongoResearchRetriever:
    """Execute scoped hybrid research retrieval against an injected collection."""

    def __init__(
        self,
        collection: AggregateCollection,
        config: MongoResearchIndexConfig | None = None,
        *,
        owned_client: CloseableClient | None = None,
    ) -> None:
        self._collection = collection
        self.config = config or MongoResearchIndexConfig()
        self._owned_client = owned_client

    @classmethod
    def from_uri(
        cls,
        uri: str,
        config: MongoResearchIndexConfig | None = None,
        *,
        app_name: str = "nextgen-memory",
    ) -> Self:
        """Create a retriever that owns its PyMongo client."""

        if not uri.strip():
            raise ValueError("uri must not be empty")
        from pymongo import MongoClient

        resolved = config or MongoResearchIndexConfig()
        client = MongoClient(uri, appname=app_name)
        collection = client[resolved.database][resolved.collection]
        return cls(collection, resolved, owned_client=client)

    def search(
        self,
        query: ResearchRetrievalQuery,
    ) -> tuple[ResearchRetrievalHit, ...]:
        pipeline = build_research_hybrid_pipeline(query, self.config)
        documents = self._collection.aggregate(pipeline)
        hits: list[ResearchRetrievalHit] = []
        seen_memory_ids: set[UUID] = set()
        seen_backend_refs: set[str] = set()

        for rank, document in enumerate(documents, start=1):
            if rank > query.limit:
                raise ValueError("retrieval batch exceeds query limit")
            hit = self._map_document(
                document,
                rank,
                query=query,
                config=self.config,
            )
            if hit.memory_id in seen_memory_ids:
                raise ValueError("retrieval batch contains duplicate memory_id")
            if hit.backend_ref in seen_backend_refs:
                raise ValueError("retrieval batch contains duplicate backend_ref")
            seen_memory_ids.add(hit.memory_id)
            seen_backend_refs.add(hit.backend_ref)
            hits.append(hit)
        return tuple(hits)

    def close(self) -> None:
        if self._owned_client is not None:
            self._owned_client.close()

    @staticmethod
    def _map_document(
        document: Mapping[str, Any],
        rank: int,
        *,
        query: ResearchRetrievalQuery,
        config: MongoResearchIndexConfig,
    ) -> ResearchRetrievalHit:
        if not isinstance(document, Mapping):
            raise ValueError("retrieval document must be a mapping")

        raw_space_id = document.get("space_id")
        try:
            space_id = UUID(str(raw_space_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("retrieval document has an invalid space_id") from exc
        if space_id != query.space_id:
            raise ValueError("retrieval document space_id mismatch")
        if document.get("status") != config.active_status:
            raise ValueError("retrieval document status mismatch")
        if document.get("source_type") != config.source_type:
            raise ValueError("retrieval document source_type mismatch")

        raw_memory_id = document.get("memory_id")
        try:
            memory_id = UUID(str(raw_memory_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("retrieval document lacks a canonical memory_id UUID") from exc

        raw_backend_ref = document.get("_id")
        backend_ref = str(raw_backend_ref).strip() if raw_backend_ref is not None else ""
        if not backend_ref:
            raise ValueError("retrieval document lacks a canonical backend_ref")

        tags_value = document.get("tags", ())
        if (
            isinstance(tags_value, (str, bytes))
            or not isinstance(tags_value, Sequence)
            or not all(isinstance(tag, str) for tag in tags_value)
        ):
            raise ValueError("tags must be an array of strings")
        tags = tuple(tags_value)

        if "score" not in document:
            raise ValueError("retrieval document lacks a fusion score")
        try:
            score = float(document["score"])
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("retrieval document has an invalid fusion score") from exc

        score_details = document.get("score_details")
        if score_details is not None and not isinstance(score_details, Mapping):
            raise ValueError("score_details must be a mapping when supplied")

        return ResearchRetrievalHit(
            memory_id=memory_id,
            backend_ref=backend_ref,
            rank=rank,
            score=score,
            title=str(document.get("title", "")),
            source_uri=str(document.get("source_uri", "")),
            tags=tags,
            score_details=score_details,
        )


def _normalize_policy_text(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{name} must not be empty")
    return normalized
