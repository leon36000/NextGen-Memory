from __future__ import annotations

import hashlib

from scripts.simulate_provenance_credit import SimulationConfig, simulate


def test_simulation_exposes_naive_branch_inflation_and_false_credit() -> None:
    result = simulate(SimulationConfig())

    assert result.naive_branch_propagated == 1.0
    assert result.conservative_branch_propagated == 0.5
    assert result.naive_branch_inflation_ratio == 2.0
    assert result.conservative_branch_inflation_ratio == 1.0
    assert result.naive_blocked_relation_false_credit == 0.5
    assert result.conservative_blocked_relation_false_credit == 0.0
    assert result.naive_negative_false_blame == 0.5
    assert result.conservative_negative_false_blame == 0.0
    assert result.conservative_max_conservation_residual == 0.0


def test_simulation_is_deterministic_and_json_is_byte_identical() -> None:
    config = SimulationConfig(seed=20_260_814)
    first = simulate(config)
    second = simulate(config)

    assert first == second
    assert first.to_json() == second.to_json()
    digest = hashlib.sha256((first.to_json() + "\n").encode("utf-8")).hexdigest()
    assert len(digest) == 64
    assert digest == hashlib.sha256(
        (second.to_json() + "\n").encode("utf-8")
    ).hexdigest()
