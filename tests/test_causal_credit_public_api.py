import sys

from nextgen_memory import (
    CAUSAL_FEEDBACK_INSERT_SQL,
    CAUSAL_FEEDBACK_SELECT_SQL,
    CREDIT_TARGETS_SELECT_SQL,
    AttributedMemoryCredit,
    CausalCreditAssigner,
    CausalCreditConfig,
    CausalFeedbackConflictError,
    CausalFeedbackWriter,
    CounterfactualTrial,
    CreditAbstention,
    CreditAbstentionReason,
    CreditAssignmentResult,
    CreditTarget,
    CreditTargetReader,
    CreditVerdict,
    MemoryFeedbackRecord,
    OutcomeMeasurement,
    build_memory_feedback_records,
)


def test_post_action_causal_credit_contracts_are_public_and_dependency_free() -> None:
    assert CAUSAL_FEEDBACK_INSERT_SQL.startswith("INSERT")
    assert CAUSAL_FEEDBACK_SELECT_SQL.startswith("SELECT")
    assert CREDIT_TARGETS_SELECT_SQL.startswith("SELECT")
    assert AttributedMemoryCredit is not None
    assert CausalCreditAssigner is not None
    assert CausalCreditConfig is not None
    assert CausalFeedbackConflictError is not None
    assert CausalFeedbackWriter is not None
    assert CounterfactualTrial is not None
    assert CreditAbstention is not None
    assert CreditAbstentionReason is not None
    assert CreditAssignmentResult is not None
    assert CreditTarget is not None
    assert CreditTargetReader is not None
    assert CreditVerdict is not None
    assert MemoryFeedbackRecord is not None
    assert OutcomeMeasurement is not None
    assert build_memory_feedback_records is not None

    for module_name in ("psycopg", "pymongo", "numpy", "torch", "tensorflow"):
        assert module_name not in sys.modules
