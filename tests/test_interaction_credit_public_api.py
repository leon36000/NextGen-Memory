import sys

from nextgen_memory import (
    AdaptiveOrderPlanner,
    AdaptiveOrderPlannerConfig,
    CoalitionRequest,
    CoalitionRequestReason,
    InteractionCreditAbstentionReason,
    InteractionCreditConfig,
    InteractionCreditResult,
    InteractionEstimationMode,
    InteractionOrderPlan,
    InteractionTrial,
    MemoryDependencyGraph,
    MemoryInteractionAbstention,
    MemoryInteractionCredit,
    PairInteractionEstimate,
    PairInteractionKind,
    PairwiseInteractionEstimator,
    PrecedenceShapleyEstimator,
)


def test_interaction_credit_contracts_are_public_and_dependency_free() -> None:
    assert AdaptiveOrderPlanner is not None
    assert AdaptiveOrderPlannerConfig is not None
    assert CoalitionRequest is not None
    assert CoalitionRequestReason is not None
    assert InteractionCreditAbstentionReason is not None
    assert InteractionCreditConfig is not None
    assert InteractionCreditResult is not None
    assert InteractionEstimationMode is not None
    assert InteractionOrderPlan is not None
    assert InteractionTrial is not None
    assert MemoryDependencyGraph is not None
    assert MemoryInteractionAbstention is not None
    assert MemoryInteractionCredit is not None
    assert PairInteractionEstimate is not None
    assert PairInteractionKind is not None
    assert PairwiseInteractionEstimator is not None
    assert PrecedenceShapleyEstimator is not None

    for module_name in (
        "numpy",
        "scipy",
        "torch",
        "tensorflow",
        "pymongo",
        "psycopg",
    ):
        assert module_name not in sys.modules
