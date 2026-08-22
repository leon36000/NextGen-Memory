from __future__ import annotations

from dataclasses import replace
from uuid import UUID, uuid5

import pytest

from nextgen_memory.causal_credit import (
    AttributedMemoryCredit,
    CreditAssignmentResult,
    CreditVerdict,
)
from nextgen_memory.causal_feedback import (
    CAUSAL_FEEDBACK_INSERT_SQL,
    CAUSAL_FEEDBACK_SELECT_SQL,
    CausalFeedbackConflictError,
    CausalFeedbackWriter,
    build_memory_feedback_records,
)

SPACE_ID = UUID("279c0edc-e75d-5c7e-a857-2f461b4ba61e")
MEMORY_A = UUID("00000000-0000-5000-8000-000000000001")
MEMORY_B = UUID("00000000-0000-5000-8000-000000000002")
EVENT_A = UUID("00000000-0000-5000-8000-000000000011")
EVENT_B = UUID("00000000-0000-5000-8000-000000000012")
ROUTER_DECISION_ID = UUID("00000000-0000-5000-8000-000000000021")
EVALUATION_ID = UUID("00000000-0000-5000-8000-000000000031")
CONTEXT_SET_HASH = "a" * 64
CONTINUATION_SET_HASH = "b" * 64
EXPECTED_METADATA_KEYS = {
    "credit_version",
    "trial_count",
    "mean_full_score",
    "mean_no_memory_score",
    "mean_without_memory_score",
    "mean_bundle_uplift",
    "mean_effect",
    "standard_error",
    "context_set_hash",
    "continuation_set_hash",
}


def credit(
    memory_id: UUID = MEMORY_A,
    *,
    verdict: CreditVerdict = CreditVerdict.HELPFUL,
    effect: float = 0.10,
) -> AttributedMemoryCredit:
    return AttributedMemoryCredit(
        memory_id=memory_id,
        retrieval_event_id=EVENT_A if memory_id == MEMORY_A else EVENT_B,
        router_decision_id=ROUTER_DECISION_ID,
        verdict=verdict,
        reward=effect,
        task_success=True,
        token_delta=30,
        latency_delta_ms=10.0,
        trial_count=3,
        mean_full_score=0.80,
        mean_no_memory_score=0.55,
        mean_without_memory_score=0.70,
        mean_bundle_uplift=0.25,
        mean_effect=effect,
        standard_error=0.01,
        full_success_rate=1.0,
        without_success_rate=2 / 3,
        context_set_hash=CONTEXT_SET_HASH,
        continuation_set_hash=CONTINUATION_SET_HASH,
    )


def assignment(*credits: AttributedMemoryCredit) -> CreditAssignmentResult:
    return CreditAssignmentResult(
        router_decision_id=ROUTER_DECISION_ID,
        credits=tuple(credits),
        abstentions=(),
        interaction_ambiguous=False,
        context_set_hash=CONTEXT_SET_HASH,
        continuation_set_hash=CONTINUATION_SET_HASH,
    )


def record():
    return build_memory_feedback_records(
        space_id=SPACE_ID,
        credit_evaluation_id=EVALUATION_ID,
        assignment=assignment(credit()),
    )[0]


def test_builder_creates_deterministic_safe_feedback_records() -> None:
    records = build_memory_feedback_records(
        space_id=SPACE_ID,
        credit_evaluation_id=EVALUATION_ID,
        assignment=assignment(credit()),
    )
    built = records[0]

    assert built.id == uuid5(
        EVALUATION_ID,
        f"paired_leave_one_out_v0:{MEMORY_A}",
    )
    assert built.space_id == SPACE_ID
    assert built.node_id == MEMORY_A
    assert built.router_decision_id == ROUTER_DECISION_ID
    assert built.verdict == "helpful"
    assert built.reward == pytest.approx(0.10)
    assert built.task_success is True
    assert built.token_delta == 30
    assert built.latency_delta_ms == pytest.approx(10.0)
    assert built.notes is None
    assert built.credit_evaluation_id == EVALUATION_ID
    assert built.evidence_key == "paired_leave_one_out_v0"
    assert len(built.content_hash) == 64
    assert set(built.metadata) == EXPECTED_METADATA_KEYS
    with pytest.raises(TypeError):
        built.metadata["mean_effect"] = 0.0


def test_builder_orders_records_by_memory_id_and_rejects_mismatched_assignment() -> None:
    records = build_memory_feedback_records(
        space_id=SPACE_ID,
        credit_evaluation_id=EVALUATION_ID,
        assignment=assignment(credit(MEMORY_B), credit(MEMORY_A)),
    )

    assert [built.node_id for built in records] == [MEMORY_A, MEMORY_B]

    mismatched = CreditAssignmentResult(
        router_decision_id=UUID("00000000-0000-5000-8000-000000000099"),
        credits=(credit(),),
        abstentions=(),
        interaction_ambiguous=False,
        context_set_hash=CONTEXT_SET_HASH,
        continuation_set_hash=CONTINUATION_SET_HASH,
    )
    with pytest.raises(ValueError, match="router decision"):
        build_memory_feedback_records(
            space_id=SPACE_ID,
            credit_evaluation_id=EVALUATION_ID,
            assignment=mismatched,
        )


