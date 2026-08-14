from __future__ import annotations

from uuid import UUID

import pytest

from nextgen_memory.causal_credit import (
    CausalCreditAssigner,
    CausalCreditConfig,
    CounterfactualTrial,
    CreditAbstentionReason,
    CreditTarget,
    CreditVerdict,
    OutcomeMeasurement,
)

MEMORY_A = UUID("00000000-0000-5000-8000-000000000001")
MEMORY_B = UUID("00000000-0000-5000-8000-000000000002")
EVENT_A = UUID("00000000-0000-5000-8000-000000000011")
EVENT_B = UUID("00000000-0000-5000-8000-000000000012")
ROUTER_DECISION_ID = UUID("00000000-0000-5000-8000-000000000021")
CONTEXT_HASH = "a" * 64


def outcome(
    score: float,
    *,
    success: bool,
    tokens: int = 100,
    latency_ms: float = 20.0,
) -> OutcomeMeasurement:
    return OutcomeMeasurement(
        score=score,
        task_success=success,
        tokens=tokens,
        latency_ms=latency_ms,
    )


def trial(
    key: str,
    *,
    full: OutcomeMeasurement,
    no_memory: OutcomeMeasurement,
    without_a: OutcomeMeasurement | None = None,
    without_b: OutcomeMeasurement | None = None,
) -> CounterfactualTrial:
    without_memory = {}
    if without_a is not None:
        without_memory[MEMORY_A] = without_a
    if without_b is not None:
        without_memory[MEMORY_B] = without_b
    return CounterfactualTrial(
        trial_key=key,
        context_hash=CONTEXT_HASH,
        continuation_hash=(key.encode("utf-8").hex() + "0" * 64)[:64],
        full=full,
        no_memory=no_memory,
        without_memory=without_memory,
    )


def target(
    memory_id: UUID = MEMORY_A,
    *,
    selected: bool = True,
    used: bool = True,
) -> CreditTarget:
    return CreditTarget(
        memory_id=memory_id,
        retrieval_event_id=EVENT_A if memory_id == MEMORY_A else EVENT_B,
        router_decision_id=ROUTER_DECISION_ID,
        selected_for_context=selected,
        used_in_action=used,
    )


def test_stable_positive_effect_is_helpful() -> None:
    trials = (
        trial(
            "trial-1",
            full=outcome(0.80, success=True, tokens=130, latency_ms=30),
            no_memory=outcome(0.55, success=False),
            without_a=outcome(0.70, success=True, tokens=100, latency_ms=20),
        ),
        trial(
            "trial-2",
            full=outcome(0.82, success=True, tokens=132, latency_ms=32),
            no_memory=outcome(0.56, success=False),
            without_a=outcome(0.72, success=True, tokens=102, latency_ms=22),
        ),
    )

    result = CausalCreditAssigner().assign((target(),), trials)
    credit = result.credits[0]

    assert result.abstentions == ()
    assert credit.verdict is CreditVerdict.HELPFUL
    assert credit.mean_effect == pytest.approx(0.10)
    assert credit.standard_error == pytest.approx(0.0)
    assert credit.mean_bundle_uplift == pytest.approx(0.255)
    assert credit.reward == pytest.approx(0.10)
    assert credit.task_success is True
    assert credit.token_delta == 30
    assert credit.latency_delta_ms == pytest.approx(10.0)
    assert credit.trial_count == 2


def test_large_effect_that_changes_success_is_decisive() -> None:
    trials = (
        trial(
            "trial-1",
            full=outcome(0.90, success=True),
            no_memory=outcome(0.40, success=False),
            without_a=outcome(0.55, success=False),
        ),
        trial(
            "trial-2",
            full=outcome(0.88, success=True),
            no_memory=outcome(0.42, success=False),
            without_a=outcome(0.53, success=False),
        ),
    )

    credit = CausalCreditAssigner().assign((target(),), trials).credits[0]

    assert credit.verdict is CreditVerdict.DECISIVE
    assert credit.mean_effect == pytest.approx(0.35)
    assert credit.full_success_rate == 1.0
    assert credit.without_success_rate == 0.0


def test_stable_negative_effect_is_harmful() -> None:
    trials = (
        trial(
            "trial-1",
            full=outcome(0.45, success=False),
            no_memory=outcome(0.70, success=True),
            without_a=outcome(0.75, success=True),
        ),
        trial(
            "trial-2",
            full=outcome(0.47, success=False),
            no_memory=outcome(0.72, success=True),
            without_a=outcome(0.77, success=True),
        ),
    )

    credit = CausalCreditAssigner().assign((target(),), trials).credits[0]

    assert credit.verdict is CreditVerdict.HARMFUL
    assert credit.mean_effect == pytest.approx(-0.30)
    assert credit.reward == pytest.approx(-0.30)
    assert credit.task_success is False


