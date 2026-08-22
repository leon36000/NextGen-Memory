"""Deterministic, privacy-safe two-pass Neon migration rehearsal runner."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from scripts.neon_migration_manifest import MigrationManifest, load_manifest

SCHEMA_DUMP_RESTRICT_KEY = "NextGenMemoryMigrationRehearsalV1"

TABLE_LIST_SQL = (
    "SELECT tablename FROM pg_catalog.pg_tables "
    "WHERE schemaname = 'ngm' ORDER BY tablename;"
)

SCHEMA_META_SQL = """
SELECT COALESCE(
    jsonb_agg(
        jsonb_build_object(
            'schema_key', schema_key,
            'schema_version', schema_version,
            'metadata', metadata
        )
        ORDER BY schema_key
    ),
    '[]'::jsonb
)::text
FROM ngm.schema_meta;
""".strip()

_TABLE_NAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_]*$")
_NONNEGATIVE_INTEGER_PATTERN = re.compile(r"^(0|[1-9][0-9]*)$")
_REQUIRED_ENVIRONMENT_KEYS = frozenset(
    {"PGDATABASE", "PGHOST", "PGPASSWORD", "PGPORT", "PGUSER"}
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Captured process result without interpretation."""

    returncode: int
    stdout: bytes
    stderr: bytes


class CommandExecutor(Protocol):
    """Injectable argv-only process boundary."""

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: int,
    ) -> CommandResult:
        """Execute one command without a shell."""
        ...


class SubprocessCommandExecutor:
    """Production executor using an explicit argv vector and captured output."""

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: int,
    ) -> CommandResult:
        completed = subprocess.run(
            tuple(argv),
            cwd=cwd,
            env=dict(env),
            timeout=timeout_seconds,
            shell=False,
            capture_output=True,
            check=False,
        )
        return CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


class ExitClass(str, Enum):
    """Bounded failure classes safe for logs and CI artifacts."""

    NONZERO_EXIT = "nonzero_exit"
    MISSING_EXECUTABLE = "missing_executable"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"
    SEMANTIC_STATE_CHANGED = "semantic_state_changed"


class MigrationRehearsalError(RuntimeError):
    """Privacy-safe migration rehearsal failure."""

    def __init__(
        self,
        exit_class: ExitClass,
        *,
        message: str,
        migration_id: str | None = None,
        migration_path: str | None = None,
        pass_number: int | None = None,
    ) -> None:
        super().__init__(message)
        self.exit_class = exit_class
        self.migration_id = migration_id
        self.migration_path = migration_path
        self.pass_number = pass_number

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "exit_class": self.exit_class.value,
            "migration_id": self.migration_id,
            "migration_path": self.migration_path,
            "pass_number": self.pass_number,
        }

    def to_safe_json(self) -> str:
        return _canonical_json(self.to_safe_dict())


@dataclass(frozen=True, slots=True)
class SemanticState:
    """Timestamp-free semantic state after one complete migration pass."""

    schema_sha256: str
    table_counts: tuple[tuple[str, int], ...]
    schema_meta_sha256: str

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "schema_meta_sha256": self.schema_meta_sha256,
            "schema_sha256": self.schema_sha256,
            "table_counts": dict(self.table_counts),
        }


@dataclass(frozen=True, slots=True)
class MigrationRehearsalReport:
    """Canonical two-pass result containing no SQL or connection material."""

    manifest_path: str
    manifest_plan_hash: str
    migration_count: int
    pass_count: int
    pass_one: SemanticState
    pass_two: SemanticState
    stable: bool

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "manifest_path": self.manifest_path,
            "manifest_plan_hash": self.manifest_plan_hash,
            "migration_count": self.migration_count,
            "pass_count": self.pass_count,
            "pass_one": self.pass_one.to_safe_dict(),
            "pass_two": self.pass_two.to_safe_dict(),
            "stable": self.stable,
        }

    def to_safe_json(self) -> str:
        return _canonical_json(self.to_safe_dict())


