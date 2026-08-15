from __future__ import annotations

import json

from scripts.simulate_paired_rerank_policy_evaluation_v0 import (
    simulate_paired_rerank_policy_evaluation_v0,
)


def test_paired_estimator_reduces_standard_error_under_correlated_outcomes() -> None:
    result = simulate_paired_rerank_policy_evaluation_v0()
    variance = result["variance_experiment"]

    assert variance["trial_count"] == 64
    assert variance["mean_score_delta"] > 0.04
    assert variance["paired_standard_error"] > 0.0
    assert variance["unpaired_standard_error"] > 0.0
    assert (
        variance["paired_standard_error"]
        < variance["unpaired_standard_error"]
    )
    assert variance["standard_error_ratio"] < 0.25
    assert variance["verdict"] == "promising"


def test_simulation_covers_all_policy_verdicts_deterministically() -> None:
    first = simulate_paired_rerank_policy_evaluation_v0()
    second = simulate_paired_rerank_policy_evaluation_v0()

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(
        second,
        sort_keys=True,
    )
    assert first["verdict_scenarios"] == {
        "harmful": "harmful",
        "inconclusive": "inconclusive",
        "insufficient_evidence": "insufficient_evidence",
        "neutral": "neutral",
        "promising": "promising",
        "too_costly": "too_costly",
    }
    assert first["scenario_count"] == 6
    assert first["memory_level_credit_emitted"] is False
