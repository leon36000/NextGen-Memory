-- Append-only positive evidence that one action used selected memory evidence.
-- Candidate schema version 0.1.0. This migration is additive and idempotent.

CREATE TABLE IF NOT EXISTS ngm.action_memory_usage_events (
  id uuid PRIMARY KEY,
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  action_id uuid NOT NULL,
  router_decision_id uuid NOT NULL,
  retrieval_event_id uuid NOT NULL
    REFERENCES ngm.retrieval_events(id) ON DELETE RESTRICT,
  node_id uuid NOT NULL,
  content_hash text NOT NULL
    CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (space_id, action_id, retrieval_event_id),
  FOREIGN KEY (space_id, router_decision_id)
    REFERENCES ngm.router_decisions(space_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (space_id, node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT
);

CREATE OR REPLACE FUNCTION ngm.validate_action_memory_usage_target()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  target_space_id uuid;
  target_decision_id uuid;
  target_node_id uuid;
  target_selected boolean;
BEGIN
  SELECT
    space_id,
    router_decision_id,
    node_id,
    selected_for_context
  INTO
    target_space_id,
    target_decision_id,
    target_node_id,
    target_selected
  FROM ngm.retrieval_events
  WHERE id = NEW.retrieval_event_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'action memory usage retrieval target is missing'
      USING ERRCODE = '23503';
  END IF;
  IF target_space_id IS DISTINCT FROM NEW.space_id THEN
    RAISE EXCEPTION 'action memory usage retrieval target space mismatch'
      USING ERRCODE = '23514';
  END IF;
  IF target_decision_id IS DISTINCT FROM NEW.router_decision_id THEN
    RAISE EXCEPTION 'action memory usage retrieval target decision mismatch'
      USING ERRCODE = '23514';
  END IF;
  IF target_node_id IS DISTINCT FROM NEW.node_id THEN
    RAISE EXCEPTION 'action memory usage retrieval target node mismatch'
      USING ERRCODE = '23514';
  END IF;
  IF target_selected IS DISTINCT FROM TRUE THEN
    RAISE EXCEPTION 'action memory usage retrieval target was not selected'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS action_memory_usage_validate_target
  ON ngm.action_memory_usage_events;
CREATE TRIGGER action_memory_usage_validate_target
BEFORE INSERT ON ngm.action_memory_usage_events
FOR EACH ROW EXECUTE FUNCTION ngm.validate_action_memory_usage_target();

DROP TRIGGER IF EXISTS action_memory_usage_immutable
  ON ngm.action_memory_usage_events;
CREATE TRIGGER action_memory_usage_immutable
BEFORE UPDATE OR DELETE ON ngm.action_memory_usage_events
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

CREATE INDEX IF NOT EXISTS action_memory_usage_action_idx
  ON ngm.action_memory_usage_events (
    space_id,
    action_id,
    router_decision_id,
    created_at DESC
  );

CREATE INDEX IF NOT EXISTS action_memory_usage_retrieval_idx
  ON ngm.action_memory_usage_events (space_id, retrieval_event_id);

CREATE INDEX IF NOT EXISTS action_memory_usage_decision_idx
  ON ngm.action_memory_usage_events (
    space_id,
    router_decision_id,
    node_id,
    created_at DESC
  );

INSERT INTO ngm.schema_meta (schema_key, schema_version, metadata)
VALUES (
  'action_memory_usage_events',
  '0.1.0',
  jsonb_build_object(
    'status', 'candidate',
    'capabilities', jsonb_build_array(
      'append_only_positive_usage',
      'action_specific_credit_targets',
      'deterministic_usage_identity',
      'exact_immutable_readback'
    )
  )
)
ON CONFLICT (schema_key) DO UPDATE
SET schema_version = EXCLUDED.schema_version,
    metadata = EXCLUDED.metadata,
    updated_at = now();
