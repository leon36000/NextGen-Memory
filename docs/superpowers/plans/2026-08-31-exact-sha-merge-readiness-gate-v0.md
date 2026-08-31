# Exact-SHA Merge Readiness Gate v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure deterministic advisory gate that converts exact candidate, review, verification, dependency, branch-control, and freshness evidence into `READY`, `HOLD`, or `BLOCKED` without performing a merge or any I/O.

**Architecture:** One zero-dependency module owns bounded enums, frozen immutable evidence contracts, canonical SHA-256/UUID5 identity, exact review-registry composition, ordered dependency hashing, and block-over-hold decision precedence. Tests are split into focused validation/behavior, 5,000-case generated properties plus process determinism, and package-root API verification. The product has no callback, GitHub client, signature verifier, persistence adapter, executor, clock, environment, network, filesystem, worker, deployment, activation, or release surface.

**Tech Stack:** Python 3.12/3.13, standard library only, frozen slotted dataclasses, `enum.StrEnum`, SHA-256, UUID5, canonical JSON, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-31-exact-sha-merge-readiness-gate-v0-design.md`

## Global Constraints

- Exact base branch: `candidate/exact-sha-review-attestation-registry-v0-r4-20260831`.
- Exact base SHA: `41b0b104e5a3f06c4d238060ad0fd3dd51dd4446`.
- Final product scope is exactly the nine paths listed in the design spec and issue #166.
- Runtime dependencies remain empty.
- Gate policy version is exactly `exact-sha-merge-readiness-v0`.
- `READY`, technical approval, or authenticated review evidence never performs or implicitly authorizes merge, migration, deployment, feedback, policy activation, or release.
- Authentication is externally supplied evidence; product code makes no signature-verification claim.
- No network, GitHub, database, filesystem, environment, clock, randomness, subprocess, thread, task, worker, lease, scheduler, model, or agent.
- No raw review prose, source diff, prompt, answer, memory body, command output, credential, path, reviewer name/email, token, arbitrary metadata, or backend payload.
- No stub, `pass`, executable ellipsis, `NotImplementedError`, skip, xfail, opportunistic `noqa`, weakened assertion, or fake success.
- Exact built-in/enum/dataclass types are required at security-sensitive boundaries; subclasses are hostile.
- Every public immutable type is frozen and slotted, emits canonical JSON, and validates before identity construction.
- Hard `BLOCKED` reasons suppress every `HOLD` reason.
- A genuine externally authenticated exact-SHA GPT-5.6 Sol `APPROVE` remains mandatory before any merge.

---

### Task 1: Record the complete tests-only module-absence RED

**Files:**
- Create: `docs/exact-sha-merge-readiness-gate-v0-red.md`
- Create: `tests/test_merge_readiness_gate.py`
- Create: `tests/test_merge_readiness_gate_properties.py`
- Create: `tests/test_merge_readiness_gate_public_api.py`

**Interfaces:**
- Consumes: existing exact r4 public types `ExactShaReviewRequest`, `ReviewAttestationRegistrySummary`, `ReviewAttestationDecision`, `ReviewAdvisoryState`, and related review enums.
- Produces: the exact merge-readiness API Tasks 2–6 must satisfy.

- [ ] **Step 1: Write deterministic review-registry fixtures**

Use standard-library `importlib` at module initialization so the RED remains Ruff-clean in both absent-module and product contexts:

```python
from __future__ import annotations

import hashlib
import importlib
from uuid import UUID

import pytest

from nextgen_memory import (
    ExactShaReviewRequest,
    ReviewAdvisoryState,
    ReviewAttestationDecision,
    ReviewAttestationRegistrySummary,
    ReviewModel,
)

