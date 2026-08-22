from pathlib import Path

MIGRATION = Path("migrations/neon/0006_action_memory_usage_events.sql")


def test_action_usage_migration_exists_and_is_additive() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS ngm.action_memory_usage_events" in sql
    assert "DROP TABLE" not in sql
    assert "UPDATE ngm.retrieval_events" not in sql
    assert "ALTER TABLE ngm.retrieval_events" not in sql
    assert "DELETE FROM ngm.retrieval_events" not in sql


def test_table_has_deterministic_identity_and_canonical_links() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "id uuid PRIMARY KEY" in sql
    assert "space_id uuid NOT NULL" in sql
    assert "action_id uuid NOT NULL" in sql
    assert "router_decision_id uuid NOT NULL" in sql
    assert "retrieval_event_id uuid NOT NULL" in sql
    assert "node_id uuid NOT NULL" in sql
    assert "content_hash text NOT NULL" in sql
    assert "content_hash ~ '^[0-9a-f]{64}$'" in sql
    assert "UNIQUE (space_id, action_id, retrieval_event_id)" in sql
    assert "REFERENCES ngm.retrieval_events(id)" in sql
    assert "REFERENCES ngm.memory_spaces(id)" in sql
    assert "REFERENCES ngm.router_decisions(space_id, id)" in sql
    assert "REFERENCES ngm.memory_nodes(space_id, id)" in sql


def test_database_trigger_revalidates_selected_retrieval_identity() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "validate_action_memory_usage_target" in sql
    assert "FROM ngm.retrieval_events" in sql
    assert "NEW.retrieval_event_id" in sql
    assert "selected_for_context" in sql
    assert "target_space_id IS DISTINCT FROM NEW.space_id" in sql
    assert "target_decision_id IS DISTINCT FROM NEW.router_decision_id" in sql
    assert "target_node_id IS DISTINCT FROM NEW.node_id" in sql
    assert "target_selected IS DISTINCT FROM TRUE" in sql


def test_table_is_append_only_and_indexed_for_read_paths() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "reject_immutable_mutation" in sql
    assert "BEFORE UPDATE OR DELETE" in sql
    assert "action_memory_usage_action_idx" in sql
    assert "action_memory_usage_retrieval_idx" in sql
    assert "action_memory_usage_decision_idx" in sql


def test_schema_registration_is_idempotent_and_versioned() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "action_memory_usage_events" in sql
    assert "'0.1.0'" in sql
    assert "ON CONFLICT (schema_key) DO UPDATE" in sql
    assert "append_only_positive_usage" in sql
    assert "action_specific_credit_targets" in sql
