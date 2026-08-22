from __future__ import annotations

import nextgen_memory


def test_action_usage_symbols_are_explicit_package_root_exports() -> None:
    expected = {
        "ACTION_MEMORY_USAGE_INSERT_SQL",
        "ACTION_MEMORY_USAGE_SELECT_SQL",
        "ACTION_CREDIT_TARGETS_SELECT_SQL",
        "ActionMemoryUsageConflictError",
        "ActionMemoryUsageEvent",
        "ActionMemoryUsageWriter",
        "build_action_memory_usage_events",
    }

    assert expected.issubset(set(nextgen_memory.__all__))
    for name in expected:
        assert hasattr(nextgen_memory, name)
