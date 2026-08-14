from __future__ import annotations

import importlib
import sys


def test_public_api_exposes_research_retrieval_components_without_importing_pymongo() -> None:
    sys.modules.pop("pymongo", None)
    package = importlib.import_module("nextgen_memory")
    package = importlib.reload(package)

    assert package.ResearchRetrievalQuery is not None
    assert package.ResearchRetrievalHit is not None
    assert package.MongoResearchIndexConfig is not None
    assert package.MongoResearchRetriever is not None
    assert package.build_research_hybrid_pipeline is not None
    assert package.RetrievalEvent is not None
    assert package.RetrievalEventWriter is not None
    assert package.build_retrieval_events is not None
    assert "pymongo" not in sys.modules
