"""Pure embedding-budget and retry directives for corrective retrieval."""

from __future__ import annotations

from dataclasses import dataclass

from .corrective_retrieval_contracts import ProviderStatusClass, RetrievalFailureClass

_BUDGET_REASONS = {
    "allowed",
    "not_embedding_bearing",
    "request_budget_exhausted",
    "token_budget_exhausted",
    "request_and_token_budget_exhausted",
    "token_estimate_exceeds_limit",
}


@dataclass(frozen=True, slots=True)
class EmbeddingBudgetPolicy:
    """Immutable caller-supplied snapshot for one embedding budget decision."""

    model: str
    rpm_limit: int
    tpm_limit: int
    window_seconds: int
    known_attempt_timestamps: tuple[int, ...]
    known_token_estimates: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", _require_text("model", self.model))
        object.__setattr__(
            self,
            "rpm_limit",
            _require_positive_int("rpm_limit", self.rpm_limit),
        )
        object.__setattr__(
            self,
            "tpm_limit",
            _require_positive_int("tpm_limit", self.tpm_limit),
        )
        object.__setattr__(
            self,
            "window_seconds",
            _require_positive_int("window_seconds", self.window_seconds),
        )
        timestamps = _require_int_tuple(
            "known_attempt_timestamps",
            self.known_attempt_timestamps,
            nonnegative=True,
        )
        tokens = _require_int_tuple(
            "known_token_estimates",
            self.known_token_estimates,
            nonnegative=True,
        )
        if len(timestamps) != len(tokens):
            raise ValueError("known attempt and token snapshots must have equal length")
        object.__setattr__(self, "known_attempt_timestamps", timestamps)
        object.__setattr__(self, "known_token_estimates", tokens)


@dataclass(frozen=True, slots=True)
class EmbeddingBudgetDecision:
    """Data-only result of one pure budget evaluation."""

    allowed: bool
    reason: str
    remaining_request_budget: int
    remaining_token_budget: int
    not_before_time: int | None
    retry_after_seconds: int | None

    def __post_init__(self) -> None:
        _require_bool("allowed", self.allowed)
        if type(self.reason) is not str or self.reason not in _BUDGET_REASONS:
            raise ValueError("reason must be a bounded embedding budget reason")
        _require_nonnegative_int(
            "remaining_request_budget",
            self.remaining_request_budget,
        )
        _require_nonnegative_int(
            "remaining_token_budget",
            self.remaining_token_budget,
        )
        _require_schedule(self.not_before_time, self.retry_after_seconds)
        if self.allowed and self.not_before_time is not None:
            raise ValueError("allowed budget decisions cannot contain a retry schedule")


class EmbeddingBudgetGuard:
    """Stateless RPM/TPM admission over explicit immutable snapshots."""

    @staticmethod
    def evaluate(
        policy: EmbeddingBudgetPolicy,
        *,
        now: int,
        token_estimate: int,
        embedding_bearing: bool,
    ) -> EmbeddingBudgetDecision:
        if not isinstance(policy, EmbeddingBudgetPolicy):
            raise TypeError("policy must be an EmbeddingBudgetPolicy")
        now = _require_nonnegative_int("now", now)
        token_estimate = _require_nonnegative_int("token_estimate", token_estimate)
        _require_bool("embedding_bearing", embedding_bearing)

        if any(timestamp > now for timestamp in policy.known_attempt_timestamps):
            raise ValueError("known attempt timestamps cannot be in the future")

        active = _active_entries(policy, at_time=now)
        active_requests = len(active)
        active_tokens = sum(tokens for _, tokens in active)
        request_budget = max(0, policy.rpm_limit - active_requests)
        token_budget = max(0, policy.tpm_limit - active_tokens)

        if not embedding_bearing:
            return EmbeddingBudgetDecision(
                allowed=True,
                reason="not_embedding_bearing",
                remaining_request_budget=request_budget,
                remaining_token_budget=token_budget,
                not_before_time=None,
                retry_after_seconds=None,
            )

        if token_estimate == 0:
            raise ValueError("embedding-bearing attempts require a positive token_estimate")

        if token_estimate > policy.tpm_limit:
            return EmbeddingBudgetDecision(
                allowed=False,
                reason="token_estimate_exceeds_limit",
                remaining_request_budget=request_budget,
                remaining_token_budget=token_budget,
                not_before_time=None,
                retry_after_seconds=None,
            )

        request_exhausted = active_requests + 1 > policy.rpm_limit
        token_exhausted = active_tokens + token_estimate > policy.tpm_limit
        if not request_exhausted and not token_exhausted:
            return EmbeddingBudgetDecision(
                allowed=True,
                reason="allowed",
                remaining_request_budget=policy.rpm_limit - active_requests - 1,
                remaining_token_budget=policy.tpm_limit - active_tokens - token_estimate,
                not_before_time=None,
                retry_after_seconds=None,
            )

        reason = _denial_reason(request_exhausted, token_exhausted)
        not_before = _earliest_budget_time(
            policy,
            now=now,
            token_estimate=token_estimate,
            active=active,
        )
        return EmbeddingBudgetDecision(
            allowed=False,
            reason=reason,
            remaining_request_budget=request_budget,
            remaining_token_budget=token_budget,
            not_before_time=not_before,
            retry_after_seconds=not_before - now,
        )


