from __future__ import annotations

import re
from pathlib import Path

SEED_PATH = Path("migrations/neon/0003_research_sources_seed.sql")
EXPECTED_MEMORY_IDS = {
    "2d6dc3f4-6fbb-51fb-b271-3ec5d70b70fa",
    "65d211f8-fc2d-5201-9b77-2852b637db5a",
    "4b84a18f-056f-5be9-bd27-a33ef835d29c",
    "d2857c1a-5f16-5eb3-ac45-518bf5858e25",
    "7d92a984-b8fa-5636-892f-99c2cd3bf934",
    "0f96583c-76ba-5a39-8820-e194df7c6454",
    "23a28be2-135d-53a4-8aed-f0e77fef72a8",
    "376e341f-c293-530b-a7b2-1dd6942e81a1",
    "7a3111ec-ca59-5c13-ad0c-7baa34bbea25",
    "757b9dd4-d5dd-51d6-953a-32aa8980bfdd",
}


def test_research_seed_is_idempotent_and_uses_canonical_experts() -> None:
    sql = SEED_PATH.read_text(encoding="utf-8")

    assert "ON CONFLICT DO NOTHING" in sql
    assert "ARRAY['research','semantic']::text[]" in sql
    assert "payload_collection\":\"research_sources" in sql
    assert "sha256:" not in sql


def test_research_seed_contains_exactly_the_atlas_memory_ids() -> None:
    sql = SEED_PATH.read_text(encoding="utf-8")
    ids = set(
        re.findall(
            r"'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})'::uuid",
            sql,
        )
    )

    assert ids >= EXPECTED_MEMORY_IDS
    assert len(ids - EXPECTED_MEMORY_IDS) == 2  # project space and source principal
