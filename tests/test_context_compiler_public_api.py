import sys

from nextgen_memory import (
    CompiledContextEvidence,
    ContextBudgetError,
    ContextCompilerValidationError,
    ContextCoverageDemand,
    ContextDependencyError,
    ContextInteractionKind,
    ContextObjectiveBreakdown,
    ContextObjectivePolicy,
    ContextOmission,
    ContextOmissionReason,
    ContextOptimizationError,
    ContextPairInteraction,
    ContextSelectionPhase,
    ContextSolverMode,
    EvidenceFidelity,
    IntegratedContextCompiler,
    IntegratedContextCompileRequest,
    IntegratedContextEvidence,
    IntegratedContextPacket,
)


def test_context_compiler_contracts_are_public_and_dependency_free() -> None:
    exports = (
        CompiledContextEvidence,
        ContextBudgetError,
        ContextCompilerValidationError,
        ContextCoverageDemand,
        ContextDependencyError,
        ContextInteractionKind,
        ContextObjectiveBreakdown,
        ContextObjectivePolicy,
        ContextOmission,
        ContextOmissionReason,
        ContextOptimizationError,
        ContextPairInteraction,
        ContextSelectionPhase,
        ContextSolverMode,
        EvidenceFidelity,
        IntegratedContextCompiler,
        IntegratedContextCompileRequest,
        IntegratedContextEvidence,
        IntegratedContextPacket,
    )
    assert all(value is not None for value in exports)

    for module_name in (
        "numpy",
        "scipy",
        "ortools",
        "torch",
        "tensorflow",
        "pymongo",
        "psycopg",
    ):
        assert module_name not in sys.modules
