from pathlib import Path

MIGRATION = Path("migrations/neon/0005_causal_credit_feedback.sql")
ALLOWED_METADATA_KEYS = (
    "credit_version",
    "trial_count",
    "mean_full_score",
    "mean_no_memory_score",
    "mean_without_memory_score",
    "mean_bundle_uplift",
    "mean_effect",
    "standard_error",
    "context_set_hash",
    "continuation_set_hash",
)


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


def test_metadata_guard_uses_exact_allowlist_not_recursive_blacklist() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "jsonb_object_length(p_metadata) = 10" in sql
    assert "p_metadata ?& ARRAY[" in sql
    assert "jsonb_object_keys(p_metadata)" in sql
    for key in ALLOWED_METADATA_KEYS:
        assert f"'{key}'" in sql

    assert "jsonb_each(p_metadata)" not in sql
    assert "jsonb_array_elements(p_metadata)" not in sql
    assert "'password'" not in sql
    assert "'secret'" not in sql
    assert "'token'" not in sql


def test_metadata_guard_validates_each_allowed_field_shape() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "p_metadata ->> 'credit_version' = 'paired_leave_one_out_v0'" in sql
    assert "p_metadata ->> 'trial_count'" in sql
    assert "^[1-9][0-9]*$" in sql
    for field in (
        "mean_full_score",
        "mean_no_memory_score",
        "mean_without_memory_score",
        "mean_bundle_uplift",
        "mean_effect",
        "standard_error",
    ):
        assert f"jsonb_typeof(p_metadata -> '{field}') = 'number'" in sql
    assert "standard_error" in sql and ">= 0" in sql
    assert "p_metadata ->> 'context_set_hash'" in sql
    assert "p_metadata ->> 'continuation_set_hash'" in sql
    assert "^[0-9a-f]{64}$" in sql


def test_new_allowlist_constraint_is_validated_without_rewriting_feedback() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "memory_feedback_causal_metadata_v0_1_1_check" in sql
    assert "NOT VALID" in sql
    assert "VALIDATE CONSTRAINT memory_feedback_causal_metadata_v0_1_1_check" in sql
    assert "UPDATE ngm.memory_feedback SET" not in sql


def test_migration_registers_schema_version_without_overwriting_feedback() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "post_action_causal_credit" in sql
    assert "'0.1.1'" in sql
    assert "ON CONFLICT (schema_key) DO UPDATE" in sql
    assert "UPDATE ngm.memory_feedback SET" not in sql
