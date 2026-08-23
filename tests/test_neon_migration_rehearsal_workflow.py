from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/neon-migration-rehearsal.yml")
EXPECTED_PATH_FILTERS = {
    ".github/workflows/neon-migration-rehearsal.yml",
    "migrations/neon/**",
    "scripts/neon_migration_manifest.py",
    "scripts/neon_migration_runner.py",
    "tests/test_neon_migration_manifest.py",
    "tests/test_neon_migration_rehearsal_workflow.py",
    "tests/test_neon_migration_runner.py",
}


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_exists_with_read_only_permissions_and_exact_path_filters() -> None:
    text = _workflow_text()

    assert "pull_request:" in text
    assert "contents: read" in text
    assert "contents: write" not in text
    assert "workflow_dispatch:" not in text
    assert "push:" not in text

    paths: set[str] = set()
    in_paths = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == "paths:":
            in_paths = True
            continue
        if in_paths and stripped.startswith("- "):
            paths.add(stripped[2:].strip('"\''))
            continue
        if in_paths and stripped and not line.startswith("      "):
            break
    assert paths == EXPECTED_PATH_FILTERS


def test_workflow_uses_pinned_pgvector_postgresql_18_without_repository_secret() -> None:
    text = _workflow_text()

    assert "image: pgvector/pgvector:0.8.6-pg18-bookworm" in text
    assert "image: postgres:18" not in text
    assert "POSTGRES_DB: nextgen_migration_rehearsal" in text
    assert "POSTGRES_USER: postgres" in text
    assert "POSTGRES_PASSWORD: synthetic-local-postgres-password" in text
    assert "postgresql-client-18" in text
    assert "psql --version" in text
    assert "pg_dump --version" in text
    assert "${{ secrets." not in text
    assert "neon.tech" not in text.lower()
    assert "DATABASE_URL" not in text


def test_workflow_runs_both_python_versions_and_the_complete_contract() -> None:
    text = _workflow_text()

    assert 'python-version: ["3.12", "3.13"]' in text
    assert "python -m pytest -q tests/test_neon_migration_manifest.py" in text
    assert "tests/test_neon_migration_runner.py" in text
    assert "tests/test_neon_migration_rehearsal_workflow.py" in text
    assert "python scripts/neon_migration_manifest.py" in text
    assert "python scripts/neon_migration_runner.py" in text
    assert "ruff check ." in text
    assert "python -m compileall -q src scripts" in text
    assert "python -m pytest -q" in text
    assert "git diff --check" in text


def test_workflow_passes_connection_data_only_through_environment() -> None:
    text = _workflow_text()

    for name in ("PGDATABASE", "PGHOST", "PGPASSWORD", "PGPORT", "PGUSER"):
        assert f"{name}:" in text
    assert "postgresql://" not in text
    assert "postgres://" not in text
    assert "--dbname" not in text
    assert "-d nextgen_migration_rehearsal" not in text
    assert "-h 127.0.0.1" not in text


def test_workflow_validates_safe_json_and_uploads_only_safe_reports() -> None:
    text = _workflow_text()

    assert "manifest-plan.json" in text
    assert "migration-rehearsal.json" in text
    assert "actions/upload-artifact@v4" in text
    assert "if-no-files-found: error" in text
    assert "retention-days: 7" in text
    assert "CREATE " in text
    assert "ALTER " in text
    assert "DROP " in text
    assert "password|secret|token|dsn|connection" in text
    assert "stdout" not in text.lower()
    assert "stderr" not in text.lower()
