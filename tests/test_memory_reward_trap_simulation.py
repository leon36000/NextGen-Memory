from scripts.simulate_memory_reward_trap import SimulationConfig, simulate


def test_counterfactual_credit_avoids_shadow_memory_contamination() -> None:
    result = simulate(SimulationConfig())

    assert result.naive_shadow_contamination_rate >= 0.80
    assert result.counterfactual_shadow_contamination_rate <= 0.05
    assert result.counterfactual_causal_rank_rate > result.naive_causal_rank_rate
    assert result.observed_success_rate > 0.80


def test_simulation_is_deterministic_and_serializable() -> None:
    config = SimulationConfig(seed=20260814, task_count=250, shadow_count=3)

    first = simulate(config)
    second = simulate(config)

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.to_json().startswith('{"config":')
    assert '"naive_shadow_contamination_rate"' in first.to_json()
