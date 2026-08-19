from __future__ import annotations

import ast
import inspect
from dataclasses import FrozenInstanceError, fields

import pytest
from nextgen_memory.corrective_retrieval_execution import (
    EmbeddingBudgetDecision,
    EmbeddingBudgetGuard,
    EmbeddingBudgetPolicy,
    RetryDirective,
    classify_provider_failure,
)

from nextgen_memory.corrective_retrieval_contracts import (
    ProviderStatusClass,
    RetrievalFailureClass,
)


def policy(**overrides: object) -> EmbeddingBudgetPolicy:
    values: dict[str, object] = {
        "model": "voyage-4-lite",
        "rpm_limit": 3,
        "tpm_limit": 100,
        "window_seconds": 60,
        "known_attempt_timestamps": (980, 990),
        "known_token_estimates": (20, 30),
    }
    values.update(overrides)
    return EmbeddingBudgetPolicy(**values)  # type: ignore[arg-type]


def evaluate(
    value: EmbeddingBudgetPolicy | None = None,
    *,
    now: int = 1000,
    token_estimate: int = 10,
    embedding_bearing: bool = True,
) -> EmbeddingBudgetDecision:
    return EmbeddingBudgetGuard.evaluate(
        value or policy(),
        now=now,
        token_estimate=token_estimate,
        embedding_bearing=embedding_bearing,
    )


def classify(
    failure: RetrievalFailureClass,
    status: ProviderStatusClass,
    *,
    attempt: int = 1,
    maximum: int = 3,
    now: int = 1000,
    retry_after: int | None = None,
) -> RetryDirective:
    return classify_provider_failure(
        failure,
        status,
        attempt_number=attempt,
        max_attempts=maximum,
        now=now,
        retry_after_seconds=retry_after,
    )


def test_policy_is_frozen_and_slotted() -> None:
    value = policy()
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.rpm_limit = 9  # type: ignore[misc]


def test_budget_decision_is_frozen_and_slotted() -> None:
    value = evaluate()
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.allowed = False  # type: ignore[misc]


def test_retry_directive_is_frozen_and_slotted() -> None:
    value = classify(RetrievalFailureClass.SUCCESS, ProviderStatusClass.SUCCESS)
    assert not hasattr(value, "__dict__")
    with pytest.raises(FrozenInstanceError):
        value.should_retry = True  # type: ignore[misc]


