from pathlib import Path

MIGRATION = Path("migrations/neon/0004_execution_ledger.sql")


def test_execution_ledger_migration_is_append_only_ordered_and_tamper_evident() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ngm.execution_runs" in sql
    assert "CREATE TABLE IF NOT EXISTS ngm.execution_events" in sql
    assert "CREATE TABLE IF NOT EXISTS ngm.execution_artifacts" in sql
    assert "execution sequence must be contiguous" in sql
    assert "cannot append after terminal execution event" in sql
    assert "reject_execution_ledger_mutation" in sql
    assert "execution_metadata_is_safe" in sql
    assert "run_started input_hash must equal execution run request_hash" in sql
    assert "NEW.event_hash := encode(" in sql
    assert "digest(coalesce(v_latest.event_hash" in sql
    assert "CREATE OR REPLACE VIEW ngm.execution_chain_drift" in sql
    assert "ON DELETE RESTRICT" in sql
    assert "conrelid = 'ngm.execution_runs'::regclass" in sql
    assert "conrelid = 'ngm.execution_events'::regclass" in sql
    assert "conrelid = 'ngm.execution_artifacts'::regclass" in sql
    assert "ON CONFLICT (schema_key) DO UPDATE" in sql


def test_execution_ledger_migration_forbids_raw_sensitive_metadata_keys() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    for forbidden in ("query_text", "stdout", "stderr", "prompt", "secret", "token"):
        assert f"'{forbidden}'" in sql
