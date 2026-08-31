# Exact-SHA Merge Readiness Gate v0 Design

**Date:** 2026-08-31
**Status:** approved by the reconciled contract in issue #166 and the project owner's standing autonomous-development direction
**Issue:** #166
**Base branch:** `candidate/exact-sha-review-attestation-registry-v0-r4-20260831`
**Base SHA:** `41b0b104e5a3f06c4d238060ad0fd3dd51dd4446`

## 1. Goal

Exact-SHA Merge Readiness Gate v0 is a zero-dependency, pure deterministic decision boundary. It consumes privacy-safe immutable candidate identity, exact review-registry evidence, verification evidence, ordered dependency readiness, branch-control evidence, and a bounded policy. It returns exactly one advisory state:

```text
READY
HOLD
BLOCKED
```

The gate cannot authenticate a signature, call GitHub, move a ref, merge, persist, contact a database, deploy, migrate, write feedback, activate a policy, or publish a release. `READY` is evidence for a later separately authorized merge controller; it is never a merge operation.

## 2. Position in the verified learning-policy stack

```text
immutable candidate
  + exact review request / summary / decision
  + externally authenticated-envelope evidence
  + exact verification artifacts
  + ordered dependency readiness
  + branch and single-writer controls
  + bounded freshness/count policy
        ↓
ExactShaMergeReadinessGate.evaluate(...)
        ↓
READY | HOLD | BLOCKED
        ↓
separate fail-closed merge operation, if later authorized
```

The gate composes with the r4 Review Attestation Registry public API. It does not duplicate reviewer registration or aggregate reviewer verdicts. It independently verifies that the supplied registry request, summary, and decision agree before using the review state.

## 3. Design principles

1. **Exact identity before readiness.** Repository, PR, base, candidate, diff, dependency chain, review request, review summary, review decision, verification evidence, and policy version must agree.
2. **Hard blocks suppress holds.** Identity drift, blocked review, unauthenticated approval, failed verification, or branch-policy violation returns `BLOCKED` even when stale or incomplete evidence also exists.
3. **Missing evidence is not success.** Incomplete but non-contradictory evidence returns `HOLD`.
4. **Authentication remains external.** V0 consumes a boolean and an envelope-evidence SHA-256 supplied by an external authenticator. It makes no signature-verification claim.
5. **Ordered dependencies remain ordered.** Dependency order is execution/integration order, not set semantics. Ordinals must be contiguous and identities unique.
6. **Validation precedes evaluation.** Malformed immutable values raise a bounded validation exception. Well-formed but drifting or failing evidence produces a deterministic `BLOCKED` record.
7. **Canonical output.** Process hash seed, retries, and Python 3.12/3.13 cannot change result bytes.
8. **No execution surface.** There is no callback, command, token, repository client, database client, filesystem path, clock, worker, task, or model field.

## 4. Public enums and errors

### 4.1 `MergeReadinessState`

```python
class MergeReadinessState(StrEnum):
    READY = "READY"
    HOLD = "HOLD"
    BLOCKED = "BLOCKED"
```

### 4.2 `MergeReadinessReason`

The enum is split conceptually into block reasons, hold reasons, and one ready reason. The exact canonical precedence tuple is part of the v0 identity contract.

Hard block reasons, in order:

```text
repository_mismatch
pull_request_mismatch
base_sha_drift
candidate_sha_drift
diff_sha_drift
dependency_chain_mismatch
review_blocked
review_evidence_blocked
unauthenticated_approval
review_request_identity_mismatch
review_summary_identity_mismatch
review_decision_identity_mismatch
static_analysis_failed
compile_failed
full_suite_failed
artifact_integrity_failed
isolated_wheel_failed
integration_rehearsal_failed
cross_python_identity_failed
postgres_replay_failed
equivalent_dependency_ref_included
single_writer_policy_violation
protected_branch_policy_violation
```

