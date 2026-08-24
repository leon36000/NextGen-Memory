# Deterministic Policy Promotion Gate v0 Design

**Date:** 2026-08-24  
**Status:** approved under the project owner's standing autonomous-development delegation  
**Base:** `candidate/paired-replay-experiment-registry-v0-20260824` at `91d14e9ff9f8c89d05cb2349b012a6681bf3d828`  
**Issue:** #112

## 1. Goal

Policy Promotion Gate v0 converts normalized paired-policy evidence and explicit operational-readiness signals into one deterministic advisory decision:

- `promote` when every statistical, identity, rollback, verification, freshness, and review criterion is satisfied;
- `hold` when evidence is incomplete, inconclusive, stale, or operationally unready without proving a hard rejection;
- `reject` when evidence is malformed, identities drift, harm or unacceptable cost is established, or a hard safety violation exists.

The gate is not an activator. It cannot deploy, persist, mutate routing, execute a replay, emit feedback, or contact infrastructure.

## 2. Position in the policy-evidence path

```text
PairedRerankPolicyTrial
  → PairedRerankPolicyEvaluation
  → PairedReplayExperimentRegistry
  → normalized PolicyPromotionEvidence
  → DeterministicPolicyPromotionGate
  → PolicyPromotionDecision
  → human / separately authorized promotion mechanism
```

A `promote` decision means only that the supplied evidence satisfies the versioned gate contract. It is never authorization to activate a policy.

## 3. Design principles

1. **Hard rejection wins.** No missing readiness signal can hide established harm, cost, corruption, or identity drift.
2. **No implicit promotion.** Anything not fully proven is `hold` or `reject`.
3. **Explicit time.** The caller supplies both evidence and decision timestamps. The gate never reads a wall clock.
4. **Exact identity.** Evaluated and current policy/base/candidate identities must match.
5. **Privacy-safe invalid input.** Malformed evidence returns `reject` without echoing raw supplied values.
6. **Deterministic output.** Set order, input order, hash seed, process, and Python version cannot change a logical decision.
7. **Pure core.** Only Python standard-library dependencies are allowed; there is no I/O.

## 4. Public contracts

### 4.1 `PolicyPromotionDisposition`

A bounded enum:

```text
PROMOTE = "promote"
HOLD    = "hold"
REJECT  = "reject"
```

### 4.2 `PolicyPromotionReason`

A bounded reason enum with one explicit precedence table.

Reject reasons, highest precedence first:

```text
MALFORMED_EVIDENCE
HARD_SAFETY_VIOLATION
IDENTITY_MISMATCH
EVALUATOR_HARMFUL
EVALUATOR_TOO_COSTLY
ESTABLISHED_NEGATIVE_EFFECT
COST_LIMIT_EXCEEDED
HARM_RATE_EXCEEDED
```

Hold reasons:

```text
EVALUATOR_INSUFFICIENT_EVIDENCE
EVALUATOR_NEUTRAL
EVALUATOR_INCONCLUSIVE
INSUFFICIENT_TRIALS
NONPOSITIVE_LOWER_BOUND
UNCERTAINTY_TOO_HIGH
STALE_EVIDENCE
ROLLBACK_NOT_READY
VERIFICATION_INCOMPLETE
INSUFFICIENT_REVIEWERS
```

Promotion reason:

```text
ALL_REQUIREMENTS_SATISFIED
```

A decision carries a non-empty tuple of reasons sorted by this versioned precedence. `reasons[0]` is the primary reason.

### 4.3 `PolicyVerificationSignal`

A bounded enum representing operational proof rather than arbitrary strings:

```text
FOCUSED_TESTS
FULL_TEST_SUITE
INTEGRATION_REHEARSAL
ARTIFACT_INTEGRITY
ROLLBACK_REHEARSAL
SECURITY_REVIEW
```

The evidence supplies required and passed collections. The gate canonicalizes both as duplicate-free, lexically ordered tuples. Unknown values make evidence malformed. Missing required values produce `VERIFICATION_INCOMPLETE`.

### 4.4 `PolicyPromotionGateConfig`

A frozen, slotted, strictly validated configuration:

```python
minimum_paired_trials: int = 16
minimum_confidence_lower_bound: float = 0.0
maximum_standard_error: float = 0.05
maximum_mean_cost_delta: float = 0.05
maximum_harm_rate: float = 0.01
established_negative_effect_tolerance: float = 0.0
policy_version: str = "policy-promotion-gate-v0"
```

Invariants:

- booleans are never accepted as integers or floats;
- counts are positive integers;
- all numeric thresholds are finite;
- standard-error, cost, harm, lower-bound, and negative-effect tolerances are non-negative;
- harm rate is at most one;
- policy version is trimmed, non-empty, and length-bounded.

