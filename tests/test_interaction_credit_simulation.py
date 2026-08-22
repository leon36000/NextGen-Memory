from __future__ import annotations

import pytest
from scripts.simulate_interaction_credit import SimulationConfig, simulate


def test_interaction_simulation_resolves_loo_failures_and_preserves_closure() -> None:
    result = simulate(SimulationConfig())

    assert result.redundant_loo_total == pytest.approx(0.0)
    assert result.redundant_shapley_total == pytest.approx(1.0, abs=0.03)
    assert result.redundancy_interaction < -0.90
    assert result.synergy_loo_total == pytest.approx(2.0)
    assert result.synergy_shapley_total == pytest.approx(1.0, abs=0.03)
    assert result.synergy_interaction > 0.90
    assert result.exact_closure_error <= 1e-9
    assert result.sampled_closure_error <= 1e-9
    assert result.sampled_rank_agreement >= 0.80
    assert result.sampled_order_count >= 2
    assert result.sampled_requested_coalitions <= result.config.sampled_order_budget


def test_interaction_simulation_is_deterministic_and_json_serializable() -> None:
    config = SimulationConfig(
        seed=20260814,
        trial_count=5,
        noise_stddev=0.01,
        sampled_order_budget=12,
    )

    first = simulate(config)
    second = simulate(config)

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.to_json().startswith('{"config":')
    assert '"sampled_rank_agreement"' in first.to_json()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"seed": True},
        {"trial_count": 1},
        {"noise_stddev": -0.1},
        {"noise_stddev": float("nan")},
        {"sampled_order_budget": 0},
    ],
)
def test_invalid_simulation_controls_fail_closed(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        SimulationConfig(**kwargs)
