-- Deterministic, append-only state resolution replay and atomic projection.
-- Existing immutable state_resolutions rows remain untouched. Future rows must
-- carry explicit slot versions and idempotency keys.

ALTER TABLE ngm.state_resolutions
  ADD COLUMN IF NOT EXISTS slot_version bigint;
ALTER TABLE ngm.state_resolutions
  ADD COLUMN IF NOT EXISTS idempotency_key text;

ALTER TABLE ngm.state_slots
  ADD COLUMN IF NOT EXISTS quarantined_node_ids uuid[]
    NOT NULL DEFAULT ARRAY[]::uuid[];
ALTER TABLE ngm.state_slots
  ADD COLUMN IF NOT EXISTS last_idempotency_key text;

ALTER TABLE ngm.state_resolutions
  DROP CONSTRAINT IF EXISTS state_resolutions_slot_version_positive;
ALTER TABLE ngm.state_resolutions
  ADD CONSTRAINT state_resolutions_slot_version_positive
  CHECK (slot_version IS NULL OR slot_version > 0) NOT VALID;
ALTER TABLE ngm.state_resolutions
  VALIDATE CONSTRAINT state_resolutions_slot_version_positive;

ALTER TABLE ngm.state_slots
  DROP CONSTRAINT IF EXISTS state_slots_current_not_quarantined;
ALTER TABLE ngm.state_slots
  ADD CONSTRAINT state_slots_current_not_quarantined
  CHECK (
    current_node_id IS NULL
    OR NOT (current_node_id = ANY(quarantined_node_ids))
  ) NOT VALID;
ALTER TABLE ngm.state_slots
  VALIDATE CONSTRAINT state_slots_current_not_quarantined;

CREATE UNIQUE INDEX IF NOT EXISTS state_resolutions_slot_version_idx
  ON ngm.state_resolutions (space_id, slot_key, slot_version)
  WHERE slot_version IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS state_resolutions_idempotency_idx
  ON ngm.state_resolutions (space_id, idempotency_key)
  WHERE idempotency_key IS NOT NULL;

CREATE OR REPLACE VIEW ngm.state_replay_events AS
WITH legacy_events AS (
  SELECT
    legacy.id,
    legacy.space_id,
    legacy.slot_key,
    row_number() OVER (
      PARTITION BY legacy.space_id, legacy.slot_key
      ORDER BY legacy.created_at, legacy.id
    )::bigint AS replay_slot_version,
    'legacy:' || legacy.id::text AS replay_idempotency_key,
    legacy.candidate_node_id,
    legacy.previous_node_id,
    legacy.verdict,
    legacy.resolver,
    legacy.evidence_node_ids,
    legacy.reasoning,
    legacy.created_at,
    true AS legacy_metadata
  FROM ngm.state_resolutions AS legacy
  WHERE legacy.slot_version IS NULL
     OR legacy.idempotency_key IS NULL
),
explicit_events AS (
  SELECT
    explicit.id,
    explicit.space_id,
    explicit.slot_key,
    explicit.slot_version::bigint AS replay_slot_version,
    explicit.idempotency_key AS replay_idempotency_key,
    explicit.candidate_node_id,
    explicit.previous_node_id,
    explicit.verdict,
    explicit.resolver,
    explicit.evidence_node_ids,
    explicit.reasoning,
    explicit.created_at,
    false AS legacy_metadata
  FROM ngm.state_resolutions AS explicit
  WHERE explicit.slot_version IS NOT NULL
    AND explicit.idempotency_key IS NOT NULL
)
SELECT * FROM legacy_events
UNION ALL
SELECT * FROM explicit_events;

