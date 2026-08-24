# Deterministic Policy Promotion Gate v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure deterministic advisory gate that converts normalized paired-policy evidence and explicit operational readiness into immutable `promote`, `hold`, or `reject` decisions.

**Architecture:** A single focused module owns bounded enums, strict configuration validation, untrusted evidence normalization, rule precedence, safe malformed-input fingerprinting, and immutable decision identity. Evidence construction remains permissive so malformed runtime values become privacy-safe reject decisions; configuration construction is strict because invalid thresholds are programmer defects. Tests are split into focused behavioral tables, generated/permutation properties, and package-root API verification.

**Tech Stack:** Python 3.12/3.13, standard library only, frozen slotted dataclasses, `enum.StrEnum`, UUID5, SHA-256, canonical JSON, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-24-policy-promotion-gate-v0-design.md`

## Global Constraints

- Exact base SHA: `91d14e9ff9f8c89d05cb2349b012a6681bf3d828`.
- Final product scope is exactly seven files listed in issue #112.
- No migration, dependency, permanent workflow, database adapter, replay executor, feedback writer, policy activator, or corrective-retrieval source.
- No network, filesystem write, subprocess, wall-clock read, environment read, random UUID, thread, task, lease, or worker.
- No stub, `pass`, executable ellipsis, `NotImplementedError`, skipped/xfail test, opportunistic `noqa`, or fake success.
- Malformed evidence returns `reject`; invalid gate configuration raises `PolicyPromotionValidationError`.
- No arbitrary `str(object)` or `repr(object)` fallback.
- Every accepted material evidence/configuration change changes decision identity.
- Merge remains forbidden pending genuine exact-SHA GPT-5.6 Sol `APPROVE` and dependency-ordered prerequisite integration.

---

### Task 1: Record the complete tests-only RED contract

**Files:**
- Create: `tests/test_policy_promotion.py`
- Create: `tests/test_policy_promotion_properties.py`
- Create: `tests/test_policy_promotion_public_api.py`

**Interfaces:**
- Consumes: `PairedPolicyVerdict` from `nextgen_memory.paired_rerank_policy_evaluation`.
- Produces: the exact public names and behavior that Tasks 2–5 must implement.

- [ ] **Step 1: Write focused fixtures and the valid promotion case**

Create a shared helper in `tests/test_policy_promotion.py` using these exact public interfaces:

```python
from datetime import UTC, datetime, timedelta
from uuid import UUID

from nextgen_memory.paired_rerank_policy_evaluation import PairedPolicyVerdict
from nextgen_memory.policy_promotion import (
    DeterministicPolicyPromotionGate,
    PolicyPromotionDisposition,
    PolicyPromotionEvidence,
    PolicyPromotionGateConfig,
    PolicyPromotionReason,
    PolicyVerificationSignal,
)

NOW = datetime(2026, 8, 24, 3, 30, tzinfo=UTC)


def valid_evidence(**overrides: object) -> PolicyPromotionEvidence:
    values: dict[str, object] = {
        "space_id": UUID("00000000-0000-5000-8000-000000000d01"),
        "candidate_policy_id": UUID("00000000-0000-5000-8000-000000000d02"),
        "evaluated_policy_version": "treatment-v1",
        "current_policy_version": "treatment-v1",
        "evaluated_policy_fingerprint": "a" * 64,
        "current_policy_fingerprint": "a" * 64,
        "evaluation_id": UUID("00000000-0000-5000-8000-000000000d03"),
        "evaluation_content_hash": "b" * 64,
        "context_collection_hash": "c" * 64,
        "continuation_set_hash": "d" * 64,
        "paired_trial_count": 32,
        "mean_effect": 0.05,
        "confidence_lower": 0.02,
        "confidence_upper": 0.08,
        "standard_error": 0.01,
        "mean_cost_delta": 0.01,
        "harm_rate": 0.0,
        "evaluator_verdict": PairedPolicyVerdict.PROMISING,
        "evidence_at": NOW - timedelta(hours=1),
        "decision_at": NOW,
        "maximum_evidence_age_seconds": 86_400,
        "rollback_plan_id": UUID("00000000-0000-5000-8000-000000000d04"),
        "rollback_plan_hash": "e" * 64,
        "rollback_ready": True,
        "required_signals": tuple(PolicyVerificationSignal),
        "passed_signals": tuple(reversed(tuple(PolicyVerificationSignal))),
        "reviewer_count": 2,
        "required_reviewer_count": 2,
        "evaluated_base_sha": "1" * 40,
        "current_base_sha": "1" * 40,
        "evaluated_candidate_sha": "2" * 40,
        "current_candidate_sha": "2" * 40,
        "hard_safety_violation": False,
    }
    values.update(overrides)
    return PolicyPromotionEvidence(**values)  # type: ignore[arg-type]