Configuration errors raise `PolicyPromotionValidationError`. They do not create an evidence decision because a malformed gate configuration is a programming/deployment defect rather than policy evidence.

### 4.5 `PolicyPromotionEvidence`

A frozen, slotted carrier for untrusted normalized evidence. Its annotations describe the required valid types, but its constructor deliberately does not validate them. This allows the gate to return a privacy-safe `reject` decision for malformed runtime values instead of raising before adjudication.

Fields:

```python
space_id: UUID
candidate_policy_id: UUID
evaluated_policy_version: str
current_policy_version: str
evaluated_policy_fingerprint: str
current_policy_fingerprint: str
evaluation_id: UUID
evaluation_content_hash: str
context_collection_hash: str
continuation_set_hash: str
paired_trial_count: int
mean_effect: float
confidence_lower: float
confidence_upper: float
standard_error: float
mean_cost_delta: float
harm_rate: float
evaluator_verdict: PairedPolicyVerdict
evidence_at: datetime
decision_at: datetime
maximum_evidence_age_seconds: int
rollback_plan_id: UUID
rollback_plan_hash: str
rollback_ready: bool
required_signals: object
passed_signals: object
reviewer_count: int
required_reviewer_count: int
evaluated_base_sha: str
current_base_sha: str
evaluated_candidate_sha: str
current_candidate_sha: str
hard_safety_violation: bool
```

The SHA-256 fields require exactly 64 lowercase hexadecimal characters. Git commit identities require exactly 40 lowercase hexadecimal characters. Timestamps must be timezone-aware.

### 4.6 `PolicyPromotionSafeMetrics`

A frozen, slotted decision summary containing only safe primitive values:

```python
paired_trial_count: int | None
mean_effect: float | None
confidence_lower: float | None
confidence_upper: float | None
standard_error: float | None
mean_cost_delta: float | None
harm_rate: float | None
evidence_age_seconds: float | None
maximum_evidence_age_seconds: int | None
reviewer_count: int | None
required_reviewer_count: int | None
required_signal_count: int | None
passed_required_signal_count: int | None
missing_signal_count: int | None
```

Malformed fields become `None`; raw invalid values are never copied to output.

### 4.7 `PolicyPromotionDecision`

A frozen, slotted immutable result containing:

```python
id: UUID
disposition: PolicyPromotionDisposition
reasons: tuple[PolicyPromotionReason, ...]
invalid_fields: tuple[str, ...]
missing_signals: tuple[PolicyVerificationSignal, ...]
candidate_policy_id: UUID | None
candidate_policy_version: str | None
evaluation_id: UUID | None
evaluation_content_hash: str | None
current_base_sha: str | None
current_candidate_sha: str | None
evidence_fingerprint: str
config_fingerprint: str
metrics: PolicyPromotionSafeMetrics
content_hash: str
```

`render_json()` emits compact canonical JSON with sorted keys, no NaN, and one trailing newline.

## 5. Normalization boundary

`DeterministicPolicyPromotionGate.evaluate(evidence)` performs normalization before any decision rule.

### 5.1 Valid values

- UUID fields require actual `UUID` objects.
- Text fields require bounded trimmed strings.
- SHA fields require lowercase exact-length hexadecimal strings.
- Integers reject booleans.
- Floats accept finite integers/floats but reject booleans, NaN, and infinities.
- Rates are constrained to `[0, 1]`.
- Timestamps require timezone information and a concrete UTC offset.
- Signal collections must be bounded, non-string iterables containing only `PolicyVerificationSignal` values.

### 5.2 Structural relationships

Valid evidence also requires:

- `confidence_lower <= mean_effect <= confidence_upper`;
- `standard_error >= 0`;
- paired-trial, reviewer, required-reviewer, and maximum-age counts are non-negative, with required reviewers positive;
- `decision_at >= evidence_at`;
- maximum evidence age is positive;
- evaluated and current policy versions are independently valid text;
- all identity hashes are structurally valid even when their values later disagree.

### 5.3 Malformed evidence decision

Any normalization failure returns:

```text
disposition = reject
reasons = (malformed_evidence,)
invalid_fields = sorted bounded field names
```

The gate computes `evidence_fingerprint` from a sanitized representation:

- valid primitive values are canonicalized normally;
- invalid strings are represented by length plus SHA-256 of their bytes, never by the string itself;
- NaN and infinities use bounded symbolic tags;
- unsupported values use only module and qualified type name;
- collections are recursively sanitized and sorted;
- neither `str(value)` nor `repr(value)` is called as a fallback.

This makes malformed exact retries deterministic while preventing payload echo. Unsupported object instances of the same type are intentionally not distinguished because their content is outside the accepted evidence contract.

## 6. Decision rules

Normalization completes before rule evaluation.

### 6.1 Reject rules

A valid evidence object is rejected when any of these conditions holds:

