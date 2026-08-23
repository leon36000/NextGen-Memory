from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from scripts.neon_migration_runner import (
    SCHEMA_DUMP_RESTRICT_KEY,
    SCHEMA_META_SQL,
    TABLE_LIST_SQL,
    CommandResult,
    ExitClass,
    MigrationRehearsalError,
    MigrationRehearsalReport,
    MigrationRunner,
    SemanticState,
    SubprocessCommandExecutor,
)


@dataclass(frozen=True, slots=True)
class Invocation:
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    timeout_seconds: int


class RecordingExecutor:
    def __init__(
        self,
        responder: Callable[[Invocation, int], CommandResult] | None = None,
    ) -> None:
        self.calls: list[Invocation] = []
        self._responder = responder or _stable_responder()

    def run(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_seconds: int,
    ) -> CommandResult:
        invocation = Invocation(tuple(argv), cwd, dict(env), timeout_seconds)
        self.calls.append(invocation)
        return self._responder(invocation, len(self.calls) - 1)


def _write_repository(root: Path) -> tuple[Path, tuple[str, ...]]:
    directory = root / "migrations" / "neon"
    directory.mkdir(parents=True, exist_ok=True)
    migration_ids = ("0001_alpha", "0002_beta")
    dependencies = ((), ("0001_alpha",))
    migrations: list[dict[str, object]] = []
    for migration_id, depends_on in zip(
        migration_ids,
        dependencies,
        strict=True,
    ):
        relative_path = f"migrations/neon/{migration_id}.sql"
        migration_path = root / relative_path
        migration_path.write_text(
            f"-- {migration_id}\nSELECT 1;\n",
            encoding="utf-8",
        )
        migrations.append(
            {
                "depends_on": list(depends_on),
                "id": migration_id,
                "path": relative_path,
                "sha256": hashlib.sha256(migration_path.read_bytes()).hexdigest(),
            }
        )
    manifest_path = directory / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "manifest_version": 1,
                "migrations": migrations,
                "schema": "nextgen-memory-neon-migrations",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path, migration_ids


def _stable_responder() -> Callable[[Invocation, int], CommandResult]:
    schema_meta_outputs = iter(
        (
            b'[{"schema_key":"alpha","schema_version":"1","metadata":{"b":2,"a":1}}]\n',
            (
                b'[ { "metadata": { "a": 1, "b": 2 }, '
                b'"schema_version": "1", "schema_key": "alpha" } ]\n'
            ),
        )
    )

    def respond(invocation: Invocation, _: int) -> CommandResult:
        argv = invocation.argv
        if argv[0] == "pg_dump":
            return CommandResult(0, b"CREATE SCHEMA ngm;\n", b"")
        if argv[0] != "psql":
            raise AssertionError(f"unexpected executable: {argv[0]}")
        if "--file" in argv:
            return CommandResult(0, b"", b"")
        command = argv[argv.index("--command") + 1]
        if command == TABLE_LIST_SQL:
            return CommandResult(0, b"schema_meta\nmemory_nodes\n", b"")
        if command == SCHEMA_META_SQL:
            return CommandResult(0, next(schema_meta_outputs), b"")
        if command == 'SELECT count(*) FROM ngm."memory_nodes";':
            return CommandResult(0, b"2\n", b"")
        if command == 'SELECT count(*) FROM ngm."schema_meta";':
            return CommandResult(0, b"1\n", b"")
        raise AssertionError(f"unexpected psql command: {command}")

    return respond


def _runner(
    root: Path,
    executor: RecordingExecutor | None = None,
) -> tuple[MigrationRunner, RecordingExecutor]:
    selected = executor or RecordingExecutor()
    runner = MigrationRunner(
        repository_root=root,
        executor=selected,
        environment={
            "PGDATABASE": "synthetic_rehearsal",
            "PGHOST": "127.0.0.1",
            "PGPASSWORD": "synthetic-password-never-emit",
            "PGPORT": "5432",
            "PGUSER": "postgres",
        },
        timeout_seconds=37,
    )
    return runner, selected


def test_plan_uses_only_the_validated_manifest_and_never_calls_database(
    tmp_path: Path,
) -> None:
    _, migration_ids = _write_repository(tmp_path)
    runner, executor = _runner(tmp_path)

    manifest = runner.plan()

    assert tuple(entry.id for entry in manifest.migrations) == migration_ids
    assert executor.calls == []


def test_rehearsal_applies_each_migration_twice_in_manifest_order(
    tmp_path: Path,
) -> None:
    _, migration_ids = _write_repository(tmp_path)
    runner, executor = _runner(tmp_path)

    report = runner.rehearse()

    migration_calls = [call for call in executor.calls if "--file" in call.argv]
    assert [Path(call.argv[-1]).stem for call in migration_calls] == [
        *migration_ids,
        *migration_ids,
    ]
    for call in migration_calls:
        assert call.argv[:6] == (
            "psql",
            "-X",
            "--no-psqlrc",
            "-v",
            "ON_ERROR_STOP=1",
            "--file",
        )
        assert call.timeout_seconds == 37
        assert call.cwd == tmp_path.resolve()
        assert "synthetic-password-never-emit" not in " ".join(call.argv)
        assert call.env["PGPASSWORD"] == "synthetic-password-never-emit"
    assert report.pass_count == 2
    assert report.migration_count == 2
    assert report.stable is True