Hold reasons, in order:

```text
review_pending
insufficient_approvals
missing_authenticated_envelope
verification_evidence_stale
insufficient_full_suite_test_count
prerequisites_not_integrated
insufficient_migration_passes
missing_verification_artifact
missing_integration_checkpoint
```

Ready reason:

```text
all_gates_passed
```

### 4.3 `MergeReadinessValidationError`

A `ValueError` subclass used only for malformed immutable public values. Messages identify bounded field categories and never echo supplied values.

## 5. Canonicalization and validation helpers

The implementation owns private helpers for:

- canonical compact JSON with sorted keys, finite values, and one trailing newline;
- SHA-256 of canonical JSON;
- UUID5 with explicit `nextgen-memory:exact-sha-merge-readiness-<kind>-v0:` domains;
- exact built-in `str`, `int`, `float`, `bool`, `UUID`, enum, tuple, and dataclass checks;
- lowercase 40-character Git SHA and 64-character SHA-256 validation;
- bounded `owner/repository` validation;
- bounded lowercase component-key validation;
- finite non-negative numeric validation with bool rejection;
- optional SHA-256 validation using exact `None` or exact built-in `str` only.

Security-sensitive inputs reject subclasses before overridden equality, iteration, formatting, conversion, or representation behavior can execute. The implementation never falls back to arbitrary `str(value)` or `repr(value)`.

## 6. Immutable input contracts

### 6.1 `MergeReadinessConfig`

```python
@dataclass(frozen=True, slots=True)
class MergeReadinessConfig:
    maximum_evidence_age_seconds: float
    minimum_full_suite_test_count: int
    minimum_migration_pass_count: int
    gate_policy_version: str = "exact-sha-merge-readiness-v0"
    content_hash: str = field(init=False)
```

Validation:

- age is exact built-in `int` or `float`, finite, and strictly positive;
- minimum full-suite test count is a positive exact built-in integer;
- minimum migration count is a non-negative exact built-in integer;
- version is exactly `exact-sha-merge-readiness-v0`.

### 6.2 `MergeCandidateIdentity`

```python
@dataclass(frozen=True, slots=True)
class MergeCandidateIdentity:
    repository: str
    pull_request_number: int
    expected_base_sha: str
    observed_base_head_sha: str
    expected_candidate_sha: str
    observed_candidate_head_sha: str
    expected_diff_sha256: str
    observed_diff_sha256: str
    expected_dependency_chain_sha256: str
    merge_policy_version: str
    content_hash: str = field(init=False)
```

Expected and observed values are separately retained so drift becomes deterministic decision evidence. The constructor validates shape only; it does not reject a mismatch that the gate must classify.

### 6.3 `ExactReviewReadinessEvidence`

```python
@dataclass(frozen=True, slots=True)
class ExactReviewReadinessEvidence:
    request: ExactShaReviewRequest
    summary: ReviewAttestationRegistrySummary
    decision: ReviewAttestationDecision
    authenticated_envelope_evidence_sha256: str | None
    authentication_verified: bool
    content_hash: str = field(init=False)
```

All three registry values must be exact instances, not subclasses. The constructor records them without trusting their semantic relationship. The gate verifies:

- summary request UUID/hash equals request UUID/hash;
- decision request UUID/hash equals request UUID/hash;
- decision summary hash equals summary hash;
- summary missing-approval count equals the request threshold calculation;
- the decision state equals the state independently derived from summary counts and the request threshold;
- repository, PR, base, candidate, and diff identities agree with the merge candidate.

The optional envelope digest is either exact `None` or a lowercase SHA-256. `authentication_verified` is an exact built-in boolean.

### 6.4 `MergeVerificationEvidence`