@pytest.mark.parametrize(
    "unexpected_key",
    ["apiKey", "credential", "providerBody", "apparently_safe"],
)
def test_record_rejects_every_unexpected_metadata_key(unexpected_key: str) -> None:
    built = record()
    metadata = dict(built.metadata)
    metadata[unexpected_key] = "protected-value"

    with pytest.raises(ValueError, match="exact causal aggregate schema"):
        replace(built, metadata=metadata)


def test_record_rejects_missing_metadata_key() -> None:
    built = record()
    metadata = dict(built.metadata)
    metadata.pop("standard_error")

    with pytest.raises(ValueError, match="exact causal aggregate schema"):
        replace(built, metadata=metadata)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("credit_version", "unapproved-version"),
        ("trial_count", True),
        ("trial_count", 0),
        ("mean_full_score", True),
        ("mean_effect", "0.1"),
        ("standard_error", -0.01),
        ("context_set_hash", "a" * 63),
        ("continuation_set_hash", "B" * 64),
    ],
)
def test_record_rejects_malformed_allowlisted_metadata(
    field: str,
    value: object,
) -> None:
    built = record()
    metadata = dict(built.metadata)
    metadata[field] = value

    with pytest.raises(ValueError):
        replace(built, metadata=metadata)


def test_record_rejects_nested_metadata_even_under_allowlisted_key() -> None:
    built = record()
    metadata = dict(built.metadata)
    metadata["mean_effect"] = {"value": 0.1}

    with pytest.raises(ValueError):
        replace(built, metadata=metadata)


class FakeCursor:
    def __init__(self, stored_rows: list[dict[str, object]]) -> None:
        self.stored_rows = stored_rows
        self.executemany_calls: list[tuple[str, list[dict[str, object]]]] = []
        self.execute_calls: list[tuple[str, dict[str, object]]] = []

    def executemany(self, sql: str, rows: list[dict[str, object]]) -> None:
        self.executemany_calls.append((sql, rows))

    def execute(self, sql: str, params: dict[str, object]) -> None:
        self.execute_calls.append((sql, params))

    def fetchall(self) -> list[dict[str, object]]:
        return self.stored_rows


def stored_row(built, **changes: object) -> dict[str, object]:
    row = built.to_db_params()
    row.update(changes)
    return row


def test_writer_inserts_then_verifies_exact_immutable_payload() -> None:
    built = record()
    cursor = FakeCursor([stored_row(built)])

    count = CausalFeedbackWriter().write(cursor, (built,))

    assert count == 1
    assert cursor.executemany_calls == [
        (CAUSAL_FEEDBACK_INSERT_SQL, [built.to_db_params()])
    ]
    assert cursor.execute_calls == [
        (
            CAUSAL_FEEDBACK_SELECT_SQL,
            {
                "space_id": SPACE_ID,
                "ids": [built.id],
            },
        )
    ]


def test_writer_accepts_identical_retry_and_rejects_conflicting_stored_payload() -> None:
    built = record()

    assert CausalFeedbackWriter().write(
        FakeCursor([stored_row(built)]),
        (built,),
    ) == 1

    with pytest.raises(CausalFeedbackConflictError, match="immutable payload"):
        CausalFeedbackWriter().write(
            FakeCursor([stored_row(built, reward=-0.50)]),
            (built,),
        )


def test_writer_rejects_missing_duplicate_or_unexpected_stored_rows() -> None:
    built = record()

    with pytest.raises(CausalFeedbackConflictError, match="missing"):
        CausalFeedbackWriter().write(FakeCursor([]), (built,))
    with pytest.raises(CausalFeedbackConflictError, match="duplicate"):
        CausalFeedbackWriter().write(
            FakeCursor([stored_row(built), stored_row(built)]),
            (built,),
        )
    unexpected = stored_row(
        built,
        id=UUID("00000000-0000-5000-8000-999999999999"),
    )
    with pytest.raises(CausalFeedbackConflictError, match="unexpected"):
        CausalFeedbackWriter().write(FakeCursor([unexpected]), (built,))


def test_writer_translates_stored_metadata_schema_failure_without_payload_leak() -> None:
    built = record()
    sentinel = "mongodb://user:secret@private-host/research"
    metadata = dict(built.metadata)
    metadata["mean_effect"] = {"credential": sentinel}
    row = stored_row(built, metadata=metadata)

    with pytest.raises(
        CausalFeedbackConflictError,
        match="metadata violates the causal aggregate schema",
    ) as exc_info:
        CausalFeedbackWriter().write(FakeCursor([row]), (built,))

    message = str(exc_info.value)
    assert sentinel not in message
    assert "secret" not in message
    assert "private-host" not in message
    assert "credential" not in message


def test_writer_skips_empty_batches_and_rejects_mixed_spaces() -> None:
    cursor = FakeCursor([])

    assert CausalFeedbackWriter().write(cursor, ()) == 0
    assert cursor.executemany_calls == []
    assert cursor.execute_calls == []

    first = build_memory_feedback_records(
        space_id=SPACE_ID,
        credit_evaluation_id=EVALUATION_ID,
        assignment=assignment(credit(MEMORY_A)),
    )[0]
    second = build_memory_feedback_records(
        space_id=UUID("00000000-0000-5000-8000-000000000099"),
        credit_evaluation_id=EVALUATION_ID,
        assignment=assignment(credit(MEMORY_B)),
    )[0]
    with pytest.raises(ValueError, match="one space_id"):
        CausalFeedbackWriter().write(FakeCursor([]), (first, second))