def test_fully_satisfied_promising_evidence_promotes() -> None:
    decision = DeterministicPolicyPromotionGate().evaluate(valid_evidence())

    assert decision.disposition is PolicyPromotionDisposition.PROMOTE
    assert decision.reasons == (PolicyPromotionReason.ALL_REQUIREMENTS_SATISFIED,)
    assert decision.invalid_fields == ()
    assert decision.missing_signals == ()
```

- [ ] **Step 2: Write table-driven reject and hold precedence tests**

Cover every reason with explicit expected disposition. Include a combined case with `hard_safety_violation=True`, stale evidence, missing signals, and too few reviewers, asserting only reject reasons are returned and `HARD_SAFETY_VIOLATION` precedes all other applicable reject reasons.

Use exact threshold cases:

```python
@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"evaluator_verdict": PairedPolicyVerdict.HARMFUL}, PolicyPromotionReason.EVALUATOR_HARMFUL),
        ({"evaluator_verdict": PairedPolicyVerdict.TOO_COSTLY}, PolicyPromotionReason.EVALUATOR_TOO_COSTLY),
        ({"confidence_upper": -0.001, "mean_effect": -0.01, "confidence_lower": -0.02}, PolicyPromotionReason.ESTABLISHED_NEGATIVE_EFFECT),
        ({"mean_cost_delta": 0.0500001}, PolicyPromotionReason.COST_LIMIT_EXCEEDED),
        ({"harm_rate": 0.0100001}, PolicyPromotionReason.HARM_RATE_EXCEEDED),
    ],
)
def test_hard_rejection_conditions(overrides: dict[str, object], reason: PolicyPromotionReason) -> None:
    decision = DeterministicPolicyPromotionGate().evaluate(valid_evidence(**overrides))
    assert decision.disposition is PolicyPromotionDisposition.REJECT
    assert reason in decision.reasons
```

Hold cases must include all non-directional evaluator verdicts, insufficient pairs, lower bound exactly equal to the configured minimum, standard error just above the maximum, age one microsecond beyond the maximum, rollback false, one missing required signal, and reviewer count one below the required threshold.

- [ ] **Step 3: Write malformed-evidence privacy tests**

Cover booleans in every numeric/count position, NaN, infinities, uppercase/short/long hashes, invalid Git SHAs, reversed/non-containing intervals, naive timestamps, decision time before evidence time, negative counts/rates/age, unknown signal values, and unsupported objects.

Use an adversarial object whose string conversion raises:

```python
class ExplosiveText:
    def __str__(self) -> str:
        raise AssertionError("str must not be called")

    def __repr__(self) -> str:
        raise AssertionError("repr must not be called")


def test_malformed_payload_is_rejected_without_echo_or_conversion() -> None:
    sentinel = "private-prompt-sentinel"
    evidence = valid_evidence(
        current_policy_version=sentinel,
        required_signals=(ExplosiveText(),),
    )

    decision = DeterministicPolicyPromotionGate().evaluate(evidence)
    rendered = decision.render_json()

    assert decision.disposition is PolicyPromotionDisposition.REJECT
    assert decision.reasons == (PolicyPromotionReason.MALFORMED_EVIDENCE,)
    assert sentinel not in rendered
    assert "ExplosiveText" in rendered