```python
@dataclass(frozen=True, slots=True)
class MergeVerificationEvidence:
    base_sha: str
    candidate_sha: str
    diff_sha256: str
    static_analysis_passed: bool
    compile_passed: bool
    full_suite_passed: bool
    full_suite_test_count: int
    artifact_integrity_passed: bool
    isolated_wheel_passed: bool
    integration_rehearsal_passed: bool
    cross_python_semantic_identity_passed: bool
    postgres_replay_required: bool
    postgres_replay_passed: bool
    migration_pass_count: int
    verification_artifact_sha256: str | None
    integration_checkpoint_sha256: str | None
    evidence_age_seconds: float
    content_hash: str = field(init=False)
```

All booleans are exact built-in booleans. Counts are non-negative exact integers. Age is finite and non-negative. Optional digests allow a well-formed incomplete state to produce `HOLD` rather than a construction error.

A false `postgres_replay_passed` blocks only when replay is required. A passing full-suite boolean with a count below policy returns `HOLD`; a false boolean returns `BLOCKED`.

### 6.5 `MergeDependencyIdentity`

```python
@dataclass(frozen=True, slots=True)
class MergeDependencyIdentity:
    ordinal: int
    component_key: str
    candidate_sha: str
    content_hash: str = field(init=False)
```

The component key uses lowercase ASCII letters, digits, dots, underscores, and hyphens, with a 100-character maximum. Ordinal is a positive exact integer. Candidate SHA is exact lowercase Git SHA.

### 6.6 `MergeDependencyReadiness`

```python
@dataclass(frozen=True, slots=True)
class MergeDependencyReadiness:
    dependencies: tuple[MergeDependencyIdentity, ...]
    observed_dependency_chain_sha256: str
    prerequisites_integrated_into_observed_base: bool
    equivalent_duplicate_refs_excluded: bool
    single_writer_reservation_active: bool
    protected_branch_policy_satisfied: bool
    computed_dependency_chain_sha256: str = field(init=False)
    content_hash: str = field(init=False)
```

Validation:

- `dependencies` is an exact tuple;
- every member is an exact `MergeDependencyIdentity`;
- tuple is non-empty and contains at most 64 entries;
- ordinals are exactly `1..N` in tuple order;
- component keys are unique;
- candidate SHAs are unique;
- all booleans are exact built-in booleans.

`computed_dependency_chain_sha256` hashes the canonical ordered dependency payload. The gate requires:

```text
candidate.expected_dependency_chain_sha256
== dependency.observed_dependency_chain_sha256
== dependency.computed_dependency_chain_sha256
```

### 6.7 `MergeReadinessRequest`

```python
@dataclass(frozen=True, slots=True)
class MergeReadinessRequest:
    candidate: MergeCandidateIdentity
    review: ExactReviewReadinessEvidence
    verification: MergeVerificationEvidence
    dependencies: MergeDependencyReadiness
    id: UUID = field(init=False)
    content_hash: str = field(init=False)
```

All fields require exact instances. Content identity binds the four complete component hashes. The request UUID uses a versioned UUID5 domain.

## 7. Gate evaluation

### 7.1 `ExactShaMergeReadinessGate`

```python
class ExactShaMergeReadinessGate:
    __slots__ = ()

    def evaluate(
        self,
        request: MergeReadinessRequest,
        config: MergeReadinessConfig,
    ) -> MergeReadinessRecord:
        ...
```

The gate accepts exact request/config instances only.

### 7.2 Candidate and cross-evidence identity checks

The gate adds block reasons when:

- review request repository differs from candidate repository;
- review request PR differs from candidate PR;
- expected and observed base heads differ;
- review or verification base SHA differs from expected base;
- expected and observed candidate heads differ;
- review or verification candidate SHA differs from expected candidate;
- expected and observed diff hashes differ;
- review or verification diff hash differs from expected diff;
- expected, observed, and computed dependency-chain hashes do not all match;
- candidate merge-policy version differs from config version.

A policy-version mismatch is classified as `dependency_chain_mismatch` only if it corrupts chain identity; otherwise malformed unsupported policy versions are rejected during construction. Both candidate and config accept only the exact v0 version, so no separate runtime reason is needed.

