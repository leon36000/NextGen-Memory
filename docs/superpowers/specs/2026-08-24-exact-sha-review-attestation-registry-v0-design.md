# Exact-SHA Review Attestation Registry v0 Design

**Date:** 2026-08-24
**Status:** approved under the project owner's standing autonomous-development delegation
**Issue:** #165
**Base branch:** `candidate/advisory-policy-promotion-gate-v0-20260824`
**Base SHA:** `f4f3aca9759b5b7a60691017c2211152c011ea92`
**Qualified RED branch:** `tdd/exact-sha-review-attestation-registry-v0-red-v5-20260825`
**Qualified RED SHA:** `849df204e899d7570ef469d52307786cf242695a`

## 1. Goal

Exact-SHA Review Attestation Registry v0 is a pure deterministic in-memory boundary for review evidence. It binds one review request and its attestations to exact immutable repository, pull-request, base-SHA, candidate-SHA, diff, review-packet, acceptance-criteria, reviewer, model, artifact, and authenticated-envelope identities.

The registry computes one advisory state:

```text
pending
approved
evidence_blocked
blocked
```

It never merges, authenticates a signature, contacts GitHub, persists state, activates a policy, deploys code, writes feedback, applies a migration, or publishes a release.

## 2. Position in the verified policy path

```text
immutable product candidate
  → exact review request
  → externally authenticated reviewer envelope
  → exact review attestation
  → in-memory attestation registry
  → advisory review decision
  → separately authorized merge or release process
```

`approved` means only that the supplied trusted exact attestations satisfy the request threshold and contain no blocker. It is not merge authorization.

## 3. Design principles

1. **Exact binding before mutation.** Repository, PR, request, candidate, model, reviewer, packet, criteria, and artifact identities must agree before the registry changes.
2. **Hard blockers win.** `CHANGES_REQUIRED` outranks evidence blockers and approvals.
3. **No implicit trust.** Only reviewer-key fingerprints explicitly present in the request are accepted.
4. **No authentication claim.** The caller authenticates the envelope; v0 binds only its SHA-256.
5. **Canonical set semantics.** Trusted reviewers, finding codes, and evidence hashes are duplicate-free and order-independent.
6. **Bounded input consumption.** Collection-like inputs are consumed through a hard limit plus one element, including arbitrary iterators.
7. **Deterministic output.** Process hash seed, insertion order, input permutation, and Python 3.12/3.13 cannot change logical identities.
8. **Pure core.** The module uses only the Python standard library and performs no I/O.

## 4. Public enums

### 4.1 `ReviewModel`

```python
class ReviewModel(StrEnum):
    GPT_5_6_SOL = "gpt-5.6-sol"
```

V0 intentionally supports one exact bounded model identity. Adding another model is a later contract change.

### 4.2 `ReviewAttestationVerdict`

```python
class ReviewAttestationVerdict(StrEnum):
    APPROVE = "APPROVE"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    BLOCKED_BY_EVIDENCE = "BLOCKED_BY_EVIDENCE"
```

### 4.3 `ReviewAdvisoryState`

```python
class ReviewAdvisoryState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    EVIDENCE_BLOCKED = "evidence_blocked"
    BLOCKED = "blocked"
```

### 4.4 `ReviewFindingCode`

Defect findings:

```text
contract_violation
safety_violation
identity_mismatch
test_failure
privacy_risk
side_effect_risk
```

Evidence findings:

```text
missing_artifact
artifact_integrity_unproven
incomplete_test_matrix
stale_or_expired_evidence
```

The module keeps explicit immutable `_DEFECT_FINDINGS` and `_EVIDENCE_FINDINGS` sets. Arbitrary review prose is not accepted.

## 5. Public immutable types

### 5.1 `ReviewerIdentity`

A frozen, slotted identity:

```python
@dataclass(frozen=True, slots=True)
class ReviewerIdentity:
    model: ReviewModel
    reviewer_key_fingerprint: str
    content_hash: str = field(init=False)
```

