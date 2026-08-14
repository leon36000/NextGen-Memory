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


def build_research_hybrid_pipeline(
    query: ResearchRetrievalQuery,
    config: MongoResearchIndexConfig,
) -> list[dict[str, Any]]:
    """Build a MongoDB 8.0 native RRF pipeline for scoped research retrieval."""

    branch_limit = min(query.limit * 2, 100)
    scope_filter = {
        "space_id": str(query.space_id),
        "status": config.active_status,
    }
    project: dict[str, Any] = {
        "_id": 1,
        "memory_id": 1,
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
        return tuple(
            self._map_document(document, rank)
            for rank, document in enumerate(documents, start=1)
        )

    def close(self) -> None:
        if self._owned_client is not None:
            self._owned_client.close()

    @staticmethod
    def _map_document(
        document: Mapping[str, Any],
        rank: int,
    ) -> ResearchRetrievalHit:
        raw_memory_id = document.get("memory_id")
        try:
            memory_id = UUID(str(raw_memory_id))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("retrieval document lacks a canonical memory_id UUID") from exc

        backend_ref = str(document.get("_id", ""))
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
        except (TypeError, ValueError) as exc:
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
