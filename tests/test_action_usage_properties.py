from __future__ import annotations

import importlib
import random
from uuid import UUID

from nextgen_memory.retrieval_telemetry import RetrievalEvent

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
DECISION_ID = UUID("00000000-0000-5000-8000-000000000021")
ACTION_ID = UUID("00000000-0000-5000-8000-000000000031")


def test_10000_permuted_usage_builds_are_byte_stable_and_scope_safe() -> None:
    module = importlib.import_module("nextgen_memory.action_usage")
    rng = random.Random(20260822)

    for case_index in range(10_000):
        count = 1 + case_index % 6
        events: list[RetrievalEvent] = []
        memory_ids: list[UUID] = []
        for item_index in range(count):
            memory_id = UUID(
                f"00000000-0000-5000-8000-{case_index * 10 + item_index + 1:012d}"
            )
            event_id = UUID(
                f"00000000-0000-5001-8000-{case_index * 10 + item_index + 1:012d}"
            )
            memory_ids.append(memory_id)
            events.append(
                RetrievalEvent(
                    id=event_id,
                    space_id=SPACE_ID,
                    router_decision_id=DECISION_ID,
                    expert_key="research",
                    node_id=memory_id,
                    backend_ref=f"paper:{case_index}:{item_index}",
                    rank=item_index + 1,
                    raw_score=0.5,
                    final_score=0.5,
                    selected_for_context=True,
                )
            )

        selected = frozenset(
            memory_id
            for index, memory_id in enumerate(memory_ids)
            if (case_index + index) % 2 == 0
        )
        baseline = module.build_action_memory_usage_events(
            action_id=ACTION_ID,
            retrieval_events=tuple(events),
            used_memory_ids=selected,
        )

        shuffled = events[:]
        rng.shuffle(shuffled)
        replay = module.build_action_memory_usage_events(
            action_id=ACTION_ID,
            retrieval_events=tuple(shuffled),
            used_memory_ids=frozenset(reversed(tuple(selected))),
        )

        assert replay == baseline
        assert all(item.space_id == SPACE_ID for item in baseline)
        assert all(item.router_decision_id == DECISION_ID for item in baseline)
        assert all(item.action_id == ACTION_ID for item in baseline)
        assert {item.memory_id for item in baseline} == selected
        assert len({item.id for item in baseline}) == len(baseline)
        assert len({item.content_hash for item in baseline}) == len(baseline)
