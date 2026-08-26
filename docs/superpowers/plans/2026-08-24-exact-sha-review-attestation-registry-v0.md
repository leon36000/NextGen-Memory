# Exact-SHA Review Attestation Registry v0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure deterministic in-memory registry that binds exact review requests and externally authenticated review attestations to immutable candidate, reviewer, model, artifact, and packet identities and returns only an advisory review state.

**Architecture:** A single focused zero-dependency module owns bounded enums, frozen immutable request/attestation contracts, canonical JSON/SHA-256/UUID5 identity, bounded iterable normalization, one in-memory registry, deterministic summaries, and advisory decisions. Tests are split into focused behavior/validation, generated properties/process determinism, and package-root API verification. No persistence, authentication, GitHub, merge, activation, feedback, or infrastructure behavior belongs in v0.

**Tech Stack:** Python 3.12/3.13, standard library only, frozen slotted dataclasses, `enum.StrEnum`, `itertools.islice`, SHA-256, UUID5, canonical JSON, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md`

## Global Constraints

- Exact base branch: `candidate/advisory-policy-promotion-gate-v0-20260824`.
- Exact base SHA: `f4f3aca9759b5b7a60691017c2211152c011ea92`.
- Qualified tests-only RED branch: `tdd/exact-sha-review-attestation-registry-v0-red-v5-20260825`.
- Qualified tests-only RED SHA: `849df204e899d7570ef469d52307786cf242695a`.
- Final product scope is exactly the nine paths listed in issue #165 and the design spec.
- Runtime dependencies remain empty.
- The registry is advisory only; `approved` never authorizes merge, deployment, migration, feedback, activation, or release.
- The caller authenticates an envelope before supplying its SHA-256; product code makes no signature-verification claim.
- No network, database, filesystem write, environment, clock, randomness, subprocess, thread, task, worker, lease, scheduler, model, or agent.
- No raw review prose, source diff, query, prompt, answer, memory body, command output, path, credential, reviewer name/email, or arbitrary metadata.
- No stub, `pass`, executable ellipsis, `NotImplementedError`, skip, xfail, opportunistic `noqa`, weakened assertion, or fake success.
- Every registry mutation occurs only after complete validation.
- Genuine exact-SHA GPT-5.6 Sol `APPROVE` remains mandatory before merge.

---

### Task 1: Record the complete tests-only module-absence RED v5

**Files:**
- Create: `docs/exact-sha-review-attestation-registry-v0-red.md`
- Create: `tests/test_review_attestation_registry.py`
- Create: `tests/test_review_attestation_registry_properties.py`
- Create: `tests/test_review_attestation_registry_public_api.py`

**Interfaces:**
- Consumes: Python standard-library `UUID`; no product module exists yet.
- Produces: the exact public API and behavior Tasks 2–6 must satisfy.

- [ ] **Step 1: Write focused fixtures with exact public names**

Use this import surface at the top of `tests/test_review_attestation_registry.py`:

```python
from nextgen_memory.review_attestation_registry import (
    ExactShaReviewAttestation,
    ExactShaReviewRequest,
    InMemoryExactShaReviewAttestationRegistry,
    ReviewAdvisoryState,
    ReviewAttestationConflictError,
    ReviewAttestationDecision,
    ReviewAttestationRegistrySummary,
    ReviewAttestationStateError,
    ReviewAttestationValidationError,
    ReviewAttestationVerdict,
    ReviewFindingCode,
    ReviewerIdentity,
    ReviewModel,
)
```

Define exact deterministic fixtures:

```python
BASE_SHA = "1" * 40
CANDIDATE_SHA = "2" * 40
DIFF_SHA = "3" * 64
PACKET_SHA = "4" * 64
CRITERIA_SHA = "5" * 64
REVIEWER_A = "a" * 64
REVIEWER_B = "b" * 64
REVIEWER_C = "c" * 64


