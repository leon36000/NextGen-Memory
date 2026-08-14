from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
NEON = ROOT / "migrations" / "neon"


def read_migration(name: str) -> str:
    return (NEON / name).read_text(encoding="utf-8")


def test_bootstrap_migration_preserves_scope_and_immutable_evidence() -> None:
    sql = read_migration("0001_memory_moe_kernel.sql")

    assert "CREATE SCHEMA IF NOT EXISTS ngm" in sql
    assert "FOREIGN KEY (space_id, source_id)" in sql
    assert "FOREIGN KEY (space_id, from_node_id)" in sql
    assert "FOREIGN KEY (space_id, to_node_id)" in sql
    assert "CREATE TRIGGER memory_nodes_immutable" in sql
    assert "CREATE TRIGGER memory_edges_immutable" in sql
    assert "CREATE OR REPLACE VIEW ngm.current_state" in sql
    assert "CREATE OR REPLACE VIEW ngm.node_utility" in sql


def test_bootstrap_migration_seeds_all_memory_experts() -> None:
    sql = read_migration("0001_memory_moe_kernel.sql")
    expected = {
        "working",
        "execution",
        "episodic",
        "semantic",
        "temporal",
        "causal",
        "procedural",
        "failure",
        "decision",
        "repository",
        "research",
        "feedback",
    }

    missing = {expert for expert in expected if f"('{expert}'," not in sql}
    assert not missing


def test_core_idempotency_migration_matches_deployed_schema_version() -> None:
    sql = read_migration("0002_core_idempotency.sql")

    for table in ("memory_nodes", "memory_embeddings", "memory_edges"):
        pattern = (
            rf"ALTER\s+TABLE\s+ngm\.{table}\s+ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS"
            r"\s+idempotency_key\s+text"
        )
        assert re.search(pattern, sql, flags=re.IGNORECASE)
        assert f"{table}_idempotency_idx" in sql
    assert "'0.1.1'" in sql
    assert "idempotent_core_writes" in sql


def test_migrations_do_not_contain_credentials() -> None:
    content = "\n".join(path.read_text(encoding="utf-8") for path in NEON.glob("*.sql"))
    lowered = content.lower()

    assert "postgresql://" not in lowered
    assert "mongodb+srv://" not in lowered
    assert "npg_" not in lowered
    assert "password=" not in lowered


def test_bootstrap_migration_does_not_downgrade_newer_schema_metadata() -> None:
    sql = read_migration("0001_memory_moe_kernel.sql")

    assert "ON CONFLICT (schema_key) DO NOTHING" in sql
