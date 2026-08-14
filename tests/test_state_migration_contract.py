import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "neon" / "0003_state_resolution_replay.sql"


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_state_replay_migration_is_additive_and_preserves_immutable_history() -> None:
    sql = migration_sql()

    assert "ADD COLUMN IF NOT EXISTS slot_version bigint" in sql
    assert "ADD COLUMN IF NOT EXISTS idempotency_key text" in sql
    assert "ALTER TABLE ngm.state_slots" in sql
    assert "ADD COLUMN IF NOT EXISTS quarantined_node_ids uuid[]" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS state_resolutions_slot_version_idx" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS state_resolutions_idempotency_idx" in sql
    assert "UPDATE ngm.state_resolutions" not in sql
    assert "DELETE FROM ngm.state_resolutions" not in sql
    assert "DISABLE TRIGGER state_resolutions_immutable" not in sql


def test_new_state_events_are_serialized_and_checked_against_projection() -> None:
    sql = migration_sql()

    assert "CREATE OR REPLACE FUNCTION ngm.require_state_resolution_insert_contract()" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "FOR UPDATE" in sql
    assert "expected slot_version %" in sql
    assert "authoritative history" in sql
    assert "stored projection version %" in sql
    assert "previous_node_id is required when state is active" in sql
    assert "previous_node_id does not match expected current node" in sql
    assert "quarantined candidate cannot become current" in sql
    assert "CREATE TRIGGER state_resolutions_insert_contract" in sql
    assert "BEFORE INSERT ON ngm.state_resolutions" in sql


def test_state_replay_migration_exposes_legacy_order_and_projection_drift() -> None:
    sql = migration_sql()

    assert "CREATE OR REPLACE VIEW ngm.state_replay_events" in sql
    assert "row_number() OVER" in sql
    assert "ORDER BY legacy.created_at, legacy.id" in sql
    assert "CREATE OR REPLACE VIEW ngm.state_projection_drift" in sql
    assert "expected_version" in sql
    assert "stored_version" in sql
    assert "expected_resolution_id" in sql
    assert "stored_resolution_id" in sql


def test_state_replay_migration_uses_parser_safe_function_body() -> None:
    sql = migration_sql()

    assert "LANGUAGE plpgsql" in sql
    assert "AS E'DECLARE" in sql
    assert "$$" not in sql


def test_state_replay_migration_advances_schema_capabilities() -> None:
    sql = migration_sql()

    assert "'0.2.0'" in sql
    assert "deterministic_state_replay" in sql
    assert "state_resolution_idempotency" in sql
    assert "explicit_slot_versions" in sql
    assert "quarantine_projection" in sql


def test_legacy_replay_view_uses_a_declared_source_alias() -> None:
    sql = migration_sql()

    assert "FROM ngm.state_resolutions AS legacy" in sql


def test_keep_checks_quarantine_only_when_candidate_would_become_current() -> None:
    sql = migration_sql()
    keep_start = sql.index("IF NEW.verdict = ''KEEP'' THEN")
    supersede_start = sql.index("ELSIF NEW.verdict = ''SUPERSEDE'' THEN")
    keep_block = sql[keep_start:supersede_start]

    assert keep_block.index("IF projected_current IS NULL THEN") < keep_block.index(
        "quarantined candidate cannot become current"
    )


def test_legacy_versions_are_ranked_without_future_explicit_rows() -> None:
    sql = migration_sql()

    assert "WITH legacy_events AS" in sql
    assert "FROM ngm.state_resolutions AS legacy" in sql
    assert "WHERE legacy.slot_version IS NULL" in sql
    assert "UNION ALL" in sql
    assert "FROM ngm.state_resolutions AS explicit" in sql
    assert "WHERE explicit.slot_version IS NOT NULL" in sql


def test_state_slots_can_only_be_mutated_by_the_projection_trigger() -> None:
    sql = migration_sql()

    assert "CREATE OR REPLACE FUNCTION ngm.reject_direct_state_slot_mutation()" in sql
    assert "current_setting(''ngm.state_projection_write'', true)" in sql
    assert "pg_trigger_depth() < 2" in sql
    assert "CREATE TRIGGER state_slots_projection_guard" in sql
    assert "BEFORE INSERT OR UPDATE OR DELETE ON ngm.state_slots" in sql
    assert "set_config(''ngm.state_projection_write'', ''on'', true)" in sql
    assert "set_config(''ngm.state_projection_write'', ''off'', true)" in sql


def test_projection_write_checks_authoritative_head_identity() -> None:
    sql = migration_sql()

    assert "prior_resolution_id" in sql
    assert "stored resolution_id % does not match authoritative head %" in sql
    assert "stored idempotency key does not match authoritative head" in sql


def test_insert_contract_canonicalizes_textual_identities() -> None:
    sql = migration_sql()

    assert "NEW.slot_key := btrim(NEW.slot_key)" in sql
    assert "NEW.idempotency_key := btrim(NEW.idempotency_key)" in sql
    assert "NEW.resolver := btrim(NEW.resolver)" in sql


def test_invalidate_requires_an_active_previous_state() -> None:
    sql = migration_sql()

    assert "INVALIDATE requires previous_node_id" in sql
