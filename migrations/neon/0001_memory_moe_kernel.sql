-- NextGen Memory canonical Memory-MoE ledger (schema version 0.1.0).
-- This migration is additive and idempotent. It contains no environment credentials.

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS ngm;

CREATE TABLE IF NOT EXISTS ngm.schema_meta (
  schema_key text PRIMARY KEY,
  schema_version text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ngm.memory_spaces (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_id uuid REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  kind text NOT NULL,
  external_key text NOT NULL,
  name text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (kind, external_key)
);

CREATE TABLE IF NOT EXISTS ngm.source_principals (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  source_key text NOT NULL,
  source_type text NOT NULL,
  authority_class text NOT NULL DEFAULT 'contextual',
  authority_score numeric(4,3) NOT NULL DEFAULT 0.500
    CHECK (authority_score >= 0 AND authority_score <= 1),
  origin_uri text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (space_id, source_key),
  UNIQUE (space_id, id)
);

CREATE TABLE IF NOT EXISTS ngm.memory_nodes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  source_id uuid NOT NULL,
  kind text NOT NULL,
  layer text NOT NULL
    CHECK (layer IN ('raw','working','episodic','semantic','procedural','meta')),
  expert_keys text[] NOT NULL DEFAULT ARRAY[]::text[],
  subject_key text,
  body_text text,
  body_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  event_time timestamptz,
  knowledge_time timestamptz NOT NULL DEFAULT now(),
  valid_from timestamptz,
  valid_to timestamptz,
  confidence numeric(4,3) NOT NULL DEFAULT 0.500
    CHECK (confidence >= 0 AND confidence <= 1),
  authority numeric(4,3) NOT NULL DEFAULT 0.500
    CHECK (authority >= 0 AND authority <= 1),
  sensitivity text NOT NULL DEFAULT 'internal'
    CHECK (sensitivity IN ('public','internal','sensitive','secret')),
  content_hash text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (body_text IS NOT NULL OR body_json <> '{}'::jsonb),
  CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
  UNIQUE (space_id, id),
  FOREIGN KEY (space_id, source_id)
    REFERENCES ngm.source_principals(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.memory_embeddings (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  node_id uuid NOT NULL,
  model text NOT NULL,
  dimensions integer NOT NULL CHECK (dimensions > 0),
  embedding vector NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (vector_dims(embedding) = dimensions),
  UNIQUE (node_id, model),
  FOREIGN KEY (space_id, node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.memory_edges (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  from_node_id uuid NOT NULL,
  to_node_id uuid NOT NULL,
  relation text NOT NULL,
  confidence numeric(4,3) NOT NULL DEFAULT 1.000
    CHECK (confidence >= 0 AND confidence <= 1),
  evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (from_node_id <> to_node_id),
  UNIQUE (from_node_id, to_node_id, relation),
  FOREIGN KEY (space_id, from_node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (space_id, to_node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.state_resolutions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  slot_key text NOT NULL,
  candidate_node_id uuid,
  previous_node_id uuid,
  verdict text NOT NULL
    CHECK (verdict IN ('KEEP','SUPERSEDE','INVALIDATE','UNKNOWN','QUARANTINE')),
  resolver text NOT NULL,
  evidence_node_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
  reasoning jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (space_id, id),
  FOREIGN KEY (space_id, candidate_node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (space_id, previous_node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.state_slots (
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  slot_key text NOT NULL,
  current_node_id uuid,
  status text NOT NULL DEFAULT 'unknown'
    CHECK (status IN ('active','unknown','stale','quarantined')),
  resolution_id uuid,
  version bigint NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (space_id, slot_key),
  FOREIGN KEY (space_id, current_node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (space_id, resolution_id)
    REFERENCES ngm.state_resolutions(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.expert_registry (
  expert_key text PRIMARY KEY,
  description text NOT NULL,
  primary_backend text NOT NULL CHECK (primary_backend IN ('neon','mongodb','hybrid')),
  collection_name text,
  enabled boolean NOT NULL DEFAULT true,
  priority integer NOT NULL DEFAULT 100,
  default_budget_tokens integer NOT NULL DEFAULT 800
    CHECK (default_budget_tokens >= 0),
  hard_max_budget_tokens integer NOT NULL DEFAULT 2400
    CHECK (hard_max_budget_tokens >= default_budget_tokens),
  read_strategy jsonb NOT NULL DEFAULT '{}'::jsonb,
  write_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ngm.router_decisions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  session_key text,
  task_key text,
  query_hash text NOT NULL,
  query_features jsonb NOT NULL DEFAULT '{}'::jsonb,
  eligible_experts text[] NOT NULL DEFAULT ARRAY[]::text[],
  selected_experts text[] NOT NULL DEFAULT ARRAY[]::text[],
  expert_budgets jsonb NOT NULL DEFAULT '{}'::jsonb,
  escalation_policy jsonb NOT NULL DEFAULT '{}'::jsonb,
  route_confidence numeric(4,3)
    CHECK (route_confidence >= 0 AND route_confidence <= 1),
  decision_reason jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (space_id, id),
  CHECK (selected_experts <@ eligible_experts)
);

CREATE TABLE IF NOT EXISTS ngm.retrieval_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  router_decision_id uuid NOT NULL,
  expert_key text NOT NULL REFERENCES ngm.expert_registry(expert_key) ON DELETE RESTRICT,
  node_id uuid,
  backend_ref text,
  rank integer NOT NULL CHECK (rank > 0),
  raw_score double precision,
  final_score double precision,
  estimated_tokens integer CHECK (estimated_tokens IS NULL OR estimated_tokens >= 0),
  selected_for_context boolean NOT NULL DEFAULT false,
  used_in_action boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (node_id IS NOT NULL OR backend_ref IS NOT NULL),
  FOREIGN KEY (space_id, router_decision_id)
    REFERENCES ngm.router_decisions(space_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (space_id, node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.memory_feedback (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  node_id uuid,
  router_decision_id uuid,
  verdict text NOT NULL
    CHECK (verdict IN ('helpful','neutral','harmful','stale','incorrect','decisive','redundant')),
  reward double precision,
  task_success boolean,
  token_delta integer,
  latency_delta_ms double precision,
  notes text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (node_id IS NOT NULL OR router_decision_id IS NOT NULL),
  FOREIGN KEY (space_id, node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (space_id, router_decision_id)
    REFERENCES ngm.router_decisions(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.write_verifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  node_id uuid NOT NULL,
  verifier_source_id uuid,
  coverage numeric(4,3) CHECK (coverage >= 0 AND coverage <= 1),
  preservation numeric(4,3) CHECK (preservation >= 0 AND preservation <= 1),
  faithfulness numeric(4,3) CHECK (faithfulness >= 0 AND faithfulness <= 1),
  verdict text NOT NULL CHECK (verdict IN ('accept','reject','quarantine')),
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (space_id, node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (space_id, verifier_source_id)
    REFERENCES ngm.source_principals(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.skill_registry (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  node_id uuid NOT NULL,
  skill_key text NOT NULL,
  version integer NOT NULL CHECK (version > 0),
  status text NOT NULL DEFAULT 'candidate'
    CHECK (status IN ('candidate','validated','deprecated','quarantined')),
  trigger_spec jsonb NOT NULL DEFAULT '{}'::jsonb,
  preconditions jsonb NOT NULL DEFAULT '{}'::jsonb,
  procedure jsonb NOT NULL DEFAULT '{}'::jsonb,
  validation_spec jsonb NOT NULL DEFAULT '{}'::jsonb,
  utility_score double precision NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (node_id),
  UNIQUE (space_id, skill_key, version),
  FOREIGN KEY (space_id, node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.project_checkpoints (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  checkpoint_key text NOT NULL,
  summary_text text NOT NULL,
  state_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  derived_from uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
  created_at timestamptz NOT NULL DEFAULT now()
);

-- E-string function bodies remain parser-safe for migration tools that split statements.
CREATE OR REPLACE FUNCTION ngm.set_memory_content_hash()
RETURNS trigger
LANGUAGE plpgsql
AS E'BEGIN\n  NEW.content_hash := encode(\n    digest(\n      jsonb_build_object(\n        ''kind'', NEW.kind,\n        ''body_text'', NEW.body_text,\n        ''body_json'', NEW.body_json\n      )::text,\n      ''sha256''\n    ),\n    ''hex''\n  );\n  RETURN NEW;\nEND;';

DROP TRIGGER IF EXISTS memory_nodes_hash_before_insert ON ngm.memory_nodes;
CREATE TRIGGER memory_nodes_hash_before_insert
BEFORE INSERT ON ngm.memory_nodes
FOR EACH ROW EXECUTE FUNCTION ngm.set_memory_content_hash();

CREATE OR REPLACE FUNCTION ngm.reject_immutable_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS E'BEGIN\n  RAISE EXCEPTION ''NextGen Memory immutable relation % does not allow %; append a corrective event instead'', TG_TABLE_NAME, TG_OP\n    USING ERRCODE = ''55000'';\nEND;';

DROP TRIGGER IF EXISTS memory_nodes_immutable ON ngm.memory_nodes;
CREATE TRIGGER memory_nodes_immutable
BEFORE UPDATE OR DELETE ON ngm.memory_nodes
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

DROP TRIGGER IF EXISTS memory_embeddings_immutable ON ngm.memory_embeddings;
CREATE TRIGGER memory_embeddings_immutable
BEFORE UPDATE OR DELETE ON ngm.memory_embeddings
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

DROP TRIGGER IF EXISTS memory_edges_immutable ON ngm.memory_edges;
CREATE TRIGGER memory_edges_immutable
BEFORE UPDATE OR DELETE ON ngm.memory_edges
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

DROP TRIGGER IF EXISTS state_resolutions_immutable ON ngm.state_resolutions;
CREATE TRIGGER state_resolutions_immutable
BEFORE UPDATE OR DELETE ON ngm.state_resolutions
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

DROP TRIGGER IF EXISTS router_decisions_immutable ON ngm.router_decisions;
CREATE TRIGGER router_decisions_immutable
BEFORE UPDATE OR DELETE ON ngm.router_decisions
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

DROP TRIGGER IF EXISTS retrieval_events_immutable ON ngm.retrieval_events;
CREATE TRIGGER retrieval_events_immutable
BEFORE UPDATE OR DELETE ON ngm.retrieval_events
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

DROP TRIGGER IF EXISTS memory_feedback_immutable ON ngm.memory_feedback;
CREATE TRIGGER memory_feedback_immutable
BEFORE UPDATE OR DELETE ON ngm.memory_feedback
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

DROP TRIGGER IF EXISTS write_verifications_immutable ON ngm.write_verifications;
CREATE TRIGGER write_verifications_immutable
BEFORE UPDATE OR DELETE ON ngm.write_verifications
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

DROP TRIGGER IF EXISTS project_checkpoints_immutable ON ngm.project_checkpoints;
CREATE TRIGGER project_checkpoints_immutable
BEFORE UPDATE OR DELETE ON ngm.project_checkpoints
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

CREATE INDEX IF NOT EXISTS memory_nodes_scope_layer_time_idx
  ON ngm.memory_nodes (space_id, layer, knowledge_time DESC);
CREATE INDEX IF NOT EXISTS memory_nodes_subject_time_idx
  ON ngm.memory_nodes (space_id, subject_key, knowledge_time DESC)
  WHERE subject_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS memory_nodes_experts_gin_idx
  ON ngm.memory_nodes USING gin (expert_keys);
CREATE INDEX IF NOT EXISTS memory_nodes_json_gin_idx
  ON ngm.memory_nodes USING gin (body_json);
CREATE INDEX IF NOT EXISTS memory_nodes_fts_idx
  ON ngm.memory_nodes USING gin (to_tsvector('simple', coalesce(body_text, '')));
CREATE INDEX IF NOT EXISTS memory_edges_from_idx
  ON ngm.memory_edges (space_id, from_node_id, relation);
CREATE INDEX IF NOT EXISTS memory_edges_to_idx
  ON ngm.memory_edges (space_id, to_node_id, relation);
CREATE INDEX IF NOT EXISTS state_resolutions_slot_idx
  ON ngm.state_resolutions (space_id, slot_key, created_at DESC);
CREATE INDEX IF NOT EXISTS router_decisions_space_time_idx
  ON ngm.router_decisions (space_id, created_at DESC);
CREATE INDEX IF NOT EXISTS retrieval_events_router_idx
  ON ngm.retrieval_events (space_id, router_decision_id, rank);
CREATE INDEX IF NOT EXISTS retrieval_events_node_idx
  ON ngm.retrieval_events (space_id, node_id) WHERE node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS memory_feedback_node_idx
  ON ngm.memory_feedback (space_id, node_id, created_at DESC) WHERE node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS project_checkpoints_latest_idx
  ON ngm.project_checkpoints (space_id, checkpoint_key, created_at DESC);

CREATE OR REPLACE VIEW ngm.current_state AS
SELECT
  s.space_id,
  s.slot_key,
  s.status,
  s.version,
  s.updated_at,
  s.current_node_id,
  n.kind AS node_kind,
  n.body_text,
  n.body_json,
  n.event_time,
  n.knowledge_time,
  n.confidence,
  n.authority,
  s.resolution_id
FROM ngm.state_slots AS s
LEFT JOIN ngm.memory_nodes AS n
  ON n.space_id = s.space_id AND n.id = s.current_node_id;

CREATE OR REPLACE VIEW ngm.node_utility AS
SELECT
  n.space_id,
  n.id AS node_id,
  count(f.id) AS feedback_count,
  avg(f.reward) FILTER (WHERE f.reward IS NOT NULL) AS avg_reward,
  count(*) FILTER (WHERE f.verdict IN ('helpful','decisive')) AS positive_count,
  count(*) FILTER (WHERE f.verdict IN ('harmful','stale','incorrect')) AS negative_count,
  max(f.created_at) AS last_feedback_at
FROM ngm.memory_nodes AS n
LEFT JOIN ngm.memory_feedback AS f
  ON f.space_id = n.space_id AND f.node_id = n.id
GROUP BY n.space_id, n.id;

CREATE OR REPLACE VIEW ngm.latest_checkpoints AS
SELECT DISTINCT ON (space_id, checkpoint_key)
  id,
  space_id,
  checkpoint_key,
  summary_text,
  state_json,
  derived_from,
  created_at
FROM ngm.project_checkpoints
ORDER BY space_id, checkpoint_key, created_at DESC;

INSERT INTO ngm.schema_meta (schema_key, schema_version, metadata)
VALUES ('memory_moe_kernel', '0.1.0', '{"status":"bootstrap"}'::jsonb)
ON CONFLICT (schema_key) DO NOTHING;

INSERT INTO ngm.expert_registry (
  expert_key,
  description,
  primary_backend,
  collection_name,
  priority,
  default_budget_tokens,
  hard_max_budget_tokens,
  read_strategy,
  write_policy
)
VALUES
  ('working', 'Bounded task-local working state', 'neon', NULL, 10, 600, 1200,
    '{"modes":["key","recent"]}', '{"admission":"explicit"}'),
  ('execution', 'Deterministic observations, modifications, commands and tests',
    'neon', NULL, 20, 900, 1800,
    '{"modes":["state","recent","exact"]}', '{"admission":"runtime"}'),
  ('episodic', 'Exact past episodes and trajectories', 'mongodb', 'memory_objects',
    60, 1200, 3200, '{"modes":["hybrid","temporal"]}', '{"admission":"episode"}'),
  ('semantic', 'Stable facts and abstractions', 'hybrid', 'memory_objects',
    30, 800, 2000, '{"modes":["hybrid","graph"]}', '{"admission":"verified"}'),
  ('temporal', 'State evolution and temporal relations', 'neon', NULL,
    25, 800, 1800, '{"modes":["state","range","graph"]}', '{"admission":"verified"}'),
  ('causal', 'Cause/effect and evidence chains', 'neon', NULL,
    35, 900, 2200, '{"modes":["graph","evidence"]}', '{"admission":"verified"}'),
  ('procedural', 'Reusable workflows and skills', 'hybrid', 'memory_objects',
    40, 1000, 2400, '{"modes":["trigger","hybrid"]}',
    '{"admission":"validated_skill"}'),
  ('failure', 'Failed attempts, root causes and recovery precedents',
    'hybrid', 'memory_objects', 15, 900, 2200,
    '{"modes":["trigger","hybrid","exact"]}', '{"admission":"verified_failure"}'),
  ('decision', 'Architecture, product and user decisions', 'neon', NULL,
    12, 700, 1600, '{"modes":["state","key","temporal"]}',
    '{"admission":"authorized"}'),
  ('repository', 'Repository entities, dependencies and change history',
    'hybrid', 'repository_artifacts', 25, 1200, 3000,
    '{"modes":["structural","hybrid"]}', '{"admission":"runtime_or_vcs"}'),
  ('research', 'Research papers, external sources and notes',
    'mongodb', 'research_sources', 70, 1200, 3200,
    '{"modes":["hybrid","citation"]}', '{"admission":"provenance_required"}'),
  ('feedback', 'Memory and routing quality signals', 'neon', NULL,
    90, 400, 1000, '{"modes":["aggregate","recent"]}', '{"admission":"outcome"}')
ON CONFLICT (expert_key) DO UPDATE
SET description = EXCLUDED.description,
    primary_backend = EXCLUDED.primary_backend,
    collection_name = EXCLUDED.collection_name,
    priority = EXCLUDED.priority,
    default_budget_tokens = EXCLUDED.default_budget_tokens,
    hard_max_budget_tokens = EXCLUDED.hard_max_budget_tokens,
    read_strategy = EXCLUDED.read_strategy,
    write_policy = EXCLUDED.write_policy,
    updated_at = now();