def reviewer(
    fingerprint: str = REVIEWER_A,
    *,
    model: ReviewModel = ReviewModel.GPT_5_6_SOL,
) -> ReviewerIdentity:
    return ReviewerIdentity(
        model=model,
        reviewer_key_fingerprint=fingerprint,
    )


def review_request(**overrides: object) -> ExactShaReviewRequest:
    values: dict[str, object] = {
        "repository": "leon36000/NextGen-Memory",
        "pull_request_number": 172,
        "base_sha": BASE_SHA,
        "candidate_sha": CANDIDATE_SHA,
        "diff_sha256": DIFF_SHA,
        "review_packet_sha256": PACKET_SHA,
        "acceptance_criteria_sha256": CRITERIA_SHA,
        "required_model": ReviewModel.GPT_5_6_SOL,
        "trusted_reviewer_fingerprints": (
            REVIEWER_A,
            REVIEWER_B,
            REVIEWER_C,
        ),
        "minimum_approvals": 2,
    }
    values.update(overrides)
    return ExactShaReviewRequest(**values)  # type: ignore[arg-type]


def attestation(
    request: ExactShaReviewRequest,
    *,
    reviewer_identity: ReviewerIdentity | None = None,
    verdict: ReviewAttestationVerdict = ReviewAttestationVerdict.APPROVE,
    finding_codes: object = (),
    review_artifact_sha256: str = "6" * 64,
    evidence_artifact_sha256s: object = ("7" * 64, "8" * 64),
    authenticated_envelope_sha256: str = "9" * 64,
    **overrides: object,
) -> ExactShaReviewAttestation:
    values: dict[str, object] = {
        "request_id": request.id,
        "request_content_hash": request.content_hash,
        "repository": request.repository,
        "pull_request_number": request.pull_request_number,
        "candidate_sha": request.candidate_sha,
        "reviewer": reviewer_identity or reviewer(),
        "verdict": verdict,
        "finding_codes": finding_codes,
        "review_artifact_sha256": review_artifact_sha256,
        "evidence_artifact_sha256s": evidence_artifact_sha256s,
        "authenticated_envelope_sha256": authenticated_envelope_sha256,
    }
    values.update(overrides)
    return ExactShaReviewAttestation(**values)  # type: ignore[arg-type]
```

- [ ] **Step 2: Write the four-state and precedence tests**

Add exact tests for:

```python
def test_empty_registered_request_is_pending() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    request = registry.register_request(review_request())
    assert registry.decision(request.id).state is ReviewAdvisoryState.PENDING


def test_distinct_approval_threshold_is_approved() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    request = registry.register_request(review_request())
    registry.record_attestation(attestation(request))
    registry.record_attestation(
        attestation(
            request,
            reviewer_identity=reviewer(REVIEWER_B),
            review_artifact_sha256="a" * 64,
            authenticated_envelope_sha256="b" * 64,
        )
    )
    assert registry.decision(request.id).state is ReviewAdvisoryState.APPROVED
