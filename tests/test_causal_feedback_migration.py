from pathlib import Path

MIGRATION = Path("migrations/neon/0005_causal_credit_feedback.sql")


def test_migration_is_additive_idempotent_and_causal_only() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS credit_evaluation_id" in sql
    assert "ADD COLUMN IF NOT EXISTS evidence_key" in sql
    assert "ADD COLUMN IF NOT EXISTS content_hash" in sql
    assert "paired_leave_one_out_v0" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS memory_feedback_causal_identity_uidx" in sql
    assert "credit_metadata_is_safe" in sql
    assert "assert_same_causal_feedback_payload" in sql
    assert "reject_causal_feedback_mutation" in sql
    assert "credit_evaluation_id IS NOT NULL" in sql
    assert "conrelid = 'ngm.memory_feedback'::regclass" in sql
    assert "ON DELETE RESTRICT" not in sql
    assert "DROP TABLE" not in sql
    assert "CREATE TABLE ngm.memory_feedback" not in sql


def test_causal_rows_require_complete_safe_immutable_evidence() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "node_id IS NOT NULL" in sql
    assert "router_decision_id IS NOT NULL" in sql
    assert "evidence_key = 'paired_leave_one_out_v0'" in sql
    assert "content_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "notes IS NULL" in sql
    assert "jsonb_typeof(metadata) = 'object'" in sql
    assert "ngm.credit_metadata_is_safe(metadata)" in sql
    assert "OLD.credit_evaluation_id IS NOT NULL" in sql
    assert "idempotency key reused with different immutable content" in sql


def test_metadata_guard_blocks_raw_sensitive_fields_recursively() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    for forbidden in (
        "api_key",
        "argv",
        "command",
        "diff",
        "environment",
        "notes",
        "password",
        "patch",
        "prompt",
        "query_text",
        "raw_payload",
        "secret",
        "stderr",
        "stdout",
        "token",
    ):
        assert f"'{forbidden}'" in sql
    assert "jsonb_each(p_metadata)" in sql
    assert "jsonb_array_elements(p_metadata)" in sql


def test_migration_registers_schema_version_without_overwriting_feedback() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "post_action_causal_credit" in sql
    assert "'0.1.0'" in sql
    assert "ON CONFLICT (schema_key) DO UPDATE" in sql
    assert "UPDATE ngm.memory_feedback SET" not in sql
