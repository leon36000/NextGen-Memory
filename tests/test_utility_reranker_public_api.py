import sys

from nextgen_memory import (
    NODE_UTILITY_SELECT_SQL,
    NodeUtilityReader,
    RerankedMemory,
    UtilityAwareReranker,
    UtilityAwareResearchRetriever,
    UtilityEvidence,
    UtilityRerankCandidate,
    UtilityRerankerConfig,
    UtilityScoreBreakdown,
    UtilitySnapshotProvider,
)


def test_utility_reranker_contracts_are_public_and_dependency_free() -> None:
    assert NODE_UTILITY_SELECT_SQL.startswith("SELECT")
    assert NodeUtilityReader is not None
    assert RerankedMemory is not None
    assert UtilityAwareReranker is not None
    assert UtilityAwareResearchRetriever is not None
    assert UtilityEvidence is not None
    assert UtilityRerankCandidate is not None
    assert UtilityRerankerConfig is not None
    assert UtilityScoreBreakdown is not None
    assert UtilitySnapshotProvider is not None

    for module_name in ("pymongo", "psycopg", "numpy", "torch", "tensorflow"):
        assert module_name not in sys.modules