_merge_gate = importlib.import_module("nextgen_memory.merge_readiness_gate")
ExactReviewReadinessEvidence = _merge_gate.ExactReviewReadinessEvidence
ExactShaMergeReadinessGate = _merge_gate.ExactShaMergeReadinessGate
MergeCandidateIdentity = _merge_gate.MergeCandidateIdentity
MergeDependencyIdentity = _merge_gate.MergeDependencyIdentity
MergeDependencyReadiness = _merge_gate.MergeDependencyReadiness
MergeReadinessConfig = _merge_gate.MergeReadinessConfig
MergeReadinessReason = _merge_gate.MergeReadinessReason
MergeReadinessRequest = _merge_gate.MergeReadinessRequest
MergeReadinessState = _merge_gate.MergeReadinessState
MergeReadinessValidationError = _merge_gate.MergeReadinessValidationError
MergeVerificationEvidence = _merge_gate.MergeVerificationEvidence
```

Define exact constants and helper functions:

```python
BASE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
DIFF_SHA = "3" * 64
CHAIN_SHA = "4" * 64
REQUEST_ID = UUID("00000000-0000-5000-8000-00000000a001")


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()
```

Construct a valid `ExactShaReviewRequest`, a summary with two approvals and zero blockers/missing approvals, and an `APPROVED` decision whose summary hash matches. The helper must use real content hashes and the exact request UUID generated by the review request rather than overriding frozen fields.

- [ ] **Step 2: Write one exact READY case**

Build:

```python
record = ExactShaMergeReadinessGate().evaluate(
    ready_request(),
    ready_config(),
)
assert record.state is MergeReadinessState.READY
assert record.reasons == (MergeReadinessReason.ALL_GATES_PASSED,)
assert record.advisory_only is True
```

Require exact retry object equality, identical `render_json()` bytes, deterministic UUID/content hash, and no merge/execution method on the gate or record.

- [ ] **Step 3: Cover every hard block reason independently**

Table-drive one structurally valid mutation for each exact reason:

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

Each case requires:

```python
assert record.state is MergeReadinessState.BLOCKED
assert expected_reason in record.reasons
assert all(reason in BLOCK_REASONS for reason in record.reasons)
```

- [ ] **Step 4: Cover every hold reason independently**

Table-drive:

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

Require exact freshness equality to pass and a finite value immediately above the boundary to hold.

- [ ] **Step 5: Prove block precedence**

Create one request containing:

- candidate/base/diff drift;
- blocked review;
- unauthenticated approval evidence;
- failed static/full/wheel/integration evidence;
- stale/missing artifacts;
- prerequisites not integrated;
- single-writer/protected-branch violations.

Require `BLOCKED`, canonical hard reasons only, and no hold reason in the record.

- [ ] **Step 6: Prove review identity independently**

Cover:

- summary request UUID mismatch;
- summary request hash mismatch;
- decision request UUID/hash mismatch;
- decision summary hash mismatch;
- decision state inconsistent with counts;
- summary missing-approval count inconsistent with request threshold;
- review request repository/PR/base/candidate/diff mismatch;
- `APPROVED` with `authentication_verified=False`;
- digest present without authentication;
- authentication true without digest.

The first six are block reasons. Digest present without authentication blocks only when the state claims approval. Authentication true without digest holds.

- [ ] **Step 7: Write constructor validation and hostile-subclass tests**

Cover exact-type rejection for every public dataclass/enum/bool/int/float/UUID/tuple input. Add hostile subclasses whose `__str__`, `__repr__`, `__eq__`, `__iter__`, `__hash__`, or numeric conversion raises or returns protected text. Require bounded `MergeReadinessValidationError` with no hostile marker, cause, context, path, review text, or payload in `str(exc)`.

Cover malformed/uppercase hashes, malformed repository, invalid component key, bool-as-count, NaN/infinity, negative ages/counts, empty dependency tuple, more than 64 dependencies, duplicate component/SHA, ordinal gaps, and mutable list dependencies.

- [ ] **Step 8: Write canonical JSON, immutability, and identity-sensitivity tests**

For every public immutable type:

```python
raw = value.render_json()
assert raw.endswith("\n")
assert raw == canonical_json(json.loads(raw))
assert not hasattr(value, "__dict__")
```

Mutate every accepted material field independently and require changed content hash/UUID where applicable or a validation failure. Verify no serialized key contains `prompt`, `query`, `answer`, `memory`, `command`, `credential`, `token`, `path`, `reviewer_name`, or `reviewer_email`.

- [ ] **Step 9: Write 5,000 generated combinations and 1,000 retries**

`tests/test_merge_readiness_gate_properties.py` must run 5,000 deterministic cases partitioned among `READY`, `HOLD`, and `BLOCKED`. For each case:

- evaluate twice;
- require exact record equality and canonical bytes;
- verify block-over-hold precedence;
- verify reason uniqueness/order;
- verify the chosen state matches the case oracle.

For one ready request, evaluate 1,000 times and require one unique JSON byte string.

- [ ] **Step 10: Write process hash-seed invariance**

Run a subprocess under `PYTHONHASHSEED=1`, `37`, and `999`. Construct trusted-review fingerprints from sets through the existing review request, construct exact ordered dependencies as a tuple, evaluate the gate, and print only canonical record JSON. Require one unique stdout value and state `READY`.

- [ ] **Step 11: Write package-root public API tests**

Import these names from both the module and `nextgen_memory`, require object identity, and require exactly-once `__all__` membership:

```text
ExactReviewReadinessEvidence
ExactShaMergeReadinessGate
MergeCandidateIdentity
MergeDependencyIdentity
MergeDependencyReadiness
MergeReadinessConfig
MergeReadinessReason
MergeReadinessRecord
MergeReadinessRequest
MergeReadinessState
MergeReadinessValidationError
MergeVerificationEvidence
```

- [ ] **Step 12: Prove the precise RED**

Run:

```bash
ruff check \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py
ruff format --check \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py
python -m py_compile \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py
```

Copy each test independently into an isolated worktree at `41b0b104e5a3f06c4d238060ad0fd3dd51dd4446`. Each collection must fail only with:

```text
ModuleNotFoundError: nextgen_memory.merge_readiness_gate
```

- [ ] **Step 13: Commit and publish immutable RED**

```bash
git add \
  docs/exact-sha-merge-readiness-gate-v0-red.md \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py
