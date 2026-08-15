from __future__ import annotations

import nextgen_memory
from nextgen_memory.bounded_inherited_reranker import (
    BoundedInheritedReranker,
    BoundedInheritedRerankerConfig,
    BoundedInheritedRerankerValidationError,
    InheritedAwareRerankedMemory,
    InheritedEvidenceDisposition,
    InheritedScoreBreakdown,
)


def test_package_exports_stable_bounded_inherited_reranker_v0_api() -> None:
    expected = {
        "BoundedInheritedReranker": BoundedInheritedReranker,
        "BoundedInheritedRerankerConfig": BoundedInheritedRerankerConfig,
        "BoundedInheritedRerankerValidationError": (
            BoundedInheritedRerankerValidationError
        ),
        "InheritedAwareRerankedMemory": InheritedAwareRerankedMemory,
        "InheritedEvidenceDisposition": InheritedEvidenceDisposition,
        "InheritedScoreBreakdown": InheritedScoreBreakdown,
    }

    for name, value in expected.items():
        assert getattr(nextgen_memory, name) is value
        assert name in nextgen_memory.__all__