### 7.3 Review consistency and state

The gate independently derives the expected review state:

```text
changes_required_count > 0            → BLOCKED
evidence_blocked_count > 0            → EVIDENCE_BLOCKED
approval_count >= minimum_approvals    → APPROVED
otherwise                              → PENDING
```

Request/summary mismatch adds `review_summary_identity_mismatch`. Request/decision mismatch or a decision state that differs from independently derived state adds `review_decision_identity_mismatch`. The request object itself is compared to candidate identities; those mismatches use the candidate identity reasons.

Then:

- review `BLOCKED` adds `review_blocked`;
- review `EVIDENCE_BLOCKED` adds `review_evidence_blocked`;
- review `APPROVED` with `authentication_verified=False` adds `unauthenticated_approval`;
- review `PENDING` adds hold `review_pending`;
- approval count below threshold or non-zero missing approvals adds hold `insufficient_approvals`;
- missing envelope digest adds hold `missing_authenticated_envelope`.

An envelope digest does not imply authentication. An authentication boolean does not replace the digest. Both are required for `READY`.

### 7.4 Verification checks

Block when any required verification boolean is false:

```text
static_analysis_passed
compile_passed
full_suite_passed
artifact_integrity_passed
isolated_wheel_passed
integration_rehearsal_passed
cross_python_semantic_identity_passed
postgres_replay_passed, only when postgres_replay_required
```

Hold when:

- age is greater than the configured maximum; equality passes;
- full-suite count is below the configured minimum despite `full_suite_passed=True`;
- migration count is below the configured minimum;
- verification artifact digest is absent;
- integration checkpoint digest is absent.

### 7.5 Dependency and branch controls

Block when:

- the observed/computed/expected chain hashes differ;
- `equivalent_duplicate_refs_excluded=False`;
- `single_writer_reservation_active=False`;
- `protected_branch_policy_satisfied=False`.

Hold when `prerequisites_integrated_into_observed_base=False`.

### 7.6 Result precedence

The gate accumulates reasons without duplicating them, then emits:

```text
if any hard block reason:
    state = BLOCKED
    reasons = canonical hard block reasons only
elif any hold reason:
    state = HOLD
    reasons = canonical hold reasons
else:
    state = READY
    reasons = (all_gates_passed,)
```

No hold reason leaks into a blocked record.

## 8. `MergeReadinessRecord`

```python
@dataclass(frozen=True, slots=True)
class MergeReadinessRecord:
    request_id: UUID
    request_content_hash: str
    config_content_hash: str
    candidate_content_hash: str
    review_content_hash: str
    verification_content_hash: str
    dependency_content_hash: str
    state: MergeReadinessState
    reasons: tuple[MergeReadinessReason, ...]
    advisory_only: bool = True
    id: UUID = field(init=False)
    content_hash: str = field(init=False)
```

Validation requires exact types, canonical reason order, no duplicates, correct reason category for state, and `advisory_only is True`. The content hash binds every public field except the derived ID. The ID uses domain `nextgen-memory:exact-sha-merge-readiness-record-v0:<content_hash>`.

The record contains no raw review prose, dependency path, branch name, author, command, environment value, or payload.

## 9. Error model and privacy

`MergeReadinessValidationError` is used for malformed constructors and exact-type violations. Evaluation never catches and echoes arbitrary caller exceptions. Error messages contain only allowlisted field/category text.

Canonical payloads contain only:

- repository and PR identity;
- UUIDs;
- Git SHAs and SHA-256 values;
- bounded enums and policy version;
- booleans, finite ages, counts, ordinals, and bounded component keys.

They contain no raw source diff, review text, query, prompt, answer, memory body, command output, credentials, filesystem paths, reviewer name/email, token, environment, or arbitrary metadata.

## 10. TDD strategy