git commit -m "test: define exact-SHA merge readiness gate v0"
git push origin HEAD:tdd/exact-sha-merge-readiness-gate-v0-red-r4-v2-20260831
```

---

### Task 2: Implement canonical helpers, enums, config, candidate, and dependencies

**Files:**
- Create: `src/nextgen_memory/merge_readiness_gate.py`
- Test: `tests/test_merge_readiness_gate.py`

**Interfaces:**
- Consumes: Python standard library only.
- Produces: validation error, enums, `MergeReadinessConfig`, `MergeCandidateIdentity`, `MergeDependencyIdentity`, and `MergeDependencyReadiness`.

- [ ] **Step 1: Add versioned constants and reason precedence**

Create exact constants:

```python
_SCHEMA = "nextgen-memory-exact-sha-merge-readiness-gate-v0"
_POLICY_VERSION = "exact-sha-merge-readiness-v0"
_MAX_REPOSITORY_LENGTH = 200
_MAX_COMPONENT_KEY_LENGTH = 100
_MAX_DEPENDENCIES = 64
```

Define `_BLOCK_REASON_ORDER`, `_HOLD_REASON_ORDER`, and `_READY_REASON` as immutable tuples of enum members in the design-spec order.

- [ ] **Step 2: Implement exact scalar and canonicalization helpers**

Implement:

```python
def _canonical_json(value: object) -> str: ...
def _hash_payload(value: object) -> str: ...
def _stable_uuid(kind: str, content_hash: str) -> UUID: ...
def _require_exact_bool(name: str, value: object) -> bool: ...
def _require_positive_int(name: str, value: object) -> int: ...
def _require_nonnegative_int(name: str, value: object) -> int: ...
def _require_finite_nonnegative(name: str, value: object) -> float: ...
def _require_finite_positive(name: str, value: object) -> float: ...
def _require_repository(value: object) -> str: ...
def _require_git_sha(name: str, value: object) -> str: ...
def _require_sha256(name: str, value: object) -> str: ...
def _require_optional_sha256(name: str, value: object) -> str | None: ...
def _require_component_key(value: object) -> str: ...
def _require_exact_enum[T](name: str, value: object, enum_type: type[T]) -> T: ...
```

Every helper rejects subclasses before calling caller-controlled behavior. Numeric helpers accept exact built-in `int`/`float`, reject bool, and use `math.isfinite` only after the exact-type check.

- [ ] **Step 3: Implement config and candidate identity**

Each type validates, snapshots normalized values, computes `content_hash`, and exposes `to_dict()`/`render_json()`. Candidate mismatch values remain accepted as evidence.

- [ ] **Step 4: Implement dependency identity and ordered readiness**

Require exact tuple and exact member types. Validate contiguous ordinals and unique component/SHA identities. Compute the chain digest from:

```python
{
    "schema": _SCHEMA,
    "kind": "dependency_chain",
    "dependencies": [item.to_dict() for item in dependencies],
}
```

Do not sort the tuple.

- [ ] **Step 5: Run focused constructor/dependency tests**

```bash
python -m pytest -q tests/test_merge_readiness_gate.py -k \
  'config or candidate or dependency or malformed or hostile or immutable'