Validation:

- `model` must be an actual `ReviewModel` value;
- `reviewer_key_fingerprint` must be exactly 64 lowercase hexadecimal characters;
- no reviewer name, email, account, free-form label, or credential exists;
- `content_hash` is SHA-256 over the canonical identity payload.

### 5.2 `ExactShaReviewRequest`

```python
@dataclass(frozen=True, slots=True)
class ExactShaReviewRequest:
    repository: str
    pull_request_number: int
    base_sha: str
    candidate_sha: str
    diff_sha256: str
    review_packet_sha256: str
    acceptance_criteria_sha256: str
    required_model: ReviewModel
    trusted_reviewer_fingerprints: object
    minimum_approvals: int
    id: UUID = field(init=False)
    content_hash: str = field(init=False)
```

Validation and normalization:

- repository is exact trimmed `owner/name`, at most 200 characters, using only ASCII letters, digits, `.`, `_`, and `-` in each segment;
- PR number and approval threshold are positive integers; booleans are rejected;
- base and candidate SHAs are exact lowercase 40-character Git SHAs and must differ;
- diff, review-packet, and acceptance-criteria identities are lowercase SHA-256;
- required model is an actual `ReviewModel`;
- trusted reviewer fingerprints are consumed through `MAX_TRUSTED_REVIEWERS + 1`, with a v0 maximum of 64;
- trusted reviewer fingerprints are non-empty, valid SHA-256 values, and duplicate-free before canonical sorting;
- minimum approvals cannot exceed the trusted-reviewer count.

Identity:

```text
content_hash = SHA-256(canonical request payload)
id = UUID5(NAMESPACE_URL, "nextgen-memory:exact-sha-review-request-v0:<content_hash>")
```

The registry uniqueness key is:

```python
(repository, pull_request_number, candidate_sha)
```

### 5.3 `ExactShaReviewAttestation`

```python
@dataclass(frozen=True, slots=True)
class ExactShaReviewAttestation:
    request_id: UUID
    request_content_hash: str
    repository: str
    pull_request_number: int
    candidate_sha: str
    reviewer: ReviewerIdentity
    verdict: ReviewAttestationVerdict
    finding_codes: object
    review_artifact_sha256: str
    evidence_artifact_sha256s: object
    authenticated_envelope_sha256: str
    id: UUID = field(init=False)
    content_hash: str = field(init=False)
```

Structural validation:

- UUID, request hash, repository, PR, candidate SHA, reviewer, verdict, and artifact hashes use exact bounded types;
- finding inputs are consumed through 33 elements, must contain only `ReviewFindingCode`, and must be duplicate-free before canonical sorting;
- evidence hashes are consumed through 65 elements, must be non-empty SHA-256 values, and must be duplicate-free before canonical sorting;
- `APPROVE` requires zero findings;
- `CHANGES_REQUIRED` requires at least one defect finding; evidence findings may accompany a defect;
- `BLOCKED_BY_EVIDENCE` requires at least one evidence finding and permits no defect finding;
- the authenticated-envelope hash is only a caller-supplied immutable identity; v0 makes no signature-verification claim.

Identity:

```text
content_hash = SHA-256(canonical attestation payload)
id = UUID5(NAMESPACE_URL, "nextgen-memory:exact-sha-review-attestation-v0:<content_hash>")
```

### 5.4 `ReviewAttestationRegistrySummary`

A frozen, slotted summary containing only bounded identities and counts:

```python
request_id: UUID
request_content_hash: str
attestation_ids: tuple[UUID, ...]
registered_attestation_count: int
approval_count: int
changes_required_count: int
evidence_blocked_count: int
distinct_reviewer_count: int
missing_approval_count: int
content_hash: str
```

Attestation IDs are ordered by reviewer fingerprint and then attestation UUID. Counts exactly partition stored attestations. `missing_approval_count` is `max(0, minimum_approvals - approval_count)`.

### 5.5 `ReviewAttestationDecision`