```

- [ ] **Step 4: Write exact retry, material mutation, and canonical-order tests**

Assert:

```python
first = DeterministicPolicyPromotionGate().evaluate(valid_evidence())
second = DeterministicPolicyPromotionGate().evaluate(valid_evidence())
assert first == second
assert first.id == second.id
assert first.content_hash == second.content_hash
assert first.render_json() == second.render_json()
```

Then mutate each accepted material field one at a time and require a changed decision ID/content hash. Signal permutations and duplicates must not change identity.

- [ ] **Step 5: Write generated properties and subprocess hash-seed test**

`tests/test_policy_promotion_properties.py` must generate at least 5,000 deterministic valid/hold/reject cases. For each case assert finite safe metrics, reason/disposition consistency, deterministic retry, identity change for one material mutation, and privacy-safe canonical JSON.

Add a subprocess test that constructs identical evidence from a set under `PYTHONHASHSEED=1`, `37`, and `999`, prints `render_json()`, and asserts byte identity.

- [ ] **Step 6: Write package-root API RED**

`tests/test_policy_promotion_public_api.py` imports every public type from both `nextgen_memory.policy_promotion` and `nextgen_memory`, then asserts object identity and membership in `nextgen_memory.__all__`.

Required names:

```text
DeterministicPolicyPromotionGate
PolicyPromotionDecision
PolicyPromotionDisposition
PolicyPromotionEvidence
PolicyPromotionGateConfig
PolicyPromotionReason
PolicyPromotionSafeMetrics
PolicyPromotionValidationError
PolicyVerificationSignal
fingerprint_policy_promotion_config
```

- [ ] **Step 7: Run Ruff before pytest**

Run:

```bash
ruff format --check tests/test_policy_promotion.py tests/test_policy_promotion_properties.py tests/test_policy_promotion_public_api.py
ruff check tests/test_policy_promotion.py tests/test_policy_promotion_properties.py tests/test_policy_promotion_public_api.py
```

Expected: all checks pass.

- [ ] **Step 8: Prove precise module-absence RED**

Run:

```bash
python -m pytest -q \
  tests/test_policy_promotion.py \
  tests/test_policy_promotion_properties.py \
  tests/test_policy_promotion_public_api.py
```

Expected: collection fails only with `ModuleNotFoundError: No module named 'nextgen_memory.policy_promotion'`. Reject any RED containing syntax, fixture, Ruff, name, or unrelated import failures.

- [ ] **Step 9: Commit the tests-only RED**

```bash
git add tests/test_policy_promotion.py tests/test_policy_promotion_properties.py tests/test_policy_promotion_public_api.py
git commit -m "test: define policy promotion gate v0 contract"
```

---

### Task 2: Implement immutable public types and strict configuration

**Files:**
- Create: `src/nextgen_memory/policy_promotion.py`
- Test: `tests/test_policy_promotion.py`

**Interfaces:**
- Consumes: `PairedPolicyVerdict`.
- Produces: public enums, evidence/config/metrics/decision dataclasses, validation exception, and config fingerprint function.

- [ ] **Step 1: Implement enums and explicit reason precedence**

Define `StrEnum` classes exactly as specified. Store one module-level tuple `_REASON_PRECEDENCE` and mapping `_REASON_PRIORITY` so every reason ordering uses one versioned source.

- [ ] **Step 2: Implement strict configuration validation**

Use a frozen slotted dataclass:

```python
@dataclass(frozen=True, slots=True)
class PolicyPromotionGateConfig:
    minimum_paired_trials: int = 16
    minimum_confidence_lower_bound: float = 0.0
    maximum_standard_error: float = 0.05
    maximum_mean_cost_delta: float = 0.05
    maximum_harm_rate: float = 0.01
    established_negative_effect_tolerance: float = 0.0
    policy_version: str = "policy-promotion-gate-v0"
```

Reject booleans, non-finite values, negative limits, harm above one, nonpositive pair count, and invalid policy version through `PolicyPromotionValidationError`.

- [ ] **Step 3: Implement configuration fingerprint**

```python
def fingerprint_policy_promotion_config(config: PolicyPromotionGateConfig) -> str:
    if not isinstance(config, PolicyPromotionGateConfig):
        raise PolicyPromotionValidationError(
            "config must be a PolicyPromotionGateConfig"
        )
    return _hash_payload(config.to_dict())
