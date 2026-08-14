-- Append-only, tamper-evident repository execution ledger (schema version 0.1.0).
-- Additive and idempotent. Raw commands, prompts, output, and secrets belong in rich payload storage.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION ngm.execution_metadata_is_safe(p_metadata jsonb)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
STRICT
AS $$
DECLARE
  v_key text;
  v_value jsonb;
  v_normalized text;
  v_compact text;
  v_seen text[] := ARRAY[]::text[];
BEGIN
  IF octet_length(p_metadata::text) > 8192 THEN
    RETURN false;
  END IF;

  IF jsonb_typeof(p_metadata) = 'object' THEN
    FOR v_key, v_value IN SELECT key, value FROM jsonb_each(p_metadata)
    LOOP
      v_normalized := lower(
        regexp_replace(
          regexp_replace(
            regexp_replace(
              btrim(v_key),
              '([A-Z]+)([A-Z][a-z])',
              E'\\1_\\2',
              'g'
            ),
            '([a-z0-9])([A-Z])',
            E'\\1_\\2',
            'g'
          ),
          '[^A-Za-z0-9]+',
          '_',
          'g'
        )
      );
      v_normalized := btrim(v_normalized, '_');
      v_compact := replace(v_normalized, '_', '');

      IF v_normalized = '' OR v_normalized = ANY(v_seen) THEN
        RETURN false;
      END IF;
      v_seen := array_append(v_seen, v_normalized);

      IF v_normalized = ANY (ARRAY[
        'api_key', 'argv', 'command', 'command_text', 'diff', 'env',
        'environment', 'password', 'patch', 'patch_text', 'prompt',
        'query', 'query_text', 'raw', 'raw_payload', 'secret',
        'stderr', 'stdout', 'token'
      ]) OR v_compact = ANY (ARRAY[
        'apikey', 'argv', 'command', 'commandtext', 'diff', 'env',
        'environment', 'password', 'patch', 'patchtext', 'prompt',
        'query', 'querytext', 'raw', 'rawpayload', 'secret',
        'stderr', 'stdout', 'token'
      ]) OR EXISTS (
        SELECT 1
        FROM unnest(string_to_array(v_normalized, '_')) AS segment(value)
        WHERE segment.value = ANY (ARRAY[
          'api_key', 'argv', 'command', 'command_text', 'diff', 'env',
          'environment', 'password', 'patch', 'patch_text', 'prompt',
          'query', 'query_text', 'raw', 'raw_payload', 'secret',
          'stderr', 'stdout', 'token'
        ])
      ) THEN
        RETURN false;
      END IF;

      IF NOT ngm.execution_metadata_is_safe(v_value) THEN
        RETURN false;
      END IF;
    END LOOP;
  ELSIF jsonb_typeof(p_metadata) = 'array' THEN
    FOR v_value IN SELECT value FROM jsonb_array_elements(p_metadata)
    LOOP
      IF NOT ngm.execution_metadata_is_safe(v_value) THEN
        RETURN false;
      END IF;
    END LOOP;
  END IF;

  RETURN true;
END;
$$;