@pytest.mark.parametrize("history", [[940], {940}])
def test_policy_requires_tuple_timestamp_snapshot(history: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        policy(known_attempt_timestamps=history)


def test_policy_requires_paired_history_snapshots() -> None:
    with pytest.raises(ValueError):
        policy(known_token_estimates=(20,))


def test_rpm_exact_boundary_is_allowed() -> None:
    decision = evaluate(policy(rpm_limit=3))
    assert decision.allowed
    assert decision.remaining_request_budget == 0


def test_rpm_candidate_above_boundary_is_denied() -> None:
    decision = evaluate(policy(rpm_limit=2))
    assert not decision.allowed
    assert decision.reason == "request_budget_exhausted"
    assert decision.not_before_time == 1040
    assert decision.retry_after_seconds == 40


def test_tpm_exact_boundary_is_allowed() -> None:
    decision = evaluate(policy(tpm_limit=60), token_estimate=10)
    assert decision.allowed
    assert decision.remaining_token_budget == 0


def test_tpm_candidate_above_boundary_is_denied() -> None:
    decision = evaluate(policy(tpm_limit=59), token_estimate=10)
    assert not decision.allowed
    assert decision.reason == "token_budget_exhausted"


def test_sliding_window_lower_boundary_is_excluded() -> None:
    decision = evaluate(
        policy(rpm_limit=1, known_attempt_timestamps=(940,), known_token_estimates=(99,)),
        token_estimate=100,
    )
    assert decision.allowed


def test_sliding_window_upper_boundary_is_included() -> None:
    decision = evaluate(
        policy(rpm_limit=1, known_attempt_timestamps=(1000,), known_token_estimates=(1,)),
    )
    assert not decision.allowed
    assert decision.not_before_time == 1060


def test_just_inside_window_expires_at_exact_future_boundary() -> None:
    decision = evaluate(
        policy(rpm_limit=1, known_attempt_timestamps=(941,), known_token_estimates=(1,)),
    )
    assert not decision.allowed
    assert decision.not_before_time == 1001
    assert decision.retry_after_seconds == 1


def test_future_timestamp_fails_closed() -> None:
    with pytest.raises(ValueError):
        evaluate(policy(known_attempt_timestamps=(1001,), known_token_estimates=(1,)))


def test_evaluation_is_deterministic_and_does_not_mutate_snapshot() -> None:
    value = policy()
    before = (value.known_attempt_timestamps, value.known_token_estimates)
    first = evaluate(value)
    second = evaluate(value)
    assert first == second
    assert (value.known_attempt_timestamps, value.known_token_estimates) == before


def test_embedding_bearing_explain_consumes_candidate_budget() -> None:
    decision = evaluate(policy(rpm_limit=3, tpm_limit=60), token_estimate=10)
    assert decision.allowed
    assert decision.remaining_request_budget == 0
    assert decision.remaining_token_budget == 0


def test_non_embedding_bearing_explain_does_not_consume_candidate_budget() -> None:
    decision = evaluate(
        policy(rpm_limit=2, tpm_limit=50),
        token_estimate=0,
        embedding_bearing=False,
    )
    assert decision.allowed
    assert decision.reason == "not_embedding_bearing"
    assert decision.remaining_request_budget == 0
    assert decision.remaining_token_budget == 0


def test_candidate_larger_than_tpm_limit_has_no_fake_schedule() -> None:
    decision = evaluate(policy(tpm_limit=50), token_estimate=51)
    assert not decision.allowed
    assert decision.reason == "token_estimate_exceeds_limit"
    assert decision.not_before_time is None
    assert decision.retry_after_seconds is None


def test_combined_exhaustion_waits_until_both_budgets_fit() -> None:
    decision = evaluate(
        policy(
            rpm_limit=2,
            tpm_limit=50,
            known_attempt_timestamps=(950, 990),
            known_token_estimates=(40, 10),
        ),
        token_estimate=30,
    )
    assert not decision.allowed
    assert decision.reason == "request_and_token_budget_exhausted"
    assert decision.not_before_time == 1010
    assert decision.retry_after_seconds == 10


@pytest.mark.parametrize(
    "field",
    ["rpm_limit", "tpm_limit", "window_seconds", "known_token_estimates"],
)
def test_policy_rejects_bool_numeric_inputs(field: str) -> None:
    replacement: object = (True, 30) if field == "known_token_estimates" else True
    with pytest.raises((TypeError, ValueError)):
        policy(**{field: replacement})


@pytest.mark.parametrize(
    ("timestamps", "tokens"),
    [((True, 980), (20, 30)), ((940, 980), (True, 30))],
)
def test_history_rejects_bool_numeric_entries(
    timestamps: tuple[object, ...], tokens: tuple[object, ...]
) -> None:
    with pytest.raises((TypeError, ValueError)):
        policy(known_attempt_timestamps=timestamps, known_token_estimates=tokens)


@pytest.mark.parametrize("field", ["now", "token_estimate"])
def test_evaluate_rejects_bool_numeric_inputs(field: str) -> None:
    kwargs: dict[str, object] = {"now": 1000, "token_estimate": 10, "embedding_bearing": True}
    kwargs[field] = True
    with pytest.raises((TypeError, ValueError)):
        EmbeddingBudgetGuard.evaluate(policy(), **kwargs)  # type: ignore[arg-type]


def test_embedding_bearing_zero_token_estimate_is_invalid() -> None:
    with pytest.raises(ValueError):
        evaluate(token_estimate=0)


def test_retry_directive_has_no_fallback_or_mode_surface() -> None:
    declared = {item.name for item in fields(RetryDirective)}
    assert declared == {
        "failure_class",
        "provider_status_class",
        "should_retry",
        "terminal",
        "retry_after_seconds",
        "not_before_time",
    }


def test_success_mapping_is_nonterminal_without_retry() -> None:
    directive = classify(RetrievalFailureClass.SUCCESS, ProviderStatusClass.SUCCESS)
    assert not directive.should_retry
    assert not directive.terminal
    assert directive.retry_after_seconds is None
    assert directive.not_before_time is None


@pytest.mark.parametrize("retry_after", [None, -10, 0])
def test_rate_limit_normalizes_nonpositive_retry_after(retry_after: int | None) -> None:
    directive = classify(
        RetrievalFailureClass.RATE_LIMITED,
        ProviderStatusClass.RATE_LIMITED,
        retry_after=retry_after,
    )
    assert directive.should_retry
    assert not directive.terminal
    assert directive.retry_after_seconds == 1
    assert directive.not_before_time == 1001


def test_rate_limit_honors_positive_retry_after() -> None:
    directive = classify(
        RetrievalFailureClass.RATE_LIMITED,
        ProviderStatusClass.RATE_LIMITED,
        retry_after=7,
    )
    assert directive.should_retry
    assert directive.retry_after_seconds == 7
    assert directive.not_before_time == 1007


def test_rate_limit_at_max_attempt_is_terminal() -> None:
    directive = classify(
        RetrievalFailureClass.RATE_LIMITED,
        ProviderStatusClass.RATE_LIMITED,
        attempt=3,
        maximum=3,
        retry_after=7,
    )
    assert not directive.should_retry
    assert directive.terminal
    assert directive.retry_after_seconds is None
    assert directive.not_before_time is None


def test_transient_failure_before_max_attempt_can_retry_immediately() -> None:
    directive = classify(
        RetrievalFailureClass.PROVIDER_TRANSIENT,
        ProviderStatusClass.TRANSIENT_ERROR,
    )
    assert directive.should_retry
    assert not directive.terminal
    assert directive.retry_after_seconds == 0
    assert directive.not_before_time == 1000


def test_transient_failure_at_max_attempt_is_terminal() -> None:
    directive = classify(
        RetrievalFailureClass.PROVIDER_TRANSIENT,
        ProviderStatusClass.TRANSIENT_ERROR,
        attempt=3,
        maximum=3,
    )
    assert not directive.should_retry
    assert directive.terminal


@pytest.mark.parametrize(
    "failure",
    [
        RetrievalFailureClass.UNSUPPORTED_CAPABILITY,
        RetrievalFailureClass.INDEX_UNAVAILABLE,
        RetrievalFailureClass.SCOPE_VIOLATION,
        RetrievalFailureClass.INVALID_PIPELINE,
        RetrievalFailureClass.INVALID_QUERY,
        RetrievalFailureClass.MATERIALIZATION_MISSING,
        RetrievalFailureClass.MATERIALIZATION_IDENTITY_MISMATCH,
        RetrievalFailureClass.MATERIALIZATION_SCOPE_MISMATCH,
        RetrievalFailureClass.MATERIALIZATION_INACTIVE,
        RetrievalFailureClass.MATERIALIZATION_SOURCE_TYPE_MISMATCH,
    ],
)
def test_nonprovider_failure_taxonomy_is_terminal(failure: RetrievalFailureClass) -> None:
    directive = classify(failure, ProviderStatusClass.NOT_APPLICABLE)
    assert directive.terminal
    assert not directive.should_retry


def test_provider_permanent_failure_is_terminal() -> None:
    directive = classify(
        RetrievalFailureClass.PROVIDER_PERMANENT,
        ProviderStatusClass.PERMANENT_ERROR,
    )
    assert directive.terminal
    assert not directive.should_retry


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (RetrievalFailureClass.SUCCESS, ProviderStatusClass.NOT_APPLICABLE),
        (RetrievalFailureClass.RATE_LIMITED, ProviderStatusClass.TRANSIENT_ERROR),
        (RetrievalFailureClass.PROVIDER_TRANSIENT, ProviderStatusClass.PERMANENT_ERROR),
        (RetrievalFailureClass.PROVIDER_PERMANENT, ProviderStatusClass.SUCCESS),
    ],
)
def test_provider_status_mismatch_fails_closed(
    failure: RetrievalFailureClass,
    status: ProviderStatusClass,
) -> None:
    with pytest.raises(ValueError):
        classify(failure, status)


