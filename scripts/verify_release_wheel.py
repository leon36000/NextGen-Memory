"""Validate release wheels without extracting or importing their contents."""

from __future__ import annotations

import email.policy
import hashlib
import json
import re
import stat
import zipfile
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path, PurePosixPath

_DISTRIBUTION_SEPARATOR = re.compile(r"[-_.]+")
_MODULE_COMPONENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_FORBIDDEN_COMPONENTS = frozenset(
    {
        ".git",
        ".hg",
        ".idea",
        ".pytest_cache",
        ".svn",
        ".vscode",
        "__pycache__",
        "certs",
        "credentials",
        "secrets",
        "tests",
    }
)
_FORBIDDEN_FILENAMES = frozenset({".env", "id_dsa", "id_ecdsa", "id_ed25519", "id_rsa"})
_FORBIDDEN_SUFFIXES = frozenset({".crt", ".der", ".key", ".p12", ".pem", ".pyc", ".pyo"})


class WheelValidationError(ValueError):
    """The wheel is malformed, unsafe, or incompatible with the expected release."""


@dataclass(frozen=True, slots=True)
class WheelMemberEvidence:
    """Allowlisted evidence for one validated wheel member."""

    name: str
    size: int
    compressed_size: int
    crc32: str
    timestamp: tuple[int, int, int, int, int, int]
    sha256: str

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "compressed_size": self.compressed_size,
            "crc32": self.crc32,
            "name": self.name,
            "sha256": self.sha256,
            "size": self.size,
            "timestamp": list(self.timestamp),
        }


@dataclass(frozen=True, slots=True)
class WheelInspectionReport:
    """Canonical privacy-safe evidence for one validated wheel."""

    wheel_filename: str
    wheel_sha256: str
    wheel_size_bytes: int
    distribution: str
    version: str
    member_count: int
    package_member_count: int
    required_modules: tuple[str, ...]
    metadata_sha256: str
    wheel_metadata_sha256: str
    record_sha256: str
    members: tuple[WheelMemberEvidence, ...]

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "distribution": self.distribution,
            "member_count": self.member_count,
            "members": [member.to_safe_dict() for member in self.members],
            "metadata_sha256": self.metadata_sha256,
            "package_member_count": self.package_member_count,
            "record_sha256": self.record_sha256,
            "required_modules": list(self.required_modules),
            "version": self.version,
            "wheel_filename": self.wheel_filename,
            "wheel_metadata_sha256": self.wheel_metadata_sha256,
            "wheel_sha256": self.wheel_sha256,
            "wheel_size_bytes": self.wheel_size_bytes,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_safe_dict())


def inspect_wheel(
    path: Path,
    *,
    expected_name: str,
    expected_version: str,
    required_modules: tuple[str, ...],
) -> WheelInspectionReport:
    """Validate one wheel and return bounded immutable archive evidence."""

    wheel_path = Path(path)
    _validate_input_path(wheel_path)
    normalized_expected_name = _normalize_distribution(expected_name)
    if not isinstance(expected_version, str) or not expected_version:
        raise WheelValidationError("expected version is invalid")
    normalized_modules = _normalize_required_modules(required_modules)

    try:
        with zipfile.ZipFile(wheel_path, "r") as archive:
            infos = archive.infolist()
            _validate_member_names(infos)
            evidence, payload_by_name = _read_member_evidence(archive, infos)
    except zipfile.BadZipFile as exc:
        raise WheelValidationError("wheel must be a valid ZIP archive") from exc
    except (OSError, RuntimeError, UnicodeError) as exc:
        raise WheelValidationError("wheel archive could not be read safely") from exc

    names = tuple(member.name for member in evidence)
    metadata_name = _one_dist_info_record(names, "METADATA")
    wheel_metadata_name = _one_dist_info_record(names, "WHEEL")
    record_name = _one_dist_info_record(names, "RECORD")
    parents = {
        str(PurePosixPath(metadata_name).parent),
        str(PurePosixPath(wheel_metadata_name).parent),
        str(PurePosixPath(record_name).parent),
    }
    if len(parents) != 1:
        raise WheelValidationError("wheel records must share the same dist-info directory")

    distribution, version = _parse_metadata_identity(payload_by_name[metadata_name])
    if distribution != normalized_expected_name:
        raise WheelValidationError("wheel distribution does not match expected distribution")
    if version != expected_version:
        raise WheelValidationError("wheel version does not match expected version")

    if "nextgen_memory/__init__.py" not in payload_by_name:
        raise WheelValidationError("wheel package root is missing")
    _validate_required_modules(payload_by_name, normalized_modules)

    package_member_count = sum(name.startswith("nextgen_memory/") for name in names)
    return WheelInspectionReport(
        wheel_filename=wheel_path.name,
        wheel_sha256=_sha256_file(wheel_path),
        wheel_size_bytes=wheel_path.stat().st_size,
        distribution=distribution,
        version=version,
        member_count=len(evidence),
        package_member_count=package_member_count,
        required_modules=normalized_modules,
        metadata_sha256=hashlib.sha256(payload_by_name[metadata_name]).hexdigest(),
        wheel_metadata_sha256=hashlib.sha256(
            payload_by_name[wheel_metadata_name]
        ).hexdigest(),
        record_sha256=hashlib.sha256(payload_by_name[record_name]).hexdigest(),
        members=evidence,
    )