```

- [ ] **Step 6: Commit immutable foundations**

```bash
git add src/nextgen_memory/merge_readiness_gate.py tests/test_merge_readiness_gate.py
git commit -m "feat: add merge readiness evidence foundations"
```

---

### Task 3: Implement review, verification, request, and result records

**Files:**
- Modify: `src/nextgen_memory/merge_readiness_gate.py`
- Test: `tests/test_merge_readiness_gate.py`

**Interfaces:**
- Consumes: exact public review-registry types from `nextgen_memory.review_attestation_registry` and Task 2 evidence types.
- Produces: `ExactReviewReadinessEvidence`, `MergeVerificationEvidence`, `MergeReadinessRequest`, and `MergeReadinessRecord`.

- [ ] **Step 1: Import exact review-registry types internally**

Use explicit relative imports:

```python
from .review_attestation_registry import (
    ExactShaReviewRequest,
    ReviewAdvisoryState,
    ReviewAttestationDecision,
    ReviewAttestationRegistrySummary,
)
```

No import from package root.

- [ ] **Step 2: Implement exact review evidence**

Require `type(value) is ExpectedType` for request, summary, and decision. Store optional digest and exact authentication boolean. Identity payload contains the complete `to_dict()` values plus the authentication fields.

- [ ] **Step 3: Implement verification evidence**

Validate every boolean/count/age/hash, compute canonical content identity, and preserve optional missing digests as `None`.

- [ ] **Step 4: Implement aggregate readiness request**

Require exact component types. Bind only component hashes in the request identity payload and create UUID5 domain `exact-sha-merge-readiness-request`.

- [ ] **Step 5: Implement readiness record validation**

Require canonical reason tuple and enforce:

```text
BLOCKED → non-empty subset of hard reasons in canonical order
HOLD    → non-empty subset of hold reasons in canonical order
READY   → exactly (all_gates_passed,)
```

`advisory_only` must be exact `True`.

- [ ] **Step 6: Run identity/record tests and commit**

```bash
python -m pytest -q tests/test_merge_readiness_gate.py -k \
  'review or verification or request or record or canonical or identity'
