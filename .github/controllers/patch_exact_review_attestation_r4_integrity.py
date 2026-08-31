#!/usr/bin/env python3
"""Apply the minimal post-construction integrity hardening for registry R4."""

from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def replace_in_class(
    source: str,
    class_name: str,
    old: str,
    new: str,
    *,
    label: str,
) -> str:
    start_marker = f"class {class_name}:"
    start = source.index(start_marker)
    next_class = source.find("\n\nclass ", start + len(start_marker))
    end = len(source) if next_class == -1 else next_class
    segment = source[start:end]
    if segment.count(old) != 1:
        raise SystemExit(
            f"{label}: expected one match inside {class_name}, found {segment.count(old)}"
        )
    segment = segment.replace(old, new, 1)
    return source[:start] + segment + source[end:]


def patch_module(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    # Public serialization must never emit stale identity/content pairs.
    for class_name, checker in (
        ("ReviewerIdentity", "_assert_reviewer_integrity"),
        ("ExactShaReviewRequest", "_assert_request_integrity"),
        ("ExactShaReviewAttestation", "_assert_attestation_integrity"),
        ("ReviewAttestationRegistrySummary", "_assert_summary_integrity"),
        ("ReviewAttestationDecision", "_assert_decision_integrity"),
    ):
        source = replace_in_class(
            source,
            class_name,
            "    def to_dict(self) -> dict[str, object]:\n        return {\n",
            f"    def to_dict(self) -> dict[str, object]:\n        {checker}(self)\n        return {{\n",
            label=f"{class_name}.to_dict integrity hook",
        )

    integrity_helpers = r'''

def _raise_integrity(message: str) -> None:
    raise ReviewAttestationValidationError(message)


def _exact_sha256(value: object) -> bool:
    return type(value) is str and _SHA256_RE.fullmatch(value) is not None


def _exact_git_sha(value: object) -> bool:
    return type(value) is str and _GIT_SHA_RE.fullmatch(value) is not None


def _assert_reviewer_integrity(value: ReviewerIdentity) -> None:
    if type(value) is not ReviewerIdentity:
        _raise_integrity("reviewer integrity check failed")
    if type(value.model) is not ReviewModel:
        _raise_integrity("reviewer integrity check failed")
    if not _exact_sha256(value.reviewer_key_fingerprint):
        _raise_integrity("reviewer integrity check failed")
    if not _exact_sha256(value.content_hash):
        _raise_integrity("reviewer integrity check failed")
    expected_hash = _hash_payload(
        {
            "kind": "reviewer_identity",
            "model": value.model.value,
            "reviewer_key_fingerprint": value.reviewer_key_fingerprint,
            "schema": _SCHEMA,
        }
    )
    if value.content_hash != expected_hash:
        _raise_integrity("reviewer integrity check failed")


def _assert_request_integrity(value: ExactShaReviewRequest) -> None:
    if type(value) is not ExactShaReviewRequest:
        _raise_integrity("review request integrity check failed")
    if (
        type(value.repository) is not str
        or value.repository != value.repository.strip()
        or not value.repository
        or len(value.repository) > _MAX_REPOSITORY_LENGTH
        or _REPOSITORY_RE.fullmatch(value.repository) is None
    ):
        _raise_integrity("review request integrity check failed")
    if type(value.pull_request_number) is not int or value.pull_request_number <= 0:
        _raise_integrity("review request integrity check failed")
    if not _exact_git_sha(value.base_sha) or not _exact_git_sha(value.candidate_sha):
        _raise_integrity("review request integrity check failed")
    if value.base_sha == value.candidate_sha:
        _raise_integrity("review request integrity check failed")
    if not all(
        _exact_sha256(item)
        for item in (
            value.diff_sha256,
            value.review_packet_sha256,
            value.acceptance_criteria_sha256,
        )
    ):
        _raise_integrity("review request integrity check failed")
    if type(value.required_model) is not ReviewModel:
        _raise_integrity("review request integrity check failed")
    trusted = value.trusted_reviewer_fingerprints
    if (
        type(trusted) is not tuple
        or not trusted
        or len(trusted) > _MAX_TRUSTED_REVIEWERS
        or any(not _exact_sha256(item) for item in trusted)
        or len(set(trusted)) != len(trusted)
        or tuple(sorted(trusted)) != trusted
    ):
        _raise_integrity("review request integrity check failed")
    if (
        type(value.minimum_approvals) is not int
        or value.minimum_approvals <= 0
        or value.minimum_approvals > len(trusted)
    ):
        _raise_integrity("review request integrity check failed")
    if not _exact_sha256(value.content_hash) or type(value.id) is not UUID:
        _raise_integrity("review request integrity check failed")
    payload = {
        "acceptance_criteria_sha256": value.acceptance_criteria_sha256,
        "base_sha": value.base_sha,
        "candidate_sha": value.candidate_sha,
        "diff_sha256": value.diff_sha256,
        "kind": "review_request",
        "minimum_approvals": value.minimum_approvals,
        "pull_request_number": value.pull_request_number,
        "repository": value.repository,
        "required_model": value.required_model.value,
        "review_packet_sha256": value.review_packet_sha256,
        "schema": _SCHEMA,
        "trusted_reviewer_fingerprints": list(trusted),
    }
    expected_hash = _hash_payload(payload)
    expected_id = _stable_uuid("exact-sha-review-request", expected_hash)
    if value.content_hash != expected_hash or value.id != expected_id:
        _raise_integrity("review request integrity check failed")


def _assert_attestation_integrity(value: ExactShaReviewAttestation) -> None:
    if type(value) is not ExactShaReviewAttestation:
        _raise_integrity("review attestation integrity check failed")
    if type(value.request_id) is not UUID or not _exact_sha256(value.request_content_hash):
        _raise_integrity("review attestation integrity check failed")
    if (
        type(value.repository) is not str
        or value.repository != value.repository.strip()
        or not value.repository
        or len(value.repository) > _MAX_REPOSITORY_LENGTH
        or _REPOSITORY_RE.fullmatch(value.repository) is None
    ):
        _raise_integrity("review attestation integrity check failed")
    if type(value.pull_request_number) is not int or value.pull_request_number <= 0:
        _raise_integrity("review attestation integrity check failed")
    if not _exact_git_sha(value.candidate_sha):
        _raise_integrity("review attestation integrity check failed")
    _assert_reviewer_integrity(value.reviewer)
    if type(value.verdict) is not ReviewAttestationVerdict:
        _raise_integrity("review attestation integrity check failed")
    findings = value.finding_codes
    if (
        type(findings) is not tuple
        or len(findings) > _MAX_FINDINGS
        or any(type(item) is not ReviewFindingCode for item in findings)
        or len(set(findings)) != len(findings)
        or tuple(sorted(findings, key=lambda item: item.value)) != findings
    ):
        _raise_integrity("review attestation integrity check failed")
    defect_findings = _DEFECT_FINDINGS.intersection(findings)
    evidence_findings = _EVIDENCE_FINDINGS.intersection(findings)
    if value.verdict is ReviewAttestationVerdict.APPROVE and findings:
        _raise_integrity("review attestation integrity check failed")
    if value.verdict is ReviewAttestationVerdict.CHANGES_REQUIRED and not defect_findings:
        _raise_integrity("review attestation integrity check failed")
    if value.verdict is ReviewAttestationVerdict.BLOCKED_BY_EVIDENCE and (
        not evidence_findings or defect_findings
    ):
        _raise_integrity("review attestation integrity check failed")
    evidence = value.evidence_artifact_sha256s
    if (
        type(evidence) is not tuple
        or not evidence
        or len(evidence) > _MAX_EVIDENCE_ARTIFACTS
        or any(not _exact_sha256(item) for item in evidence)
        or len(set(evidence)) != len(evidence)
        or tuple(sorted(evidence)) != evidence
    ):
        _raise_integrity("review attestation integrity check failed")
    if not _exact_sha256(value.review_artifact_sha256) or not _exact_sha256(
        value.authenticated_envelope_sha256
    ):
        _raise_integrity("review attestation integrity check failed")
    if not _exact_sha256(value.content_hash) or type(value.id) is not UUID:
        _raise_integrity("review attestation integrity check failed")
    payload = {
        "authenticated_envelope_sha256": value.authenticated_envelope_sha256,
        "candidate_sha": value.candidate_sha,
        "evidence_artifact_sha256s": list(evidence),
        "finding_codes": [item.value for item in findings],
        "kind": "review_attestation",
        "pull_request_number": value.pull_request_number,
        "repository": value.repository,
        "request_content_hash": value.request_content_hash,
        "request_id": str(value.request_id),
        "review_artifact_sha256": value.review_artifact_sha256,
        "reviewer": value.reviewer.to_dict(),
        "schema": _SCHEMA,
        "verdict": value.verdict.value,
    }
    expected_hash = _hash_payload(payload)
    expected_id = _stable_uuid("exact-sha-review-attestation", expected_hash)
    if value.content_hash != expected_hash or value.id != expected_id:
        _raise_integrity("review attestation integrity check failed")


def _assert_summary_integrity(value: ReviewAttestationRegistrySummary) -> None:
    if type(value) is not ReviewAttestationRegistrySummary:
        _raise_integrity("registry summary integrity check failed")
    if type(value.request_id) is not UUID or not _exact_sha256(value.request_content_hash):
        _raise_integrity("registry summary integrity check failed")
    ids = value.attestation_ids
    if (
        type(ids) is not tuple
        or any(type(item) is not UUID for item in ids)
        or len(set(ids)) != len(ids)
    ):
        _raise_integrity("registry summary integrity check failed")
    counts = (
        value.registered_attestation_count,
        value.approval_count,
        value.changes_required_count,
        value.evidence_blocked_count,
        value.distinct_reviewer_count,
        value.missing_approval_count,
    )
    if any(type(item) is not int or item < 0 for item in counts):
        _raise_integrity("registry summary integrity check failed")
    if len(ids) != value.registered_attestation_count:
        _raise_integrity("registry summary integrity check failed")
    if (
        value.approval_count
        + value.changes_required_count
        + value.evidence_blocked_count
        != value.registered_attestation_count
        or value.distinct_reviewer_count != value.registered_attestation_count
    ):
        _raise_integrity("registry summary integrity check failed")
    if not _exact_sha256(value.content_hash):
        _raise_integrity("registry summary integrity check failed")
    expected_hash = _hash_payload(value._identity_payload())
    if value.content_hash != expected_hash:
        _raise_integrity("registry summary integrity check failed")


def _assert_decision_integrity(value: ReviewAttestationDecision) -> None:
    if type(value) is not ReviewAttestationDecision:
        _raise_integrity("review decision integrity check failed")
    if (
        type(value.request_id) is not UUID
        or not _exact_sha256(value.request_content_hash)
        or type(value.state) is not ReviewAdvisoryState
        or not _exact_sha256(value.summary_content_hash)
        or value.advisory_only is not True
        or not _exact_sha256(value.content_hash)
        or type(value.id) is not UUID
    ):
        _raise_integrity("review decision integrity check failed")
    expected_hash = _hash_payload(value._identity_payload())
    expected_id = _stable_uuid("review-attestation-decision", expected_hash)
    if value.content_hash != expected_hash or value.id != expected_id:
        _raise_integrity("review decision integrity check failed")
'''

    registry_marker = "\n\nclass InMemoryExactShaReviewAttestationRegistry:\n"
    if source.count(registry_marker) != 1:
        raise SystemExit("registry class marker is absent or duplicated")
    source = source.replace(registry_marker, integrity_helpers + registry_marker, 1)

    # Registry now keeps immutable snapshots separate from exposed object references.
    source = replace_in_class(
        source,
        "InMemoryExactShaReviewAttestationRegistry",
        '''    __slots__ = (
        "_attestations_by_request",
        "_request_ids_by_key",
        "_requests_by_id",
    )
''',
        '''    __slots__ = (
        "_attestations_by_request",
        "_request_ids_by_key",
        "_request_snapshots",
        "_requests_by_id",
    )
''',
        label="registry slots",
    )
    source = replace_in_class(
        source,
        "InMemoryExactShaReviewAttestationRegistry",
        '''        self._requests_by_id: dict[UUID, ExactShaReviewRequest] = {}
        self._request_ids_by_key: dict[tuple[str, int, str], UUID] = {}
        self._attestations_by_request: dict[UUID, dict[str, ExactShaReviewAttestation]] = {}
''',
        '''        self._requests_by_id: dict[UUID, ExactShaReviewRequest] = {}
        self._request_ids_by_key: dict[tuple[str, int, str], UUID] = {}
        self._request_snapshots: dict[
            UUID, tuple[tuple[str, int, str], str]
        ] = {}
        self._attestations_by_request: dict[
            UUID, dict[str, tuple[UUID, str, ExactShaReviewAttestation]]
        ] = {}
''',
        label="registry initialization",
    )
    source = replace_in_class(
        source,
        "InMemoryExactShaReviewAttestationRegistry",
        '''    def register_request(self, request: ExactShaReviewRequest) -> ExactShaReviewRequest:
        if type(request) is not ExactShaReviewRequest:
            raise ReviewAttestationValidationError("request must be an exact ExactShaReviewRequest")
        existing_id = self._request_ids_by_key.get(request.registry_key)
        if existing_id is not None:
            existing = self._requests_by_id[existing_id]
            if existing == request:
                return existing
            raise ReviewAttestationConflictError("review request key conflict")
        existing_by_id = self._requests_by_id.get(request.id)
        if existing_by_id is not None:
            if existing_by_id == request:
                return existing_by_id
            raise ReviewAttestationConflictError("review request identity conflict")
        self._requests_by_id[request.id] = request
        self._request_ids_by_key[request.registry_key] = request.id
        self._attestations_by_request[request.id] = {}
        return request
''',
        '''    def register_request(self, request: ExactShaReviewRequest) -> ExactShaReviewRequest:
        if type(request) is not ExactShaReviewRequest:
            raise ReviewAttestationValidationError("request must be an exact ExactShaReviewRequest")
        _assert_request_integrity(request)
        registry_key = (request.repository, request.pull_request_number, request.candidate_sha)
        existing_id = self._request_ids_by_key.get(registry_key)
        if existing_id is not None:
            existing = self._require_registered_request(existing_id)
            if existing == request:
                return existing
            raise ReviewAttestationConflictError("review request key conflict")
        existing_by_id = self._requests_by_id.get(request.id)
        if existing_by_id is not None:
            existing_by_id = self._require_registered_request(request.id)
            if existing_by_id == request:
                return existing_by_id
            raise ReviewAttestationConflictError("review request identity conflict")
        self._requests_by_id[request.id] = request
        self._request_ids_by_key[registry_key] = request.id
        self._request_snapshots[request.id] = (registry_key, request.content_hash)
        self._attestations_by_request[request.id] = {}
        return request
''',
        label="register_request",
    )
    source = replace_in_class(
        source,
        "InMemoryExactShaReviewAttestationRegistry",
        '''    def _require_registered_request(self, request_id: UUID) -> ExactShaReviewRequest:
        normalized_id = _require_uuid("request id", request_id)
        try:
            return self._requests_by_id[normalized_id]
        except KeyError as exc:
            raise ReviewAttestationStateError("review request is not registered") from exc
''',
        '''    def _require_registered_request(self, request_id: UUID) -> ExactShaReviewRequest:
        normalized_id = _require_uuid("request id", request_id)
        try:
            request = self._requests_by_id[normalized_id]
        except KeyError as exc:
            raise ReviewAttestationStateError("review request is not registered") from exc
        _assert_request_integrity(request)
        registry_key = (request.repository, request.pull_request_number, request.candidate_sha)
        snapshot = self._request_snapshots.get(normalized_id)
        if (
            request.id != normalized_id
            or snapshot != (registry_key, request.content_hash)
            or self._request_ids_by_key.get(registry_key) != normalized_id
            or normalized_id not in self._attestations_by_request
        ):
            _raise_integrity("review request registry integrity check failed")
        return request
''',
        label="registered request integrity",
    )

    # Insert a single stored-attestation validator before record_attestation.
    record_marker = '''    def record_attestation(
        self, attestation: ExactShaReviewAttestation
    ) -> ExactShaReviewAttestation:
'''
    validator_method = '''    def _validate_stored_attestation(
        self,
        request: ExactShaReviewRequest,
        fingerprint: str,
        stored: tuple[UUID, str, ExactShaReviewAttestation],
    ) -> ExactShaReviewAttestation:
        stored_id, stored_hash, attestation = stored
        _assert_attestation_integrity(attestation)
        if (
            attestation.id != stored_id
            or attestation.content_hash != stored_hash
            or attestation.reviewer.reviewer_key_fingerprint != fingerprint
            or attestation.request_id != request.id
            or attestation.request_content_hash != request.content_hash
            or attestation.repository != request.repository
            or attestation.pull_request_number != request.pull_request_number
            or attestation.candidate_sha != request.candidate_sha
        ):
            _raise_integrity("stored review attestation integrity check failed")
        return attestation

'''
    if source.count(record_marker) != 1:
        raise SystemExit("record_attestation marker is absent or duplicated")
    source = source.replace(record_marker, validator_method + record_marker, 1)

    source = replace_in_class(
        source,
        "InMemoryExactShaReviewAttestationRegistry",
        '''        if type(attestation) is not ExactShaReviewAttestation:
            raise ReviewAttestationValidationError(
                "attestation must be an exact ExactShaReviewAttestation"
            )
        request = self._require_registered_request(attestation.request_id)
''',
        '''        if type(attestation) is not ExactShaReviewAttestation:
            raise ReviewAttestationValidationError(
                "attestation must be an exact ExactShaReviewAttestation"
            )
        _assert_attestation_integrity(attestation)
        request = self._require_registered_request(attestation.request_id)
''',
        label="record attestation pre-integrity",
    )
    source = replace_in_class(
        source,
        "InMemoryExactShaReviewAttestationRegistry",
        '''        existing = reviewer_attestations.get(fingerprint)
        if existing is not None:
            if existing == attestation:
                return existing
            raise ReviewAttestationConflictError("reviewer attestation conflict")
        reviewer_attestations[fingerprint] = attestation
        return attestation
''',
        '''        existing_record = reviewer_attestations.get(fingerprint)
        if existing_record is not None:
            existing = self._validate_stored_attestation(
                request, fingerprint, existing_record
            )
            if existing == attestation:
                return existing
            raise ReviewAttestationConflictError("reviewer attestation conflict")
        reviewer_attestations[fingerprint] = (
            attestation.id,
            attestation.content_hash,
            attestation,
        )
        return attestation
''',
        label="attestation snapshot storage",
    )
    source = replace_in_class(
        source,
        "InMemoryExactShaReviewAttestationRegistry",
        '''    def attestations(self, request_id: UUID) -> tuple[ExactShaReviewAttestation, ...]:
        request = self._require_registered_request(request_id)
        return tuple(
            sorted(
                self._attestations_by_request[request.id].values(),
                key=lambda item: (
                    item.reviewer.reviewer_key_fingerprint,
                    str(item.id),
                ),
            )
        )
''',
        '''    def attestations(self, request_id: UUID) -> tuple[ExactShaReviewAttestation, ...]:
        request = self._require_registered_request(request_id)
        values = tuple(
            self._validate_stored_attestation(request, fingerprint, stored)
            for fingerprint, stored in self._attestations_by_request[request.id].items()
        )
        return tuple(
            sorted(
                values,
                key=lambda item: (
                    item.reviewer.reviewer_key_fingerprint,
                    str(item.id),
                ),
            )
        )
''',
        label="attestation snapshot readback",
    )

    # Normal public registry_key access also validates the request object.
    source = replace_in_class(
        source,
        "ExactShaReviewRequest",
        '''    @property
    def registry_key(self) -> tuple[str, int, str]:
        return (self.repository, self.pull_request_number, self.candidate_sha)
''',
        '''    @property
    def registry_key(self) -> tuple[str, int, str]:
        _assert_request_integrity(self)
        return (self.repository, self.pull_request_number, self.candidate_sha)
''',
        label="registry_key integrity hook",
    )

    path.write_text(source, encoding="utf-8")


def patch_tests(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    marker = "def test_request_tampering_before_registration_is_rejected() -> None:"
    if marker in source:
        return
    block = r'''


def assert_integrity_rejection(operation: object) -> None:
    with pytest.raises(ReviewAttestationValidationError, match="integrity") as caught:
        operation()  # type: ignore[operator]
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_request_tampering_before_registration_is_rejected() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = request()
    original_hash = review_request.content_hash
    original_id = review_request.id
    object.__setattr__(review_request, "minimum_approvals", 1)
    assert review_request.content_hash == original_hash
    assert review_request.id == original_id
    assert_integrity_rejection(lambda: registry.register_request(review_request))


def test_request_tampering_after_registration_cannot_change_decision() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(request())
    approve(registry, review_request, REVIEWER_A, "a")
    assert registry.decision(review_request.id).state is ReviewAdvisoryState.PENDING
    object.__setattr__(review_request, "minimum_approvals", 1)
    assert_integrity_rejection(lambda: registry.decision(review_request.id))


def test_reviewer_tampering_is_rejected_before_attestation_identity_is_built() -> None:
    review_request = request()
    identity = reviewer(REVIEWER_A)
    original_hash = identity.content_hash
    object.__setattr__(identity, "reviewer_key_fingerprint", REVIEWER_B)
    assert identity.content_hash == original_hash
    assert_integrity_rejection(
        lambda: attestation(review_request, reviewer=identity)
    )


def test_attestation_tampering_before_record_is_rejected() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(request(minimum_approvals=1))
    value = attestation(review_request, suffix="a")
    original_hash = value.content_hash
    original_id = value.id
    object.__setattr__(value, "verdict", ReviewAttestationVerdict.CHANGES_REQUIRED)
    object.__setattr__(
        value,
        "finding_codes",
        (ReviewFindingCode.CONTRACT_VIOLATION,),
    )
    assert value.content_hash == original_hash
    assert value.id == original_id
    assert_integrity_rejection(lambda: registry.record_attestation(value))
    assert registry.attestations(review_request.id) == ()


def test_attestation_tampering_after_record_cannot_rewrite_registry_history() -> None:
    registry = InMemoryExactShaReviewAttestationRegistry()
    review_request = registry.register_request(request(minimum_approvals=1))
    value = approve(registry, review_request, REVIEWER_A, "a")
    assert registry.decision(review_request.id).state is ReviewAdvisoryState.APPROVED
    object.__setattr__(value, "verdict", ReviewAttestationVerdict.CHANGES_REQUIRED)
    object.__setattr__(
        value,
        "finding_codes",
        (ReviewFindingCode.CONTRACT_VIOLATION,),
    )
    assert_integrity_rejection(lambda: registry.decision(review_request.id))
'''
    path.write_text(source.rstrip() + block + "\n", encoding="utf-8")


def patch_docs(stable: Path, design: Path) -> None:
    stable_source = stable.read_text(encoding="utf-8")
    stable_marker = "## Post-construction identity integrity"
    if stable_marker not in stable_source:
        stable_source = stable_source.rstrip() + r'''


## Post-construction identity integrity

`frozen=True` is not treated as a security boundary. Every reviewer, request,
attestation, summary, and decision revalidates its canonical material against its
derived SHA-256/UUID5 before serialization or registry use. The registry stores
immutable request-key/content-hash snapshots and attestation
reviewer-fingerprint/UUID/content-hash snapshots separately from exposed object
references. A caller that uses Python's `object.__setattr__` escape hatch can
therefore corrupt its local object, but the next registry or serialization
operation fails closed instead of rewriting prior review history.
'''
        stable.write_text(stable_source + "\n", encoding="utf-8")

    design_source = design.read_text(encoding="utf-8")
    design_marker = "### Post-construction tamper model"
    if design_marker not in design_source:
        design_source = design_source.rstrip() + r'''


### Post-construction tamper model

Frozen slotted dataclasses provide ergonomic immutability, not hostile-code
integrity. R4 therefore treats derived identity as a continuously checked
invariant. Public serialization recomputes canonical identity, registry lookups
reconcile request snapshots, and stored attestations are reconciled against
separate immutable fingerprint/UUID/content-hash snapshots before any summary or
decision is calculated. Post-init mutation is a bounded validation failure and
never an implicit state transition.
'''
        design.write_text(design_source + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    arguments = parser.parse_args()
    root = Path(arguments.root)
    patch_module(root / "src/nextgen_memory/review_attestation_registry.py")
    patch_tests(root / "tests/test_review_attestation_registry.py")
    patch_docs(
        root / "docs/exact-sha-review-attestation-registry-v0.md",
        root / "docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md",
    )
    print("exact_review_attestation_r4_integrity_patch_applied=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
