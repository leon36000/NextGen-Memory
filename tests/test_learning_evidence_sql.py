from nextgen_memory.learning_evidence import LEARNING_EVIDENCE_SELECT_SQL


def test_learning_evidence_sql_is_static_scoped_and_complete() -> None:
    sql = LEARNING_EVIDENCE_SELECT_SQL

    assert "FROM ngm.node_learning_evidence" in sql
    assert "WHERE space_id = %(space_id)s" in sql
    assert "node_id = ANY(%(memory_ids)s::uuid[])" in sql
    assert "ORDER BY node_id" in sql
    for column in (
        "space_id",
        "node_id",
        "direct_feedback_count",
        "direct_avg_reward",
        "direct_positive_count",
        "direct_negative_count",
        "last_direct_feedback_at",
        "inherited_contribution_count",
        "inherited_value_sum",
        "inherited_absolute_value_sum",
        "inherited_standard_error_sum",
        "minimum_structural_confidence",
        "last_inherited_credit_at",
    ):
        assert column in sql


def test_learning_evidence_sql_contains_no_raw_payload_or_combined_score_fields() -> None:
    lowered = LEARNING_EVIDENCE_SELECT_SQL.lower()

    for forbidden in (
        "query_text",
        "prompt",
        "answer",
        "memory_body",
        "body_text",
        "command_text",
        "stdout",
        "stderr",
        "secret",
        "token",
        "patch_text",
        "environment",
        "feedback_note",
        "combined_utility",
    ):
        assert forbidden not in lowered


def test_learning_evidence_sql_does_not_replace_direct_utility_reader_source() -> None:
    lowered = LEARNING_EVIDENCE_SELECT_SQL.lower()

    assert "from ngm.node_utility" not in lowered
    assert "memory_feedback" not in lowered
    assert "inherited_credit_contributions" not in lowered