def test_attempt_number_above_max_fails_closed() -> None:
    with pytest.raises(ValueError):
        classify(
            RetrievalFailureClass.PROVIDER_TRANSIENT,
            ProviderStatusClass.TRANSIENT_ERROR,
            attempt=4,
            maximum=3,
        )


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (RetrievalFailureClass.SUCCESS, ProviderStatusClass.SUCCESS),
        (RetrievalFailureClass.PROVIDER_TRANSIENT, ProviderStatusClass.TRANSIENT_ERROR),
        (RetrievalFailureClass.PROVIDER_PERMANENT, ProviderStatusClass.PERMANENT_ERROR),
    ],
)
def test_retry_after_is_only_accepted_for_rate_limits(
    failure: RetrievalFailureClass,
    status: ProviderStatusClass,
) -> None:
    with pytest.raises(ValueError):
        classify(failure, status, retry_after=1)


def test_classifier_does_not_accept_raw_provider_payload() -> None:
    sentinel = "provider-body-secret"
    with pytest.raises(TypeError) as exc:
        classify_provider_failure(  # type: ignore[call-arg]
            RetrievalFailureClass.PROVIDER_TRANSIENT,
            ProviderStatusClass.TRANSIENT_ERROR,
            attempt_number=1,
            max_attempts=3,
            now=1000,
            provider_body=sentinel,
        )
    assert sentinel not in str(exc.value)


