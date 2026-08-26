# Exact-SHA Review Attestation Registry v0

## Status

Exact-SHA Review Attestation Registry v0 is a pure, deterministic, in-memory review-evidence boundary. It binds one immutable review request and its externally authenticated attestations to exact repository, pull-request, candidate, reviewer, model, packet, criteria, and artifact identities.

The component is advisory only. It cannot authenticate a signature, contact GitHub, persist data, merge code, deploy, migrate, write feedback, activate a policy, or publish a release.

## Request identity

`ExactShaReviewRequest` binds:

- repository `owner/name`;
- positive pull-request number;
- exact lowercase base and candidate Git SHAs;
- SHA-256 of the diff, review packet, and acceptance criteria;
- required review model;
- a non-empty, duplicate-free trusted reviewer-key fingerprint set;
- a positive approval threshold that does not exceed the trusted set.

The immutable registry key is:

```python
(repository, pull_request_number, candidate_sha)
```

An exact retry returns the existing request. Reusing that key with changed immutable content raises `ReviewAttestationConflictError` before mutation.

## Attestation identity

`ExactShaReviewAttestation` binds:

- exact request UUID and content hash;
- repository, pull-request number, and candidate SHA;
- bounded `ReviewerIdentity`;
- exact verdict and canonical finding codes;
- review-artifact SHA-256;
- non-empty canonical evidence-artifact SHA-256 set;
- authenticated-envelope SHA-256 supplied by an already-authenticated caller.

The product does not verify a signature. It records only the caller-supplied fingerprint of an envelope whose provenance was authenticated outside the module.

One reviewer-key fingerprint may contribute one immutable attestation per request. An exact retry is idempotent; changed immutable content under the same reviewer key conflicts.

## Verdict and finding compatibility

| Verdict | Required finding contract |
| --- | --- |
| `APPROVE` | no findings |
| `CHANGES_REQUIRED` | at least one defect finding; evidence findings may accompany it |
| `BLOCKED_BY_EVIDENCE` | at least one evidence finding and no defect finding |

Defect findings are bounded to contract, safety, identity, test, privacy, and side-effect risks. Evidence findings are bounded to missing artifacts, unproven integrity, incomplete test matrices, and stale or expired evidence.

## Advisory state precedence

The registry computes one deterministic state:

```text
BLOCKED > EVIDENCE_BLOCKED > APPROVED > PENDING
```

The exact rules are:

1. any trusted exact `CHANGES_REQUIRED` attestation yields `blocked`;
2. otherwise, any trusted exact `BLOCKED_BY_EVIDENCE` attestation yields `evidence_blocked`;
3. otherwise, distinct exact approvals meeting the request threshold yield `approved`;
4. otherwise the request remains `pending`.

`ReviewAttestationDecision.advisory_only` is always `True`. Even `approved` is evidence for a separately authorized operation and never authorizes merge, deployment, migration, feedback, activation, or release.

## Determinism

Every accepted collection is bounded, duplicate-free, and canonicalized before identity generation. Request identity is invariant to trusted-reviewer input order. Attestation identity is invariant to finding and evidence input order. Summary and decision identity are invariant to attestation insertion order.

Canonical JSON uses sorted keys, compact separators, finite values, and one trailing newline. SHA-256 content hashes and UUID5 identifiers use explicit versioned domains. Exact retries remain byte-identical across process hash seeds and supported Python versions.

## Validation and privacy boundary

All structural and request-binding validation occurs before mutation. The module rejects malformed UUIDs, repositories, Git SHAs, SHA-256 values, enum values, bool-as-integer values, duplicate collections, oversized iterators, impossible thresholds, untrusted reviewers, and mismatched request identities.

Canonical records contain only bounded identities, enums, counts, and advisory state. They contain no raw review prose, source diff, query, prompt, answer, memory body, command output, path, credential, reviewer name, or reviewer email.

## Public API

The package root exports:

```text
ExactShaReviewAttestation
ExactShaReviewRequest
InMemoryExactShaReviewAttestationRegistry
ReviewAdvisoryState
ReviewAttestationConflictError
ReviewAttestationDecision
ReviewAttestationRegistrySummary
ReviewAttestationStateError
ReviewAttestationValidationError
ReviewAttestationVerdict
ReviewFindingCode
ReviewerIdentity
ReviewModel
```