git add src/nextgen_memory/merge_readiness_gate.py tests/test_merge_readiness_gate.py
git commit -m "feat: add merge readiness request and result contracts"
```

---

### Task 4: Implement deterministic block-over-hold evaluation

**Files:**
- Modify: `src/nextgen_memory/merge_readiness_gate.py`
- Test: `tests/test_merge_readiness_gate.py`

**Interfaces:**
- Consumes: `MergeReadinessRequest`, `MergeReadinessConfig`.
- Produces: `ExactShaMergeReadinessGate.evaluate(...) -> MergeReadinessRecord`.

- [ ] **Step 1: Implement independent review-state derivation**

```python
def _derive_review_state(
    request: ExactShaReviewRequest,
    summary: ReviewAttestationRegistrySummary,
) -> ReviewAdvisoryState:
    if summary.changes_required_count > 0:
        return ReviewAdvisoryState.BLOCKED
    if summary.evidence_blocked_count > 0:
        return ReviewAdvisoryState.EVIDENCE_BLOCKED
    if summary.approval_count >= request.minimum_approvals:
        return ReviewAdvisoryState.APPROVED
    return ReviewAdvisoryState.PENDING
```

- [ ] **Step 2: Implement candidate/review identity checks**

Add reasons without duplicates to local sets. Compare expected/observed candidate values, review request values, verification values, and dependency hashes exactly.

- [ ] **Step 3: Implement review consistency and authentication checks**

Check request/summary/decision UUID/hash bindings, missing-approval calculation, independently derived state, blockers, pending, approvals, authentication, and envelope digest.

- [ ] **Step 4: Implement verification and dependency checks**

Apply exact boolean semantics, required-PostgreSQL behavior, equality-pass freshness boundary, count thresholds, missing digests, prerequisites, equivalent refs, single-writer, and protected branch.

- [ ] **Step 5: Canonicalize reasons and return one record**

```python
hard = tuple(reason for reason in _BLOCK_REASON_ORDER if reason in hard_found)
if hard:
    state = MergeReadinessState.BLOCKED
    reasons = hard
else:
    holds = tuple(reason for reason in _HOLD_REASON_ORDER if reason in hold_found)
    if holds:
        state = MergeReadinessState.HOLD
        reasons = holds
    else:
        state = MergeReadinessState.READY
        reasons = (_READY_REASON,)