def test_schema_dump_uses_repeatable_postgresql_18_restrict_key(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    runner, executor = _runner(tmp_path)

    runner.rehearse()

    dump_calls = [call for call in executor.calls if call.argv[0] == "pg_dump"]
    assert len(dump_calls) == 2
    assert dump_calls[0].argv == (
        "pg_dump",
        "--schema-only",
        "--no-owner",
        "--no-privileges",
        "--schema=ngm",
        "--format=plain",
        f"--restrict-key={SCHEMA_DUMP_RESTRICT_KEY}",
    )
    assert SCHEMA_DUMP_RESTRICT_KEY.isalnum()


def test_semantic_snapshot_is_order_stable_and_excludes_timestamps(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    runner, _ = _runner(tmp_path)

    report = runner.rehearse()

    expected_schema_hash = hashlib.sha256(b"CREATE SCHEMA ngm;\n").hexdigest()
    expected_meta_hash = hashlib.sha256(
        b'[{"metadata":{"a":1,"b":2},"schema_key":"alpha","schema_version":"1"}]'
    ).hexdigest()
    expected_state = SemanticState(
        schema_sha256=expected_schema_hash,
        table_counts=(("memory_nodes", 2), ("schema_meta", 1)),
        schema_meta_sha256=expected_meta_hash,
    )
    assert report.pass_one == expected_state
    assert report.pass_two == expected_state

    safe_json = report.to_safe_json()
    decoded = json.loads(safe_json)
    assert decoded["stable"] is True
    assert decoded["pass_one"]["table_counts"] == {
        "memory_nodes": 2,
        "schema_meta": 1,
    }
    assert "updated_at" not in safe_json
    assert "synthetic-password-never-emit" not in safe_json
    assert "SELECT " not in safe_json
    assert "CREATE SCHEMA" not in safe_json


def test_repeated_rehearsals_produce_identical_canonical_report(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    first, _ = _runner(tmp_path)
    second, _ = _runner(tmp_path)

    assert first.rehearse().to_safe_json() == second.rehearse().to_safe_json()


def test_report_is_frozen_and_slotted(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    runner, _ = _runner(tmp_path)

    report = runner.rehearse()

    assert isinstance(report, MigrationRehearsalReport)
    assert not hasattr(report, "__dict__")
    with pytest.raises(AttributeError):
        report.stable = False  # type: ignore[misc]


def test_migration_nonzero_exit_is_bounded_and_fail_fast(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    sentinel = "postgres://user:secret@private-host/database"

    def responder(invocation: Invocation, _: int) -> CommandResult:
        if "--file" in invocation.argv:
            migration = Path(invocation.argv[-1]).stem
            if migration == "0002_beta":
                return CommandResult(9, b"raw stdout", sentinel.encode())
            return CommandResult(0, b"", b"")
        raise AssertionError("state capture must not run after migration failure")

    executor = RecordingExecutor(responder)
    runner, _ = _runner(tmp_path, executor)

    with pytest.raises(MigrationRehearsalError) as exc_info:
        runner.rehearse()

    error = exc_info.value
    assert error.exit_class is ExitClass.NONZERO_EXIT
    assert error.migration_id == "0002_beta"
    assert error.migration_path == "migrations/neon/0002_beta.sql"
    assert [Path(call.argv[-1]).stem for call in executor.calls] == [
        "0001_alpha",
        "0002_beta",
    ]
    safe = error.to_safe_json()
    assert sentinel not in safe
    assert "secret" not in safe
    assert "raw stdout" not in safe
    assert "nonzero_exit" in safe


def test_missing_executable_is_classified_without_backend_text(tmp_path: Path) -> None:
    _write_repository(tmp_path)

    class MissingExecutor(RecordingExecutor):
        def run(self, *args: object, **kwargs: object) -> CommandResult:
            del args, kwargs
            raise FileNotFoundError("private runner path")

    runner, _ = _runner(tmp_path, MissingExecutor())

    with pytest.raises(MigrationRehearsalError) as exc_info:
        runner.rehearse()

    assert exc_info.value.exit_class is ExitClass.MISSING_EXECUTABLE
    assert "private runner path" not in exc_info.value.to_safe_json()


def test_timeout_is_classified_without_command_or_output(tmp_path: Path) -> None:
    _write_repository(tmp_path)

    class TimeoutExecutor(RecordingExecutor):
        def run(self, argv: Sequence[str], **kwargs: object) -> CommandResult:
            del kwargs
            raise subprocess.TimeoutExpired(argv, timeout=37, output=b"secret")

    runner, _ = _runner(tmp_path, TimeoutExecutor())

    with pytest.raises(MigrationRehearsalError) as exc_info:
        runner.rehearse()

    assert exc_info.value.exit_class is ExitClass.TIMEOUT
    safe = exc_info.value.to_safe_json()
    assert "secret" not in safe
    assert "psql" not in safe


def test_semantic_state_change_between_passes_fails_closed(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    dump_count = 0
    stable = _stable_responder()

    def responder(invocation: Invocation, index: int) -> CommandResult:
        nonlocal dump_count
        if invocation.argv[0] == "pg_dump":
            dump_count += 1
            return CommandResult(
                0,
                f"CREATE SCHEMA ngm; -- pass {dump_count}\n".encode(),
                b"",
            )
        return stable(invocation, index)

    runner, _ = _runner(tmp_path, RecordingExecutor(responder))

    with pytest.raises(
        MigrationRehearsalError,
        match="semantic state changed",
    ) as exc_info:
        runner.rehearse()

    assert exc_info.value.exit_class is ExitClass.SEMANTIC_STATE_CHANGED
    assert exc_info.value.migration_id is None


def test_invalid_table_name_output_fails_closed(tmp_path: Path) -> None:
    _write_repository(tmp_path)
    stable = _stable_responder()

    def responder(invocation: Invocation, index: int) -> CommandResult:
        if (
            invocation.argv[0] == "psql"
            and "--command" in invocation.argv
            and invocation.argv[invocation.argv.index("--command") + 1]
            == TABLE_LIST_SQL
        ):
            return CommandResult(0, b"memory_nodes\nevil;drop table\n", b"")
        return stable(invocation, index)

    runner, _ = _runner(tmp_path, RecordingExecutor(responder))

    with pytest.raises(MigrationRehearsalError) as exc_info:
        runner.rehearse()

    assert exc_info.value.exit_class is ExitClass.INVALID_OUTPUT
    assert "evil" not in exc_info.value.to_safe_json()


def test_invalid_count_and_schema_meta_outputs_fail_closed(tmp_path: Path) -> None:
    _write_repository(tmp_path)

    def invalid_count(invocation: Invocation, _: int) -> CommandResult:
        if "--file" in invocation.argv:
            return CommandResult(0, b"", b"")
        if invocation.argv[0] == "pg_dump":
            return CommandResult(0, b"schema", b"")
        command = invocation.argv[invocation.argv.index("--command") + 1]
        if command == TABLE_LIST_SQL:
            return CommandResult(0, b"memory_nodes\n", b"")
        return CommandResult(0, b"-1\n", b"")

    runner, _ = _runner(tmp_path, RecordingExecutor(invalid_count))
    with pytest.raises(MigrationRehearsalError) as count_error:
        runner.rehearse()
    assert count_error.value.exit_class is ExitClass.INVALID_OUTPUT

    stable = _stable_responder()

    def invalid_meta(invocation: Invocation, index: int) -> CommandResult:
        if (
            invocation.argv[0] == "psql"
            and "--command" in invocation.argv
            and invocation.argv[invocation.argv.index("--command") + 1]
            == SCHEMA_META_SQL
        ):
            return CommandResult(0, b"not-json\n", b"")
        return stable(invocation, index)

    runner, _ = _runner(tmp_path, RecordingExecutor(invalid_meta))
    with pytest.raises(MigrationRehearsalError) as meta_error:
        runner.rehearse()
    assert meta_error.value.exit_class is ExitClass.INVALID_OUTPUT


def test_query_commands_are_static_and_table_counts_quote_validated_names(
    tmp_path: Path,
) -> None:
    _write_repository(tmp_path)
    runner, executor = _runner(tmp_path)

    runner.rehearse()

    query_calls = [
        call for call in executor.calls
        if call.argv[0] == "psql" and "--command" in call.argv
    ]
    assert query_calls
    for call in query_calls:
        assert call.argv[:8] == (
            "psql",
            "-X",
            "--no-psqlrc",
            "--tuples-only",
            "--no-align",
            "--quiet",
            "-v",
            "ON_ERROR_STOP=1",
        )
        assert call.argv[8] == "--command"
        assert "synthetic-password-never-emit" not in " ".join(call.argv)
    count_commands = {
        call.argv[-1]
        for call in query_calls
        if call.argv[-1].startswith("SELECT count(*)")
    }
    assert count_commands == {
        'SELECT count(*) FROM ngm."memory_nodes";',
        'SELECT count(*) FROM ngm."schema_meta";',
    }


def test_subprocess_executor_never_uses_shell_and_captures_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: Sequence[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured["argv"] = tuple(argv)
        captured.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, stdout=b"safe", stderr=b"hidden")

    monkeypatch.setattr(subprocess, "run", fake_run)
    executor = SubprocessCommandExecutor()

    result = executor.run(
        ("psql", "--version"),
        cwd=tmp_path,
        env={"PGPASSWORD": "secret"},
        timeout_seconds=12,
    )

    assert result == CommandResult(0, b"safe", b"hidden")
    assert captured["argv"] == ("psql", "--version")
    assert captured["shell"] is False
    assert captured["capture_output"] is True
    assert captured["check"] is False
    assert captured["cwd"] == tmp_path
    assert captured["env"] == {"PGPASSWORD": "secret"}
    assert captured["timeout"] == 12
