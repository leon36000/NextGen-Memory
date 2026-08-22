from __future__ import annotations

import importlib
from dataclasses import FrozenInstanceError, fields
from types import ModuleType
from uuid import UUID, uuid4

import pytest

from nextgen_memory.retrieval_telemetry import RetrievalEvent

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
OTHER_SPACE_ID = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
DECISION_ID = UUID("00000000-0000-5000-8000-000000000021")
OTHER_DECISION_ID = UUID("00000000-0000-5000-8000-000000000022")
ACTION_ID = UUID("00000000-0000-5000-8000-000000000031")
MEMORY_A = UUID("00000000-0000-5000-8000-000000000001")
MEMORY_B = UUID("00000000-0000-5000-8000-000000000002")
EVENT_A = UUID("00000000-0000-5000-8000-000000000011")
EVENT_B = UUID("00000000-0000-5000-8000-000000000012")


def action_usage() -> ModuleType:
    return importlib.import_module("nextgen_memory.action_usage")


def retrieval_event(
    memory_id: UUID | None = MEMORY_A,
    *,
    event_id: UUID = EVENT_A,
    space_id: UUID = SPACE_ID,
    router_decision_id: UUID = DECISION_ID,
    selected_for_context: bool = True,
) -> RetrievalEvent:
    return RetrievalEvent(
        id=event_id,
        space_id=space_id,
        router_decision_id=router_decision_id,
        expert_key="research",
        node_id=memory_id,
        backend_ref=f"paper:{event_id}",
        rank=1,
        raw_score=0.5,
        final_score=0.5,
        selected_for_context=selected_for_context,
        used_in_action=False,
    )


def build(
    events: tuple[RetrievalEvent, ...] | None = None,
    used: frozenset[UUID] | None = None,
):
    module = action_usage()
    return module.build_action_memory_usage_events(
        action_id=ACTION_ID,
        retrieval_events=events or (retrieval_event(),),
        used_memory_ids=used or frozenset({MEMORY_A}),
    )


def test_action_usage_module_and_contract_exist() -> None:
    module = action_usage()

    assert hasattr(module, "ActionMemoryUsageEvent")
    assert hasattr(module, "ActionMemoryUsageWriter")
    assert hasattr(module, "ActionMemoryUsageConflictError")
    assert hasattr(module, "build_action_memory_usage_events")
    assert isinstance(module.ACTION_MEMORY_USAGE_INSERT_SQL, str)
    assert isinstance(module.ACTION_MEMORY_USAGE_SELECT_SQL, str)


def test_built_event_is_frozen_slotted_and_privacy_safe() -> None:
    built = build()[0]

    assert not hasattr(built, "__dict__")
    with pytest.raises(FrozenInstanceError):
        built.action_id = uuid4()

    assert {field.name for field in fields(built)} == {
        "id",
        "space_id",
        "action_id",
        "router_decision_id",
        "retrieval_event_id",
        "memory_id",
        "content_hash",
    }
    params = built.to_db_params()
    assert set(params) == {
        "id",
        "space_id",
        "action_id",
        "router_decision_id",
        "retrieval_event_id",
        "node_id",
        "content_hash",
    }
    forbidden = {
        "query",
        "prompt",
        "answer",
        "content",
        "title",
        "source_uri",
        "backend_ref",
        "score",
        "command",
        "output",
        "secret",
    }
    assert forbidden.isdisjoint(params)
    assert len(built.content_hash) == 64


def test_builder_is_deterministic_under_event_and_set_permutations() -> None:
    event_a = retrieval_event()
    event_b = retrieval_event(MEMORY_B, event_id=EVENT_B)

    first = build((event_a, event_b), frozenset({MEMORY_A, MEMORY_B}))
    second = build((event_b, event_a), frozenset({MEMORY_B, MEMORY_A}))

    assert first == second
    assert [item.memory_id for item in first] == [MEMORY_A, MEMORY_B]
    assert len({item.id for item in first}) == 2
    assert len({item.content_hash for item in first}) == 2


def test_builder_persists_only_positive_used_subset() -> None:
    event_a = retrieval_event()
    event_b = retrieval_event(MEMORY_B, event_id=EVENT_B)

    built = build((event_a, event_b), frozenset({MEMORY_B}))

    assert len(built) == 1
    assert built[0].memory_id == MEMORY_B
    assert built[0].retrieval_event_id == EVENT_B


@pytest.mark.parametrize(
    ("events", "used", "message"),
    [
        ((retrieval_event(selected_for_context=False),), frozenset({MEMORY_A}), "selected"),
        ((retrieval_event(None),), frozenset({MEMORY_A}), "unknown"),
        ((retrieval_event(),), frozenset({MEMORY_B}), "unknown"),
        (
            (
                retrieval_event(),
                retrieval_event(MEMORY_B, event_id=EVENT_B, space_id=OTHER_SPACE_ID),
            ),
            frozenset({MEMORY_A}),
            "one space_id",
        ),
        (
            (
                retrieval_event(),
                retrieval_event(
                    MEMORY_B,
                    event_id=EVENT_B,
                    router_decision_id=OTHER_DECISION_ID,
                ),
            ),
            frozenset({MEMORY_A}),
            "one router_decision_id",
        ),
        (
            (retrieval_event(), retrieval_event(event_id=EVENT_B)),
            frozenset({MEMORY_A}),
            "duplicate memory",
        ),
        (
            (retrieval_event(), retrieval_event(MEMORY_B, event_id=EVENT_A)),
            frozenset({MEMORY_A}),
            "duplicate retrieval",
        ),
    ],
)
def test_builder_rejects_invalid_usage_evidence(
    events: tuple[RetrievalEvent, ...],
    used: frozenset[UUID],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        build(events, used)


def test_empty_exact_usage_set_is_a_valid_empty_result() -> None:
    module = action_usage()

    assert module.build_action_memory_usage_events(
        action_id=ACTION_ID,
        retrieval_events=(retrieval_event(),),
        used_memory_ids=frozenset(),
    ) == ()


@pytest.mark.parametrize("value", [True, "not-a-uuid", None])
def test_builder_requires_uuid_action_id(value: object) -> None:
    module = action_usage()

    with pytest.raises(ValueError, match="action_id"):
        module.build_action_memory_usage_events(
            action_id=value,
            retrieval_events=(retrieval_event(),),
            used_memory_ids=frozenset({MEMORY_A}),
        )