def test_execution_module_has_no_clock_sleep_io_network_or_telemetry_edges() -> None:
    import nextgen_memory.corrective_retrieval_execution as module

    source = inspect.getsource(module)
    tree = ast.parse(source)
    forbidden_roots = {
        "asyncio",
        "http",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "time",
        "urllib",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(forbidden_roots)
    assert "retrieval_telemetry" not in source


@pytest.mark.parametrize("field", ["rpm_limit", "tpm_limit", "window_seconds"])
def test_policy_rejects_nonpositive_limits(field: str) -> None:
    with pytest.raises(ValueError):
        policy(**{field: 0})


def test_policy_rejects_negative_history_timestamp() -> None:
    with pytest.raises(ValueError):
        policy(known_attempt_timestamps=(-1, 980))


def test_policy_rejects_negative_history_token_estimate() -> None:
    with pytest.raises(ValueError):
        policy(known_token_estimates=(-1, 30))


def test_rate_limit_rejects_bool_retry_after() -> None:
    with pytest.raises((TypeError, ValueError)):
        classify(
            RetrievalFailureClass.RATE_LIMITED,
            ProviderStatusClass.RATE_LIMITED,
            retry_after=True,  # type: ignore[arg-type]
        )


def test_classifier_rejects_bool_attempt_number() -> None:
    with pytest.raises((TypeError, ValueError)):
        classify_provider_failure(
            RetrievalFailureClass.PROVIDER_TRANSIENT,
            ProviderStatusClass.TRANSIENT_ERROR,
            attempt_number=True,  # type: ignore[arg-type]
            max_attempts=3,
            now=1000,
        )


def test_classifier_rejects_bool_max_attempts() -> None:
    with pytest.raises((TypeError, ValueError)):
        classify_provider_failure(
            RetrievalFailureClass.PROVIDER_TRANSIENT,
            ProviderStatusClass.TRANSIENT_ERROR,
            attempt_number=1,
            max_attempts=True,  # type: ignore[arg-type]
            now=1000,
        )