@dataclass(frozen=True, slots=True)
class RetryDirective:
    """Privacy-safe data-only retry decision for one classified failure."""

    failure_class: RetrievalFailureClass
    provider_status_class: ProviderStatusClass
    should_retry: bool
    terminal: bool
    retry_after_seconds: int | None
    not_before_time: int | None

    def __post_init__(self) -> None:
        if not isinstance(self.failure_class, RetrievalFailureClass):
            raise TypeError("failure_class must be a RetrievalFailureClass")
        if not isinstance(self.provider_status_class, ProviderStatusClass):
            raise TypeError("provider_status_class must be a ProviderStatusClass")
        _require_bool("should_retry", self.should_retry)
        _require_bool("terminal", self.terminal)
        _require_schedule(self.not_before_time, self.retry_after_seconds)
        if self.should_retry and self.terminal:
            raise ValueError("a retry directive cannot be retryable and terminal")
        if self.should_retry and self.not_before_time is None:
            raise ValueError("retryable directives require an explicit schedule")
        if not self.should_retry and self.not_before_time is not None:
            raise ValueError("non-retry directives cannot contain a retry schedule")


def classify_provider_failure(
    failure_class: RetrievalFailureClass,
    provider_status_class: ProviderStatusClass,
    *,
    attempt_number: int,
    max_attempts: int,
    now: int,
    retry_after_seconds: int | None = None,
) -> RetryDirective:
    """Map bounded provider status to a bounded caller-controlled retry directive."""

    if not isinstance(failure_class, RetrievalFailureClass):
        raise TypeError("failure_class must be a RetrievalFailureClass")
    if not isinstance(provider_status_class, ProviderStatusClass):
        raise TypeError("provider_status_class must be a ProviderStatusClass")
    attempt_number = _require_positive_int("attempt_number", attempt_number)
    max_attempts = _require_positive_int("max_attempts", max_attempts)
    now = _require_nonnegative_int("now", now)
    if attempt_number > max_attempts:
        raise ValueError("attempt_number cannot exceed max_attempts")
    retry_after_seconds = _require_optional_int(
        "retry_after_seconds",
        retry_after_seconds,
    )

    expected_status = _expected_provider_status(failure_class)
    if provider_status_class is not expected_status:
        raise ValueError("provider_status_class is inconsistent with failure_class")

    if (
        failure_class is not RetrievalFailureClass.RATE_LIMITED
        and retry_after_seconds is not None
    ):
        raise ValueError("retry_after_seconds is only valid for rate limits")

    if failure_class is RetrievalFailureClass.SUCCESS:
        return _directive(
            failure_class,
            provider_status_class,
            should_retry=False,
            terminal=False,
        )

    at_limit = attempt_number == max_attempts
    if failure_class is RetrievalFailureClass.RATE_LIMITED:
        if at_limit:
            return _directive(
                failure_class,
                provider_status_class,
                should_retry=False,
                terminal=True,
            )
        delay = max(1, retry_after_seconds or 0)
        return _directive(
            failure_class,
            provider_status_class,
            should_retry=True,
            terminal=False,
            retry_after_seconds=delay,
            not_before_time=now + delay,
        )

    if failure_class is RetrievalFailureClass.PROVIDER_TRANSIENT:
        if at_limit:
            return _directive(
                failure_class,
                provider_status_class,
                should_retry=False,
                terminal=True,
            )
        return _directive(
            failure_class,
            provider_status_class,
            should_retry=True,
            terminal=False,
            retry_after_seconds=0,
            not_before_time=now,
        )

    return _directive(
        failure_class,
        provider_status_class,
        should_retry=False,
        terminal=True,
    )


