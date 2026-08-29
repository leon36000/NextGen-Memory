#!/usr/bin/env python3
"""Apply the minimal adversarial privacy-boundary fix to the exact review registry."""

from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, *, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("module")
    arguments = parser.parse_args()
    path = Path(arguments.module)
    source = path.read_text(encoding="utf-8")

    source = replace_once(
        source,
        '''def _require_repository(value: object) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > _MAX_REPOSITORY_LENGTH
        or _REPOSITORY_RE.fullmatch(value) is None
    ):
''',
        '''def _require_repository(value: object) -> str:
    if (
        type(value) is not str
        or value != value.strip()
        or not value
        or len(value) > _MAX_REPOSITORY_LENGTH
        or _REPOSITORY_RE.fullmatch(value) is None
    ):
''',
        label="repository exact-type boundary",
    )
    source = replace_once(
        source,
        '''def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReviewAttestationValidationError(f"{name} must be a positive integer")
    return value
''',
        '''def _positive_integer(name: str, value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ReviewAttestationValidationError(f"{name} must be a positive integer")
    return value
''',
        label="positive integer exact-type boundary",
    )
    source = replace_once(
        source,
        '''def _nonnegative_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ReviewAttestationValidationError(f"{name} must be a nonnegative integer")
    return value
''',
        '''def _nonnegative_integer(name: str, value: object) -> int:
    if type(value) is not int or value < 0:
        raise ReviewAttestationValidationError(f"{name} must be a nonnegative integer")
    return value
''',
        label="nonnegative integer exact-type boundary",
    )
    source = replace_once(
        source,
        '''def _require_uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise ReviewAttestationValidationError(f"{name} must be a UUID")
    return value
''',
        '''def _require_uuid(name: str, value: object) -> UUID:
    if type(value) is not UUID:
        raise ReviewAttestationValidationError(f"{name} must be a UUID")
    return value
''',
        label="UUID exact-type boundary",
    )
    source = replace_once(
        source,
        '''def _require_sha256(name: str, value: object) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ReviewAttestationValidationError(f"{name} must be a lowercase SHA-256")
    return value
''',
        '''def _require_sha256(name: str, value: object) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise ReviewAttestationValidationError(f"{name} must be a lowercase SHA-256")
    return value
''',
        label="SHA-256 exact-type boundary",
    )
    source = replace_once(
        source,
        '''def _require_git_sha(name: str, value: object) -> str:
    if not isinstance(value, str) or _GIT_SHA_RE.fullmatch(value) is None:
        raise ReviewAttestationValidationError(f"{name} must be a lowercase 40-character Git SHA")
    return value
''',
        '''def _require_git_sha(name: str, value: object) -> str:
    if type(value) is not str or _GIT_SHA_RE.fullmatch(value) is None:
        raise ReviewAttestationValidationError(f"{name} must be a lowercase 40-character Git SHA")
    return value
''',
        label="Git SHA exact-type boundary",
    )
    source = replace_once(
        source,
        '''def _require_enum[T](name: str, value: object, enum_type: type[T]) -> T:
    if not isinstance(value, enum_type):
        raise ReviewAttestationValidationError(f"{name} must use the bounded enum")
    return value
''',
        '''def _require_enum[T](name: str, value: object, enum_type: type[T]) -> T:
    if type(value) is not enum_type:
        raise ReviewAttestationValidationError(f"{name} must use the bounded enum")
    return value
''',
        label="enum exact-type boundary",
    )
    source = replace_once(
        source,
        '''    try:
        iterator = iter(values)  # type: ignore[arg-type]
    except TypeError as exc:
        raise ReviewAttestationValidationError(f"{name} must be a bounded iterable") from exc
    raw = tuple(islice(iterator, limit + 1))
''',
        '''    iteration_failed = False
    raw: tuple[object, ...] = ()
    try:
        iterator = iter(values)  # type: ignore[arg-type]
        raw = tuple(islice(iterator, limit + 1))
    except Exception:
        iteration_failed = True
    if iteration_failed:
        raise ReviewAttestationValidationError(f"{name} must be a bounded iterable")
''',
        label="bounded iterable privacy boundary",
    )
    source = replace_once(
        source,
        '''        if not isinstance(self.reviewer, ReviewerIdentity):
            raise ReviewAttestationValidationError("reviewer must be a ReviewerIdentity")
''',
        '''        if type(self.reviewer) is not ReviewerIdentity:
            raise ReviewAttestationValidationError(
                "reviewer must be an exact ReviewerIdentity"
            )
''',
        label="reviewer exact-type boundary",
    )
    source = replace_once(
        source,
        '''        if not isinstance(self.attestation_ids, tuple) or any(
            not isinstance(item, UUID) for item in self.attestation_ids
        ):
''',
        '''        if type(self.attestation_ids) is not tuple or any(
            type(item) is not UUID for item in self.attestation_ids
        ):
''',
        label="summary exact tuple/UUID boundary",
    )
    source = replace_once(
        source,
        '''    def register_request(self, request: ExactShaReviewRequest) -> ExactShaReviewRequest:
        if not isinstance(request, ExactShaReviewRequest):
            raise ReviewAttestationValidationError("request must be an ExactShaReviewRequest")
''',
        '''    def register_request(self, request: ExactShaReviewRequest) -> ExactShaReviewRequest:
        if type(request) is not ExactShaReviewRequest:
            raise ReviewAttestationValidationError(
                "request must be an exact ExactShaReviewRequest"
            )
''',
        label="request exact-type registry boundary",
    )
    source = replace_once(
        source,
        '''        if not isinstance(attestation, ExactShaReviewAttestation):
            raise ReviewAttestationValidationError(
                "attestation must be an ExactShaReviewAttestation"
            )
''',
        '''        if type(attestation) is not ExactShaReviewAttestation:
            raise ReviewAttestationValidationError(
                "attestation must be an exact ExactShaReviewAttestation"
            )
''',
        label="attestation exact-type registry boundary",
    )

    forbidden = (
        "not isinstance(value, str)",
        "not isinstance(value, int)",
        "not isinstance(value, UUID)",
        "not isinstance(self.reviewer, ReviewerIdentity)",
        "not isinstance(request, ExactShaReviewRequest)",
        "not isinstance(attestation, ExactShaReviewAttestation)",
    )
    for marker in forbidden:
        if marker in source:
            raise SystemExit(f"unsafe subclass boundary remains: {marker}")

    path.write_text(source, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
