from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Any
from uuid import UUID

import pytest

from nextgen_memory.context_compiler import (
    ContextCompileRequest,
    ContextCompiler,
    ContextEvidence,
    EvidenceFidelity,
)
from nextgen_memory.domain import (
    EvidenceNeed,
    ExpertAllocation,
    ExpertKey,
    RoutingDecision,
    RoutingRequest,
    RoutingScope,
    TaskKind,
)
from nextgen_memory.research_read_pipeline import (
    MaterializedResearchEvidence,
    ResearchMemoryMetadata,
    ResearchReadBudgetError,
    ResearchReadPipeline,
    ResearchReadRequest,
    ResearchReadStatus,
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
ROUTE_ID = UUID("33333333-3333-3333-3333-333333333333")
REQUEST_ID = UUID("44444444-4444-4444-4444-444444444444")
NOW = datetime(2026, 8, 14, 18, 0, tzinfo=UTC)
HASH_A = "a" * 64
HASH_B = "b" * 64
VIEW_HASH_A = "c" * 64
VIEW_HASH_B = "d" * 64


def routing_request(**overrides: object) -> RoutingRequest:
    values: dict[str, object] = {
        "request_id": REQUEST_ID,
        "query": "compare memory routing architectures",
        "scope": RoutingScope(
            space_id=SPACE,
            project_key="nextgen-memory",
            permissions=frozenset({"memory:read"}),
        ),
        "task_kind": TaskKind.RESEARCH,
        "needs": frozenset({EvidenceNeed.RESEARCH}),
        "token_budget": 1500,
        "max_experts": 5,
    }
    values.update(overrides)
    return RoutingRequest(**values)


def retrieval_query(**overrides: object) -> ResearchRetrievalQuery:
    values: dict[str, object] = {
        "text": "compare memory routing architectures",
        "space_id": SPACE,
        "limit": 5,
    }
    values.update(overrides)
    return ResearchRetrievalQuery(**values)


def compile_request(**overrides: object) -> ContextCompileRequest:
    values: dict[str, object] = {
        "space_id": SPACE,
        "token_budget": 700,
        "envelope_tokens": 100,
        "max_items": 5,
        "required_coverage_keys": ("router",),
    }
    values.update(overrides)
    return ContextCompileRequest(**values)


def read_request(**overrides: object) -> ResearchReadRequest:
    values: dict[str, object] = {
        "routing_request": routing_request(),
        "retrieval_query": retrieval_query(),
        "compile_request": compile_request(),
        "mandatory_memory_ids": (),
        "coverage_aliases": {"hybrid-retrieval": ("router",)},
        "active_status": "active",
    }
    values.update(overrides)
    return ResearchReadRequest(**values)


def decision(*, research_selected: bool = True, research_budget: int = 600) -> RoutingDecision:
    allocations = [
        ExpertAllocation(
            expert=ExpertKey.WORKING,
            token_budget=300,
            score=100.0,
            reasons=("task:research",),
        )
    ]
    if research_selected:
        allocations.append(
            ExpertAllocation(
                expert=ExpertKey.RESEARCH,
                token_budget=research_budget,
                score=190.0,
                reasons=("need:research",),
            )
        )
    return RoutingDecision(
        decision_id=ROUTE_ID,
        request_id=REQUEST_ID,
        eligible_experts=(
            ExpertKey.WORKING,
            ExpertKey.RESEARCH,
            ExpertKey.SEMANTIC,
        ),
        allocations=tuple(allocations),
        escalation_experts=(
            () if research_selected else (ExpertKey.RESEARCH,)
        ),
        token_budget=1500,
        confidence=0.9,
        policy_version="test-router",
    )


def hit(
    memory_id: UUID = MEMORY_A,
    *,
    backend_ref: str = "paper:a",
    rank: int = 1,
    score: float = 0.9,
    title: str = "Paper A",
    source_uri: str = "https://example.invalid/a",
    tags: tuple[str, ...] = ("hybrid-retrieval",),
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


def reranked(
    retrieval_hit: ResearchRetrievalHit | None = None,
    *,
    final_rank: int = 1,
    final_score: float = 0.8,
) -> RerankedMemory:
    retrieval_hit = retrieval_hit or hit()
    return RerankedMemory(
        hit=retrieval_hit,
        final_rank=final_rank,
        final_score=final_score,
        score_breakdown=UtilityScoreBreakdown(
            relevance_component=0.7,
            reward_component=0.1,
            verdict_component=0.05,
            harm_penalty=0.0,
            token_penalty=0.01,
            latency_penalty=0.01,
            final_score=final_score,
        ),
        utility_evidence=UtilityEvidence(
            memory_id=retrieval_hit.memory_id,
            feedback_count=3,
            avg_reward=0.4,
            positive_count=2,
            negative_count=0,
            last_feedback_at=NOW,
        ),
    )


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
    values: dict[str, object] = {
        "backend_ref": "paper:a" if memory_id == MEMORY_A else "paper:b",
        "memory_id": memory_id,
        "space_id": SPACE,
        "status": "active",
        "source_type": "paper",
        "title": "Paper A" if memory_id == MEMORY_A else "Paper B",
        "source_uri": (
            "https://example.invalid/a"
            if memory_id == MEMORY_A
            else "https://example.invalid/b"
        ),
        "authors": ("Researcher",),
        "claims": ("Claim one.",),
        "tags": ("hybrid-retrieval",),
        "rag_text": "Paper A\nClaim one.\nTags: hybrid-retrieval",
        "provenance": {"retriever": "Exa", "canonical": "arXiv"},
    }
    values.update(overrides)
    return ResearchSourceDocument(**values)


def materialized(
    item: RerankedMemory | None = None,
    *,
    coverage_keys: tuple[str, ...] = ("hybrid-retrieval", "router"),
    mandatory: bool = False,
    estimated_tokens: int = 100,
) -> MaterializedResearchEvidence:
    item = item or reranked()
    return MaterializedResearchEvidence(
        reranked=item,
        metadata=metadata(item.hit.memory_id),
        document=document(
            item.hit.memory_id,
            backend_ref=item.hit.backend_ref,
            title=item.hit.title,
            source_uri=item.hit.source_uri,
            tags=item.hit.tags,
        ),
        materialized_content_hash=(
            VIEW_HASH_A if item.hit.memory_id == MEMORY_A else VIEW_HASH_B
        ),
        estimated_tokens=estimated_tokens,
        coverage_keys=coverage_keys,
        mandatory=mandatory,
    )


class FakeRouter:
    def __init__(self, route_decision: RoutingDecision) -> None:
        self.route_decision = route_decision
        self.calls = 0
        self.last_sink: object | None = None

    def route(self, request: RoutingRequest, *, sink: object | None = None) -> RoutingDecision:
        self.calls += 1
        self.last_sink = sink
        assert request.request_id == self.route_decision.request_id
        return self.route_decision


class FakeRetriever:
    def __init__(self, results: Sequence[RerankedMemory] = ()) -> None:
        self.results = tuple(results)
        self.calls = 0
        self.last_query: ResearchRetrievalQuery | None = None
        self.error: Exception | None = None

    def search(self, query: ResearchRetrievalQuery) -> tuple[RerankedMemory, ...]:
        self.calls += 1
        self.last_query = query
        if self.error is not None:
            raise self.error
        return self.results


class FakeMaterializer:
    def __init__(self, results: Sequence[MaterializedResearchEvidence] = ()) -> None:
        self.results = tuple(results)
        self.calls = 0
        self.last_request: ResearchReadRequest | None = None
        self.last_reranked: tuple[RerankedMemory, ...] = ()
        self.error: Exception | None = None

    def materialize(
        self,
        request: ResearchReadRequest,
        reranked_items: Sequence[RerankedMemory],
    ) -> tuple[MaterializedResearchEvidence, ...]:
        self.calls += 1
        self.last_request = request
        self.last_reranked = tuple(reranked_items)
        if self.error is not None:
            raise self.error
        return self.results


class FakeCompiler:
    def __init__(self) -> None:
        self.delegate = ContextCompiler()
        self.calls = 0
        self.last_evidence: tuple[ContextEvidence, ...] = ()

    def compile(
        self,
        request: ContextCompileRequest,
        candidates: Sequence[ContextEvidence],
    ):
        self.calls += 1
        self.last_evidence = tuple(candidates)
        return self.delegate.compile(request, candidates)


def pipeline(
    *,
    route_decision: RoutingDecision | None = None,
    retrieved: Sequence[RerankedMemory] = (),
    materialized_items: Sequence[MaterializedResearchEvidence] = (),
):
    router = FakeRouter(route_decision or decision())
    retriever = FakeRetriever(retrieved)
    materializer = FakeMaterializer(materialized_items)
    compiler = FakeCompiler()
    instance = ResearchReadPipeline(
        router=router,
        retriever=retriever,
        materializer=materializer,
        compiler=compiler,
    )
    return instance, router, retriever, materializer, compiler


def test_request_requires_matching_scopes_query_text_permission_and_research_intent() -> None:
    with pytest.raises(ResearchReadValidationError, match="space_id"):
        read_request(retrieval_query=retrieval_query(space_id=OTHER_SPACE))
    with pytest.raises(ResearchReadValidationError, match="query text"):
        read_request(retrieval_query=retrieval_query(text="different"))
    with pytest.raises(ResearchReadValidationError, match="memory:read"):
        read_request(
            routing_request=routing_request(
                scope=RoutingScope(
                    space_id=SPACE,
                    project_key="nextgen-memory",
                    permissions=frozenset(),
                )
            )
        )
    with pytest.raises(ResearchReadValidationError, match="research intent"):
        read_request(
            routing_request=routing_request(
                task_kind=TaskKind.GENERAL,
                needs=frozenset(),
            )
        )


def test_request_normalizes_and_freezes_mandatory_ids_aliases_and_status() -> None:
    request = read_request(
        mandatory_memory_ids=(MEMORY_B, MEMORY_A, MEMORY_A),
        coverage_aliases={
            " Hybrid_Retrieval ": (" router ", "retrieval", "router")
        },
        active_status=" active ",
    )

    assert request.mandatory_memory_ids == (MEMORY_A, MEMORY_B)
    assert request.coverage_aliases == {
        "hybrid-retrieval": ("retrieval", "router")
    }
    assert isinstance(request.coverage_aliases, MappingProxyType)
    assert request.active_status == "active"
    with pytest.raises(TypeError):
        request.coverage_aliases["x"] = ("y",)  # type: ignore[index]


def test_request_rejects_empty_or_invalid_aliases_and_status() -> None:
    with pytest.raises(ResearchReadValidationError, match="coverage alias"):
        read_request(coverage_aliases={" ": ("router",)})
    with pytest.raises(ResearchReadValidationError, match="coverage alias"):
        read_request(coverage_aliases={"hybrid": (" ",)})
    with pytest.raises(ResearchReadValidationError, match="active_status"):
        read_request(active_status=" ")


def test_not_routed_returns_without_any_downstream_side_effect() -> None:
    instance, router, retriever, materializer, compiler = pipeline(
        route_decision=decision(research_selected=False)
    )
    sink = object()

    result = instance.execute(read_request(), routing_sink=sink)

    assert result.status is ResearchReadStatus.NOT_ROUTED
    assert result.route_decision == router.route_decision
    assert result.reranked == ()
    assert result.materialized == ()
    assert result.packet is None
    assert result.retrieval_events == ()
    assert result.missing_coverage_keys == ("router",)
    assert router.calls == 1
    assert router.last_sink is sink
    assert retriever.calls == materializer.calls == compiler.calls == 0


def test_compile_budget_cannot_exceed_router_research_allocation() -> None:
    instance, _, retriever, materializer, compiler = pipeline(
        route_decision=decision(research_budget=500)
    )

    with pytest.raises(ResearchReadBudgetError, match="allocation"):
        instance.execute(
            read_request(
                compile_request=compile_request(
                    token_budget=701,
                    envelope_tokens=100,
                )
            )
        )

    assert retriever.calls == materializer.calls == compiler.calls == 0


def test_no_results_is_explicit_and_does_not_materialize_or_compile() -> None:
    instance, _, retriever, materializer, compiler = pipeline()

    result = instance.execute(read_request())

    assert result.status is ResearchReadStatus.NO_RESULTS
    assert result.packet is None
    assert result.missing_coverage_keys == ("router",)
    assert retriever.calls == 1
    assert materializer.calls == compiler.calls == 0


def test_complete_pipeline_materializes_compiles_and_builds_enriched_events() -> None:
    ranked = reranked()
    ready = materialized(ranked)
    instance, _, retriever, materializer, compiler = pipeline(
        retrieved=(ranked,),
        materialized_items=(ready,),
    )

    result = instance.execute(read_request())

    assert result.status is ResearchReadStatus.COMPLETE
    assert result.packet is not None and result.packet.complete
    assert result.packet.selected_memory_ids == (MEMORY_A,)
    assert result.missing_coverage_keys == ()
    assert materializer.last_reranked == (ranked,)
    assert compiler.last_evidence == (ready.to_context_evidence(),)
    assert len(result.retrieval_events) == 1
    retrieval_event = result.retrieval_events[0]
    assert retrieval_event.node_id == MEMORY_A
    assert retrieval_event.raw_score == ranked.hit.score
    assert retrieval_event.final_score == ranked.final_score
    assert retrieval_event.estimated_tokens == ready.estimated_tokens
    assert retrieval_event.selected_for_context is True
    assert retriever.last_query == read_request().retrieval_query


def test_incomplete_coverage_returns_packet_and_gap_without_exception() -> None:
    ranked = reranked()
    ready = materialized(ranked, coverage_keys=("different",))
    instance, _, _, _, _ = pipeline(
        retrieved=(ranked,),
        materialized_items=(ready,),
    )

    result = instance.execute(read_request())

    assert result.status is ResearchReadStatus.INCOMPLETE
    assert result.packet is not None and result.packet.complete is False
    assert result.missing_coverage_keys == ("router",)


def test_pipeline_preserves_reranker_order_before_compilation() -> None:
    first = reranked(hit(), final_rank=1, final_score=0.9)
    second_hit = hit(
        MEMORY_B,
        backend_ref="paper:b",
        rank=2,
        score=0.8,
        title="Paper B",
        source_uri="https://example.invalid/b",
    )
    second = reranked(second_hit, final_rank=2, final_score=0.7)
    first_materialized = materialized(first, coverage_keys=("router",))
    second_materialized = materialized(second, coverage_keys=("other",))
    instance, _, _, materializer, _, = pipeline(
        retrieved=(first, second),
        materialized_items=(first_materialized, second_materialized),
    )

    result = instance.execute(read_request())

    assert materializer.last_reranked == (first, second)
    assert result.reranked == (first, second)
    assert result.materialized == (first_materialized, second_materialized)


def test_backend_exceptions_propagate_without_fallback() -> None:
    instance, _, retriever, materializer, compiler = pipeline()
    retriever.error = RuntimeError("atlas unavailable")

    with pytest.raises(RuntimeError, match="atlas unavailable"):
        instance.execute(read_request())

    assert materializer.calls == compiler.calls == 0


def test_result_is_immutable_and_telemetry_contains_no_query_or_content() -> None:
    ranked = reranked()
    ready = materialized(ranked)
    instance, _, _, _, _ = pipeline(
        retrieved=(ranked,),
        materialized_items=(ready,),
    )

    result = instance.execute(read_request())
    payload = result.to_telemetry_dict()
    serialized = str(payload).lower()

    assert isinstance(result.reranked, tuple)
    assert isinstance(result.materialized, tuple)
    assert isinstance(result.retrieval_events, tuple)
    assert "compare memory routing architectures" not in serialized
    assert ready.document.rag_text.lower() not in serialized
    assert payload["status"] == "complete"
    assert payload["packet_id"] == str(result.packet.packet_id)
    with pytest.raises(FrozenInstanceError):
        result.status = ResearchReadStatus.INCOMPLETE  # type: ignore[misc]