def _active_entries(
    policy: EmbeddingBudgetPolicy,
    *,
    at_time: int,
) -> tuple[tuple[int, int], ...]:
    lower_bound = at_time - policy.window_seconds
    return tuple(
        (timestamp, tokens)
        for timestamp, tokens in zip(
            policy.known_attempt_timestamps,
            policy.known_token_estimates,
            strict=True,
        )
        if lower_bound < timestamp <= at_time
    )


def _earliest_budget_time(
    policy: EmbeddingBudgetPolicy,
    *,
    now: int,
    token_estimate: int,
    active: tuple[tuple[int, int], ...],
) -> int:
    expiries = sorted({timestamp + policy.window_seconds for timestamp, _ in active})
    for candidate_time in expiries:
        future_active = _active_entries(policy, at_time=candidate_time)
        if (
            len(future_active) + 1 <= policy.rpm_limit
            and sum(tokens for _, tokens in future_active) + token_estimate <= policy.tpm_limit
        ):
            return candidate_time
    raise ValueError("no bounded retry time could be derived from the supplied snapshot")


def _denial_reason(request_exhausted: bool, token_exhausted: bool) -> str:
    if request_exhausted and token_exhausted:
        return "request_and_token_budget_exhausted"
    if request_exhausted:
        return "request_budget_exhausted"
    return "token_budget_exhausted"


def _directive(
    failure_class: RetrievalFailureClass,
    provider_status_class: ProviderStatusClass,
    *,
    should_retry: bool,
    terminal: bool,
    retry_after_seconds: int | None = None,
    not_before_time: int | None = None,
) -> RetryDirective:
    return RetryDirective(
        failure_class=failure_class,
        provider_status_class=provider_status_class,
        should_retry=should_retry,
        terminal=terminal,
        retry_after_seconds=retry_after_seconds,
        not_before_time=not_before_time,
    )


def _expected_provider_status(failure_class: RetrievalFailureClass) -> ProviderStatusClass:
    if failure_class is RetrievalFailureClass.SUCCESS:
        return ProviderStatusClass.SUCCESS
    if failure_class is RetrievalFailureClass.RATE_LIMITED:
        return ProviderStatusClass.RATE_LIMITED
    if failure_class is RetrievalFailureClass.PROVIDER_TRANSIENT:
        return ProviderStatusClass.TRANSIENT_ERROR
    if failure_class is RetrievalFailureClass.PROVIDER_PERMANENT:
        return ProviderStatusClass.PERMANENT_ERROR
    return ProviderStatusClass.NOT_APPLICABLE


def _require_text(name: str, value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()


def _require_bool(name: str, value: object) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{name} must be a bool")
    return value


def _require_positive_int(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _require_nonnegative_int(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _require_optional_int(name: str, value: object) -> int | None:
    if value is None:
        return None
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer or None")
    return value


def _require_int_tuple(
    name: str,
    value: object,
    *,
    nonnegative: bool,
) -> tuple[int, ...]:
    if type(value) is not tuple:
        raise TypeError(f"{name} must be an immutable tuple snapshot")
    resolved: list[int] = []
    for item in value:
        if type(item) is not int:
            raise TypeError(f"{name} entries must be integers")
        if nonnegative and item < 0:
            raise ValueError(f"{name} entries must be non-negative")
        resolved.append(item)
    return tuple(resolved)


def _require_schedule(not_before_time: object, retry_after_seconds: object) -> None:
    if (not_before_time is None) != (retry_after_seconds is None):
        raise ValueError("not_before_time and retry_after_seconds must be paired")
    if not_before_time is not None:
        _require_nonnegative_int("not_before_time", not_before_time)
        _require_nonnegative_int("retry_after_seconds", retry_after_seconds)
