from pathlib import Path

MIGRATION = Path("migrations/neon/0006_inherited_credit_ledger.sql")
BASE_MIGRATION = Path("migrations/neon/0001_memory_moe_kernel.sql")


def migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_migration_creates_four_separate_append_only_evidence_tables() -> None:
    sql = migration_sql()

    for table in (
        "ngm.provenance_credit_evaluations",
        "ngm.inherited_credit_contributions",
        "ngm.provenance_credit_observations",
        "ngm.provenance_credit_accounting",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql
        trigger_name = table.removeprefix("ngm.") + "_immutable"
        assert f"DROP TRIGGER IF EXISTS {trigger_name} ON {table}" in sql
        assert f"CREATE TRIGGER {trigger_name}" in sql
        assert "ngm.reject_immutable_mutation()" in sql


def test_evaluation_contract_tracks_direct_graph_policy_and_exact_accounting() -> None:
    sql = migration_sql()

    for column in (
        "direct_credit_id uuid NOT NULL",
        "evidence_group_id uuid NOT NULL",
        "root_node_id uuid NOT NULL",
        "source_kind text NOT NULL",
        "direct_value double precision NOT NULL",
        "direct_standard_error double precision NOT NULL",
        "trial_count integer NOT NULL",
        "context_set_hash text NOT NULL",
        "continuation_set_hash text NOT NULL",
        "graph_fingerprint text NOT NULL",
        "policy_fingerprint text NOT NULL",
        "policy_version text NOT NULL",
        "status text NOT NULL",
        "result_hash text NOT NULL",
        "accounting_id uuid NOT NULL",
        "content_hash text NOT NULL",
    ):
        assert column in sql

    assert "source_kind IN ('causal','interaction')" in sql
    assert "status IN ('propagated','abstained')" in sql
    assert "UNIQUE (space_id, direct_credit_id, graph_fingerprint, policy_fingerprint)" in sql
    assert "FOREIGN KEY (space_id, root_node_id)" in sql
    assert "REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "FOREIGN KEY (space_id, id, accounting_id)" in sql
    assert "REFERENCES ngm.provenance_credit_accounting(space_id, evaluation_id, id)" in sql


def test_contribution_contract_preserves_exact_typed_paths_and_target_scope() -> None:
    sql = migration_sql()

    for column in (
        "evaluation_id uuid NOT NULL",
        "target_node_id uuid NOT NULL",
        "propagated_value double precision NOT NULL",
        "propagated_standard_error double precision NOT NULL",
        "structural_confidence double precision NOT NULL",
        "minimum_edge_confidence double precision NOT NULL",
        "depth integer NOT NULL",
        "relation_path text[] NOT NULL",
        "edge_path uuid[] NOT NULL",
        "path_fingerprint text NOT NULL",
        "content_hash text NOT NULL",
    ):
        assert column in sql

    assert "cardinality(relation_path) = depth" in sql
    assert "cardinality(edge_path) = depth" in sql
    assert "array_position(relation_path, NULL) IS NULL" in sql
    assert "array_position(relation_path, '') IS NULL" in sql
    assert "array_position(edge_path, NULL) IS NULL" in sql
    assert "UNIQUE (space_id, evaluation_id, path_fingerprint)" in sql
    assert "FOREIGN KEY (space_id, target_node_id)" in sql


def test_observation_contract_distinguishes_blocked_paths_from_abstentions() -> None:
    sql = migration_sql()

    assert "kind IN ('blocked','abstention')" in sql
    assert "reason text NOT NULL" in sql
    assert "kind = 'blocked'" in sql
    assert "current_node_id IS NOT NULL" in sql
    assert "target_node_id IS NOT NULL" in sql
    assert "edge_id IS NOT NULL" in sql
    assert "relation IS NOT NULL" in sql
    assert "depth IS NOT NULL" in sql
    assert "path_fingerprint IS NOT NULL" in sql
    assert "kind = 'abstention'" in sql
    assert "current_node_id IS NULL" in sql
    assert "target_node_id IS NULL" in sql
    assert "edge_id IS NULL" in sql
    assert "relation IS NULL" in sql
    assert "depth IS NULL" in sql
    assert "path_fingerprint IS NULL" in sql
    assert "FOREIGN KEY (space_id, edge_id)" in sql
    assert "REFERENCES ngm.memory_edges(space_id, id) ON DELETE RESTRICT" in sql


def test_accounting_contract_is_exactly_one_row_per_evaluation() -> None:
    sql = migration_sql()

    for column in (
        "direct_value double precision NOT NULL",
        "propagation_budget double precision NOT NULL",
        "propagated_value double precision NOT NULL",
        "dropped_value double precision NOT NULL",
        "unallocated_value double precision NOT NULL",
        "conservation_residual double precision NOT NULL",
        "content_hash text NOT NULL",
    ):
        assert column in sql

    assert "UNIQUE (space_id, evaluation_id)" in sql
    assert "UNIQUE (space_id, evaluation_id, id)" in sql
    assert "FOREIGN KEY (space_id, evaluation_id)" in sql
    assert "REFERENCES ngm.provenance_credit_evaluations(space_id, id)" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql


def test_migration_checks_hashes_probabilities_finite_numbers_and_normalized_text() -> None:
    sql = migration_sql()

    assert sql.count("~ '^[0-9a-f]{64}$'") >= 9
    assert "ngm.is_finite_float8" in sql
    assert "structural_confidence >= 0 AND structural_confidence <= 1" in sql
    assert "minimum_edge_confidence >= 0 AND minimum_edge_confidence <= 1" in sql
    assert "direct_standard_error >= 0" in sql
    assert "propagated_standard_error >= 0" in sql
    assert "trial_count > 0" in sql
    assert "depth > 0" in sql
    assert "policy_version = btrim(policy_version) AND policy_version <> ''" in sql
    assert "reason = btrim(reason) AND reason <> ''" in sql
    assert "relation IS NULL OR (relation = btrim(relation) AND relation <> '')" in sql


def test_analytical_views_keep_direct_and_inherited_evidence_separate() -> None:
    sql = migration_sql()
    base_sql = BASE_MIGRATION.read_text(encoding="utf-8")

    assert "CREATE OR REPLACE VIEW ngm.node_inherited_credit AS" in sql
    assert "CREATE OR REPLACE VIEW ngm.node_learning_evidence AS" in sql
    assert "LEFT JOIN ngm.memory_feedback" not in sql
    assert "CREATE OR REPLACE VIEW ngm.node_utility" not in sql
    assert "FROM ngm.node_utility AS direct" in sql
    assert "LEFT JOIN ngm.node_inherited_credit AS inherited" in sql
    assert "combined_utility" not in sql
    assert "CREATE OR REPLACE VIEW ngm.node_utility AS" in base_sql


def test_migration_never_writes_direct_feedback_and_registers_its_own_schema_key() -> None:
    sql = migration_sql()

    assert "INSERT INTO ngm.memory_feedback" not in sql
    assert "UPDATE ngm.memory_feedback" not in sql
    assert "DELETE FROM ngm.memory_feedback" not in sql
    assert "'inherited_credit_ledger'" in sql
    assert "'0.1.0'" in sql
    assert "ON CONFLICT (schema_key) DO UPDATE" in sql


def test_migration_adds_scoped_edge_identity_and_query_indexes_idempotently() -> None:
    sql = migration_sql()

    assert "memory_edges_space_id_id_key" in sql
    assert "UNIQUE (space_id, id)" in sql
    for index_name in (
        "provenance_credit_evaluations_root_idx",
        "inherited_credit_contributions_target_idx",
        "provenance_credit_observations_evaluation_idx",
        "provenance_credit_accounting_evaluation_idx",
    ):
        assert f"CREATE INDEX IF NOT EXISTS {index_name}" in sql
