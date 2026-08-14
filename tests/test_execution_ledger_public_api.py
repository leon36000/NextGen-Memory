from nextgen_memory import (
    AppendOnlyExecutionLedger,
    ExecutionArtifact,
    ExecutionEvent,
    ExecutionEventKind,
    ExecutionLedgerConflictError,
    ExecutionLedgerValidationError,
    ExecutionOutcome,
    ExecutionRun,
    ExecutionStatus,
)


def test_execution_ledger_contracts_are_public() -> None:
    assert AppendOnlyExecutionLedger is not None
    assert ExecutionArtifact is not None
    assert ExecutionEvent is not None
    assert ExecutionEventKind is not None
    assert ExecutionLedgerConflictError is not None
    assert ExecutionLedgerValidationError is not None
    assert ExecutionOutcome is not None
    assert ExecutionRun is not None
    assert ExecutionStatus is not None