```

Then add evidence-blocked and changes-required cases. The combined-precedence case must contain two approvals, one evidence blocker, and one changes-required attestation and require `BLOCKED`.

- [ ] **Step 3: Write request and attestation retry/conflict tests**

Require:

```python
first = registry.register_request(request)
second = registry.register_request(request)
assert first is second
```

Reuse the same repository/PR/candidate key with a changed packet hash and require `ReviewAttestationConflictError`. Record one exact attestation twice and require the same object; change its review-artifact hash under the same reviewer fingerprint and require a conflict.

- [ ] **Step 4: Write no-partial-mutation binding tests**

Before each invalid `record_attestation` call, capture:

```python
before = registry.summary(request.id)
```

After the expected validation/state exception, require:

```python
assert registry.summary(request.id) == before
assert registry.attestations(request.id) == ()
```

Cover wrong request content hash, repository, PR, candidate SHA, reviewer model, untrusted reviewer fingerprint, and unknown request UUID.

- [ ] **Step 5: Write verdict/finding compatibility tests**

Table-drive these exact cases:

```text
APPROVE + any finding                         invalid
CHANGES_REQUIRED + no defect finding         invalid
CHANGES_REQUIRED + contract_violation        valid
BLOCKED_BY_EVIDENCE + no evidence finding    invalid
BLOCKED_BY_EVIDENCE + missing_artifact       valid
BLOCKED_BY_EVIDENCE + contract_violation     invalid
```

- [ ] **Step 6: Write malformed input and bounded-iterator tests**

Cover:

- bool PR number/minimum approvals;
- zero/negative numbers;
- same base/candidate SHA;
- uppercase, short, long, or nonhex Git/SHA-256 values;
- malformed repository forms;
- non-enum model/verdict/finding values;
- empty trusted set/evidence set;
- duplicate trusted reviewers/findings/evidence hashes;
- threshold greater than trusted count;
- more than 64 trusted reviewers/evidence hashes;
- more than 32 finding codes.

Use guarded iterators whose `__next__` raises after limit plus one and assert the exact pull count is 65 for reviewer/evidence collections and 33 for findings.

- [ ] **Step 7: Write deterministic identity, canonical JSON, and immutability tests**

Require request identity to survive trusted-reviewer input permutation and attestation identity to survive finding/evidence permutation. Require changed material fields to change content hash and UUID. Parse every `render_json()` result, re-dump with sorted compact JSON, and require exact bytes plus one trailing newline. Frozen instances must reject assignment and have no `__dict__`.

- [ ] **Step 8: Write 5,000 generated traces and process hash-seed invariance**

`tests/test_review_attestation_registry_properties.py` must generate 5,000 deterministic traces partitioned across all four states. Each trace registers the request twice, records every attestation twice, checks state/count partitioning, and verifies exact summary/decision retry equality.

Add a subprocess script that builds trusted reviewers, findings, and evidence hashes from sets under `PYTHONHASHSEED=1`, `37`, and `999`, prints summary and decision canonical JSON, and requires byte-identical output.

- [ ] **Step 9: Write package-root public API tests**

`tests/test_review_attestation_registry_public_api.py` imports all 14 public names from both the module and `nextgen_memory`, then requires object identity and exactly-once membership in `nextgen_memory.__all__`.

- [ ] **Step 10: Prove the precise RED**

Run Ruff before pytest:

```bash
ruff format --check \
  tests/test_review_attestation_registry.py \
  tests/test_review_attestation_registry_properties.py \
  tests/test_review_attestation_registry_public_api.py
ruff check \
  tests/test_review_attestation_registry.py \
  tests/test_review_attestation_registry_properties.py \
  tests/test_review_attestation_registry_public_api.py
python -m py_compile \
  tests/test_review_attestation_registry.py \
  tests/test_review_attestation_registry_properties.py \
  tests/test_review_attestation_registry_public_api.py
```

In an isolated worktree at `f4f3aca9759b5b7a60691017c2211152c011ea92`, collect each test independently. Expected missing-module set for each file:

```text
{"nextgen_memory.review_attestation_registry"}
```

Reject any syntax, fixture, name, unrelated import, or setup error.

- [ ] **Step 11: Commit the immutable tests-only RED**

```bash
git add \
  docs/exact-sha-review-attestation-registry-v0-red.md \
  tests/test_review_attestation_registry.py \
  tests/test_review_attestation_registry_properties.py \
  tests/test_review_attestation_registry_public_api.py
