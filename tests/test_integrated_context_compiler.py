from __future__ import annotations

import hashlib
from uuid import UUID

import pytest

from nextgen_memory.context_compiler_engine import (
    CompiledContextEvidence,
    IntegratedContextCompiler,
    IntegratedContextPacket,
)
from nextgen_memory.integrated_context_compiler import (
    ContextBudgetError,
    ContextCoverageDemand,
    ContextFidelity,
    ContextInteractionKind,
    ContextOmissionReason,
    ContextPairInteraction,
    ContextSelectionPhase,
    ContextSolverMode,
    IntegratedContextCompileRequest,
    IntegratedContextEvidence,
)

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
GROUP_ID = UUID("00000000-0000-5000-8000-000000000099")


def memory_id(index: int) -> UUID:
    return UUID(f"00000000-0000-5000-8000-{index:012d}")


def digest(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def item(index: int, **overrides: object) -> IntegratedContextEvidence:
    content = str(overrides.pop("content", f"evidence:{index}"))
    values: dict[str, object] = {
        "memory_id": memory_id(index),
        "space_id": SPACE_ID,
        "expert": "research",
        "subject_key": f"subject:{index}",
        "source_cluster_key": f"source:{index}",
        "content": content,
        "content_hash": digest(content),
        "backend_ref": f"memory:{index}",
        "source_uri": None,
        "fidelity": ContextFidelity.EXACT,
        "estimated_tokens": 100,
        "original_rank": index,
        "coverage_keys": frozenset(),
        "prerequisite_memory_ids": frozenset(),
        "mandatory": False,
        "relevance": 0.0,
        "utility": 0.0,
        "direct_credit": 0.0,
        "inherited_credit": 0.0,
        "harm_risk": 0.0,
        "authority": 1.0,
        "confidence": 1.0,
    }
    values.update(overrides)
    return IntegratedContextEvidence(**values)


def request(**overrides: object) -> IntegratedContextCompileRequest:
    values: dict[str, object] = {
        "space_id": SPACE_ID,
        "token_budget": 700,
        "envelope_tokens": 100,
        "max_items": 6,
        "coverage_demands": (),
        "exact_candidate_limit": 18,
    }
    values.update(overrides)
    return IntegratedContextCompileRequest(**values)


def pair(
    left: int,
    right: int,
    *,
    kind: ContextInteractionKind,
    value: float,
) -> ContextPairInteraction:
    return ContextPairInteraction(
        left_memory_id=memory_id(left),
        right_memory_id=memory_id(right),
        kind=kind,
        value=value,
        standard_error=0.01,
        trial_count=4,
        evidence_group_id=GROUP_ID,
    )


def test_compiler_switches_between_exact_and_heuristic_modes() -> None:
    exact = IntegratedContextCompiler().compile(
        request(exact_candidate_limit=2),
        (item(1, relevance=0.5), item(2, relevance=0.4)),
    )
    heuristic = IntegratedContextCompiler().compile(
        request(exact_candidate_limit=1),
        (item(1, relevance=0.5), item(2, relevance=0.4)),
    )

    assert exact.solver_mode is ContextSolverMode.EXACT
    assert exact.optimality_gap == 0.0
    assert heuristic.solver_mode is ContextSolverMode.HEURISTIC
    assert heuristic.optimality_gap is None


def test_mandatory_closure_is_ordered_before_dependents_and_never_truncated() -> None:
    exact_content = "A" * 400
    prerequisite = item(1, content=exact_content, estimated_tokens=90)
    mandatory = item(
        2,
        mandatory=True,
        prerequisite_memory_ids={memory_id(1)},
        estimated_tokens=110,
        relevance=0.2,
    )

    packet = IntegratedContextCompiler().compile(
        request(token_budget=350, envelope_tokens=100, max_items=2),
        (mandatory, prerequisite),
    )

    assert tuple(entry.evidence.memory_id for entry in packet.selected) == (
        memory_id(1),
        memory_id(2),
    )
    assert packet.selected[0].evidence.content == exact_content
    assert packet.selected[0].evidence.content_hash == digest(exact_content)
    assert packet.evidence_tokens == 200
    assert packet.total_tokens == 300
    assert packet.remaining_tokens == 50
    assert packet.selected[0].selection_phase is ContextSelectionPhase.MANDATORY
    assert packet.selected[1].selection_phase is ContextSelectionPhase.MANDATORY


def test_mandatory_closure_overflow_fails_instead_of_truncating() -> None:
    prerequisite = item(1, estimated_tokens=150)
    mandatory = item(
        2,
        mandatory=True,
        prerequisite_memory_ids={memory_id(1)},
        estimated_tokens=150,
    )

    with pytest.raises(ContextBudgetError, match="mandatory"):
        IntegratedContextCompiler().compile(
            request(token_budget=300, envelope_tokens=100, max_items=2),
            (mandatory, prerequisite),
        )


def test_packet_reports_covered_and_uncovered_required_demands() -> None:
    compile_request = request(
        coverage_demands=(
            ContextCoverageDemand("state", 2.0, True),
            ContextCoverageDemand("failure", 1.0, True),
        ),
        max_items=1,
    )
    state = item(1, coverage_keys={"state"}, relevance=0.4)

    packet = IntegratedContextCompiler().compile(compile_request, (state,))

    assert packet.required_coverage_keys == ("failure", "state")
    assert packet.covered_required_keys == ("state",)
    assert packet.uncovered_required_keys == ("failure",)
    assert packet.complete is False


def test_compiled_evidence_audits_separate_direct_and_inherited_contributions() -> None:
    candidate = item(
        1,
        relevance=0.3,
        direct_credit=0.6,
        inherited_credit=1.0,
    )

    packet = IntegratedContextCompiler().compile(request(), (candidate,))
    compiled = packet.selected[0]

    assert isinstance(compiled, CompiledContextEvidence)
    assert compiled.direct_credit_contribution == pytest.approx(0.27)
    assert compiled.inherited_credit_contribution == pytest.approx(0.10)
    assert compiled.direct_credit_contribution != compiled.inherited_credit_contribution
    assert compiled.marginal_tokens == candidate.estimated_tokens
    assert compiled.final_position == 1


def test_topological_order_precedes_mandatory_and_required_priority() -> None:
    prerequisite = item(1, relevance=0.1)
    dependent = item(
        2,
        mandatory=True,
        prerequisite_memory_ids={memory_id(1)},
        relevance=0.9,
    )
    required = item(3, coverage_keys={"state"}, relevance=0.2)
    optional = item(4, relevance=0.8)

    packet = IntegratedContextCompiler().compile(
        request(
            coverage_demands=(ContextCoverageDemand("state", 1.0, True),)
        ),
        (optional, required, dependent, prerequisite),
    )

    ordered_ids = tuple(entry.evidence.memory_id for entry in packet.selected)
    assert ordered_ids.index(memory_id(1)) < ordered_ids.index(memory_id(2))
    assert packet.dependency_closure[memory_id(2)] == (memory_id(1),)


def test_nonselected_candidates_receive_deterministic_omission_reasons() -> None:
    selected = item(1, relevance=0.5, estimated_tokens=100)
    negative = item(2, utility=-1.0, estimated_tokens=100)
    too_large = item(3, relevance=0.9, estimated_tokens=500)

    packet = IntegratedContextCompiler().compile(
        request(token_budget=350, envelope_tokens=100, max_items=2),
        (too_large, negative, selected),
    )
    omissions = {entry.memory_id: entry.reason for entry in packet.omissions}

    assert omissions[memory_id(2)] in (
        ContextOmissionReason.NON_POSITIVE_MARGINAL_VALUE,
        ContextOmissionReason.NOT_SELECTED_BY_EXACT_SOLVER,
    )
    assert omissions[memory_id(3)] is ContextOmissionReason.TOKEN_BUDGET


def test_packet_identity_and_json_are_invariant_to_input_order() -> None:
    compile_request = request(
        coverage_demands=(ContextCoverageDemand("state", 1.0, True),)
    )
    candidates = (
        item(1, coverage_keys={"state"}, relevance=0.2),
        item(2, relevance=0.4),
        item(3, relevance=0.3),
    )
    interactions = (
        pair(2, 3, kind=ContextInteractionKind.REDUNDANCY, value=-0.2),
    )

    first = IntegratedContextCompiler().compile(
        compile_request,
        candidates,
        interactions,
    )
    second = IntegratedContextCompiler().compile(
        compile_request,
        tuple(reversed(candidates)),
        tuple(reversed(interactions)),
    )

    assert first == second
    assert first.packet_id == second.packet_id
    assert first.render_json() == second.render_json()


def test_packet_collections_are_immutable() -> None:
    packet = IntegratedContextCompiler().compile(
        request(),
        (item(1, relevance=0.4),),
    )

    assert isinstance(packet, IntegratedContextPacket)
    with pytest.raises(TypeError):
        packet.dependency_closure[memory_id(1)] = ()
    with pytest.raises(AttributeError):
        packet.selected.append(packet.selected[0])
