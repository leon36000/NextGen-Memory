from __future__ import annotations

import hashlib
import json
from uuid import UUID

import pytest

from nextgen_memory.context_compiler import IntegratedContextCompiler
from nextgen_memory.context_compiler_contracts import (
    ContextCompilerValidationError,
    EvidenceFidelity,
    IntegratedContextCompileRequest,
    IntegratedContextEvidence,
)

SPACE_ID = UUID("11111111-1111-5111-8111-111111111111")
MEMORY_ID = UUID("aaaaaaaa-aaaa-5aaa-8aaa-aaaaaaaaaaaa")


def materialized_hash(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()


def evidence(**overrides: object) -> IntegratedContextEvidence:
    content = "Exact materialized evidence."
    values: dict[str, object] = {
        "memory_id": MEMORY_ID,
        "space_id": SPACE_ID,
        "expert": "research",
        "subject_key": "memory.routing",
        "source_cluster_key": "paper-family-a",
        "content": content,
        "content_hash": materialized_hash(content),
        "backend_ref": "research_sources:memory-a",
        "source_uri": "https://example.invalid/paper-a",
        "fidelity": EvidenceFidelity.EXACT,
        "estimated_tokens": 32,
        "original_rank": 1,
        "relevance": 0.8,
        "authority": 0.9,
        "confidence": 0.9,
    }
    values.update(overrides)
    return IntegratedContextEvidence(**values)


def test_matching_hash_binds_the_normalized_stored_content() -> None:
    item = evidence(
        content="  Exact materialized evidence.\n",
        content_hash=materialized_hash("Exact materialized evidence."),
    )

    assert item.content == "Exact materialized evidence."
    assert item.content_hash == materialized_hash(item.content)


def test_unicode_materialized_content_hash_is_utf8_deterministic() -> None:
    content = "Mémoire exacte — 東京 — 🧠"

    first = evidence(content=content, content_hash=materialized_hash(content))
    second = evidence(content=content, content_hash=materialized_hash(content))

    assert first == second
    assert first.content_hash == hashlib.sha256(content.encode("utf-8")).hexdigest()


def test_syntactically_valid_unrelated_hash_fails_closed() -> None:
    with pytest.raises(
        ContextCompilerValidationError,
        match="content_hash must match normalized materialized content",
    ):
        evidence(
            content="Exact materialized evidence.",
            content_hash=materialized_hash("Different materialized evidence."),
        )


def test_hash_mismatch_error_does_not_echo_protected_payload() -> None:
    sentinel_content = "private payload: mongodb://user:secret@private-host/research"
    sentinel_backend = "private-backend-reference"
    sentinel_uri = "https://private-host/source"

    with pytest.raises(ContextCompilerValidationError) as exc_info:
        evidence(
            content=sentinel_content,
            content_hash=materialized_hash("different"),
            backend_ref=sentinel_backend,
            source_uri=sentinel_uri,
        )

    message = str(exc_info.value)
    assert sentinel_content not in message
    assert sentinel_backend not in message
    assert sentinel_uri not in message
    assert "secret" not in message
    assert "private-host" not in message


def test_verified_hash_is_preserved_in_packet_json_and_identity() -> None:
    compiler = IntegratedContextCompiler()
    request = IntegratedContextCompileRequest(
        space_id=SPACE_ID,
        token_budget=128,
        envelope_tokens=32,
        max_items=1,
    )
    first_content = "First exact evidence."
    second_content = "Second exact evidence."

    first = compiler.compile(
        request,
        (
            evidence(
                content=first_content,
                content_hash=materialized_hash(first_content),
            ),
        ),
    )
    second = compiler.compile(
        request,
        (
            evidence(
                content=second_content,
                content_hash=materialized_hash(second_content),
            ),
        ),
    )

    rendered = json.loads(first.render_json())
    assert rendered["evidence"][0]["content_hash"] == materialized_hash(
        first_content
    )
    assert first.packet_id != second.packet_id