```

- [ ] **Step 6: Run complete focused suite and commit**

```bash
python -m pytest -q tests/test_merge_readiness_gate.py
git add src/nextgen_memory/merge_readiness_gate.py tests/test_merge_readiness_gate.py
git commit -m "feat: evaluate exact-SHA merge readiness deterministically"
```

---

### Task 5: Complete generated properties and process determinism

**Files:**
- Modify: `tests/test_merge_readiness_gate_properties.py`
- Modify: `src/nextgen_memory/merge_readiness_gate.py` only for defects exposed by tests

**Interfaces:**
- Consumes: complete gate API.
- Produces: generated precedence, retry, identity, and cross-process evidence.

- [ ] **Step 1: Implement the 5,000-case oracle**

For index `0..4999`, deterministically choose one mode:

```text
0 → exact READY
1 → HOLD from one or more incomplete evidence signals
2 → BLOCKED from one or more hard signals
3 → BLOCKED with simultaneous hold signals
4 → exact-threshold READY/HOLD neighborhoods
```

Require state, reason category, canonical order, no duplicates, and exact retry equality.

- [ ] **Step 2: Implement 1,000 exact retries**

Evaluate one ready request 1,000 times and require one `(id, content_hash, render_json())` tuple.

- [ ] **Step 3: Implement material-field sensitivity**

Mutate every accepted field in config, candidate, review authentication, verification, dependencies, and request. Keep each mutation structurally valid. Require changed component/request/record identity or a deterministic validation outcome.

- [ ] **Step 4: Implement process hash-seed invariance**

Use subprocesses with seeds `1`, `37`, `999`; require byte-identical ready-record JSON.

- [ ] **Step 5: Run properties alone and combined**

```bash
python -m pytest -q tests/test_merge_readiness_gate_properties.py
python -m pytest -q \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py
```

- [ ] **Step 6: Commit deterministic properties**

```bash
git add src/nextgen_memory/merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py
git commit -m "test: prove merge readiness determinism"
```

---

### Task 6: Export the public API and document the stable subsystem

**Files:**
- Modify: `src/nextgen_memory/__init__.py`
- Create: `docs/exact-sha-merge-readiness-gate-v0.md`
- Test: `tests/test_merge_readiness_gate_public_api.py`

**Interfaces:**
- Consumes: complete gate module.
- Produces: package-root API and stable subsystem documentation.

- [ ] **Step 1: Add one explicit package import block**

```python
from .merge_readiness_gate import (
    ExactReviewReadinessEvidence,
    ExactShaMergeReadinessGate,
    MergeCandidateIdentity,
    MergeDependencyIdentity,
    MergeDependencyReadiness,
    MergeReadinessConfig,
    MergeReadinessReason,
    MergeReadinessRecord,
    MergeReadinessRequest,
    MergeReadinessState,
    MergeReadinessValidationError,
    MergeVerificationEvidence,
)
```

Add every name exactly once to `__all__`, preserving its existing sorted organization.

- [ ] **Step 2: Write stable subsystem documentation**

Document:

- exact fields and identities;
- review-registry composition;
- external authentication boundary;
- ordered dependency-chain hashing;
- exact block/hold/ready precedence;
- freshness equality;
- PostgreSQL required/not-required semantics;
- canonical JSON/UUID/hash rules;
- privacy and no-I/O boundary;
- explicit statement that `READY` is not merge authorization.

- [ ] **Step 3: Run public API and isolated wheel smoke**

```bash
python -m pytest -q tests/test_merge_readiness_gate_public_api.py
python -m pip wheel --no-deps . -w wheelhouse
python -m venv /tmp/merge-readiness-wheel
/tmp/merge-readiness-wheel/bin/python -m pip install --no-deps wheelhouse/*.whl
cd /tmp
/tmp/merge-readiness-wheel/bin/python - <<'PY'
import nextgen_memory
from nextgen_memory import (
    ExactShaMergeReadinessGate,
    MergeReadinessState,
    MergeReadinessValidationError,
)
assert ExactShaMergeReadinessGate is not None
assert MergeReadinessState.READY.value == "READY"
assert MergeReadinessValidationError is not None
assert "ExactShaMergeReadinessGate" in nextgen_memory.__all__
PY
/tmp/merge-readiness-wheel/bin/python -m pip check
```

- [ ] **Step 4: Commit exports and documentation**

```bash
git add src/nextgen_memory/__init__.py \
  docs/exact-sha-merge-readiness-gate-v0.md \
  tests/test_merge_readiness_gate_public_api.py
git commit -m "feat: export exact-SHA merge readiness gate v0"
```

---

### Task 7: Qualify and publish one immutable product candidate

**Files:**
- Verify: all nine product paths
- No workflow remains in the final product diff

**Interfaces:**
- Consumes: completed feature branch and immutable RED branch.
- Produces: immutable candidate, producer evidence, and no merge.

- [ ] **Step 1: Run exact static, focused, and complete verification**

```bash
ruff format --check \
  src/nextgen_memory/__init__.py \
  src/nextgen_memory/merge_readiness_gate.py \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py
ruff check .
python -m compileall -q src scripts
python -m pytest -q \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py
python -m pytest -q
```

- [ ] **Step 2: Run strict AST and privacy audit**

Fail on:

```text
non-standard-library runtime imports
network/GitHub/database/filesystem/environment/time/random/subprocess APIs
builtins eval/exec/compile/open
uuid1/uuid4
pass, executable ellipsis, NotImplementedError
skip, xfail, noqa
raw review prose/diff/query/prompt/answer/memory/credential/path fields
merge/deploy/activate/write_feedback/signature-verification behavior
```

Type-hint ellipses are not executable stubs.

- [ ] **Step 3: Prove exact nine-path scope**

Compare to base `41b0b104e5a3f06c4d238060ad0fd3dd51dd4446` and require exactly the nine design-spec paths. Reject any workflow, migration, dependency, database adapter, merge executor, feedback writer, activation path, release path, or corrective-retrieval source.

- [ ] **Step 4: Publish one immutable candidate**

```bash
git push origin HEAD:feat/exact-sha-merge-readiness-gate-v0-r4-v2-20260831
git push origin HEAD:candidate/exact-sha-merge-readiness-gate-v0-r4-20260831
```

Refuse to move an existing candidate ref to another SHA.

- [ ] **Step 5: Persist producer checkpoint as verification pending**

Record exact base/candidate/RED SHAs, nine paths, focused/full counts, generated/retry counts, audit result, wheel hash, safety boundaries, and next action. Status remains `verification_pending_unmerged` until Task 8 succeeds.

---

### Task 8: Run independent Python 3.12/3.13 exact-SHA verification

**Files:**
- Product candidate remains unchanged
- Evidence branches add only bounded JSON documents outside the product diff

**Interfaces:**
- Consumes: immutable candidate SHA from Task 7.
- Produces: exact matrix artifacts, immutable evidence/checkpoint branches, canonical draft PR, and blind review packet.

- [ ] **Step 1: Check out the immutable candidate SHA directly**

Each Python job independently proves base, ancestry, exact nine paths, clean status, Ruff, compileall, focused/full suites, 5,000 combinations, 1,000 retries, process hash-seed invariance, strict audit, and isolated wheel import.

- [ ] **Step 2: Generate bounded semantic evidence**

Under `PYTHONHASHSEED=1` and `999`, generate exactly:

```text
READY complete authenticated evidence
HOLD pending review
HOLD stale evidence
BLOCKED unauthenticated approval
BLOCKED candidate drift plus simultaneous holds
```

Store only request/record UUIDs, content hashes, states, reason codes, counts, exact base/candidate SHAs, and config hash.

- [ ] **Step 3: Compare Python evidence byte-for-byte**

Require identical semantic JSON, state/reason records, generated/retry counts, audit result, and exact path count across Python 3.12/3.13. Record wheel hashes separately; cross-runtime wheel byte identity is not required.

- [ ] **Step 4: Download and rehash artifacts**

Recompute ZIP and wheel SHA-256, compare manifests and semantic bytes, and reject missing or expired artifacts.

- [ ] **Step 5: Publish immutable evidence and checkpoint branches**

Use candidate-bound names:

```text
evidence/exact-sha-merge-readiness-gate-v0-<short-sha>-green-20260830
evidence/exact-sha-merge-readiness-gate-v0-<short-sha>-checkpoint-20260830
```

- [ ] **Step 6: Create one canonical draft product PR and blind review packet**

Base the product PR on `candidate/exact-sha-review-attestation-registry-v0-r4-20260831`. The packet binds exact base/candidate SHA, diff digest, acceptance criteria, tests, artifacts, residual risks, and allowed verdicts:

```text
APPROVE
CHANGES_REQUIRED
BLOCKED_BY_EVIDENCE
```

- [ ] **Step 7: Persist and read back GREEN state**

Write one idempotent project checkpoint and memory node, mirror to MongoDB Atlas, and read both stores back. If a connector is unavailable or schema-incompatible, record the exact failure and keep Git evidence authoritative rather than claiming persistence succeeded.

- [ ] **Step 8: Close development/verifier transports without merge**

Keep only the immutable canonical product PR open. Preserve RED, producer, verifier, and artifact history as provenance. No merge occurs in this task.