@pytest.mark.parametrize(
    ("selected", "used", "reason"),
    [
        (False, False, CreditAbstentionReason.NOT_SELECTED),
        (True, False, CreditAbstentionReason.NOT_USED),
    ],
)
def test_unused_or_unselected_memory_is_withheld(
    selected: bool,
    used: bool,
    reason: CreditAbstentionReason,
) -> None:
    trials = (
        trial(
            "trial-1",
            full=outcome(0.8, success=True),
            no_memory=outcome(0.5, success=False),
            without_a=outcome(0.6, success=False),
        ),
        trial(
            "trial-2",
            full=outcome(0.8, success=True),
            no_memory=outcome(0.5, success=False),
            without_a=outcome(0.6, success=False),
        ),
    )

    result = CausalCreditAssigner().assign(
        (target(selected=selected, used=used),),
        trials,
    )

    assert result.credits == ()
    assert result.abstentions[0].reason is reason


def test_missing_ablation_is_withheld() -> None:
    trials = (
        trial(
            "trial-1",
            full=outcome(0.8, success=True),
            no_memory=outcome(0.5, success=False),
            without_a=outcome(0.6, success=False),
        ),
        trial(
            "trial-2",
            full=outcome(0.8, success=True),
            no_memory=outcome(0.5, success=False),
        ),
    )

    result = CausalCreditAssigner().assign((target(),), trials)

    assert result.credits == ()
    assert result.abstentions[0].reason is CreditAbstentionReason.MISSING_ABLATION


def test_one_trial_is_insufficient_by_default() -> None:
    trials = (
        trial(
            "trial-1",
            full=outcome(0.8, success=True),
            no_memory=outcome(0.5, success=False),
            without_a=outcome(0.6, success=False),
        ),
    )

    result = CausalCreditAssigner().assign((target(),), trials)

    assert result.credits == ()
    assert result.abstentions[0].reason is CreditAbstentionReason.INSUFFICIENT_TRIALS


def test_high_variance_effect_is_withheld() -> None:
    trials = (
        trial(
            "trial-1",
            full=outcome(0.9, success=True),
            no_memory=outcome(0.5, success=False),
            without_a=outcome(0.3, success=False),
        ),
        trial(
            "trial-2",
            full=outcome(0.3, success=False),
            no_memory=outcome(0.5, success=False),
            without_a=outcome(0.9, success=True),
        ),
    )

    result = CausalCreditAssigner().assign((target(),), trials)

    assert result.credits == ()
    assert result.abstentions[0].reason is CreditAbstentionReason.HIGH_VARIANCE
    assert result.abstentions[0].standard_error > 0.10


def test_duplicate_trial_key_fails_closed() -> None:
    duplicate = trial(
        "same-trial",
        full=outcome(0.8, success=True),
        no_memory=outcome(0.5, success=False),
        without_a=outcome(0.6, success=False),
    )

    with pytest.raises(ValueError, match="duplicate trial_key"):
        CausalCreditAssigner().assign((target(),), (duplicate, duplicate))


def test_redundant_positive_bundle_is_interaction_ambiguous() -> None:
    trials = (
        trial(
            "trial-1",
            full=outcome(0.9, success=True),
            no_memory=outcome(0.5, success=False),
            without_a=outcome(0.9, success=True),
            without_b=outcome(0.9, success=True),
        ),
        trial(
            "trial-2",
            full=outcome(0.9, success=True),
            no_memory=outcome(0.5, success=False),
            without_a=outcome(0.9, success=True),
            without_b=outcome(0.9, success=True),
        ),
    )

    result = CausalCreditAssigner(
        CausalCreditConfig(record_neutral=True)
    ).assign((target(MEMORY_A), target(MEMORY_B)), trials)

    assert result.credits == ()
    assert result.interaction_ambiguous is True
    assert {item.reason for item in result.abstentions} == {
        CreditAbstentionReason.INTERACTION_AMBIGUOUS
    }


def test_cost_delta_sign_is_full_minus_without_memory() -> None:
    trials = (
        trial(
            "trial-1",
            full=outcome(0.8, success=True, tokens=150, latency_ms=35),
            no_memory=outcome(0.5, success=False),
            without_a=outcome(0.7, success=True, tokens=100, latency_ms=20),
        ),
        trial(
            "trial-2",
            full=outcome(0.8, success=True, tokens=140, latency_ms=32),
            no_memory=outcome(0.5, success=False),
            without_a=outcome(0.7, success=True, tokens=100, latency_ms=22),
        ),
    )

    credit = CausalCreditAssigner().assign((target(),), trials).credits[0]

    assert credit.token_delta == 45
    assert credit.latency_delta_ms == pytest.approx(12.5)
