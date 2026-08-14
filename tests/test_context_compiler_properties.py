from __future__ import annotations

import hashlib
import json
import random
from uuid import UUID

import nextgen_memory
import pytest

from nextgen_memory.context_compiler import (
    ContextBudgetError,
    ContextCompiler,
    ContextCompileRequest,
    ContextEvidence,
    ContextPacket,
    EvidenceFidelity,
)

SPACE = UUID("99999999-9999-9999-9999-999999999999")
EXPERTS = ("research", "semantic", "decision", "failure")
SUBJECTS = (
    "memory.routing",
    "project.architecture",
    "execution.failure",
    "research.evidence",
)
COVERAGE_KEYS = ("cause", "current_state", "decision", "failure", "time")


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _generated_case(
    seed: int,
) -> tuple[ContextCompileRequest, tuple[ContextEvidence, ...]]:
    rng = random.Random(seed)
    envelope = rng.randint(16, 96)
    token_budget = envelope + rng.randint(64, 900)
    required = tuple(key for key in COVERAGE_KEYS if rng.random() < 0.25)
    compile_request = ContextCompileRequest(
        space_id=SPACE,
        token_budget=token_budget,
        envelope_tokens=envelope,
        max_items=rng.randint(1, 8),
        required_coverage_keys=required,
        max_items_per_expert=(
            None if rng.random() < 0.5 else rng.randint(1, 3)
        ),
        minimum_authority=0.0,
        minimum_confidence=0.0,
        new_expert_bonus=round(rng.random() * 0.15, 6),
        new_subject_bonus=round(rng.random() * 0.10, 6),
    )
    candidates: list[ContextEvidence] = []
    for index in range(rng.randint(0, 12)):
        memory_id = UUID(int=(seed + 1) * 1000 + index + 1)
        content = f"evidence:{seed}:{index}"
        candidates.append(
            ContextEvidence(
                memory_id=memory_id,
                space_id=SPACE,
                expert=rng.choice(EXPERTS),
                subject_key=rng.choice(SUBJECTS),
                content=content,
                content_hash=_hash(content),
                backend_ref=f"memory:{memory_id}",
                source_uri=None,
                fidelity=(
                    EvidenceFidelity.EXACT
                    if rng.random() < 0.7
                    else EvidenceFidelity.DERIVED
                ),
                score=round(rng.uniform(-1.25, 1.25), 6),
                authority=round(rng.uniform(0.2, 1.0), 6),
                confidence=round(rng.uniform(0.2, 1.0), 6),
                estimated_tokens=rng.randint(8, 220),
                coverage_keys=tuple(
                    key for key in COVERAGE_KEYS if rng.random() < 0.2
                ),
                mandatory=rng.random() < 0.12,
                original_rank=index + 1,
            )
        )
    return compile_request, tuple(candidates)


def test_package_exports_context_compiler_api() -> None:
    assert nextgen_memory.ContextCompiler is ContextCompiler
    assert nextgen_memory.ContextCompileRequest is ContextCompileRequest
    assert nextgen_memory.ContextEvidence is ContextEvidence
    assert nextgen_memory.ContextPacket is ContextPacket


def test_randomized_compilation_preserves_core_invariants() -> None:
    compiler = ContextCompiler()
    successful = 0
    mandatory_overflows = 0

    for seed in range(5000):
        compile_request, candidates = _generated_case(seed)
        mandatory = tuple(item for item in candidates if item.mandatory)
        mandatory_overflow = (
            len(mandatory) > compile_request.max_items
            or sum(item.estimated_tokens for item in mandatory)
            > compile_request.usable_evidence_tokens
        )

        if mandatory_overflow:
            with pytest.raises(ContextBudgetError):
                compiler.compile(compile_request, candidates)
            mandatory_overflows += 1
            continue

        packet = compiler.compile(compile_request, candidates)
        reversed_packet = compiler.compile(
            compile_request, tuple(reversed(candidates))
        )
        successful += 1

        assert packet == reversed_packet
        assert packet.packet_id == reversed_packet.packet_id
        assert packet.render_json() == reversed_packet.render_json()
        assert packet.total_estimated_tokens <= compile_request.token_budget
        assert len(packet.selected) <= compile_request.max_items
        assert all(
            item.evidence.space_id == compile_request.space_id
            for item in packet.selected
        )
        assert len(packet.selected_memory_ids) == len(
            set(packet.selected_memory_ids)
        )
        assert {item.memory_id for item in mandatory} <= set(
            packet.selected_memory_ids
        )
        assert set(packet.covered_coverage_keys) | set(
            packet.uncovered_coverage_keys
        ) == set(compile_request.required_coverage_keys)
        assert not (
            set(packet.covered_coverage_keys)
            & set(packet.uncovered_coverage_keys)
        )
        payload = json.loads(packet.render_json())
        assert payload["packet_id"] == str(packet.packet_id)
        assert payload["estimated_total_tokens"] == packet.total_estimated_tokens
        assert payload["complete"] is packet.complete
        assert [item["memory_id"] for item in payload["evidence"]] == [
            str(memory_id) for memory_id in packet.selected_memory_ids
        ]

    assert successful > 3000
    assert mandatory_overflows > 0