CREATE TABLE IF NOT EXISTS ngm.execution_runs (
  id uuid PRIMARY KEY,
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  source_id uuid NOT NULL,
  repository_key text NOT NULL CHECK (btrim(repository_key) <> ''),
  branch text,
  base_revision text,
  task_key text,
  session_key text,
  started_at timestamptz NOT NULL,
  idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
  request_hash text NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (space_id, id),
  UNIQUE (space_id, idempotency_key),
  FOREIGN KEY (space_id, source_id)
    REFERENCES ngm.source_principals(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.execution_events (
  id uuid PRIMARY KEY,
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL,
  sequence bigint NOT NULL CHECK (sequence > 0),
  previous_event_id uuid,
  kind text NOT NULL CHECK (kind IN (
    'run_started', 'observation', 'command', 'file_change', 'test', 'build',
    'checkpoint', 'run_completed', 'run_failed', 'run_cancelled'
  )),
  outcome text NOT NULL CHECK (
    outcome IN ('unknown', 'success', 'failure', 'skipped', 'cancelled')
  ),
  action_key text NOT NULL CHECK (action_key ~ '^[a-z0-9][a-z0-9_.:-]{0,127}$'),
  started_at timestamptz NOT NULL,
  ended_at timestamptz,
  command_fingerprint text CHECK (
    command_fingerprint IS NULL OR command_fingerprint ~ '^[0-9a-f]{64}$'
  ),
  input_hash text CHECK (input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'),
  output_hash text CHECK (output_hash IS NULL OR output_hash ~ '^[0-9a-f]{64}$'),
  backend_ref text,
  idempotency_key text NOT NULL CHECK (btrim(idempotency_key) <> ''),
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  storage_content_hash text NOT NULL CHECK (
    storage_content_hash ~ '^[0-9a-f]{64}$'
  ),
  event_hash text NOT NULL CHECK (event_hash ~ '^[0-9a-f]{64}$'),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (ended_at IS NULL OR ended_at >= started_at),
  UNIQUE (space_id, id),
  UNIQUE (space_id, run_id, id),
  UNIQUE (space_id, run_id, sequence),
  UNIQUE (space_id, run_id, idempotency_key),
  FOREIGN KEY (space_id, run_id)
    REFERENCES ngm.execution_runs(space_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (space_id, run_id, previous_event_id)
    REFERENCES ngm.execution_events(space_id, run_id, id) ON DELETE RESTRICT
);

-- Repair a partially applied earlier candidate without rewriting immutable events.
-- Existing rows may keep NULL until a controlled backfill; every new row receives
-- a storage_content_hash from the insert trigger below.
ALTER TABLE ngm.execution_events
  ADD COLUMN IF NOT EXISTS storage_content_hash text;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'execution_events_storage_content_hash_format_check'
      AND conrelid = 'ngm.execution_events'::regclass
  ) THEN
    ALTER TABLE ngm.execution_events
      ADD CONSTRAINT execution_events_storage_content_hash_format_check
      CHECK (
        storage_content_hash IS NULL
        OR storage_content_hash ~ '^[0-9a-f]{64}$'
      ) NOT VALID;
    ALTER TABLE ngm.execution_events
      VALIDATE CONSTRAINT execution_events_storage_content_hash_format_check;
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS ngm.execution_artifacts (
  id uuid PRIMARY KEY,
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  run_id uuid NOT NULL,
  event_id uuid NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal > 0),
  role text NOT NULL CHECK (role IN (
    'material', 'product', 'modified', 'deleted', 'observed', 'log',
    'byproduct', 'test_report'
  )),
  artifact_key text NOT NULL CHECK (btrim(artifact_key) <> ''),
  artifact_type text NOT NULL CHECK (btrim(artifact_type) <> ''),
  memory_id uuid,
  backend_ref text,
  digest_algorithm text,
  digest text,
  content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (memory_id IS NOT NULL OR btrim(coalesce(backend_ref, '')) <> ''),
  CHECK ((digest_algorithm IS NULL) = (digest IS NULL)),
  CHECK (
    digest_algorithm IS NULL
    OR digest_algorithm ~ '^[a-z0-9][a-z0-9_-]{0,31}$'
  ),
  CHECK (digest IS NULL OR digest ~ '^[0-9a-f]{16,128}$'),
  UNIQUE (space_id, id),
  UNIQUE (space_id, event_id, ordinal),
  FOREIGN KEY (space_id, run_id, event_id)
    REFERENCES ngm.execution_events(space_id, run_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (space_id, memory_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'execution_runs_metadata_safe_check'
      AND conrelid = 'ngm.execution_runs'::regclass
  ) THEN
    ALTER TABLE ngm.execution_runs
      ADD CONSTRAINT execution_runs_metadata_safe_check
      CHECK (
        jsonb_typeof(metadata) = 'object'
        AND ngm.execution_metadata_is_safe(metadata)
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'execution_events_metadata_safe_check'
      AND conrelid = 'ngm.execution_events'::regclass
  ) THEN
    ALTER TABLE ngm.execution_events
      ADD CONSTRAINT execution_events_metadata_safe_check
      CHECK (
        jsonb_typeof(metadata) = 'object'
        AND ngm.execution_metadata_is_safe(metadata)
      );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'execution_artifacts_metadata_safe_check'
      AND conrelid = 'ngm.execution_artifacts'::regclass
  ) THEN
    ALTER TABLE ngm.execution_artifacts
      ADD CONSTRAINT execution_artifacts_metadata_safe_check
      CHECK (
        jsonb_typeof(metadata) = 'object'
        AND ngm.execution_metadata_is_safe(metadata)
      );
  END IF;
END;
$$;

CREATE OR REPLACE FUNCTION ngm.assert_same_execution_payload(
  p_existing_id uuid,
  p_incoming_id uuid,
  p_existing_hash text,
  p_incoming_hash text,
  p_entity_name text
)
RETURNS text
LANGUAGE plpgsql
AS $$
BEGIN
  IF p_existing_id IS DISTINCT FROM p_incoming_id
     OR p_existing_hash IS DISTINCT FROM p_incoming_hash THEN
    RAISE EXCEPTION
      'idempotency key reused with different immutable content for %',
      p_entity_name
      USING ERRCODE = '23505';
  END IF;
  RETURN p_existing_hash;
END;
$$;

CREATE OR REPLACE FUNCTION ngm.reject_execution_ledger_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'execution ledger relation % is append-only', TG_TABLE_NAME
      USING ERRCODE = '55000';
  END IF;
  IF NEW IS DISTINCT FROM OLD THEN
    RAISE EXCEPTION 'execution ledger relation % rejects mutable updates', TG_TABLE_NAME
      USING ERRCODE = '55000';
  END IF;
  RETURN OLD;
END;
$$;

CREATE OR REPLACE FUNCTION ngm.validate_execution_event_append()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  v_run_started_at timestamptz;
  v_run_request_hash text;
  v_existing ngm.execution_events%ROWTYPE;
  v_latest ngm.execution_events%ROWTYPE;
  v_expected_outcome text;
BEGIN
  NEW.idempotency_key := btrim(NEW.idempotency_key);
  IF NEW.backend_ref IS NOT NULL THEN
    NEW.backend_ref := nullif(btrim(NEW.backend_ref), '');
  END IF;

  SELECT started_at, request_hash
    INTO v_run_started_at, v_run_request_hash
    FROM ngm.execution_runs
   WHERE space_id = NEW.space_id AND id = NEW.run_id
   FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'execution run does not exist in scope'
      USING ERRCODE = '23503';
  END IF;

  SELECT *
    INTO v_existing
    FROM ngm.execution_events
   WHERE space_id = NEW.space_id
     AND run_id = NEW.run_id
     AND idempotency_key = NEW.idempotency_key;

  IF v_existing.id IS NOT NULL THEN
    IF v_existing.id IS DISTINCT FROM NEW.id
       OR v_existing.content_hash IS DISTINCT FROM NEW.content_hash THEN
      RAISE EXCEPTION
        'idempotency key reused with different immutable content for execution_event'
        USING ERRCODE = '23505';
    END IF;
    NEW.storage_content_hash := v_existing.storage_content_hash;
    NEW.event_hash := v_existing.event_hash;
    RETURN NEW;
  END IF;

  SELECT *
    INTO v_latest
    FROM ngm.execution_events
   WHERE space_id = NEW.space_id AND run_id = NEW.run_id
   ORDER BY sequence DESC
   LIMIT 1;

  IF v_latest.id IS NULL THEN
    IF NEW.sequence <> 1 OR NEW.previous_event_id IS NOT NULL THEN
      RAISE EXCEPTION 'execution sequence must be contiguous'
        USING ERRCODE = '23514';
    END IF;
    IF NEW.kind <> 'run_started' THEN
      RAISE EXCEPTION 'first execution event must be run_started'
        USING ERRCODE = '23514';
    END IF;
    IF NEW.started_at <> v_run_started_at THEN
      RAISE EXCEPTION 'run_started time must equal execution run started_at'
        USING ERRCODE = '23514';
    END IF;
    IF NEW.input_hash IS DISTINCT FROM v_run_request_hash THEN
      RAISE EXCEPTION
        'run_started input_hash must equal execution run request_hash'
        USING ERRCODE = '23514';
    END IF;
  ELSE
    IF v_latest.kind IN ('run_completed', 'run_failed', 'run_cancelled') THEN
      RAISE EXCEPTION 'cannot append after terminal execution event'
        USING ERRCODE = '23514';
    END IF;
    IF NEW.sequence <> v_latest.sequence + 1 THEN
      RAISE EXCEPTION 'execution sequence must be contiguous'
        USING ERRCODE = '23514';
    END IF;
    IF NEW.previous_event_id IS DISTINCT FROM v_latest.id THEN
      RAISE EXCEPTION 'previous_event_id must reference the current execution head'
        USING ERRCODE = '23514';
    END IF;
    IF NEW.kind = 'run_started' THEN
      RAISE EXCEPTION 'run_started can only be the first execution event'
        USING ERRCODE = '23514';
    END IF;
    IF NEW.started_at < v_latest.started_at THEN
      RAISE EXCEPTION 'execution event time must be non-decreasing'
        USING ERRCODE = '23514';
    END IF;
  END IF;

  IF NEW.kind = 'run_started' AND NEW.outcome <> 'unknown' THEN
    RAISE EXCEPTION 'run_started outcome must be unknown'
      USING ERRCODE = '23514';
  END IF;

  v_expected_outcome := CASE NEW.kind
    WHEN 'run_completed' THEN 'success'
    WHEN 'run_failed' THEN 'failure'
    WHEN 'run_cancelled' THEN 'cancelled'
    ELSE NULL
  END;
  IF v_expected_outcome IS NOT NULL AND NEW.outcome <> v_expected_outcome THEN
    RAISE EXCEPTION 'terminal execution event outcome mismatch'
      USING ERRCODE = '23514';
  END IF;
  IF v_expected_outcome IS NOT NULL AND NEW.ended_at IS NULL THEN
    RAISE EXCEPTION 'terminal execution events require ended_at'
      USING ERRCODE = '23514';
  END IF;

  -- content_hash is the canonical application identity and must be preserved.
  -- storage_content_hash is a separate database-local payload integrity digest.
  NEW.storage_content_hash := encode(
    digest(
      jsonb_build_object(
        'event_id', NEW.id,
        'space_id', NEW.space_id,
        'run_id', NEW.run_id,
        'sequence', NEW.sequence,
        'previous_event_id', NEW.previous_event_id,
        'kind', NEW.kind,
        'outcome', NEW.outcome,
        'action_key', NEW.action_key,
        'started_at', NEW.started_at,
        'ended_at', NEW.ended_at,
        'command_fingerprint', NEW.command_fingerprint,
        'input_hash', NEW.input_hash,
        'output_hash', NEW.output_hash,
        'backend_ref', NEW.backend_ref,
        'idempotency_key', NEW.idempotency_key,
        'content_hash', NEW.content_hash,
        'metadata', NEW.metadata
      )::text,
      'sha256'
    ),
    'hex'
  );
  NEW.event_hash := encode(
    digest(coalesce(v_latest.event_hash, '') || ':' || NEW.content_hash, 'sha256'),
    'hex'
  );
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS execution_runs_immutable ON ngm.execution_runs;
CREATE TRIGGER execution_runs_immutable
BEFORE UPDATE OR DELETE ON ngm.execution_runs
FOR EACH ROW EXECUTE FUNCTION ngm.reject_execution_ledger_mutation();

DROP TRIGGER IF EXISTS execution_events_validate_append ON ngm.execution_events;
CREATE TRIGGER execution_events_validate_append
BEFORE INSERT ON ngm.execution_events
FOR EACH ROW EXECUTE FUNCTION ngm.validate_execution_event_append();

DROP TRIGGER IF EXISTS execution_events_immutable ON ngm.execution_events;
CREATE TRIGGER execution_events_immutable
BEFORE UPDATE OR DELETE ON ngm.execution_events
FOR EACH ROW EXECUTE FUNCTION ngm.reject_execution_ledger_mutation();

DROP TRIGGER IF EXISTS execution_artifacts_immutable ON ngm.execution_artifacts;
CREATE TRIGGER execution_artifacts_immutable
BEFORE UPDATE OR DELETE ON ngm.execution_artifacts
FOR EACH ROW EXECUTE FUNCTION ngm.reject_execution_ledger_mutation();

CREATE INDEX IF NOT EXISTS execution_runs_repository_time_idx
  ON ngm.execution_runs (space_id, repository_key, started_at DESC);
CREATE INDEX IF NOT EXISTS execution_events_kind_time_idx
  ON ngm.execution_events (space_id, kind, started_at DESC);
CREATE INDEX IF NOT EXISTS execution_artifacts_key_idx
  ON ngm.execution_artifacts (space_id, artifact_key, created_at DESC);
CREATE INDEX IF NOT EXISTS execution_artifacts_memory_idx
  ON ngm.execution_artifacts (space_id, memory_id)
  WHERE memory_id IS NOT NULL;

CREATE OR REPLACE VIEW ngm.execution_run_heads AS
SELECT
  runs.id AS run_id,
  runs.space_id,
  runs.source_id,
  runs.repository_key,
  runs.branch,
  runs.base_revision,
  runs.task_key,
  runs.session_key,
  runs.started_at,
  head.id AS head_event_id,
  head.sequence AS head_sequence,
  head.kind AS head_kind,
  head.outcome AS head_outcome,
  head.event_hash AS head_event_hash,
  CASE
    WHEN head.id IS NULL THEN 'pending'
    WHEN head.kind = 'run_completed' THEN 'completed'
    WHEN head.kind = 'run_failed' THEN 'failed'
    WHEN head.kind = 'run_cancelled' THEN 'cancelled'
    ELSE 'running'
  END AS status
FROM ngm.execution_runs AS runs
LEFT JOIN LATERAL (
  SELECT id, sequence, kind, outcome, event_hash
  FROM ngm.execution_events AS events
  WHERE events.space_id = runs.space_id AND events.run_id = runs.id
  ORDER BY sequence DESC
  LIMIT 1
) AS head ON true;

CREATE OR REPLACE VIEW ngm.execution_chain_drift AS
WITH ordered AS (
  SELECT
    events.*,
    row_number() OVER (
      PARTITION BY events.space_id, events.run_id ORDER BY events.sequence
    ) AS expected_sequence,
    lag(events.id) OVER (
      PARTITION BY events.space_id, events.run_id ORDER BY events.sequence
    ) AS expected_previous_event_id,
    lag(events.event_hash) OVER (
      PARTITION BY events.space_id, events.run_id ORDER BY events.sequence
    ) AS expected_previous_event_hash,
    encode(
      digest(
        jsonb_build_object(
          'event_id', events.id,
          'space_id', events.space_id,
          'run_id', events.run_id,
          'sequence', events.sequence,
          'previous_event_id', events.previous_event_id,
          'kind', events.kind,
          'outcome', events.outcome,
          'action_key', events.action_key,
          'started_at', events.started_at,
          'ended_at', events.ended_at,
          'command_fingerprint', events.command_fingerprint,
          'input_hash', events.input_hash,
          'output_hash', events.output_hash,
          'backend_ref', events.backend_ref,
          'idempotency_key', events.idempotency_key,
          'content_hash', events.content_hash,
          'metadata', events.metadata
        )::text,
        'sha256'
      ),
      'hex'
    ) AS expected_storage_content_hash
  FROM ngm.execution_events AS events
), checked AS (
  SELECT
    ordered.*,
    encode(
      digest(
        coalesce(expected_previous_event_hash, '') || ':' || content_hash,
        'sha256'
      ),
      'hex'
    ) AS expected_event_hash
  FROM ordered
)
SELECT
  space_id,
  run_id,
  id AS event_id,
  sequence,
  expected_sequence,
  previous_event_id,
  expected_previous_event_id,
  content_hash,
  storage_content_hash,
  expected_storage_content_hash,
  event_hash,
  expected_event_hash
FROM checked
WHERE sequence <> expected_sequence
   OR previous_event_id IS DISTINCT FROM expected_previous_event_id
   OR storage_content_hash IS DISTINCT FROM expected_storage_content_hash
   OR event_hash IS DISTINCT FROM expected_event_hash;

INSERT INTO ngm.schema_meta (schema_key, schema_version, metadata)
VALUES (
  'repository_execution_ledger',
  '0.1.0',
  jsonb_build_object(
    'status', 'verified-candidate',
    'capabilities', jsonb_build_array(
      'append_only_runs',
      'ordered_events',
      'artifact_provenance',
      'tamper_evident_chain',
      'idempotent_retries',
      'cross_layer_content_identity',
      'storage_payload_drift_detection'
    )
  )
)
ON CONFLICT (schema_key) DO UPDATE
SET schema_version = EXCLUDED.schema_version,
    metadata = EXCLUDED.metadata,
    updated_at = now();
