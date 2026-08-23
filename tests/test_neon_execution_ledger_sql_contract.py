from nextgen_memory.neon_execution_ledger import (
    INSERT_ARTIFACT_SQL,
    INSERT_EVENT_SQL,
    INSERT_RUN_SQL,
    VERIFY_RUN_SQL,
)


def test_write_sql_is_static_parameterized_and_conflict_safe() -> None:
    for sql in (INSERT_RUN_SQL, INSERT_EVENT_SQL, INSERT_ARTIFACT_SQL):
        assert "%(" in sql
        assert "ON CONFLICT" in sql
        assert "ngm.assert_same_execution_payload" in sql
        assert "RETURNING" in sql
        assert "::jsonb" in sql
        assert "{" not in sql
        assert "}" not in sql


def test_run_conflict_is_scoped_by_space_and_idempotency_key() -> None:
    assert "ON CONFLICT (space_id, idempotency_key)" in INSERT_RUN_SQL
    assert "'execution_run'" in INSERT_RUN_SQL


def test_event_conflict_is_scoped_by_run_and_preserves_database_hashes() -> None:
    assert "ON CONFLICT (space_id, run_id, idempotency_key)" in INSERT_EVENT_SQL
    assert "storage_content_hash" in INSERT_EVENT_SQL
    assert "event_hash" in INSERT_EVENT_SQL
    assert "'execution_event'" in INSERT_EVENT_SQL


def test_artifact_conflict_uses_event_ordinal_identity() -> None:
    assert "ON CONFLICT (space_id, event_id, ordinal)" in INSERT_ARTIFACT_SQL
    assert "'execution_artifact'" in INSERT_ARTIFACT_SQL


def test_verification_sql_reads_head_and_drift_views_with_scope() -> None:
    assert "ngm.execution_run_heads" in VERIFY_RUN_SQL
    assert "ngm.execution_chain_drift" in VERIFY_RUN_SQL
    assert "space_id = %(space_id)s" in VERIFY_RUN_SQL
    assert "run_id = %(run_id)s" in VERIFY_RUN_SQL
