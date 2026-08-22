from scripts.simulate_causal_credit import SimulationConfig, simulate


def test_leave_one_out_localizes_credit_and_abstains_under_noise() -> None:
    result = simulate(SimulationConfig())

    assert result.bundle_shadow_contamination_rate >= 0.80
    assert result.loo_shadow_false_credit_rate <= 0.05
    assert result.loo_causal_detection_rate >= 0.75
    assert result.noisy_abstention_precision >= 0.90
    assert result.observed_success_rate >= 0.80


def test_simulation_is_deterministic_and_json_serializable() -> None:
    config = SimulationConfig(
        seed=20260814,
        task_count=250,
        shadow_count=3,
        trial_count=3,
        noise_stddev=0.03,
    )

    first = simulate(config)
    second = simulate(config)

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.to_json().startswith('{"bundle_shadow_contamination_rate":')
    assert '"loo_causal_detection_rate"' in first.to_json()


def test_invalid_simulation_controls_fail_closed() -> None:
    for kwargs in (
        {"task_count": 0},
        {"shadow_count": 0},
        {"trial_count": 1},
        {"noise_stddev": -0.1},
        {"success_probability": 1.1},
    ):
        try:
            SimulationConfig(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected invalid config to fail: {kwargs}")
