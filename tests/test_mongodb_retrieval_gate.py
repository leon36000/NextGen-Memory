from __future__ import annotations

import inspect
from collections.abc import Mapping
from uuid import UUID

import pytest

import nextgen_memory.mongodb_retrieval as mongodb_retrieval

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
MEMORY_A = UUID("4b84a18f-056f-5be9-bd27-a33ef835d29c")
MEMORY_B = UUID("4fa23ec8-3e26-5d39-ab9a-ea9620ade536")


def safe_row(
    *,
    memory_id: object = MEMORY_A,
    backend_ref: object = "paper:arxiv:2605.21951",
    space_id: object = SPACE_ID,
    status: object = "active",
    source_type: object = "research_paper",
    **extra: object,
) -> dict[str, object]:
    row: dict[str, object] = {
        "memory_id": memory_id,
        "backend_ref": backend_ref,
        "space_id": space_id,
        "status": status,
        "source_type": source_type,
        "title": "Synthetic research title",
        "source_uri": "https://example.invalid/research",
        "tags": ["research"],
        "score": 0.5,
    }
    row.update(extra)
    return row


def gate(
    rows: object,
    *,
    space_id: UUID = SPACE_ID,
    max_results: int = 3,
) -> tuple[Mapping[str, object], ...]:
    validator = getattr(mongodb_retrieval, "_validate_research_result_batch", None)
    assert callable(validator)
    return validator(rows, space_id=space_id, max_results=max_results)


def projection(pipeline: object) -> list[dict[str, object]]:
    projector = getattr(mongodb_retrieval, "_with_canonical_projection", None)
    assert callable(projector)
    return projector(pipeline)


def test_projection_adds_canonical_lifecycle_envelope_without_mutating_input() -> None:
    original = [{"$project": {"memory_id": 1, "backend_ref": 1, "score": 1}}]

    projected = projection(original)

    assert projected is not original
    assert projected[-1]["$project"] == {
        "memory_id": 1,
        "backend_ref": 1,
        "score": 1,
        "space_id": 1,
        "status": 1,
        "source_type": 1,
    }
    assert original == [{"$project": {"memory_id": 1, "backend_ref": 1, "score": 1}}]


def test_projection_fails_closed_without_one_mapping_project_stage() -> None:
    with pytest.raises(ValueError, match="projection"):
        projection([{"$limit": 3}])
    with pytest.raises(ValueError, match="projection"):
        projection([{"$project": "not-a-mapping"}])
    with pytest.raises(ValueError, match="projection"):
        projection([{"$project": {}}, {"$project": {}}])


def test_pipeline_builder_and_retriever_use_the_canonical_gate() -> None:
    builder_source = inspect.getsource(mongodb_retrieval.build_research_hybrid_pipeline)
    retriever_source = inspect.getsource(mongodb_retrieval.MongoResearchRetriever.retrieve)

    assert "_with_canonical_projection" in builder_source
    assert "_validate_research_result_batch" in retriever_source
    assert ".aggregate(" in retriever_source


def test_gate_accepts_safe_rows_and_returns_detached_mappings() -> None:
    first = safe_row()
    second = safe_row(
        memory_id=MEMORY_B,
        backend_ref="paper:arxiv:2606.00001",
    )

    admitted = gate([first, second], max_results=2)

    assert admitted == (first, second)
    assert admitted[0] is not first
    assert admitted[1] is not second


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (safe_row(space_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")), "scope"),
        (safe_row(status="inactive"), "active"),
        (safe_row(status=None), "active"),
        (safe_row(source_type=""), "source_type"),
        (safe_row(source_type=None), "source_type"),
        (safe_row(memory_id="not-a-uuid"), "memory_id"),
        (safe_row(backend_ref=""), "backend_ref"),
        (safe_row(backend_ref=None), "backend_ref"),
    ],
)
def test_gate_rejects_unsafe_or_malformed_rows(
    row: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        gate([row])


def test_gate_rejects_non_mapping_and_missing_envelope_fields() -> None:
    with pytest.raises(ValueError, match="mapping"):
        gate([object()])

    for field in ("memory_id", "backend_ref", "space_id", "status", "source_type"):
        row = safe_row()
        row.pop(field)
        with pytest.raises(ValueError, match=field):
            gate([row])


def test_gate_rejects_duplicate_canonical_identities() -> None:
    first = safe_row()
    same_memory = safe_row(backend_ref="paper:arxiv:other")
    same_backend = safe_row(memory_id=MEMORY_B)

    with pytest.raises(ValueError, match="duplicate memory_id"):
        gate([first, same_memory])
    with pytest.raises(ValueError, match="duplicate backend_ref"):
        gate([first, same_backend])


def test_gate_rejects_result_count_above_request_limit() -> None:
    rows = [
        safe_row(),
        safe_row(memory_id=MEMORY_B, backend_ref="paper:arxiv:other"),
    ]

    with pytest.raises(ValueError, match="result limit"):
        gate(rows, max_results=1)


@pytest.mark.parametrize("max_results", [0, -1, True])
def test_gate_rejects_invalid_result_limit(max_results: object) -> None:
    with pytest.raises((TypeError, ValueError), match="max_results"):
        gate([safe_row()], max_results=max_results)  # type: ignore[arg-type]


def test_gate_errors_do_not_echo_provider_or_query_like_payloads() -> None:
    sentinel_backend = "mongodb://user:secret@private-host/research"
    sentinel_title = "raw-query-like-private-payload"
    row = safe_row(
        backend_ref=sentinel_backend,
        status="inactive",
        title=sentinel_title,
    )

    with pytest.raises(ValueError) as exc_info:
        gate([row])

    message = str(exc_info.value)
    assert sentinel_backend not in message
    assert sentinel_title not in message
    assert "secret" not in message
    assert "private-host" not in message
