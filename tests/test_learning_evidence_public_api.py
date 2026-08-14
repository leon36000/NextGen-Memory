from __future__ import annotations

import nextgen_memory
from nextgen_memory.learning_evidence import (
    LEARNING_EVIDENCE_SELECT_SQL,
    DirectUtilityEvidence,
    InheritedUtilityEvidence,
    LearningEvidenceCursor,
    LearningEvidenceReadConflictError,
    LearningEvidenceValidationError,
    NeonLearningEvidenceReader,
    NodeLearningEvidence,
)


def test_package_exports_stable_learning_evidence_reader_v0_api() -> None:
    expected = {
        "LEARNING_EVIDENCE_SELECT_SQL": LEARNING_EVIDENCE_SELECT_SQL,
        "DirectUtilityEvidence": DirectUtilityEvidence,
        "InheritedUtilityEvidence": InheritedUtilityEvidence,
        "LearningEvidenceCursor": LearningEvidenceCursor,
        "LearningEvidenceReadConflictError": LearningEvidenceReadConflictError,
        "LearningEvidenceValidationError": LearningEvidenceValidationError,
        "NeonLearningEvidenceReader": NeonLearningEvidenceReader,
        "NodeLearningEvidence": NodeLearningEvidence,
    }

    for name, value in expected.items():
        assert getattr(nextgen_memory, name) is value
        assert name in nextgen_memory.__all__
