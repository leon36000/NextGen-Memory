from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.neon_migration_manifest import (
    ManifestError,
    MigrationManifest,
    load_manifest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_IDS = (
    "0001_memory_moe_kernel",
    "0002_core_idempotency",
    "0003_research_sources_seed",
    "0005_causal_credit_feedback",
    "0006_action_memory_usage_events",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_migration(root: Path, migration_id: str, content: bytes | None = None) -> str:
    directory = root / "migrations" / "neon"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{migration_id}.sql"
    path.write_bytes(content or f"-- {migration_id}\nSELECT 1;\n".encode())
    return _sha256(path)


def _entry(
    migration_id: str,
    sha256: str,
    *,
    depends_on: list[str] | None = None,
    path: str | None = None,
) -> dict[str, object]:
    return {
        "id": migration_id,
        "path": path or f"migrations/neon/{migration_id}.sql",
        "sha256": sha256,
        "depends_on": depends_on or [],
    }


def _write_manifest(root: Path, migrations: list[dict[str, object]]) -> Path:
    path = root / "migrations" / "neon" / "manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "schema": "nextgen-memory-neon-migrations",
                "migrations": migrations,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _valid_repository(root: Path) -> tuple[Path, list[dict[str, object]]]:
    first = "0001_alpha"
    second = "0002_beta"
    first_hash = _write_migration(root, first)
    second_hash = _write_migration(root, second)
    entries = [
        _entry(first, first_hash),
        _entry(second, second_hash, depends_on=[first]),
    ]
    return _write_manifest(root, entries), entries


def test_current_manifest_covers_every_sql_file_exactly_once() -> None:
    manifest = load_manifest(REPOSITORY_ROOT)

    assert isinstance(manifest, MigrationManifest)
    assert manifest.manifest_version == 1
    assert manifest.schema == "nextgen-memory-neon-migrations"
    assert tuple(entry.id for entry in manifest.migrations) == EXPECTED_IDS
    assert "0004" not in " ".join(entry.id for entry in manifest.migrations)

    sql_paths = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (REPOSITORY_ROOT / "migrations" / "neon").glob("*.sql")
    }
    manifest_paths = {entry.path for entry in manifest.migrations}
    assert manifest_paths == sql_paths
    assert len(manifest_paths) == len(manifest.migrations)

    for entry in manifest.migrations:
        path = REPOSITORY_ROOT / entry.path
        assert entry.id == path.stem
        assert entry.sha256 == _sha256(path)


def test_current_dependency_order_is_explicit_and_backward_only() -> None:
    manifest = load_manifest(REPOSITORY_ROOT)
    positions = {entry.id: index for index, entry in enumerate(manifest.migrations)}

    assert manifest.migrations[0].depends_on == ()
    for entry in manifest.migrations:
        assert len(entry.depends_on) == len(set(entry.depends_on))
        assert all(positions[dependency] < positions[entry.id] for dependency in entry.depends_on)


def test_safe_plan_is_deterministic_and_contains_no_sql_or_connection_data() -> None:
    manifest = load_manifest(REPOSITORY_ROOT)

    first = manifest.to_safe_json()
    second = load_manifest(REPOSITORY_ROOT).to_safe_json()

    assert first == second
    decoded = json.loads(first)
    assert decoded["manifest_path"] == "migrations/neon/manifest.json"
    assert decoded["migration_count"] == len(EXPECTED_IDS)
    assert decoded["plan_hash"] == manifest.plan_hash
    assert len(decoded["plan_hash"]) == 64
    assert "CREATE TABLE" not in first
    assert "SELECT " not in first
    assert "password" not in first.lower()
    assert "dsn" not in first.lower()
    assert "connection" not in first.lower()


def test_manifest_is_canonical_json_and_round_trips_without_reordering() -> None:
    manifest_path = REPOSITORY_ROOT / "migrations" / "neon" / "manifest.json"
    raw = manifest_path.read_text(encoding="utf-8")
    decoded = json.loads(raw)

    assert raw.endswith("\n")
    assert raw == json.dumps(decoded, indent=2, sort_keys=True) + "\n"
    assert [migration["id"] for migration in decoded["migrations"]] == list(EXPECTED_IDS)


def test_missing_manifest_fails_closed(tmp_path: Path) -> None:
    _write_migration(tmp_path, "0001_alpha")

    with pytest.raises(ManifestError, match="exactly one canonical manifest"):
        load_manifest(tmp_path)


def test_duplicate_manifest_candidates_fail_closed(tmp_path: Path) -> None:
    manifest, _ = _valid_repository(tmp_path)
    (manifest.parent / "migration-manifest.json").write_text(
        manifest.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError, match="exactly one canonical manifest"):
        load_manifest(tmp_path)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"manifest_version": 1, "schema": "nextgen-memory-neon-migrations"},
        {
            "manifest_version": True,
            "schema": "nextgen-memory-neon-migrations",
            "migrations": [],
        },
        {
            "manifest_version": 1,
            "schema": "wrong-schema",
            "migrations": [],
        },
        {
            "manifest_version": 1,
            "schema": "nextgen-memory-neon-migrations",
            "migrations": [],
            "unexpected": True,
        },
    ],
)
def test_malformed_top_level_schema_fails_closed(
    tmp_path: Path,
    payload: object,
) -> None:
    directory = tmp_path / "migrations" / "neon"
    directory.mkdir(parents=True)
    (directory / "manifest.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(ManifestError):
        load_manifest(tmp_path)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda entries: entries[0].update({"unexpected": True}),
            "exact fields",
        ),
        (
            lambda entries: entries[0].update({"id": "UPPERCASE"}),
            "migration id",
        ),
        (
            lambda entries: entries[0].update({"sha256": "0" * 63}),
            "sha256",
        ),
        (
            lambda entries: entries[0].update({"depends_on": "0000_root"}),
            "depends_on",
        ),
        (
            lambda entries: entries[0].update({"path": "/tmp/escape.sql"}),
            "safe repository-relative",
        ),
        (
            lambda entries: entries[0].update({"path": "migrations/neon/../escape.sql"}),
            "safe repository-relative",
        ),
        (
            lambda entries: entries[0].update({"path": "migrations\\neon\\0001_alpha.sql"}),
            "safe repository-relative",
        ),
        (
            lambda entries: entries[0].update({"path": "migrations/neon/0001_alpha.txt"}),
            "migration path",
        ),
    ],
)
def test_malformed_entry_fails_closed(
    tmp_path: Path,
    mutator: object,
    message: str,
) -> None:
    _, entries = _valid_repository(tmp_path)
    mutator(entries)  # type: ignore[operator]
    _write_manifest(tmp_path, entries)

    with pytest.raises(ManifestError, match=message):
        load_manifest(tmp_path)


