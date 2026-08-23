-- Synthetic prerequisites for migrations/neon/0003_research_sources_seed.sql.
-- This fixture is not a production migration and inserts no memory node.

INSERT INTO ngm.memory_spaces (
  id,
  parent_id,
  kind,
  external_key,
  name,
  metadata
)
VALUES (
  '279c0edc-e75d-5c7e-a857-2f461b4ba61e'::uuid,
  NULL,
  'project',
  'synthetic:nextgen-memory-migration-rehearsal',
  'Synthetic NextGen Memory Migration Rehearsal',
  jsonb_build_object(
    'purpose', 'migration_rehearsal',
    'synthetic', true
  )
)
ON CONFLICT DO NOTHING;

INSERT INTO ngm.source_principals (
  id,
  space_id,
  source_key,
  source_type,
  authority_class,
  authority_score,
  origin_uri,
  metadata
)
VALUES (
  '049b6cff-c7a6-5116-a38f-5a7527ca3a21'::uuid,
  '279c0edc-e75d-5c7e-a857-2f461b4ba61e'::uuid,
  'synthetic:research-sources-seed',
  'research_corpus',
  'contextual',
  0.650,
  NULL,
  jsonb_build_object(
    'purpose', 'migration_rehearsal',
    'synthetic', true
  )
)
ON CONFLICT DO NOTHING;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM ngm.memory_spaces
    WHERE id = '279c0edc-e75d-5c7e-a857-2f461b4ba61e'::uuid
      AND parent_id IS NULL
      AND kind = 'project'
      AND external_key = 'synthetic:nextgen-memory-migration-rehearsal'
      AND name = 'Synthetic NextGen Memory Migration Rehearsal'
      AND metadata = jsonb_build_object(
        'purpose', 'migration_rehearsal',
        'synthetic', true
      )
  ) THEN
    RAISE EXCEPTION 'synthetic migration rehearsal space differs';
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM ngm.source_principals
    WHERE id = '049b6cff-c7a6-5116-a38f-5a7527ca3a21'::uuid
      AND space_id = '279c0edc-e75d-5c7e-a857-2f461b4ba61e'::uuid
      AND source_key = 'synthetic:research-sources-seed'
      AND source_type = 'research_corpus'
      AND authority_class = 'contextual'
      AND authority_score = 0.650
      AND origin_uri IS NULL
      AND metadata = jsonb_build_object(
        'purpose', 'migration_rehearsal',
        'synthetic', true
      )
  ) THEN
    RAISE EXCEPTION 'synthetic migration rehearsal principal differs';
  END IF;
END;
$$;