```

- [ ] **Step 4: Implement permissive evidence carrier**

Create `PolicyPromotionEvidence` as frozen/slotted with the exact fields from the spec and no `__post_init__`. Do not add a `to_dict()` that might accidentally echo malformed values.

- [ ] **Step 5: Implement safe metrics and decision self-validation**

`PolicyPromotionSafeMetrics` validates every non-`None` field and emits explicit dictionaries. `PolicyPromotionDecision` validates UUID/hash/reason ordering, non-empty reasons, missing-signal ordering, disposition/reason consistency, and recomputes its expected content hash and UUID5.

- [ ] **Step 6: Run focused type/config tests**

Run the configuration, enum, safe-metrics, and decision-construction test subset. Expected: pass while gate behavior tests still fail because `evaluate` is not complete.

- [ ] **Step 7: Commit immutable contracts**

```bash
git add src/nextgen_memory/policy_promotion.py tests/test_policy_promotion.py
git commit -m "feat: add policy promotion decision contracts"
```

---

### Task 3: Implement privacy-safe evidence normalization

**Files:**
- Modify: `src/nextgen_memory/policy_promotion.py`
- Test: `tests/test_policy_promotion.py`
- Test: `tests/test_policy_promotion_properties.py`

**Interfaces:**
- Consumes: `PolicyPromotionEvidence` with potentially malformed runtime values.
- Produces: private `_NormalizedEvidence`, `_NormalizationResult`, sanitized evidence fingerprint, invalid field tuple, canonical signals, and safe metrics.

- [ ] **Step 1: Implement field-specific normalizers**

Add helpers that never call arbitrary string conversion:

```python
def _normalize_uuid(name: str, value: object, invalid: set[str]) -> UUID | None: ...
def _normalize_text(name: str, value: object, invalid: set[str]) -> str | None: ...
def _normalize_hash(name: str, value: object, length: int, invalid: set[str]) -> str | None: ...
def _normalize_integer(name: str, value: object, *, minimum: int, invalid: set[str]) -> int | None: ...
def _normalize_finite_number(name: str, value: object, *, minimum: float | None = None, maximum: float | None = None, invalid: set[str]) -> float | None: ...
def _normalize_datetime(name: str, value: object, invalid: set[str]) -> datetime | None: ...
def _normalize_signals(name: str, value: object, invalid: set[str]) -> tuple[PolicyVerificationSignal, ...] | None: ...
```

- [ ] **Step 2: Implement sanitized fingerprint values**

Implement `_sanitize_untrusted(value)` with explicit branches for `None`, bool, int, finite/non-finite float, string, UUID, datetime, StrEnum, mapping, and bounded iterable. Invalid strings become `{kind, length, sha256}`. Unsupported objects become `{kind: "unsupported", type: "module.qualname"}`. Never call `str` or `repr` on unsupported values.

- [ ] **Step 3: Normalize structural relationships**

After individual fields normalize, mark exact field names invalid for:

```text
confidence_interval
paired_trial_count
reviewer_count
required_reviewer_count
maximum_evidence_age_seconds
evidence_time_order
```

when the interval is reversed/does not contain mean, counts violate bounds, or decision time precedes evidence time.

- [ ] **Step 4: Return malformed reject skeleton**

If any invalid field exists, construct safe metrics from valid fields only and return a deterministic reject decision with:

```python
reasons=(PolicyPromotionReason.MALFORMED_EVIDENCE,)
invalid_fields=tuple(sorted(invalid_fields))
missing_signals=()
```

- [ ] **Step 5: Run all malformed/privacy tests**

Expected: every malformed input returns reject; no sentinel appears; adversarial `__str__`/`__repr__` is never invoked.

- [ ] **Step 6: Commit normalization boundary**

```bash
git add src/nextgen_memory/policy_promotion.py tests/test_policy_promotion.py tests/test_policy_promotion_properties.py
git commit -m "feat: normalize policy promotion evidence privately"
```

---

### Task 4: Implement deterministic rejection, hold, and promotion rules

**Files:**
- Modify: `src/nextgen_memory/policy_promotion.py`
- Test: `tests/test_policy_promotion.py`
- Test: `tests/test_policy_promotion_properties.py`

**Interfaces:**
- Consumes: complete `_NormalizedEvidence` plus `PolicyPromotionGateConfig`.
- Produces: final immutable `PolicyPromotionDecision`.

- [ ] **Step 1: Implement hard rejection collection**

Collect every applicable reason, then sort by `_REASON_PRIORITY`:

```python
if normalized.hard_safety_violation:
    reject.add(PolicyPromotionReason.HARD_SAFETY_VIOLATION)