1. `hard_safety_violation` is true.
2. Evaluated/current policy version, policy fingerprint, base SHA, or candidate SHA differs.
3. Evaluator verdict is `harmful`.
4. Evaluator verdict is `too_costly`.
5. `confidence_upper < -established_negative_effect_tolerance`.
6. `mean_cost_delta > maximum_mean_cost_delta`.
7. `harm_rate > maximum_harm_rate`.

All applicable reject reasons are returned in precedence order. Hold conditions are not added once any reject reason exists.

### 6.2 Hold rules

When no reject reason exists, the gate holds for every applicable condition:

- evaluator verdict `insufficient_evidence`, `neutral`, or `inconclusive`;
- paired trials below `minimum_paired_trials`;
- `confidence_lower <= minimum_confidence_lower_bound`;
- standard error above `maximum_standard_error`;
- evidence age above the explicit maximum;
- rollback readiness false;
- any required verification signal missing;
- reviewer count below required reviewer count.

The evaluator verdict `promising` is necessary but not sufficient for promotion.

### 6.3 Promote rule

The gate promotes only when:

- normalization produced no invalid field;
- no reject rule applies;
- no hold rule applies;
- evaluator verdict is exactly `promising`.

The sole reason is `all_requirements_satisfied`.

## 7. Identity and canonicalization

The gate computes two independent fingerprints:

1. **Configuration fingerprint** — SHA-256 over the complete canonical configuration.
2. **Evidence fingerprint** — SHA-256 over complete normalized evidence, or the sanitized malformed representation.

The decision payload binds:

- schema/version;
- configuration fingerprint;
- evidence fingerprint;
- disposition;
- ordered reasons;
- bounded invalid field names;
- ordered missing signals;
- safe identities and metrics.

`content_hash` is SHA-256 of the canonical decision payload. `id` is UUID5 under `NAMESPACE_URL` with domain:

```text
nextgen-memory-policy-promotion-gate-v0:<content_hash>
```

Exact retries are byte-identical. Every accepted material evidence or configuration change changes the evidence/config fingerprint and therefore decision identity.

## 8. Error model

- `PolicyPromotionValidationError` — invalid gate configuration or impossible internal decision construction.
- Malformed evidence — immutable `reject`, never an exception.
- No backend exception, fallback, retry, or partial decision exists.

## 9. Privacy and side-effect boundary

The module imports only the Python standard library plus `PairedPolicyVerdict` from the existing evaluator contract.

It contains no:

```text
network
SQL or database driver
filesystem write
subprocess
clock read
environment read
random UUID
thread, task, lease, or worker
feedback write
router mutation
policy activation
model or agent invocation
```

Decision JSON contains only bounded enums, UUIDs, hashes, Git SHAs, finite metrics, counts, and timestamps converted to evidence age. It never includes raw timestamps, text payloads, or arbitrary errors.

## 10. Testing strategy

The tests must cover:

1. one fully valid `promote` decision;
2. every reject reason and hard-rejection precedence over simultaneous holds;
3. every hold reason and deterministic multi-reason ordering;
4. all six `PairedPolicyVerdict` values;
5. exact threshold equality for lower bound, uncertainty, cost, harm, age, pairs, and reviewers;
6. bool/int confusion for every count and numeric field;
7. NaN and positive/negative infinity;
8. malformed, uppercase, short, and long SHA/Git identities;
9. reversed intervals and intervals not containing the mean;
10. naive and backward timestamps;
11. unknown, duplicate, reordered, and missing verification signals;
12. policy/base/candidate identity drift;
13. exact retry and every accepted material-field mutation;
14. deterministic reason, invalid-field, and missing-signal ordering;
15. malformed payload privacy with sentinels and objects whose `__str__`/`__repr__` raise;
16. process-independent `PYTHONHASHSEED` invariance;
17. at least 5,000 deterministic generated valid/hold/reject cases;
18. explicit package-root exports and isolated wheel import;
19. strict AST audit for forbidden imports, calls, stubs, and sensitive markers;
20. full Python 3.12/3.13 suite and exact seven-path diff.

## 11. Non-goals

V0 does not:

- consume raw prompts, answers, or memory content;
- run paired replays;
- persist evidence or decisions;
- count reviewer identities;
- verify signatures or external attestations;
- deploy, activate, rollback, or mutate a policy;
- choose a production environment;
- read current time;
- learn thresholds;
- replace independent human or GPT-5.6 Sol review.

## 12. Success criteria

The feature is complete when malformed evidence rejects privately, hard rejection always wins, promotion is possible only under the full explicit contract, all identities and JSON are deterministic across process/Python versions, the exact seven-file candidate is independently verified, and the canonical PR remains draft and unmerged pending genuine exact-SHA GPT-5.6 Sol approval.