def _validate_input_path(path: Path) -> None:
    if path.suffix != ".whl":
        raise WheelValidationError("wheel filename must end with .whl")
    try:
        status = path.lstat()
    except OSError as exc:
        raise WheelValidationError("wheel input must be a regular wheel file") from exc
    if stat.S_ISLNK(status.st_mode):
        raise WheelValidationError("wheel input must be a regular non-symlink wheel file")
    if not stat.S_ISREG(status.st_mode):
        raise WheelValidationError("wheel input must be a regular wheel file")


def _validate_member_names(infos: list[zipfile.ZipInfo]) -> None:
    exact_names: set[str] = set()
    casefolded_names: set[str] = set()
    for info in infos:
        name = info.orig_filename
        _validate_archive_name(name)
        if name in exact_names:
            raise WheelValidationError("wheel contains a duplicate archive member")
        folded = name.casefold()
        if folded in casefolded_names:
            raise WheelValidationError("wheel contains case-colliding archive members")
        exact_names.add(name)
        casefolded_names.add(folded)
        _reject_forbidden_payload(name)


def _validate_archive_name(name: str) -> None:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise WheelValidationError("wheel archive member name is not canonical")
    if name.startswith("/") or name.endswith("/") or "//" in name:
        raise WheelValidationError("wheel archive member name is not canonical")
    pure = PurePosixPath(name)
    if pure.is_absolute() or pure.as_posix() != name:
        raise WheelValidationError("wheel archive member name is not canonical")
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise WheelValidationError("wheel archive member name is not canonical")


def _reject_forbidden_payload(name: str) -> None:
    pure = PurePosixPath(name)
    lowered_parts = tuple(part.casefold() for part in pure.parts)
    lowered_name = pure.name.casefold()
    lowered_suffix = pure.suffix.casefold()
    if any(part in _FORBIDDEN_COMPONENTS for part in lowered_parts):
        raise WheelValidationError("wheel contains a forbidden release payload")
    if lowered_name in _FORBIDDEN_FILENAMES or lowered_suffix in _FORBIDDEN_SUFFIXES:
        raise WheelValidationError("wheel contains a forbidden release payload")


def _read_member_evidence(
    archive: zipfile.ZipFile,
    infos: list[zipfile.ZipInfo],
) -> tuple[tuple[WheelMemberEvidence, ...], dict[str, bytes]]:
    records: list[WheelMemberEvidence] = []
    payload_by_name: dict[str, bytes] = {}
    for info in infos:
        try:
            payload = archive.read(info)
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise WheelValidationError("wheel member could not be read safely") from exc
        payload_by_name[info.orig_filename] = payload
        records.append(
            WheelMemberEvidence(
                name=info.orig_filename,
                size=info.file_size,
                compressed_size=info.compress_size,
                crc32=f"{info.CRC:08x}",
                timestamp=tuple(info.date_time),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
    records.sort(key=lambda item: item.name)
    return tuple(records), payload_by_name


def _one_dist_info_record(names: tuple[str, ...], record_name: str) -> str:
    suffix = f".dist-info/{record_name}"
    matches = [name for name in names if name.endswith(suffix)]
    if len(matches) != 1:
        raise WheelValidationError(f"wheel must contain exactly one {record_name} record")
    return matches[0]


def _parse_metadata_identity(payload: bytes) -> tuple[str, str]:
    try:
        payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise WheelValidationError("wheel must contain valid UTF-8 metadata") from exc
    try:
        message = BytesParser(policy=email.policy.default).parsebytes(payload)
    except (TypeError, ValueError) as exc:
        raise WheelValidationError("wheel metadata identity is invalid") from exc
    names = message.get_all("Name", [])
    versions = message.get_all("Version", [])
    if len(names) != 1 or len(versions) != 1:
        raise WheelValidationError("wheel metadata identity is invalid")
    raw_name = names[0].strip()
    version = versions[0].strip()
    if not raw_name or not version:
        raise WheelValidationError("wheel metadata identity is invalid")
    return _normalize_distribution(raw_name), version


def _normalize_distribution(value: str) -> str:
    if not isinstance(value, str):
        raise WheelValidationError("distribution name is invalid")
    normalized = _DISTRIBUTION_SEPARATOR.sub("-", value).lower()
    if not normalized or normalized.startswith("-") or normalized.endswith("-"):
        raise WheelValidationError("distribution name is invalid")
    return normalized


def _normalize_required_modules(required_modules: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(required_modules, tuple):
        raise WheelValidationError("required modules must be a tuple")
    normalized = tuple(sorted(set(required_modules)))
    for module in normalized:
        if not isinstance(module, str) or not module:
            raise WheelValidationError("required module name is invalid")
        if any(_MODULE_COMPONENT.fullmatch(part) is None for part in module.split(".")):
            raise WheelValidationError("required module name is invalid")
    return normalized


def _validate_required_modules(
    payload_by_name: dict[str, bytes],
    required_modules: tuple[str, ...],
) -> None:
    names = payload_by_name.keys()
    for module in required_modules:
        relative = module.replace(".", "/")
        if f"{relative}.py" not in names and f"{relative}/__init__.py" not in names:
            raise WheelValidationError("wheel is missing a required module")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: object) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