### 10.1 Tests-only RED

The immutable RED branch is based on the design/plan commit above r4 and adds only:

```text
docs/exact-sha-merge-readiness-gate-v0-red.md
tests/test_merge_readiness_gate.py
tests/test_merge_readiness_gate_properties.py
tests/test_merge_readiness_gate_public_api.py
```

Every test file must be Ruff-clean and syntactically valid. Each independent collection must fail only because `nextgen_memory.merge_readiness_gate` does not exist.

### 10.2 Focused coverage

Focused tests cover:

- one exact `READY` request;
- every hard block reason independently;
- every hold reason independently;
- hard-block suppression of simultaneous holds;
- exact review request/summary/decision binding;
- independent state derivation from review counts;
- approved-but-unauthenticated blocking;
- digest-without-authentication and authentication-without-digest behavior;
- exact freshness equality and adjacent finite values;
- PostgreSQL required/not-required behavior;
- ordered dependency validation, duplicate identities, gaps, and chain hash drift;
- bool/int confusion, NaN/infinity, malformed hashes, exact-type and hostile-subclass rejection;
- canonical JSON, immutability, exact retry, and material-field identity sensitivity;
- privacy-safe exceptions and serialized records;
- advisory-only invariant.

### 10.3 Generated and process properties

At least 5,000 deterministic combinations vary review state, authentication, verification booleans, freshness, counts, dependency readiness, and identity drift. Each case requires the expected precedence and exact retry equality.

At least 1,000 repeated evaluations of one ready request require byte-identical output.

A subprocess property constructs the same request from set-derived review inputs and exact ordered dependencies under `PYTHONHASHSEED=1`, `37`, and `999`; record JSON must be byte-identical.

## 11. Exact product surface

The immutable product candidate contains exactly nine paths:

```text
docs/exact-sha-merge-readiness-gate-v0-red.md
docs/exact-sha-merge-readiness-gate-v0.md
docs/superpowers/specs/2026-08-31-exact-sha-merge-readiness-gate-v0-design.md
docs/superpowers/plans/2026-08-31-exact-sha-merge-readiness-gate-v0.md
src/nextgen_memory/__init__.py
src/nextgen_memory/merge_readiness_gate.py
tests/test_merge_readiness_gate.py
tests/test_merge_readiness_gate_properties.py
tests/test_merge_readiness_gate_public_api.py
```

No workflow, migration, dependency, database adapter, merge executor, feedback writer, activation path, release path, or corrective-retrieval source belongs in the product diff.

The stacked parent does not contain the later project-level `docs/architecture-and-contracts.md` file. Global architecture documentation is reconciled during integration from the branch that actually contains that file rather than injecting unrelated history into this candidate.

## 12. Verification and review gate

Before technical review, an independent exact-SHA Python 3.12/3.13 matrix must prove:

- exact r4 base, ancestry, and nine-path surface;
- Ruff and compileall;
- focused and complete suites;
- 5,000 generated combinations and 1,000 exact retries;
- process hash-seed invariance;
- byte-identical cross-Python semantic evidence;
- strict dependency/privacy/side-effect/stub audit;
- isolated wheel installation and package-root import;
- immutable artifact-bound evidence and checkpoint branches.

A technical review is tied to the unchanged candidate SHA. A separate externally authenticated GPT-5.6 Sol approval remains a merge gate. Any candidate movement invalidates all evidence. Neither technical approval nor `READY` authorizes merge, migration, deployment, feedback, activation, or release.


## R4 parent integrity boundary

The parent registry is exact SHA `41b0b104e5a3f06c4d238060ad0fd3dd51dd4446`. It revalidates canonical review identities before serialization or registry use and stores request/attestation identity snapshots separately from exposed references. Merge-readiness review evidence is trusted only after these R4 integrity checks and the gate's own request/summary/decision consistency checks succeed. Any post-construction mutation therefore fails closed.