if normalized.identity_drift:
    reject.add(PolicyPromotionReason.IDENTITY_MISMATCH)
if normalized.evaluator_verdict is PairedPolicyVerdict.HARMFUL:
    reject.add(PolicyPromotionReason.EVALUATOR_HARMFUL)
if normalized.evaluator_verdict is PairedPolicyVerdict.TOO_COSTLY:
    reject.add(PolicyPromotionReason.EVALUATOR_TOO_COSTLY)
if normalized.confidence_upper < -config.established_negative_effect_tolerance:
    reject.add(PolicyPromotionReason.ESTABLISHED_NEGATIVE_EFFECT)
if normalized.mean_cost_delta > config.maximum_mean_cost_delta:
    reject.add(PolicyPromotionReason.COST_LIMIT_EXCEEDED)
if normalized.harm_rate > config.maximum_harm_rate:
    reject.add(PolicyPromotionReason.HARM_RATE_EXCEEDED)
```

When `reject` is non-empty, do not calculate or include hold reasons.

- [ ] **Step 2: Implement hold collection**

Map the three non-promising/non-hard evaluator verdicts to distinct reasons. Add threshold/readiness reasons exactly as specified. Lower-bound promotion is strict: equality with `minimum_confidence_lower_bound` holds.

- [ ] **Step 3: Implement promotion**

Only `PairedPolicyVerdict.PROMISING` with no reject and no hold reason returns `PROMOTE` and `ALL_REQUIREMENTS_SATISFIED`.

- [ ] **Step 4: Bind complete decision identity**

Build a canonical decision payload containing schema, disposition, ordered reasons, invalid fields, missing signals, safe identities, metrics, evidence fingerprint, and config fingerprint. Compute SHA-256 then UUID5:

```python
content_hash = _hash_payload(payload)
decision_id = uuid5(
    NAMESPACE_URL,
    f"nextgen-memory-policy-promotion-gate-v0:{content_hash}",
)
```

- [ ] **Step 5: Run every disposition and precedence boundary**

Run all focused tests. Expected: every reason passes, hard reject excludes holds, exact thresholds match spec, and valid promising evidence promotes.

- [ ] **Step 6: Run generated and hash-seed properties**

Run all property tests. Expected: at least 5,000 generated cases pass and subprocess JSON is byte-identical.

- [ ] **Step 7: Commit decision engine**

```bash
git add src/nextgen_memory/policy_promotion.py tests/test_policy_promotion.py tests/test_policy_promotion_properties.py
git commit -m "feat: evaluate policy promotion evidence deterministically"
```

---

### Task 5: Export the API and prove package/wheel integration

**Files:**
- Modify: `src/nextgen_memory/__init__.py`
- Test: `tests/test_policy_promotion_public_api.py`

**Interfaces:**
- Consumes: public module names from Tasks 2–4.
- Produces: package-root imports and `__all__` entries.

- [ ] **Step 1: Add explicit import block**

Insert:

```python
from .policy_promotion import (
    DeterministicPolicyPromotionGate,
    PolicyPromotionDecision,
    PolicyPromotionDisposition,
    PolicyPromotionEvidence,
    PolicyPromotionGateConfig,
    PolicyPromotionReason,
    PolicyPromotionSafeMetrics,
    PolicyPromotionValidationError,
    PolicyVerificationSignal,
    fingerprint_policy_promotion_config,
)
```

Add each name exactly once to the sorted package `__all__` list.

- [ ] **Step 2: Run public API test**

```bash
python -m pytest -q tests/test_policy_promotion_public_api.py
```

Expected: all root imports and `__all__` assertions pass.

- [ ] **Step 3: Build and install wheel outside checkout**

```bash
python -m pip wheel --no-deps . -w wheelhouse
python -m venv /tmp/policy-promotion-wheel
/tmp/policy-promotion-wheel/bin/python -m pip install --no-deps wheelhouse/*.whl
/tmp/policy-promotion-wheel/bin/python -c \
  'from nextgen_memory import DeterministicPolicyPromotionGate, PolicyPromotionDisposition; assert PolicyPromotionDisposition.PROMOTE.value == "promote"'
/tmp/policy-promotion-wheel/bin/python -m pip check
```

- [ ] **Step 4: Commit package integration**

```bash
git add src/nextgen_memory/__init__.py tests/test_policy_promotion_public_api.py
git commit -m "feat: export policy promotion gate v0"
```

---

### Task 6: Execute complete exact-candidate verification

**Files:**
- Verify: all seven product files
- No permanent workflow file remains in final diff

**Interfaces:**
- Consumes: completed product candidate.
- Produces: immutable candidate branch, canonical draft PR, evidence artifacts, persistent checkpoint, and blind Sol packet.

- [ ] **Step 1: Run static and focused verification**

```bash
ruff format --check \
  src/nextgen_memory/policy_promotion.py \
  src/nextgen_memory/__init__.py \
  tests/test_policy_promotion.py \
  tests/test_policy_promotion_properties.py \
  tests/test_policy_promotion_public_api.py
ruff check .
python -m compileall -q src scripts
python -m pytest -q \
  tests/test_policy_promotion.py \
  tests/test_policy_promotion_properties.py \
  tests/test_policy_promotion_public_api.py
```

- [ ] **Step 2: Run full regression**

```bash
python -m pytest -q
git diff --check 91d14e9ff9f8c89d05cb2349b012a6681bf3d828...HEAD
```

- [ ] **Step 3: Run strict AST safety audit**

Parse `policy_promotion.py` and fail on forbidden imports/calls, `ast.Pass`, builtin `NotImplementedError`, sensitive textual markers, executable ellipses, network/database/process/filesystem/time/environment/random APIs.

- [ ] **Step 4: Prove exact seven-file scope**

Expected paths are exactly the seven files from issue #112. Assert no `.github/workflows`, `migrations`, `pyproject.toml`, database adapter, replay executor, or corrective-retrieval path changed.

- [ ] **Step 5: Publish immutable candidate branch**

Use a fresh branch name such as:

```text
candidate/policy-promotion-gate-v0-20260824
```

Never move it after review evidence is attached.

- [ ] **Step 6: Run independent raw-SHA matrix**

Check out the immutable SHA directly on Python 3.12 and 3.13. Re-run exact scope, Ruff, compileall, focused/full tests, hash-seed evidence, privacy/stub audit, and isolated wheel install. Require cross-Python byte-identical decision JSON for promote, hold, reject, and malformed-reject fixtures.

- [ ] **Step 7: Create canonical draft PR and blind Sol packet**

The PR body must bind base SHA, candidate SHA, exact seven paths, RED evidence, test counts, artifact IDs/digests, decision fixture hashes, safety boundaries, and merge rule. Post a blind review packet requiring exactly `APPROVE`, `CHANGES_REQUIRED`, or `BLOCKED_BY_EVIDENCE`.

- [ ] **Step 8: Persist and read back checkpoint**

Write Neon checkpoint key:

```text
m-head:policy-promotion-gate-v0:green:<short-sha>
```

Mirror the memory node into MongoDB, then read both stores back and compare candidate SHA, PR, run IDs, status, Sol verdict, and merge prohibition.

- [ ] **Step 9: Close development and verifier transports without merge**

Keep only the canonical immutable product PR open. Preserve all RED/debugging history in closed unmerged PRs and workflow logs.
