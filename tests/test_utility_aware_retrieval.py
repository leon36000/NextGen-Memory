from __future__ import annotations

from collections.abc import Mapping, Sequence
from uuid import UUID

import pytest

from nextgen_memory.retrieval import ResearchRetrievalHit, ResearchRetrievalQuery
from nextgen_memory.utility_reranker import (
    UtilityAwareResearchRetriever,
    UtilityEvidence,
)

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")


def memory_id(index: int) -> UUID:
    return UUID(f"00000000-0000-5000-8000-{index:012d}")


def hit(index: int, *, score: float | None = None) -> ResearchRetrievalHit:
    return ResearchRetrievalHit(
        memory_id=memory_id(index),
        backend_ref=f"paper:{index}",
        rank=index,
        score=score if score is not None else 1.0 / index,
        title=f"Memory {index}",
        source_uri="https://example.invalid/research",
    )


class FakeRetriever:
    def __init__(self, hits: Sequence[ResearchRetrievalHit]) -> None:
        self.hits = tuple(hits)
        self.queries: list[ResearchRetrievalQuery] = []

    def search(
        self,
        query: ResearchRetrievalQuery,
    ) -> tuple[ResearchRetrievalHit, ...]:
        self.queries.append(query)
        return self.hits


class FakeUtilityProvider:
    def __init__(
        self,
        evidence: Mapping[UUID, UtilityEvidence],
        *,
        error: Exception | None = None,
    ) -> None:
        self.evidence = evidence
        self.error = error
        self.calls: list[tuple[UUID, tuple[UUID, ...]]] = []

    def get_many(
        self,
        space_id: UUID,
        memory_ids: Sequence[UUID],
    ) -> Mapping[UUID, UtilityEvidence]:
        self.calls.append((space_id, tuple(memory_ids)))
        if self.error is not None:
            raise self.error
        return self.evidence


def test_decorator_oversamples_then_restores_original_limit() -> None:
    hits = tuple(hit(index) for index in range(1, 9))
    base = FakeRetriever(hits)
    provider = FakeUtilityProvider(
        {
            memory_id(2): UtilityEvidence(
                memory_id=memory_id(2),
                feedback_count=20,
                avg_reward=1.0,
                positive_count=20,
            )
        }
    )
    query = ResearchRetrievalQuery(
        text="memory utility",
        space_id=SPACE_ID,
        limit=5,
    )

    results = UtilityAwareResearchRetriever(base, provider).search(query)

    assert query.limit == 5
    assert query.num_candidates == 50
    expanded = base.queries[0]
    assert expanded.limit == 20
    assert expanded.num_candidates == 200
    assert expanded.text == query.text
    assert expanded.space_id == query.space_id
    assert provider.calls == (
        (SPACE_ID, tuple(result.memory_id for result in hits)),
    ) or provider.calls == [
        (SPACE_ID, tuple(result.memory_id for result in hits)),
    ]
    assert len(results) == 5
    assert [result.final_rank for result in results] == [1, 2, 3, 4, 5]


def test_oversampling_is_capped_at_query_maximum() -> None:
    base = FakeRetriever((hit(1),))
    provider = FakeUtilityProvider({})
    query = ResearchRetrievalQuery(
        text="memory utility",
        space_id=SPACE_ID,
        limit=30,
    )

    UtilityAwareResearchRetriever(base, provider).search(query)

    assert base.queries[0].limit == 100
    assert base.queries[0].num_candidates == 1_000


def test_missing_utility_rows_are_neutral() -> None:
    base = FakeRetriever((hit(1), hit(2)))
    provider = FakeUtilityProvider({})

    results = UtilityAwareResearchRetriever(base, provider).search(
        ResearchRetrievalQuery(
            text="memory utility",
            space_id=SPACE_ID,
            limit=2,
        )
    )

    assert [result.breakdown.utility for result in results] == [0.0, 0.0]
    assert [result.hit.memory_id for result in results] == [memory_id(1), memory_id(2)]


def test_provider_failure_propagates_without_neutral_fallback() -> None:
    base = FakeRetriever((hit(1),))
    provider = FakeUtilityProvider({}, error=RuntimeError("utility backend unavailable"))

    with pytest.raises(RuntimeError, match="utility backend unavailable"):
        UtilityAwareResearchRetriever(base, provider).search(
            ResearchRetrievalQuery(
                text="memory utility",
                space_id=SPACE_ID,
                limit=1,
            )
        )


def test_provider_cannot_return_unrequested_memory() -> None:
    base = FakeRetriever((hit(1),))
    provider = FakeUtilityProvider(
        {memory_id(99): UtilityEvidence.neutral(memory_id(99))}
    )

    with pytest.raises(ValueError, match="unrequested memory_id"):
        UtilityAwareResearchRetriever(base, provider).search(
            ResearchRetrievalQuery(
                text="memory utility",
                space_id=SPACE_ID,
                limit=1,
            )
        )


@pytest.mark.parametrize("factor", [0, -1, True, 1.5])
def test_invalid_oversample_factor_fails_closed(factor: object) -> None:
    with pytest.raises(ValueError, match="oversample_factor"):
        UtilityAwareResearchRetriever(
            FakeRetriever(()),
            FakeUtilityProvider({}),
            oversample_factor=factor,
        )