class MigrationRunner:
    """Apply the canonical manifest twice and compare semantic state."""

    def __init__(
        self,
        *,
        repository_root: Path,
        executor: CommandExecutor,
        environment: Mapping[str, str],
        timeout_seconds: int = 120,
    ) -> None:
        root = Path(repository_root).resolve()
        if not root.is_dir():
            raise ValueError("repository_root must be a directory")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive integer")
        normalized_environment = dict(environment)
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in normalized_environment.items()
        ):
            raise ValueError("environment must contain string keys and values")
        missing_environment = _REQUIRED_ENVIRONMENT_KEYS.difference(
            normalized_environment
        )
        if missing_environment:
            raise ValueError("environment is missing required PostgreSQL variables")
        if any(not normalized_environment[key] for key in _REQUIRED_ENVIRONMENT_KEYS):
            raise ValueError("required PostgreSQL environment values must not be empty")

        self._repository_root = root
        self._executor = executor
        self._environment = normalized_environment
        self._timeout_seconds = timeout_seconds

    def plan(self) -> MigrationManifest:
        """Validate and return the canonical manifest without database access."""

        return load_manifest(self._repository_root)

    def rehearse(self) -> MigrationRehearsalReport:
        """Apply two complete passes and require exact semantic stability."""

        manifest = self.plan()
        states: list[SemanticState] = []
        for pass_number in (1, 2):
            for migration in manifest.migrations:
                self._apply_migration(
                    migration_id=migration.id,
                    migration_path=migration.path,
                    pass_number=pass_number,
                )
            states.append(self._capture_semantic_state(pass_number=pass_number))

        pass_one, pass_two = states
        if pass_one != pass_two:
            raise MigrationRehearsalError(
                ExitClass.SEMANTIC_STATE_CHANGED,
                message="semantic state changed between migration passes",
                pass_number=2,
            )
        return MigrationRehearsalReport(
            manifest_path=manifest.manifest_path,
            manifest_plan_hash=manifest.plan_hash,
            migration_count=len(manifest.migrations),
            pass_count=2,
            pass_one=pass_one,
            pass_two=pass_two,
            stable=True,
        )

    def _apply_migration(
        self,
        *,
        migration_id: str,
        migration_path: str,
        pass_number: int,
    ) -> None:
        absolute_path = (self._repository_root / migration_path).resolve(strict=True)
        self._run_checked(
            (
                "psql",
                "-X",
                "--no-psqlrc",
                "-v",
                "ON_ERROR_STOP=1",
                "--file",
                str(absolute_path),
            ),
            migration_id=migration_id,
            migration_path=migration_path,
            pass_number=pass_number,
        )

    def _capture_semantic_state(self, *, pass_number: int) -> SemanticState:
        schema_dump = self._run_checked(
            (
                "pg_dump",
                "--schema-only",
                "--no-owner",
                "--no-privileges",
                "--schema=ngm",
                "--format=plain",
                f"--restrict-key={SCHEMA_DUMP_RESTRICT_KEY}",
            ),
            pass_number=pass_number,
        ).stdout
        schema_sha256 = hashlib.sha256(schema_dump).hexdigest()

        table_list_output = self._run_query(
            TABLE_LIST_SQL,
            pass_number=pass_number,
        )
        table_names = _parse_table_names(table_list_output, pass_number=pass_number)
        table_counts: list[tuple[str, int]] = []
        for table_name in table_names:
            count_output = self._run_query(
                f'SELECT count(*) FROM ngm."{table_name}";',
                pass_number=pass_number,
            )
            table_counts.append(
                (
                    table_name,
                    _parse_nonnegative_count(
                        count_output,
                        pass_number=pass_number,
                    ),
                )
            )

        schema_meta_output = self._run_query(
            SCHEMA_META_SQL,
            pass_number=pass_number,
        )
        schema_meta_sha256 = hashlib.sha256(
            _canonical_schema_meta(schema_meta_output, pass_number=pass_number)
        ).hexdigest()
        return SemanticState(
            schema_sha256=schema_sha256,
            table_counts=tuple(table_counts),
            schema_meta_sha256=schema_meta_sha256,
        )

    def _run_query(self, sql: str, *, pass_number: int) -> bytes:
        return self._run_checked(
            (
                "psql",
                "-X",
                "--no-psqlrc",
                "--tuples-only",
                "--no-align",
                "--quiet",
                "-v",
                "ON_ERROR_STOP=1",
                "--command",
                sql,
            ),
            pass_number=pass_number,
        ).stdout

    def _run_checked(
        self,
        argv: Sequence[str],
        *,
        migration_id: str | None = None,
        migration_path: str | None = None,
        pass_number: int | None = None,
    ) -> CommandResult:
        try:
            result = self._executor.run(
                tuple(argv),
                cwd=self._repository_root,
                env=self._environment,
                timeout_seconds=self._timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise MigrationRehearsalError(
                ExitClass.MISSING_EXECUTABLE,
                message="required PostgreSQL executable is unavailable",
                migration_id=migration_id,
                migration_path=migration_path,
                pass_number=pass_number,
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise MigrationRehearsalError(
                ExitClass.TIMEOUT,
                message="PostgreSQL command exceeded the rehearsal timeout",
                migration_id=migration_id,
                migration_path=migration_path,
                pass_number=pass_number,
            ) from exc
        if result.returncode != 0:
            raise MigrationRehearsalError(
                ExitClass.NONZERO_EXIT,
                message="PostgreSQL command returned a nonzero exit status",
                migration_id=migration_id,
                migration_path=migration_path,
                pass_number=pass_number,
            )
        return result


def _parse_table_names(output: bytes, *, pass_number: int) -> tuple[str, ...]:
    text = _decode_output(output, pass_number=pass_number)
    names = tuple(line.strip() for line in text.splitlines() if line.strip())
    if len(names) != len(set(names)) or any(
        _TABLE_NAME_PATTERN.fullmatch(name) is None for name in names
    ):
        raise MigrationRehearsalError(
            ExitClass.INVALID_OUTPUT,
            message="PostgreSQL table list output is invalid",
            pass_number=pass_number,
        )
    return tuple(sorted(names))


def _parse_nonnegative_count(output: bytes, *, pass_number: int) -> int:
    text = _decode_output(output, pass_number=pass_number).strip()
    if _NONNEGATIVE_INTEGER_PATTERN.fullmatch(text) is None:
        raise MigrationRehearsalError(
            ExitClass.INVALID_OUTPUT,
            message="PostgreSQL table count output is invalid",
            pass_number=pass_number,
        )
    return int(text)


def _canonical_schema_meta(output: bytes, *, pass_number: int) -> bytes:
    text = _decode_output(output, pass_number=pass_number).strip()
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise MigrationRehearsalError(
            ExitClass.INVALID_OUTPUT,
            message="schema metadata output is not valid JSON",
            pass_number=pass_number,
        ) from exc
    if not isinstance(document, list):
        raise MigrationRehearsalError(
            ExitClass.INVALID_OUTPUT,
            message="schema metadata output must be an array",
            pass_number=pass_number,
        )

    normalized: list[dict[str, object]] = []
    seen_keys: set[str] = set()
    for item in document:
        if not isinstance(item, dict) or set(item) != {
            "metadata",
            "schema_key",
            "schema_version",
        }:
            raise MigrationRehearsalError(
                ExitClass.INVALID_OUTPUT,
                message="schema metadata row has an invalid shape",
                pass_number=pass_number,
            )
        schema_key = item["schema_key"]
        schema_version = item["schema_version"]
        metadata = item["metadata"]
        if (
            not isinstance(schema_key, str)
            or not schema_key
            or schema_key in seen_keys
            or not isinstance(schema_version, str)
            or not schema_version
            or not isinstance(metadata, dict)
        ):
            raise MigrationRehearsalError(
                ExitClass.INVALID_OUTPUT,
                message="schema metadata row contains invalid values",
                pass_number=pass_number,
            )
        seen_keys.add(schema_key)
        normalized.append(
            {
                "metadata": metadata,
                "schema_key": schema_key,
                "schema_version": schema_version,
            }
        )
    normalized.sort(key=lambda item: str(item["schema_key"]))
    return _canonical_json(normalized).encode("utf-8")


def _decode_output(output: bytes, *, pass_number: int) -> str:
    try:
        return output.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise MigrationRehearsalError(
            ExitClass.INVALID_OUTPUT,
            message="PostgreSQL command output is not valid UTF-8",
            pass_number=pass_number,
        ) from exc


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def main() -> int:
    """Run the rehearsal using PostgreSQL connection variables from the environment."""

    import os

    environment = {
        key: os.environ.get(key, "") for key in sorted(_REQUIRED_ENVIRONMENT_KEYS)
    }
    runner = MigrationRunner(
        repository_root=Path.cwd(),
        executor=SubprocessCommandExecutor(),
        environment=environment,
    )
    try:
        report = runner.rehearse()
    except MigrationRehearsalError as exc:
        print(exc.to_safe_json(), file=sys.stderr)
        return 1
    print(report.to_safe_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