CREATE OR REPLACE FUNCTION ngm.require_state_resolution_insert_contract()
RETURNS trigger
LANGUAGE plpgsql
AS E'BEGIN\n  IF NEW.slot_key IS NULL OR btrim(NEW.slot_key) = '''' THEN\n    RAISE EXCEPTION ''slot_key must be supplied for future state resolutions''\n      USING ERRCODE = ''23502'';\n  END IF;\n  IF NEW.slot_version IS NULL OR NEW.slot_version <= 0 THEN\n    RAISE EXCEPTION ''slot_version must be supplied and positive for future state resolutions''\n      USING ERRCODE = ''23514'';\n  END IF;\n  IF NEW.idempotency_key IS NULL OR btrim(NEW.idempotency_key) = '''' THEN\n    RAISE EXCEPTION ''idempotency_key must be supplied for future state resolutions''\n      USING ERRCODE = ''23502'';\n  END IF;\n  IF NEW.resolver IS NULL OR btrim(NEW.resolver) = '''' THEN\n    RAISE EXCEPTION ''resolver must be supplied for future state resolutions''\n      USING ERRCODE = ''23502'';\n  END IF;\n  NEW.slot_key := btrim(NEW.slot_key);\n  NEW.idempotency_key := btrim(NEW.idempotency_key);\n  NEW.resolver := btrim(NEW.resolver);\n  RETURN NEW;\nEND;';

DROP TRIGGER IF EXISTS state_resolutions_insert_contract ON ngm.state_resolutions;
CREATE TRIGGER state_resolutions_insert_contract
BEFORE INSERT ON ngm.state_resolutions
FOR EACH ROW EXECUTE FUNCTION ngm.require_state_resolution_insert_contract();

CREATE OR REPLACE FUNCTION ngm.reject_direct_state_slot_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS E'BEGIN\n  IF pg_trigger_depth() < 2\n     OR current_setting(''ngm.state_projection_write'', true) IS DISTINCT FROM ''on'' THEN\n    RAISE EXCEPTION ''state_slots is a derived projection; append a state resolution instead''\n      USING ERRCODE = ''55000'';\n  END IF;\n  IF TG_OP = ''DELETE'' THEN\n    RETURN OLD;\n  END IF;\n  RETURN NEW;\nEND;';

DROP TRIGGER IF EXISTS state_slots_projection_guard ON ngm.state_slots;
CREATE TRIGGER state_slots_projection_guard
BEFORE INSERT OR UPDATE OR DELETE ON ngm.state_slots
FOR EACH ROW EXECUTE FUNCTION ngm.reject_direct_state_slot_mutation();

-- KEEP preserves active state; use SUPERSEDE to replace it.
CREATE OR REPLACE FUNCTION ngm.project_state_resolution_event()
RETURNS trigger
LANGUAGE plpgsql
AS E'DECLARE\n  stored_current uuid;\n  stored_status text;\n  stored_version bigint;\n  stored_resolution_id uuid;\n  stored_last_idempotency_key text;\n  stored_quarantined uuid[];\n  prior_event_count bigint;\n  prior_resolution_id uuid;\n  prior_idempotency_key text;\n  prior_legacy_metadata boolean;\n  expected_version bigint;\n  projected_current uuid;\n  projected_status text;\n  projected_quarantined uuid[];\nBEGIN\n  PERFORM pg_advisory_xact_lock(\n    hashtextextended(NEW.space_id::text || '':'' || NEW.slot_key, 0)\n  );\n\n  SELECT count(*)\n  INTO prior_event_count\n  FROM ngm.state_resolutions\n  WHERE space_id = NEW.space_id\n    AND slot_key = NEW.slot_key\n    AND id <> NEW.id;\n\n  SELECT id, replay_idempotency_key, legacy_metadata\n  INTO prior_resolution_id, prior_idempotency_key, prior_legacy_metadata\n  FROM ngm.state_replay_events\n  WHERE space_id = NEW.space_id\n    AND slot_key = NEW.slot_key\n    AND id <> NEW.id\n  ORDER BY replay_slot_version DESC, id DESC\n  LIMIT 1;\n\n  expected_version := prior_event_count + 1;\n  IF NEW.slot_version <> expected_version THEN\n    RAISE EXCEPTION ''expected slot_version %, received %'', expected_version, NEW.slot_version\n      USING ERRCODE = ''40001'';\n  END IF;\n\n  SELECT\n    current_node_id,\n    status,\n    version,\n    resolution_id,\n    last_idempotency_key,\n    COALESCE(quarantined_node_ids, ARRAY[]::uuid[])\n  INTO\n    stored_current,\n    stored_status,\n    stored_version,\n    stored_resolution_id,\n    stored_last_idempotency_key,\n    stored_quarantined\n  FROM ngm.state_slots\n  WHERE space_id = NEW.space_id AND slot_key = NEW.slot_key\n  FOR UPDATE;\n\n  IF FOUND THEN\n    IF stored_version <> prior_event_count THEN\n      RAISE EXCEPTION ''stored projection version % does not match authoritative history %'', stored_version, prior_event_count\n        USING ERRCODE = ''40001'';\n    END IF;\n    IF stored_resolution_id IS DISTINCT FROM prior_resolution_id THEN\n      RAISE EXCEPTION ''stored resolution_id % does not match authoritative head %'', stored_resolution_id, prior_resolution_id\n        USING ERRCODE = ''40001'';\n    END IF;\n    IF NOT COALESCE(prior_legacy_metadata, false)\n       AND stored_last_idempotency_key IS DISTINCT FROM prior_idempotency_key THEN\n      RAISE EXCEPTION ''stored idempotency key does not match authoritative head''\n        USING ERRCODE = ''40001'';\n    END IF;\n    IF prior_event_count = 0\n       AND (stored_current IS NOT NULL\n            OR stored_status <> ''unknown''\n            OR cardinality(stored_quarantined) <> 0) THEN\n      RAISE EXCEPTION ''empty authoritative history has a non-empty projection''\n        USING ERRCODE = ''40001'';\n    END IF;\n    projected_current := stored_current;\n    projected_status := stored_status;\n    projected_quarantined := stored_quarantined;\n  ELSE\n    IF prior_event_count <> 0 THEN\n      RAISE EXCEPTION ''state projection is missing for existing authoritative history''\n        USING ERRCODE = ''40001'';\n    END IF;\n    projected_current := NULL;\n    projected_status := ''unknown'';\n    projected_quarantined := ARRAY[]::uuid[];\n  END IF;\n\n  IF projected_current IS NULL THEN\n    IF NEW.previous_node_id IS NOT NULL THEN\n      RAISE EXCEPTION ''previous_node_id was provided but state has no current node''\n        USING ERRCODE = ''23514'';\n    END IF;\n  ELSE\n    IF NEW.previous_node_id IS NULL THEN\n      RAISE EXCEPTION ''previous_node_id is required when state is active''\n        USING ERRCODE = ''23514'';\n    END IF;\n    IF NEW.previous_node_id <> projected_current THEN\n      RAISE EXCEPTION ''previous_node_id does not match expected current node %'', projected_current\n        USING ERRCODE = ''40001'';\n    END IF;\n  END IF;\n\n  IF NEW.verdict = ''KEEP'' THEN\n    IF NEW.candidate_node_id IS NULL THEN\n      RAISE EXCEPTION ''KEEP requires candidate_node_id'' USING ERRCODE = ''23514'';\n    END IF;\n    IF projected_current IS NULL THEN\n      IF NEW.candidate_node_id = ANY(projected_quarantined) THEN\n        RAISE EXCEPTION ''quarantined candidate cannot become current''\n          USING ERRCODE = ''23514'';\n      END IF;\n      projected_current := NEW.candidate_node_id;\n      projected_status := ''active'';\n    END IF;\n  ELSIF NEW.verdict = ''SUPERSEDE'' THEN\n    IF NEW.candidate_node_id IS NULL THEN\n      RAISE EXCEPTION ''SUPERSEDE requires candidate_node_id'' USING ERRCODE = ''23514'';\n    END IF;\n    IF NEW.previous_node_id IS NULL THEN\n      RAISE EXCEPTION ''SUPERSEDE requires previous_node_id'' USING ERRCODE = ''23514'';\n    END IF;\n    IF NEW.candidate_node_id = NEW.previous_node_id THEN\n      RAISE EXCEPTION ''SUPERSEDE candidate must differ from previous state''\n        USING ERRCODE = ''23514'';\n    END IF;\n    IF NEW.candidate_node_id = ANY(projected_quarantined) THEN\n      RAISE EXCEPTION ''quarantined candidate cannot become current''\n        USING ERRCODE = ''23514'';\n    END IF;\n    projected_current := NEW.candidate_node_id;\n    projected_status := ''active'';\n  ELSIF NEW.verdict = ''INVALIDATE'' THEN\n    IF NEW.previous_node_id IS NULL THEN\n      RAISE EXCEPTION ''INVALIDATE requires previous_node_id''\n        USING ERRCODE = ''23514'';\n    END IF;\n    IF NEW.candidate_node_id IS NOT NULL THEN\n      RAISE EXCEPTION ''INVALIDATE does not accept candidate_node_id''\n        USING ERRCODE = ''23514'';\n    END IF;\n    projected_current := NULL;\n    projected_status := ''stale'';\n  ELSIF NEW.verdict = ''UNKNOWN'' THEN\n    IF NEW.candidate_node_id IS NOT NULL THEN\n      RAISE EXCEPTION ''UNKNOWN does not accept candidate_node_id''\n        USING ERRCODE = ''23514'';\n    END IF;\n    projected_current := NULL;\n    projected_status := ''unknown'';\n  ELSIF NEW.verdict = ''QUARANTINE'' THEN\n    IF NEW.candidate_node_id IS NULL THEN\n      RAISE EXCEPTION ''QUARANTINE requires candidate_node_id''\n        USING ERRCODE = ''23514'';\n    END IF;\n    IF NOT (NEW.candidate_node_id = ANY(projected_quarantined)) THEN\n      projected_quarantined := array_append(\n        projected_quarantined, NEW.candidate_node_id\n      );\n    END IF;\n    IF projected_current = NEW.candidate_node_id THEN\n      projected_current := NULL;\n      projected_status := ''quarantined'';\n    ELSIF projected_current IS NULL THEN\n      projected_status := ''quarantined'';\n    END IF;\n  ELSE\n    RAISE EXCEPTION ''unsupported state verdict %'', NEW.verdict\n      USING ERRCODE = ''23514'';\n  END IF;\n\n  IF projected_current IS NOT NULL\n     AND projected_current = ANY(projected_quarantined) THEN\n    RAISE EXCEPTION ''quarantined candidate cannot become current''\n      USING ERRCODE = ''23514'';\n  END IF;\n\n  PERFORM set_config(''ngm.state_projection_write'', ''on'', true);\n\n  INSERT INTO ngm.state_slots (\n    space_id,\n    slot_key,\n    current_node_id,\n    status,\n    resolution_id,\n    version,\n    updated_at,\n    quarantined_node_ids,\n    last_idempotency_key\n  ) VALUES (\n    NEW.space_id,\n    NEW.slot_key,\n    projected_current,\n    projected_status,\n    NEW.id,\n    NEW.slot_version,\n    NEW.created_at,\n    projected_quarantined,\n    NEW.idempotency_key\n  )\n  ON CONFLICT (space_id, slot_key) DO UPDATE\n  SET current_node_id = EXCLUDED.current_node_id,\n      status = EXCLUDED.status,\n      resolution_id = EXCLUDED.resolution_id,\n      version = EXCLUDED.version,\n      updated_at = EXCLUDED.updated_at,\n      quarantined_node_ids = EXCLUDED.quarantined_node_ids,\n      last_idempotency_key = EXCLUDED.last_idempotency_key;\n\n  PERFORM set_config(''ngm.state_projection_write'', ''off'', true);\n  RETURN NEW;\nEND;';

DROP TRIGGER IF EXISTS state_resolutions_project_after_insert
  ON ngm.state_resolutions;
CREATE TRIGGER state_resolutions_project_after_insert
AFTER INSERT ON ngm.state_resolutions
FOR EACH ROW EXECUTE FUNCTION ngm.project_state_resolution_event();

CREATE OR REPLACE VIEW ngm.state_projection_drift AS
WITH latest_event AS (
  SELECT DISTINCT ON (space_id, slot_key)
    space_id,
    slot_key,
    id AS expected_resolution_id,
    replay_slot_version AS expected_version,
    replay_idempotency_key AS expected_idempotency_key,
    legacy_metadata
  FROM ngm.state_replay_events
  ORDER BY space_id, slot_key, replay_slot_version DESC, id DESC
)
SELECT
  COALESCE(latest_event.space_id, stored.space_id) AS space_id,
  COALESCE(latest_event.slot_key, stored.slot_key) AS slot_key,
  latest_event.expected_version,
  stored.version AS stored_version,
  latest_event.expected_resolution_id,
  stored.resolution_id AS stored_resolution_id,
  latest_event.expected_idempotency_key,
  stored.last_idempotency_key AS stored_idempotency_key,
  (
    latest_event.expected_version IS DISTINCT FROM stored.version
    OR latest_event.expected_resolution_id IS DISTINCT FROM stored.resolution_id
    OR (
      NOT COALESCE(latest_event.legacy_metadata, false)
      AND latest_event.expected_idempotency_key
        IS DISTINCT FROM stored.last_idempotency_key
    )
  ) AS has_drift
FROM latest_event
FULL OUTER JOIN ngm.state_slots AS stored
  ON stored.space_id = latest_event.space_id
 AND stored.slot_key = latest_event.slot_key
WHERE latest_event.expected_version IS DISTINCT FROM stored.version
   OR latest_event.expected_resolution_id IS DISTINCT FROM stored.resolution_id
   OR (
     NOT COALESCE(latest_event.legacy_metadata, false)
     AND latest_event.expected_idempotency_key
       IS DISTINCT FROM stored.last_idempotency_key
   );

INSERT INTO ngm.schema_meta (schema_key, schema_version, metadata)
VALUES (
  'memory_moe_kernel',
  '0.2.0',
  '{"status":"state_replay_v0","capabilities":["state_projection_replay","deterministic_state_replay","state_resolution_idempotency","explicit_slot_versions","quarantine_projection","atomic_state_projection","legacy_replay_view","projection_mutation_guard","authoritative_head_guard","canonical_text_identity"]}'::jsonb
)
ON CONFLICT (schema_key) DO UPDATE
SET schema_version = EXCLUDED.schema_version,
    metadata = EXCLUDED.metadata,
    updated_at = now();
