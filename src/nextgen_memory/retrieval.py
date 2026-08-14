"""Typed contracts for scoped research retrieval."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Any
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ResearchRetrievalQuery:
    """Validated query for the project-scoped research memory collection."""

    text: str
    space_id: UUID
    limit: int = 8
    num_candidates: int | None = None
    semantic_weight: float = 0.65
    lexical_weight: float = 0.35
    include_score_details: bool = False

    def __post_init__(self) -> None:
        text = self.text.strip()
        if not text:
            raise ValueError("text must not be empty")
        if isinstance(self.limit, bool) or not isinstance(self.limit, int):
            raise ValueError("limit must be an integer")
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        candidates = self.num_candidates
        if candidates is None:
            candidates = self.limit * 10
        elif isinstance(candidates, bool) or not isinstance(candidates, int):
            raise ValueError("num_candidates must be an integer")
        if candidates < self.limit:
            raise ValueError("num_candidates must be greater than or equal to limit")
        if candidates > 10_000:
            raise ValueError("num_candidates must not exceed 10000")

        _validate_weight("semantic_weight", self.semantic_weight)
        _validate_weight("lexical_weight", self.lexical_weight)
        if self.semantic_weight + self.lexical_weight <= 0:
            raise ValueError("at least one fusion weight must be positive")

        object.__setattr__(self, "text", text)
        object.__setattr__(self, "num_candidates", candidates)


@dataclass(frozen=True, slots=True)
class ResearchRetrievalHit:
    """One canonical research-memory result returned by Atlas."""

    memory_id: UUID
    backend_ref: str
    rank: int
    score: float
    title: str
    source_uri: str
    tags: tuple[str, ...] = ()
    score_details: Mapping[str, Any] | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not self.backend_ref.strip():
            raise ValueError("backend_ref must not be empty")
        if self.rank <= 0:
            raise ValueError("rank must be greater than zero")
        if not isfinite(self.score):
            raise ValueError("score must be finite")
        object.__setattr__(self, "backend_ref", self.backend_ref.strip())
        object.__setattr__(self, "title", self.title.strip())
        object.__setattr__(self, "source_uri", self.source_uri.strip())
        object.__setattr__(self, "tags", tuple(self.tags))
        if self.score_details is not None:
            object.__setattr__(
                self,
                "score_details",
                MappingProxyType(dict(self.score_details)),
            )


def _validate_weight(name: str, value: float) -> None:
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