```python
@dataclass(frozen=True, slots=True)
class ReviewAttestationDecision:
    id: UUID
    request_id: UUID
    request_content_hash: str
    state: ReviewAdvisoryState
    summary_content_hash: str
    advisory_only: bool
    content_hash: str
```

`advisory_only` must be exactly `True`. The content hash binds every field except the derived ID; the ID is UUID5 under the versioned decision domain.

## 6. Registry behavior

### 6.1 Internal state

`InMemoryExactShaReviewAttestationRegistry` has exactly three mutable maps:

```python
_requests_by_id: dict[UUID, ExactShaReviewRequest]
_request_ids_by_key: dict[tuple[str, int, str], UUID]
_attestations_by_request: dict[UUID, dict[str, ExactShaReviewAttestation]]
```

The inner attestation map is keyed by reviewer-key fingerprint.

### 6.2 `register_request`

1. Require an actual `ExactShaReviewRequest`.
2. Check the repository/PR/candidate key.
3. Return the existing request for an exact immutable retry.
4. Raise `ReviewAttestationConflictError` when the key already maps to changed immutable content.
5. Check request UUID reuse defensively.
6. Mutate all maps only after every check passes.

### 6.3 `record_attestation`

1. Require an actual `ExactShaReviewAttestation`.
2. Resolve the registered request; unknown request IDs raise `ReviewAttestationStateError`.
3. Validate exact request content hash, repository, PR number, and candidate SHA.
4. Require reviewer model to equal the request model.
5. Require reviewer fingerprint in the trusted request set.
6. Resolve the reviewer-fingerprint key.
7. Return the existing attestation for an exact immutable retry.
8. Raise `ReviewAttestationConflictError` for changed immutable content from the same reviewer.
9. Mutate only after every validation succeeds.

### 6.4 Read methods

```python
get_request(request_id: UUID) -> ExactShaReviewRequest
attestations(request_id: UUID) -> tuple[ExactShaReviewAttestation, ...]
summary(request_id: UUID) -> ReviewAttestationRegistrySummary
decision(request_id: UUID) -> ReviewAttestationDecision
```

Unknown request IDs raise `ReviewAttestationStateError`. No method exposes mutable internal collections.

## 7. Advisory precedence

For stored attestations, which are necessarily trusted and exact:

```text
if any CHANGES_REQUIRED:
    BLOCKED
elif any BLOCKED_BY_EVIDENCE:
    EVIDENCE_BLOCKED
elif distinct APPROVE reviewers >= minimum approvals:
    APPROVED
else:
    PENDING
```

The registry never combines or overrides reviewer verdicts. One changes-required attestation blocks regardless of approval count. An evidence blocker outranks any approval count unless a changes-required blocker already exists.

## 8. Error model

- `ReviewAttestationValidationError(ValueError)` — malformed immutable public type or wrong request/attestation binding supplied before mutation;
- `ReviewAttestationConflictError(RuntimeError)` — immutable request-key or reviewer-key reuse with changed content;
- `ReviewAttestationStateError(RuntimeError)` — unknown request ID or impossible internal lookup.

Exception messages contain bounded field names and reason categories only. They never echo untrusted values or call arbitrary `repr`/`str` fallbacks.

## 9. Canonicalization helpers

Private helpers provide:

- exact repository validation;
- positive integer validation with bool rejection;
- UUID validation;
- lowercase Git-SHA and SHA-256 validation;
- bounded unique iterable consumption with `itertools.islice`;
- canonical JSON with `allow_nan=False`, sorted keys, compact separators, and one trailing newline;
- SHA-256 payload hashing;
- versioned UUID5 domain separation.

Collections are normalized only after duplicate detection. Exact set semantics therefore remain order-independent without silently accepting duplicated caller content.

## 10. Privacy and side-effect boundary

The module may import only Python standard-library modules such as:

```text
__future__
dataclasses
enum
hashlib
itertools
json
re
uuid
collections.abc
```

It contains no:

```text
network or database client
filesystem or environment access
clock or randomness
subprocess, thread, task, worker, lease, or scheduler
GitHub write or signature verification
model or agent execution
feedback write or policy activation
migration, deployment, merge, or release behavior
```

Canonical JSON contains only repository identity, PR number, UUIDs, Git SHAs, SHA-256 values, bounded enums, counts, and advisory state. It contains no raw review prose, diff, query, prompt, answer, memory body, command output, path, credential, reviewer name, or reviewer email.

## 11. TDD strategy

### 11.1 Tests-only RED

The immutable RED branch is based directly on `f4f3aca9759b5b7a60691017c2211152c011ea92` and contains:

```text
docs/exact-sha-review-attestation-registry-v0-red.md
tests/test_review_attestation_registry.py
tests/test_review_attestation_registry_properties.py
tests/test_review_attestation_registry_public_api.py
```

All test files must be Ruff-clean and syntactically valid. Each independent collection must fail only because `nextgen_memory.review_attestation_registry` does not exist. RED v5 preserves the accepted behavior and assertion contract while making all three test-module bootstraps context-invariant under the exact Ruff 0.16.4 product toolchain. The qualified immutable RED is `tdd/exact-sha-review-attestation-registry-v0-red-v5-20260825` at SHA `849df204e899d7570ef469d52307786cf242695a`; it preserves the complete RED v1 contract while correcting the authenticated-envelope fixture to lowercase SHA-256.

### 11.2 Focused behavior coverage

- exact request registration and retry;
- request-key conflict;
- exact attestation recording and retry;
- reviewer-key conflict;
- all three verdicts;
- all four advisory states;
- blocked-over-evidence-over-approval precedence;
- unknown request and wrong request/hash/repository/PR/candidate/model bindings;
- untrusted reviewers;
- verdict/finding compatibility;
- malformed repositories, UUIDs, Git SHAs, SHA-256 values, enums, bool-as-int values, thresholds, and collection cardinalities;
- duplicate trusted reviewers, findings, and evidence hashes;
- bounded infinite-iterator consumption;
- frozen immutable types and canonical JSON;
- exact package-root API.

### 11.3 Generated properties

At least 5,000 deterministic traces cover:

- request registration and exact retry;
- reviewer permutations;
- approval thresholds;
- pending, approved, evidence-blocked, and blocked states;
- finding/evidence permutations;
- material-field mutation sensitivity;
- conflict and no-partial-mutation guarantees.

A subprocess test builds the same request/attestations from sets under `PYTHONHASHSEED=1`, `37`, and `999` and requires byte-identical summary and decision JSON.

## 12. Exact product surface

The immutable product candidate contains exactly nine paths:

```text
docs/exact-sha-review-attestation-registry-v0-red.md
docs/exact-sha-review-attestation-registry-v0.md
docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md
docs/superpowers/plans/2026-08-24-exact-sha-review-attestation-registry-v0.md
src/nextgen_memory/__init__.py
src/nextgen_memory/review_attestation_registry.py
tests/test_review_attestation_registry.py
tests/test_review_attestation_registry_properties.py
tests/test_review_attestation_registry_public_api.py
```

No workflow, migration, dependency, package metadata, database adapter, feedback writer, activation path, or corrective-retrieval source belongs in the product diff.

## 13. Verification and merge gate

Before review, an independent exact-SHA Python 3.12/3.13 matrix must prove:

- exact base, ancestry, and nine-path surface;
- Ruff and compileall;
- focused and complete test suites;
- 5,000 generated traces;
- process hash-seed invariance;
- cross-Python byte-identical summary and decision evidence;
- strict dependency/privacy/side-effect/stub audit;
- isolated wheel installation and package-root import;
- immutable evidence and checkpoint branches.

A genuine blind GPT-5.6 Sol review must return `APPROVE` for the unchanged immutable candidate SHA before merge. Any SHA movement invalidates all evidence. `APPROVED` from this registry never authorizes merge, migration, deployment, feedback, policy activation, or release.