def test_id_must_match_filename_stem(tmp_path: Path) -> None:
    _, entries = _valid_repository(tmp_path)
    entries[0]["id"] = "0001_different"
    _write_manifest(tmp_path, entries)

    with pytest.raises(ManifestError, match="match filename stem"):
        load_manifest(tmp_path)


def test_duplicate_ids_and_paths_fail_closed(tmp_path: Path) -> None:
    _, entries = _valid_repository(tmp_path)
    entries[1]["id"] = entries[0]["id"]
    entries[1]["path"] = entries[0]["path"]
    _write_manifest(tmp_path, entries)

    with pytest.raises(ManifestError, match="duplicate"):
        load_manifest(tmp_path)


def test_missing_and_unknown_sql_files_fail_closed(tmp_path: Path) -> None:
    _, entries = _valid_repository(tmp_path)
    entries.pop()
    entries.append(
        _entry(
            "0003_unknown",
            "0" * 64,
            depends_on=["0001_alpha"],
        )
    )
    _write_manifest(tmp_path, entries)

    with pytest.raises(ManifestError, match="exactly once"):
        load_manifest(tmp_path)


def test_content_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    _, entries = _valid_repository(tmp_path)
    path = tmp_path / str(entries[0]["path"])
    path.write_text("-- mutated after manifest\n", encoding="utf-8")

    with pytest.raises(ManifestError, match="content hash mismatch"):
        load_manifest(tmp_path)


@pytest.mark.parametrize(
    ("dependency_builder", "message"),
    [
        (lambda entries: [str(entries[0]["id"])], "self dependency"),
        (lambda entries: [str(entries[1]["id"])], "earlier migration"),
        (lambda entries: ["9999_unknown"], "unknown dependency"),
        (
            lambda entries: [str(entries[0]["id"]), str(entries[0]["id"])],
            "duplicate dependency",
        ),
    ],
)
def test_invalid_dependencies_fail_closed(
    tmp_path: Path,
    dependency_builder: object,
    message: str,
) -> None:
    _, entries = _valid_repository(tmp_path)
    entries[0]["depends_on"] = dependency_builder(entries)  # type: ignore[operator]
    _write_manifest(tmp_path, entries)

    with pytest.raises(ManifestError, match=message):
        load_manifest(tmp_path)


def test_future_dependency_fails_even_when_graph_would_be_acyclic(tmp_path: Path) -> None:
    _, entries = _valid_repository(tmp_path)
    entries[0]["depends_on"] = [entries[1]["id"]]
    _write_manifest(tmp_path, entries)

    with pytest.raises(ManifestError, match="earlier migration"):
        load_manifest(tmp_path)


def test_symlink_migration_is_rejected(tmp_path: Path) -> None:
    directory = tmp_path / "migrations" / "neon"
    directory.mkdir(parents=True)
    outside = tmp_path / "outside.sql"
    outside.write_text("SELECT 1;\n", encoding="utf-8")
    migration = directory / "0001_alpha.sql"
    try:
        migration.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    _write_manifest(
        tmp_path,
        [_entry("0001_alpha", hashlib.sha256(outside.read_bytes()).hexdigest())],
    )

    with pytest.raises(ManifestError, match="regular non-symlink file"):
        load_manifest(tmp_path)


def test_plan_hash_changes_when_order_or_dependency_changes(tmp_path: Path) -> None:
    _, entries = _valid_repository(tmp_path)
    original = load_manifest(tmp_path).plan_hash

    entries[1]["depends_on"] = []
    _write_manifest(tmp_path, entries)
    changed = load_manifest(tmp_path).plan_hash

    assert changed != original
