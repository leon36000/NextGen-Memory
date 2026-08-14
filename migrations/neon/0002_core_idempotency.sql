-- Core idempotency keys deployed as schema version 0.1.1.
-- Full event-table idempotency remains a later migration after connector-safe promotion.

ALTER TABLE ngm.memory_nodes
  ADD COLUMN IF NOT EXISTS idempotency_key text;
ALTER TABLE ngm.memory_embeddings
  ADD COLUMN IF NOT EXISTS idempotency_key text;
ALTER TABLE ngm.memory_edges
  ADD COLUMN IF NOT EXISTS idempotency_key text;

CREATE UNIQUE INDEX IF NOT EXISTS memory_nodes_idempotency_idx
  ON ngm.memory_nodes (space_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS memory_embeddings_idempotency_idx
  ON ngm.memory_embeddings (space_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS memory_edges_idempotency_idx
  ON ngm.memory_edges (space_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

INSERT INTO ngm.schema_meta (schema_key, schema_version, metadata)
VALUES (
  'memory_moe_kernel',
  '0.1.1',
  '{"status":"bootstrap","capabilities":["scope_isolation","immutable_evidence","idempotent_core_writes"],"deferred":["full_event_idempotency"]}'::jsonb
)
ON CONFLICT (schema_key) DO UPDATE
SET schema_version = EXCLUDED.schema_version,
    metadata = EXCLUDED.metadata,
    updated_at = now();
