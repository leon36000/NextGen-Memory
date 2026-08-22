-- Post-Action Causal Credit v0 persistence contract.
-- Additive and idempotent. Existing non-causal feedback rows keep their behavior.

ALTER TABLE ngm.memory_feedback
  ADD COLUMN IF NOT EXISTS credit_evaluation_id uuid;
ALTER TABLE ngm.memory_feedback
  ADD COLUMN IF NOT EXISTS evidence_key text;
ALTER TABLE ngm.memory_feedback
  ADD COLUMN IF NOT EXISTS content_hash text;

CREATE OR REPLACE FUNCTION ngm.credit_metadata_is_safe(p_metadata jsonb)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
STRICT
AS $$
DECLARE
  v_key text;
  v_value jsonb;
BEGIN
  IF octet_length(p_metadata::text) > 8192 THEN
    RETURN false;
  END IF;

  IF jsonb_typeof(p_metadata) = 'object' THEN
    FOR v_key, v_value IN SELECT key, value FROM jsonb_each(p_metadata)
    LOOP
      IF lower(v_key) = ANY (ARRAY[
        'api_key', 'argv', 'command', 'command_text', 'diff', 'env',
        'environment', 'notes', 'password', 'patch', 'patch_text', 'prompt',
        'query', 'query_text', 'raw', 'raw_payload', 'secret', 'stderr',
        'stdout', 'token'
      ]) THEN
        RETURN false;
      END IF;
      IF NOT ngm.credit_metadata_is_safe(v_value) THEN
        RETURN false;
      END IF;
    END LOOP;
  ELSIF jsonb_typeof(p_metadata) = 'array' THEN
    FOR v_value IN SELECT value FROM jsonb_array_elements(p_metadata)
    LOOP
      IF NOT ngm.credit_metadata_is_safe(v_value) THEN
        RETURN false;
      END IF;
    END LOOP;
  END IF;

  RETURN true;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'memory_feedback_causal_complete_check'
      AND conrelid = 'ngm.memory_feedback'::regclass
  ) THEN
    ALTER TABLE ngm.memory_feedback
      ADD CONSTRAINT memory_feedback_causal_complete_check
      CHECK (
        credit_evaluation_id IS NULL
        OR (
          node_id IS NOT NULL
          AND router_decision_id IS NOT NULL
          AND evidence_key = 'paired_leave_one_out_v0'
          AND content_hash ~ '^[0-9a-f]{64}$'
          AND notes IS NULL
          AND jsonb_typeof(metadata) = 'object'
          AND ngm.credit_metadata_is_safe(metadata)
        )
      );
  END IF;
END;
$$;

CREATE UNIQUE INDEX IF NOT EXISTS memory_feedback_causal_identity_uidx
  ON ngm.memory_feedback (space_id, credit_evaluation_id, node_id)
  WHERE credit_evaluation_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS memory_feedback_causal_evaluation_idx
  ON ngm.memory_feedback (space_id, credit_evaluation_id, created_at DESC)
  WHERE credit_evaluation_id IS NOT NULL;

CREATE OR REPLACE FUNCTION ngm.assert_same_causal_feedback_payload(
  p_existing_id uuid,
  p_incoming_id uuid,
  p_existing_hash text,
  p_incoming_hash text
)
RETURNS text
LANGUAGE plpgsql
AS $$
BEGIN
  IF p_existing_id IS DISTINCT FROM p_incoming_id
     OR p_existing_hash IS DISTINCT FROM p_incoming_hash THEN
    RAISE EXCEPTION
      'idempotency key reused with different immutable content for causal feedback'
      USING ERRCODE = '23505';
  END IF;
  RETURN p_existing_hash;
END;
$$;

CREATE OR REPLACE FUNCTION ngm.reject_causal_feedback_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.credit_evaluation_id IS NOT NULL THEN
    IF TG_OP = 'DELETE' THEN
      RAISE EXCEPTION 'causal memory feedback is append-only'
        USING ERRCODE = '55000';
    END IF;
    IF NEW IS DISTINCT FROM OLD THEN
      RAISE EXCEPTION 'causal memory feedback rejects mutable updates'
        USING ERRCODE = '55000';
    END IF;
  END IF;

  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS memory_feedback_causal_immutable
  ON ngm.memory_feedback;
CREATE TRIGGER memory_feedback_causal_immutable
BEFORE UPDATE OR DELETE ON ngm.memory_feedback
FOR EACH ROW EXECUTE FUNCTION ngm.reject_causal_feedback_mutation();

INSERT INTO ngm.schema_meta (schema_key, schema_version, metadata)
VALUES (
  'post_action_causal_credit',
  '0.1.0',
  jsonb_build_object(
    'status', 'verified-candidate',
    'evidence_key', 'paired_leave_one_out_v0',
    'capabilities', jsonb_build_array(
      'paired_leave_one_out',
      'deterministic_feedback_identity',
      'append_only_causal_rows',
      'safe_aggregate_metadata'
    )
  )
)
ON CONFLICT (schema_key) DO UPDATE
SET schema_version = EXCLUDED.schema_version,
    metadata = EXCLUDED.metadata,
    updated_at = now();