git commit -m "test: define exact-SHA review attestation registry v0"
```

Publish a fresh immutable branch:

```text
tdd/exact-sha-review-attestation-registry-v0-red-v5-20260825
```

---

### Task 2: Implement bounded enums, validation helpers, and immutable identities

**Files:**
- Create: `src/nextgen_memory/review_attestation_registry.py`
- Test: `tests/test_review_attestation_registry.py`

**Interfaces:**
- Consumes: no internal product dependency.
- Produces: public enums, errors, `ReviewerIdentity`, `ExactShaReviewRequest`, `ExactShaReviewAttestation`, and private canonicalization helpers.

- [ ] **Step 1: Add schemas, limits, regexes, errors, and enums**

Create:

```python
_SCHEMA = "nextgen-memory-exact-sha-review-attestation-registry-v0"
_MAX_REPOSITORY_LENGTH = 200
_MAX_TRUSTED_REVIEWERS = 64
_MAX_FINDINGS = 32
_MAX_EVIDENCE_ARTIFACTS = 64
_REPOSITORY_RE = re.compile(
    r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
```

Implement the three errors and four `StrEnum` types exactly as specified in the design. Define `_DEFECT_FINDINGS` and `_EVIDENCE_FINDINGS` as frozen sets.

- [ ] **Step 2: Implement canonical JSON, hashing, UUID, scalar validation, and bounded collection normalization**

Use exact helpers:

```python
def _canonical_json(value: object) -> str: ...
def _hash_payload(value: object) -> str: ...
def _stable_uuid(kind: str, content_hash: str) -> UUID: ...
def _require_repository(value: object) -> str: ...
def _positive_integer(name: str, value: object) -> int: ...
def _require_uuid(name: str, value: object) -> UUID: ...
def _require_sha256(name: str, value: object) -> str: ...
def _require_git_sha(name: str, value: object) -> str: ...
def _bounded_unique(
    name: str,
    values: object,
    *,
    limit: int,
    validator: Callable[[str, object], T],
    sort_key: Callable[[T], str],
    require_nonempty: bool,
) -> tuple[T, ...]: ...
```

`_bounded_unique` must reject strings, bytes, bytearrays, and mappings; consume with `islice(iterator, limit + 1)`; reject overflow and duplicates before sorting; never call `repr` on invalid input.

- [ ] **Step 3: Implement `ReviewerIdentity`**

The canonical payload is:

```python
{
    "schema": _SCHEMA,
    "kind": "reviewer_identity",
    "model": self.model.value,
    "reviewer_key_fingerprint": self.reviewer_key_fingerprint,
}
```

- [ ] **Step 4: Implement `ExactShaReviewRequest`**

Normalize trusted fingerprints with `_bounded_unique`. Reject identical base/candidate SHA and impossible thresholds. Use this identity payload:

```python
{
    "schema": _SCHEMA,
    "kind": "review_request",
    "repository": self.repository,
    "pull_request_number": self.pull_request_number,
    "base_sha": self.base_sha,
    "candidate_sha": self.candidate_sha,
    "diff_sha256": self.diff_sha256,
    "review_packet_sha256": self.review_packet_sha256,
    "acceptance_criteria_sha256": self.acceptance_criteria_sha256,
    "required_model": self.required_model.value,
    "trusted_reviewer_fingerprints": list(
        self.trusted_reviewer_fingerprints
    ),
    "minimum_approvals": self.minimum_approvals,
}
```

Expose:

```python
@property
def registry_key(self) -> tuple[str, int, str]:
    return (
        self.repository,
        self.pull_request_number,
        self.candidate_sha,
    )
```

- [ ] **Step 5: Implement `ExactShaReviewAttestation`**

Normalize findings and evidence hashes through bounded helpers. Enforce verdict/finding compatibility exactly. The canonical payload must bind every public field and the reviewer identity payload plus content hash.

- [ ] **Step 6: Run immutable-contract tests**

Run enum, malformed-constructor, permutation, canonical JSON, and frozen-object subsets. Expected: all immutable public-type tests pass; registry tests still fail because the registry is absent.

- [ ] **Step 7: Commit immutable contracts**

```bash
git add \
  src/nextgen_memory/review_attestation_registry.py \
  tests/test_review_attestation_registry.py
git commit -m "feat: add exact review attestation contracts"
```

---

### Task 3: Implement request registration and immutable conflict behavior

**Files:**
- Modify: `src/nextgen_memory/review_attestation_registry.py`
- Test: `tests/test_review_attestation_registry.py`

**Interfaces:**
- Consumes: `ExactShaReviewRequest`.
- Produces: request storage and retrieval methods on `InMemoryExactShaReviewAttestationRegistry`.

- [ ] **Step 1: Add the registry state maps and slots**

```python
class InMemoryExactShaReviewAttestationRegistry:
    __slots__ = (
        "_requests_by_id",
        "_request_ids_by_key",
        "_attestations_by_request",
    )

    def __init__(self) -> None:
        self._requests_by_id: dict[UUID, ExactShaReviewRequest] = {}
        self._request_ids_by_key: dict[tuple[str, int, str], UUID] = {}
        self._attestations_by_request: dict[
            UUID,
            dict[str, ExactShaReviewAttestation],
        ] = {}
```

- [ ] **Step 2: Implement `register_request` with validation before mutation**

Use this order:

1. exact request type;
2. existing registry key;
3. exact retry return or conflict;
4. defensive UUID reuse check;
5. assign all three maps.

Do not use `setdefault` because it can obscure mutation ordering.

- [ ] **Step 3: Implement `get_request` and the private request lookup**

```python
def _require_registered_request(
    self,
    request_id: UUID,
) -> ExactShaReviewRequest:
    request_id = _require_uuid("request_id", request_id)
    try:
        return self._requests_by_id[request_id]
    except KeyError as exc:
        raise ReviewAttestationStateError(
            "review request is not registered"
        ) from exc
```

`get_request` returns the immutable object directly.

- [ ] **Step 4: Run registration/retry/conflict/state tests**

Expected: exact retries preserve object identity; key conflicts and unknown IDs use the correct bounded exceptions; failed operations leave maps unchanged.

- [ ] **Step 5: Commit request registry behavior**

```bash
git add \
  src/nextgen_memory/review_attestation_registry.py \
  tests/test_review_attestation_registry.py
git commit -m "feat: register exact review requests idempotently"
```

---

### Task 4: Implement attestation recording, summary, and advisory decision

**Files:**
- Modify: `src/nextgen_memory/review_attestation_registry.py`
- Test: `tests/test_review_attestation_registry.py`

**Interfaces:**
- Consumes: registered request plus `ExactShaReviewAttestation`.
- Produces: `ReviewAttestationRegistrySummary`, `ReviewAttestationDecision`, and complete registry behavior.

- [ ] **Step 1: Implement exact binding validation before mutation**

Add a private method that checks, in order:

```python
attestation.request_content_hash == request.content_hash
attestation.repository == request.repository
attestation.pull_request_number == request.pull_request_number
attestation.candidate_sha == request.candidate_sha
attestation.reviewer.model is request.required_model
attestation.reviewer.reviewer_key_fingerprint
    in request.trusted_reviewer_fingerprints
```

Raise `ReviewAttestationValidationError` with bounded field-category messages.

- [ ] **Step 2: Implement `record_attestation`**

Lookup the request and validate all bindings before reading or mutating the reviewer map. The reviewer fingerprint is the immutable uniqueness key. Return the existing object for an exact retry; raise conflict for changed content.

- [ ] **Step 3: Implement canonical `attestations` ordering**

Return a tuple sorted by:

```python
(
    item.reviewer.reviewer_key_fingerprint,
    str(item.id),
)
```

- [ ] **Step 4: Implement `ReviewAttestationRegistrySummary`**

Validate all UUID/hash/count fields and exact count partitioning. Generate its content hash from a payload containing schema, kind, request identity, ordered attestation IDs, and every count.

- [ ] **Step 5: Implement `summary`**

Count each verdict by enum identity. Because reviewer fingerprints are registry keys, `distinct_reviewer_count` equals stored attestation count; still compute it from the tuple and assert the invariant when constructing the summary.

- [ ] **Step 6: Implement `ReviewAttestationDecision` and `decision` precedence**

Use exactly:

```python
if summary.changes_required_count > 0:
    state = ReviewAdvisoryState.BLOCKED
elif summary.evidence_blocked_count > 0:
    state = ReviewAdvisoryState.EVIDENCE_BLOCKED
elif summary.approval_count >= request.minimum_approvals:
    state = ReviewAdvisoryState.APPROVED
else:
    state = ReviewAdvisoryState.PENDING
```

Construct a UUID5 decision whose content binds request ID/hash, state, summary hash, and `advisory_only=True`.

- [ ] **Step 7: Run complete focused behavior tests**

Expected: all focused tests pass, including combined blocker precedence, exact retry, conflict, wrong binding, no partial mutation, deterministic summary, and canonical decision JSON.

- [ ] **Step 8: Commit complete registry engine**

```bash
git add \
  src/nextgen_memory/review_attestation_registry.py \
  tests/test_review_attestation_registry.py
git commit -m "feat: evaluate exact review attestations deterministically"
```

---

### Task 5: Complete generated properties and process determinism

**Files:**
- Modify: `tests/test_review_attestation_registry_properties.py`
- Modify: `src/nextgen_memory/review_attestation_registry.py` only for defects exposed by RED tests

**Interfaces:**
- Consumes: complete public API from Tasks 2–4.
- Produces: generated trace and cross-process determinism evidence.

- [ ] **Step 1: Implement the 5,000-trace loop**

For index `0..4999`, create three trusted reviewer fingerprints from SHA-256 of deterministic labels, vary `minimum_approvals` between one and three, and choose one of four modes:

```text
0 → pending below approval threshold
1 → approved at threshold
2 → evidence_blocked despite approvals
3 → blocked despite approvals and evidence blocker
```

For each trace:

- register the same request twice;
- record each attestation twice;
- require expected state;
- require exact summary/decision retry equality;
- require count partitioning;
- mutate one material attestation field and require conflict or changed identity in a fresh registry.

- [ ] **Step 2: Implement permutation properties**

For 250 generated cases, permute trusted-reviewer, finding-code, evidence-hash, and attestation insertion order. Require identical request, attestation, summary, and decision bytes.

- [ ] **Step 3: Implement material-field sensitivity tables**

Mutate every accepted request field and every accepted attestation field independently. For paired identity fields, keep the mutated object structurally valid. Require changed UUID/content hash or explicit validation failure.

- [ ] **Step 4: Implement process hash-seed invariance**

Run the embedded script under seeds `1`, `37`, and `999`; construct collections from sets; print:

```python
summary.render_json() + decision.render_json()
```

Require one unique stdout value and state `approved`.

- [ ] **Step 5: Run generated properties separately and with focused suite**

```bash
python -m pytest -q tests/test_review_attestation_registry_properties.py
python -m pytest -q \
  tests/test_review_attestation_registry.py \
  tests/test_review_attestation_registry_properties.py \
  tests/test_review_attestation_registry_public_api.py
```

- [ ] **Step 6: Commit deterministic properties**

```bash
git add \
  src/nextgen_memory/review_attestation_registry.py \
  tests/test_review_attestation_registry_properties.py
git commit -m "test: prove review attestation registry determinism"
```

---

### Task 6: Export the public API and document the stable subsystem boundary

**Files:**
- Modify: `src/nextgen_memory/__init__.py`
- Create: `docs/exact-sha-review-attestation-registry-v0.md`
- Test: `tests/test_review_attestation_registry_public_api.py`

**Interfaces:**
- Consumes: complete registry module.
- Produces: package-root API and stable subsystem documentation.

- [ ] **Step 1: Add one explicit package import block**

```python
from .review_attestation_registry import (
    ExactShaReviewAttestation,
    ExactShaReviewRequest,
    InMemoryExactShaReviewAttestationRegistry,
    ReviewAdvisoryState,
    ReviewAttestationConflictError,
    ReviewAttestationDecision,
    ReviewAttestationRegistrySummary,
    ReviewAttestationStateError,
    ReviewAttestationValidationError,
    ReviewAttestationVerdict,
    ReviewFindingCode,
    ReviewerIdentity,
    ReviewModel,
)
```

Add each name exactly once to the sorted `__all__` list.

- [ ] **Step 2: Document state precedence and external authentication boundary**

`docs/exact-sha-review-attestation-registry-v0.md` must contain:

- exact request and attestation fields;
- one request key and one reviewer key;
- verdict/finding compatibility table;
- `BLOCKED > EVIDENCE_BLOCKED > APPROVED > PENDING` precedence;
- exact retry and immutable conflict behavior;
- canonical identity and privacy boundaries;
- explicit statement that authenticated-envelope SHA is caller-authenticated evidence, not product-side signature verification;
- explicit statement that `APPROVED` is advisory and cannot merge.

- [ ] **Step 3: Run public API and isolated wheel import**

```bash
python -m pytest -q tests/test_review_attestation_registry_public_api.py
python -m pip wheel --no-deps . -w wheelhouse
python -m venv /tmp/review-attestation-wheel
/tmp/review-attestation-wheel/bin/python -m pip install --no-deps wheelhouse/*.whl
/tmp/review-attestation-wheel/bin/python - <<'PY'
import nextgen_memory
from nextgen_memory import (
    InMemoryExactShaReviewAttestationRegistry,
    ReviewAdvisoryState,
    ReviewModel,
)
assert InMemoryExactShaReviewAttestationRegistry is not None
assert ReviewAdvisoryState.APPROVED.value == "approved"
assert ReviewModel.GPT_5_6_SOL.value == "gpt-5.6-sol"
assert "InMemoryExactShaReviewAttestationRegistry" in nextgen_memory.__all__
PY
/tmp/review-attestation-wheel/bin/python -m pip check
```

- [ ] **Step 4: Commit exports and stable docs**

```bash
git add \
  src/nextgen_memory/__init__.py \
  docs/exact-sha-review-attestation-registry-v0.md \
  tests/test_review_attestation_registry_public_api.py
git commit -m "feat: export exact review attestation registry v0"
```

---

### Task 7: Qualify and publish one immutable product candidate

**Files:**
- Verify: all nine product paths
- No workflow remains in the final product diff

**Interfaces:**
- Consumes: completed feature branch and immutable RED branch.
- Produces: one immutable candidate branch and producer evidence.

- [ ] **Step 1: Run static, focused, and complete verification**

```bash
ruff format --check \
  src/nextgen_memory/__init__.py \
  src/nextgen_memory/review_attestation_registry.py \
  tests/test_review_attestation_registry.py \
  tests/test_review_attestation_registry_properties.py \
  tests/test_review_attestation_registry_public_api.py
ruff check .
python -m compileall -q src scripts
python -m pytest -q \
  tests/test_review_attestation_registry.py \
  tests/test_review_attestation_registry_properties.py \
  tests/test_review_attestation_registry_public_api.py
python -m pytest -q
```

- [ ] **Step 2: Run the strict AST and text audit**

Fail on:

```text
non-standard-library runtime imports
network/database/filesystem/environment/time/random/subprocess APIs
builtin eval/exec/compile/open
uuid1/uuid4
pass, executable ellipsis, NotImplementedError
skip, xfail, noqa
raw review prose/diff/query/prompt/answer/memory/credential/path fields
merge/deploy/activate/write_feedback/signature-verification claims
```

Type-hint ellipses such as `tuple[str, ...]` are not executable stubs and must not be false positives.

- [ ] **Step 3: Prove exact nine-path scope**

Compare the final tree to base `f4f3aca9759b5b7a60691017c2211152c011ea92`. Require the exact nine paths in the design spec and reject any workflow, migration, dependency, package metadata, database adapter, feedback writer, activation path, or corrective-retrieval change.

- [ ] **Step 4: Publish one immutable candidate**

Commit only after all checks pass:

```bash
git commit -m "feat: add exact-SHA review attestation registry v0"
git push origin HEAD:feat/exact-sha-review-attestation-registry-v0-20260824
git push origin HEAD:candidate/exact-sha-review-attestation-registry-v0-20260824
```

Refuse to move an existing candidate branch to another SHA.

- [ ] **Step 5: Persist an unqualified producer checkpoint**

Record branch, SHA, RED SHA, test counts, audit result, exact paths, safety boundaries, and next action. Status remains `verification_pending_unmerged`; do not claim GREEN until Task 8 succeeds.

---

### Task 8: Run independent Python 3.12/3.13 exact-SHA verification and freeze review evidence

**Files:**
- Product candidate remains unchanged
- Evidence branches add only bounded JSON documents outside the product diff

**Interfaces:**
- Consumes: immutable candidate SHA from Task 7.
- Produces: exact matrix artifacts, immutable evidence/checkpoint branches, canonical draft PR, blind Sol packet, and persistent GREEN readback.

- [ ] **Step 1: Check out the immutable SHA directly in both matrix jobs**

Each job independently proves base, ancestry, exact nine paths, clean status, Ruff, compileall, focused/full suites, 5,000 traces, process hash-seed invariance, strict audit, and isolated wheel import.

- [ ] **Step 2: Generate bounded semantic evidence**

Under `PYTHONHASHSEED=1` and `999`, construct one request plus:

- pending below threshold;
- approved at threshold;
- evidence blocker despite approvals;
- changes-required blocker despite approvals/evidence blocker;
- exact request and attestation retries.

Store only canonical request/attestation/summary/decision identities and counts.

- [ ] **Step 3: Compare Python evidence byte-for-byte**

Require both Python manifests to bind the same base/candidate SHA, exact path count, focused/full counts, trace count, semantic SHA, hash-seed result, audit result, and retry result. Require semantic JSON bytes to be identical. Wheel byte identity is not required; each wheel hash is recorded separately.

- [ ] **Step 4: Download and rehash artifacts**

After matrix success, download Python 3.12, Python 3.13, and cross-Python summary ZIPs. Recompute ZIP and wheel SHA-256 values, compare manifests and semantic bytes, and reject expired or missing artifacts.

- [ ] **Step 5: Publish immutable evidence and checkpoint branches**

Use fresh candidate-bound names:

```text
evidence/exact-sha-review-attestation-registry-v0-<short-sha>-green-20260824
evidence/exact-sha-review-attestation-registry-v0-<short-sha>-checkpoint-20260824
```

Evidence includes exact SHAs, test counts, traces, semantic identities, artifact IDs/digests, review status `pending`, and all safety boundaries.

- [ ] **Step 6: Create one canonical draft product PR and blind Sol packet**

The PR head is the immutable candidate; the base is `candidate/advisory-policy-promotion-gate-v0-20260824`. The packet requires exactly `APPROVE`, `CHANGES_REQUIRED`, or `BLOCKED_BY_EVIDENCE`, names the exact SHA, and directs the reviewer to inspect code/tests/logs/artifacts rather than trust prose.

- [ ] **Step 7: Persist and read back GREEN state**

Write Neon checkpoint:

```text
m-head:exact-sha-review-attestation-registry-v0:green-readback:<short-sha>
```

Create an idempotent memory node, mirror to MongoDB Atlas, and read both stores back. Require matching candidate SHA, PR, run, artifact identities, review status, merge prohibition, and safety fields.

- [ ] **Step 8: Close development/verifier transports without merge**

Keep only the immutable canonical product PR open. Preserve all RED, debugging, producer, verifier, and artifact history as provenance.
