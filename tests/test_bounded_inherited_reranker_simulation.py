from __future__ import annotations

import json

from scripts.simulate_bounded_inherited_reranker_v0 import (
    simulate_bounded_inherited_reranker_v0,
)


def test_bounded_policy_eliminates_weak_evidence_false_promotions() -> None:
    result = simulate_bounded_inherited_reranker_v0()

    assert result["scenario_count"] == 5
    assert result["naive_false_promotions"] == 4
    assert result["bounded_false_promotions"] == 0
    assert result["bounded_strong_promotions"] == 1
    assert result["maximum_absolute_adjustment"] == 0.05

    by_name = {item["name"]: item for item in result["scenarios"]}
    assert by_name["rare_large_value"]["bounded_disposition_b"] == (
        "below_minimum_count"
    )
    assert by_name["low_structural_confidence"][
        "bounded_disposition_b"
    ] == "below_minimum_confidence"
    assert by_name["conflicting_paths"]["path_coherence_b"] == 0.02
    assert by_name["high_uncertainty"]["uncertainty_reliability_b"] < 0.1
    assert by_name["many_consistent_high_confidence_paths"][
        "bounded_adjustment_b"
    ] == 0.05


def test_simulation_is_deterministic_and_every_adjustment_is_bounded() -> None:
    first = simulate_bounded_inherited_reranker_v0()
    second = simulate_bounded_inherited_reranker_v0()

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert all(
        abs(item["bounded_adjustment_b"])
        <= first["maximum_absolute_adjustment"]
        for item in first["scenarios"]
    )
