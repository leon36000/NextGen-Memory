"""Strict, dependency-free parser for the canonical Neon migration manifest."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_MANIFEST_SCHEMA = "nextgen-memory-neon-migrations"
_MANIFEST_VERSION = 1
_MANIFEST_RELATIVE_PATH = "migrations/neon/manifest.json"
_TOP_LEVEL_FIELDS = frozenset({"manifest_version", "schema", "migrations"})
_ENTRY_FIELDS = frozenset({"id", "path", "sha256", "depends_on"})
_ID_PATTERN = re.compile(r"^[0-9]{4}_[a-z0-9_]+$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ManifestError(ValueError):
    """The migration manifest or repository migration set is unsafe or invalid."""


@dataclass(frozen=True, slots=True)
class MigrationEntry:
    """One immutable migration-plan entry."""

    id: str
    path: str
    sha256: str
    depends_on: tuple[str, ...]

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "depends_on": list(self.depends_on),
            "id": self.id,
            "path": self.path,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class MigrationManifest:
    """Validated canonical migration order and privacy-safe plan identity."""

    manifest_path: str
    manifest_version: int
    schema: str
    migrations: tuple[MigrationEntry, ...]
    plan_hash: str

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "manifest_path": self.manifest_path,
            "manifest_version": self.manifest_version,
            "migration_count": len(self.migrations),
            "migrations": [entry.to_safe_dict() for entry in self.migrations],
            "plan_hash": self.plan_hash,
            "schema": self.schema,
        }

    def to_safe_json(self) -> str:
        return _canonical_json(self.to_safe_dict())


def load_manifest(repository_root: Path) -> MigrationManifest:
    """Load and fully validate the one canonical manifest under a repository root."""

    root = Path(repository_root).resolve()
    neon_directory = root / "migrations" / "neon"
    candidates = sorted(neon_directory.glob("*manifest*.json"))
    if (
        len(candidates) != 1
        or candidates[0].name != "manifest.json"
        or candidates[0].is_symlink()
        or not candidates[0].is_file()
    ):
        raise ManifestError(
            "expected exactly one canonical manifest at migrations/neon/manifest.json"
        )

    manifest_path = candidates[0]
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        document = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("canonical manifest must be valid UTF-8 JSON") from exc

    if not isinstance(document, dict):
        raise ManifestError("manifest top level must be an object")
    if set(document) != _TOP_LEVEL_FIELDS:
        raise ManifestError("manifest top level must contain the exact fields")
    if (
        isinstance(document["manifest_version"], bool)
        or document["manifest_version"] != _MANIFEST_VERSION
    ):
        raise ManifestError("manifest_version must be the integer 1")
    if document["schema"] != _MANIFEST_SCHEMA:
        raise ManifestError(f"schema must be {_MANIFEST_SCHEMA}")
    raw_migrations = document["migrations"]
    if not isinstance(raw_migrations, list):
        raise ManifestError("migrations must be an ordered array")

    canonical_raw = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if raw != canonical_raw:
        raise ManifestError("canonical manifest JSON formatting is not deterministic")

    entries = tuple(
        _parse_entry(raw_entry, index=index)
        for index, raw_entry in enumerate(raw_migrations)
    )
    _validate_unique_identity(entries)
    _validate_dependencies(entries)
    _validate_repository_files(root, neon_directory, entries)

    plan_payload: dict[str, object] = {
        "manifest_path": _MANIFEST_RELATIVE_PATH,
        "manifest_version": _MANIFEST_VERSION,
        "migration_count": len(entries),
        "migrations": [entry.to_safe_dict() for entry in entries],
        "schema": _MANIFEST_SCHEMA,
    }
    plan_hash = hashlib.sha256(_canonical_json(plan_payload).encode("utf-8")).hexdigest()
    return MigrationManifest(
        manifest_path=_MANIFEST_RELATIVE_PATH,
        manifest_version=_MANIFEST_VERSION,
        schema=_MANIFEST_SCHEMA,
        migrations=entries,
        plan_hash=plan_hash,
    )


def _parse_entry(raw_entry: object, *, index: int) -> MigrationEntry:
    if not isinstance(raw_entry, dict):
        raise ManifestError(f"migration entry {index} must be an object")
    if set(raw_entry) != _ENTRY_FIELDS:
        raise ManifestError(f"migration entry {index} must contain the exact fields")

    migration_id = raw_entry["id"]
    path = raw_entry["path"]
    sha256 = raw_entry["sha256"]
    depends_on = raw_entry["depends_on"]
    if not isinstance(migration_id, str) or _ID_PATTERN.fullmatch(migration_id) is None:
        raise ManifestError(f"migration id at index {index} is invalid")
    if not isinstance(path, str) or not _is_safe_migration_path(path):
        raise ManifestError(
            f"migration path at index {index} must be a safe repository-relative SQL path"
        )
    if PurePosixPath(path).stem != migration_id:
        raise ManifestError("migration id must match filename stem")
    if not isinstance(sha256, str) or _SHA256_PATTERN.fullmatch(sha256) is None:
        raise ManifestError(f"sha256 at index {index} must be lowercase SHA-256 hex")
    if not isinstance(depends_on, list) or any(
        not isinstance(dependency, str) for dependency in depends_on
    ):
        raise ManifestError(f"depends_on at index {index} must be an array of strings")

    return MigrationEntry(
        id=migration_id,
        path=path,
        sha256=sha256,
        depends_on=tuple(depends_on),
    )


def _is_safe_migration_path(path: str) -> bool:
    if "\\" in path:
        return False
    pure_path = PurePosixPath(path)
    return (
        not pure_path.is_absolute()
        and pure_path.parts[:2] == ("migrations", "neon")
        and len(pure_path.parts) == 3
        and ".." not in pure_path.parts
        and "." not in pure_path.parts
        and pure_path.suffix == ".sql"
        and bool(pure_path.name)
        and pure_path.as_posix() == path
    )


def _validate_unique_identity(entries: tuple[MigrationEntry, ...]) -> None:
    ids = [entry.id for entry in entries]
    paths = [entry.path for entry in entries]
    if len(ids) != len(set(ids)):
        raise ManifestError("manifest contains duplicate migration IDs")
    if len(paths) != len(set(paths)):
        raise ManifestError("manifest contains duplicate migration paths")


def _validate_dependencies(entries: tuple[MigrationEntry, ...]) -> None:
    positions = {entry.id: index for index, entry in enumerate(entries)}
    for index, entry in enumerate(entries):
        if len(entry.depends_on) != len(set(entry.depends_on)):
            raise ManifestError(f"migration {entry.id} contains a duplicate dependency")
        for dependency in entry.depends_on:
            if dependency == entry.id:
                raise ManifestError(f"migration {entry.id} contains a self dependency")
            if dependency not in positions:
                raise ManifestError(
                    f"migration {entry.id} references an unknown dependency"
                )
            if positions[dependency] >= index:
                raise ManifestError(
                    f"migration {entry.id} dependency must be an earlier migration"
                )


def _validate_repository_files(
    root: Path,
    neon_directory: Path,
    entries: tuple[MigrationEntry, ...],
) -> None:
    repository_sql = {
        path.relative_to(root).as_posix()
        for path in neon_directory.glob("*.sql")
    }
    manifest_sql = {entry.path for entry in entries}
    if repository_sql != manifest_sql or len(manifest_sql) != len(entries):
        raise ManifestError(
            "manifest must represent every migrations/neon SQL file exactly once"
        )

    for entry in entries:
        migration_path = root / entry.path
        if migration_path.is_symlink() or not migration_path.is_file():
            raise ManifestError(
                f"migration {entry.id} must resolve to a regular non-symlink file"
            )
        try:
            resolved = migration_path.resolve(strict=True)
            resolved.relative_to(neon_directory.resolve(strict=True))
        except (OSError, ValueError) as exc:
            raise ManifestError(
                f"migration {entry.id} escapes the Neon migration directory"
            ) from exc
        actual_hash = hashlib.sha256(migration_path.read_bytes()).hexdigest()
        if actual_hash != entry.sha256:
            raise ManifestError(f"migration {entry.id} content hash mismatch")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def main() -> int:
    """Print the validated privacy-safe plan for the current repository."""

    manifest = load_manifest(Path.cwd())
    print(manifest.to_safe_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
