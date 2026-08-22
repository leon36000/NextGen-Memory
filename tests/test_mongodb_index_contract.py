import json
from pathlib import Path

INDEX_PATH = Path("migrations/mongodb/rag_lexical_v2.json")


def test_lexical_v2_indexes_scope_fields_for_in_search_filtering() -> None:
    definition = json.loads(INDEX_PATH.read_text(encoding="utf-8"))

    assert definition["name"] == "rag_lexical_v2"
    assert definition["type"] == "search"
    fields = definition["definition"]["mappings"]["fields"]
    assert fields["space_id"] == {"type": "token", "normalizer": "lowercase"}
    assert fields["status"] == {"type": "token", "normalizer": "lowercase"}
    assert fields["source_type"] == {"type": "token", "normalizer": "lowercase"}
