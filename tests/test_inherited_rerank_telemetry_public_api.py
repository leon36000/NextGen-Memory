from __future__ import annotations

import nextgen_memory
from nextgen_memory.inherited_rerank_telemetry import (
    InMemoryInheritedRerankTelemetrySink,
    InheritedRerankObservation,
    InheritedRerankSummary,
    InheritedRerankTelemetryBatch,
    InheritedRerankTelemetryConflictError,
    InheritedRerankTelemetrySink,
    InheritedRerankTelemetryValidationError,
    build_inherited_rerank_telemetry,
    fingerprint_bounded_inherited_policy,
)


def test_package_exports_stable_inherited_rerank_telemetry_v0_api() -> None:
    expected = {
        "InMemoryInheritedRerankTelemetrySink": (
            InMemoryInheritedRerankTelemetrySink
        ),
        "InheritedRerankObservation": InheritedRerankObservation,
        "InheritedRerankSummary": InheritedRerankSummary,
        "InheritedRerankTelemetryBatch": InheritedRerankTelemetryBatch,
        "InheritedRerankTelemetryConflictError": (
            InheritedRerankTelemetryConflictError
        ),
        "InheritedRerankTelemetrySink": InheritedRerankTelemetrySink,
        "InheritedRerankTelemetryValidationError": (
            InheritedRerankTelemetryValidationError
        ),
        "build_inherited_rerank_telemetry": build_inherited_rerank_telemetry,
        "fingerprint_bounded_inherited_policy": (
            fingerprint_bounded_inherited_policy
        ),
    }

    for name, value in expected.items():
        assert getattr(nextgen_memory, name) is value
        assert name in nextgen_memory.__all__
