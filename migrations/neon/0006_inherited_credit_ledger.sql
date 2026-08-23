-- Inherited Credit Ledger v0 (schema version 0.1.0).
-- Additive candidate migration. It never writes ngm.memory_feedback and does
-- not redefine ngm.node_utility. Apply only to a reviewed temporary branch.

CREATE OR REPLACE FUNCTION ngm.is_finite_float8(p_value double precision)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
STRICT
AS $$
  SELECT
    p_value > '-Infinity'::double precision
    AND p_value < 'Infinity'::double precision;
$$;

-- memory_edges already has a globally unique primary key. The scoped unique
-- identity below permits same-space composite foreign keys from observations.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'memory_edges_space_id_id_key'
      AND conrelid = 'ngm.memory_edges'::regclass
  ) THEN
    ALTER TABLE ngm.memory_edges
      ADD CONSTRAINT memory_edges_space_id_id_key
      UNIQUE (space_id, id);
  END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS ngm.provenance_credit_evaluations (
  id uuid PRIMARY KEY,
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  direct_credit_id uuid NOT NULL,
  evidence_group_id uuid NOT NULL,
  root_node_id uuid NOT NULL,
  source_kind text NOT NULL
    CHECK (source_kind IN ('causal','interaction')),
  direct_value double precision NOT NULL
    CHECK (ngm.is_finite_float8(direct_value)),
  direct_standard_error double precision NOT NULL
    CHECK (
      ngm.is_finite_float8(direct_standard_error)
      AND direct_standard_error >= 0
    ),
  trial_count integer NOT NULL CHECK (trial_count > 0),
  context_set_hash text NOT NULL
    CHECK (context_set_hash ~ '^[0-9a-f]{64}$'),
  continuation_set_hash text NOT NULL
    CHECK (continuation_set_hash ~ '^[0-9a-f]{64}$'),
  graph_fingerprint text NOT NULL
    CHECK (graph_fingerprint ~ '^[0-9a-f]{64}$'),
  policy_fingerprint text NOT NULL
    CHECK (policy_fingerprint ~ '^[0-9a-f]{64}$'),
  policy_version text NOT NULL
    CHECK (policy_version = btrim(policy_version) AND policy_version <> ''),
  status text NOT NULL
    CHECK (status IN ('propagated','abstained')),
  result_hash text NOT NULL
    CHECK (result_hash ~ '^[0-9a-f]{64}$'),
  accounting_id uuid NOT NULL,
  content_hash text NOT NULL
    CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (space_id, id),
  UNIQUE (space_id, direct_credit_id, graph_fingerprint, policy_fingerprint),
  FOREIGN KEY (space_id, root_node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.inherited_credit_contributions (
  id uuid PRIMARY KEY,
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  evaluation_id uuid NOT NULL,
  target_node_id uuid NOT NULL,
  propagated_value double precision NOT NULL
    CHECK (ngm.is_finite_float8(propagated_value)),
  propagated_standard_error double precision NOT NULL
    CHECK (
      ngm.is_finite_float8(propagated_standard_error)
      AND propagated_standard_error >= 0
    ),
  structural_confidence double precision NOT NULL
    CHECK (
      ngm.is_finite_float8(structural_confidence)
      AND structural_confidence >= 0 AND structural_confidence <= 1
    ),
  minimum_edge_confidence double precision NOT NULL
    CHECK (
      ngm.is_finite_float8(minimum_edge_confidence)
      AND minimum_edge_confidence >= 0 AND minimum_edge_confidence <= 1
    ),
  depth integer NOT NULL CHECK (depth > 0),
  relation_path text[] NOT NULL,
  edge_path uuid[] NOT NULL,
  path_fingerprint text NOT NULL
    CHECK (path_fingerprint ~ '^[0-9a-f]{64}$'),
  content_hash text NOT NULL
    CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (cardinality(relation_path) = depth),
  CHECK (cardinality(edge_path) = depth),
  CHECK (array_position(relation_path, NULL) IS NULL),
  CHECK (array_position(relation_path, '') IS NULL),
  CHECK (array_position(edge_path, NULL) IS NULL),
  UNIQUE (space_id, id),
  UNIQUE (space_id, evaluation_id, path_fingerprint),
  FOREIGN KEY (space_id, evaluation_id)
    REFERENCES ngm.provenance_credit_evaluations(space_id, id)
    ON DELETE RESTRICT,
  FOREIGN KEY (space_id, target_node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.provenance_credit_observations (
  id uuid PRIMARY KEY,
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  evaluation_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('blocked','abstention')),
  current_node_id uuid,
  target_node_id uuid,
  edge_id uuid,
  relation text,
  reason text NOT NULL
    CHECK (reason = btrim(reason) AND reason <> ''),
  depth integer,
  path_fingerprint text
    CHECK (
      path_fingerprint IS NULL
      OR path_fingerprint ~ '^[0-9a-f]{64}$'
    ),
  content_hash text NOT NULL
    CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (relation IS NULL OR (relation = btrim(relation) AND relation <> '')),
  CHECK (depth IS NULL OR depth >= 0),
  CHECK (
    (
      kind = 'blocked'
      AND current_node_id IS NOT NULL
      AND target_node_id IS NOT NULL
      AND edge_id IS NOT NULL
      AND relation IS NOT NULL
      AND depth IS NOT NULL
      AND path_fingerprint IS NOT NULL
    )
    OR
    (
      kind = 'abstention'
      AND current_node_id IS NULL
      AND target_node_id IS NULL
      AND edge_id IS NULL
      AND relation IS NULL
      AND depth IS NULL
      AND path_fingerprint IS NULL
    )
  ),
  UNIQUE (space_id, id),
  FOREIGN KEY (space_id, evaluation_id)
    REFERENCES ngm.provenance_credit_evaluations(space_id, id)
    ON DELETE RESTRICT,
  FOREIGN KEY (space_id, current_node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (space_id, target_node_id)
    REFERENCES ngm.memory_nodes(space_id, id) ON DELETE RESTRICT,
  FOREIGN KEY (space_id, edge_id)
    REFERENCES ngm.memory_edges(space_id, id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS ngm.provenance_credit_accounting (
  id uuid PRIMARY KEY,
  space_id uuid NOT NULL REFERENCES ngm.memory_spaces(id) ON DELETE RESTRICT,
  evaluation_id uuid NOT NULL,
  direct_value double precision NOT NULL
    CHECK (ngm.is_finite_float8(direct_value)),
  propagation_budget double precision NOT NULL
    CHECK (ngm.is_finite_float8(propagation_budget)),
  propagated_value double precision NOT NULL
    CHECK (ngm.is_finite_float8(propagated_value)),
  dropped_value double precision NOT NULL
    CHECK (ngm.is_finite_float8(dropped_value)),
  unallocated_value double precision NOT NULL
    CHECK (ngm.is_finite_float8(unallocated_value)),
  conservation_residual double precision NOT NULL
    CHECK (ngm.is_finite_float8(conservation_residual)),
  content_hash text NOT NULL
    CHECK (content_hash ~ '^[0-9a-f]{64}$'),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (space_id, id),
  UNIQUE (space_id, evaluation_id),
  UNIQUE (space_id, evaluation_id, id),
  FOREIGN KEY (space_id, evaluation_id)
    REFERENCES ngm.provenance_credit_evaluations(space_id, id)
    ON DELETE RESTRICT
    DEFERRABLE INITIALLY DEFERRED
);

-- The circular, deferred composite key guarantees that every evaluation has
-- exactly one accounting row, and that row points back to the same evaluation.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'provenance_credit_evaluations_accounting_fk'
      AND conrelid = 'ngm.provenance_credit_evaluations'::regclass
  ) THEN
    ALTER TABLE ngm.provenance_credit_evaluations
      ADD CONSTRAINT provenance_credit_evaluations_accounting_fk
      FOREIGN KEY (space_id, id, accounting_id)
      REFERENCES ngm.provenance_credit_accounting(space_id, evaluation_id, id)
      ON DELETE RESTRICT
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
END;
$$;

DROP TRIGGER IF EXISTS provenance_credit_evaluations_immutable
  ON ngm.provenance_credit_evaluations;
CREATE TRIGGER provenance_credit_evaluations_immutable
BEFORE UPDATE OR DELETE ON ngm.provenance_credit_evaluations
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

DROP TRIGGER IF EXISTS inherited_credit_contributions_immutable
  ON ngm.inherited_credit_contributions;
CREATE TRIGGER inherited_credit_contributions_immutable
BEFORE UPDATE OR DELETE ON ngm.inherited_credit_contributions
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

DROP TRIGGER IF EXISTS provenance_credit_observations_immutable
  ON ngm.provenance_credit_observations;
CREATE TRIGGER provenance_credit_observations_immutable
BEFORE UPDATE OR DELETE ON ngm.provenance_credit_observations
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

DROP TRIGGER IF EXISTS provenance_credit_accounting_immutable
  ON ngm.provenance_credit_accounting;
CREATE TRIGGER provenance_credit_accounting_immutable
BEFORE UPDATE OR DELETE ON ngm.provenance_credit_accounting
FOR EACH ROW EXECUTE FUNCTION ngm.reject_immutable_mutation();

CREATE INDEX IF NOT EXISTS provenance_credit_evaluations_root_idx
  ON ngm.provenance_credit_evaluations (
    space_id,
    root_node_id,
    created_at DESC
  );
CREATE INDEX IF NOT EXISTS inherited_credit_contributions_target_idx
  ON ngm.inherited_credit_contributions (
    space_id,
    target_node_id,
    created_at DESC
  );
CREATE INDEX IF NOT EXISTS provenance_credit_observations_evaluation_idx
  ON ngm.provenance_credit_observations (
    space_id,
    evaluation_id,
    created_at DESC
  );
CREATE INDEX IF NOT EXISTS provenance_credit_accounting_evaluation_idx
  ON ngm.provenance_credit_accounting (
    space_id,
    evaluation_id
  );

CREATE OR REPLACE VIEW ngm.node_inherited_credit AS
SELECT
  node.space_id,
  node.id AS node_id,
  count(contribution.id) AS inherited_contribution_count,
  sum(contribution.propagated_value)
    FILTER (WHERE contribution.id IS NOT NULL) AS inherited_value_sum,
  sum(abs(contribution.propagated_value))
    FILTER (WHERE contribution.id IS NOT NULL) AS inherited_absolute_value_sum,
  sum(contribution.propagated_standard_error)
    FILTER (WHERE contribution.id IS NOT NULL) AS inherited_standard_error_sum,
  min(contribution.structural_confidence)
    FILTER (WHERE contribution.id IS NOT NULL) AS minimum_structural_confidence,
  max(contribution.created_at) AS last_inherited_credit_at
FROM ngm.memory_nodes AS node
LEFT JOIN ngm.inherited_credit_contributions AS contribution
  ON contribution.space_id = node.space_id
 AND contribution.target_node_id = node.id
GROUP BY node.space_id, node.id;

CREATE OR REPLACE VIEW ngm.node_learning_evidence AS
SELECT
  direct.space_id,
  direct.node_id,
  direct.feedback_count AS direct_feedback_count,
  direct.avg_reward AS direct_avg_reward,
  direct.positive_count AS direct_positive_count,
  direct.negative_count AS direct_negative_count,
  direct.last_feedback_at AS last_direct_feedback_at,
  inherited.inherited_contribution_count,
  inherited.inherited_value_sum,
  inherited.inherited_absolute_value_sum,
  inherited.inherited_standard_error_sum,
  inherited.minimum_structural_confidence,
  inherited.last_inherited_credit_at
FROM ngm.node_utility AS direct
LEFT JOIN ngm.node_inherited_credit AS inherited
  ON inherited.space_id = direct.space_id
 AND inherited.node_id = direct.node_id;

INSERT INTO ngm.schema_meta (schema_key, schema_version, metadata)
VALUES (
  'inherited_credit_ledger',
  '0.1.0',
  jsonb_build_object(
    'status', 'candidate',
    'capabilities', jsonb_build_array(
      'separate_inherited_evidence',
      'path_specific_contributions',
      'blocked_and_abstention_observations',
      'exact_mass_accounting',
      'append_only_replay',
      'direct_utility_separation'
    )
  )
)
ON CONFLICT (schema_key) DO UPDATE
SET schema_version = EXCLUDED.schema_version,
    metadata = EXCLUDED.metadata,
    updated_at = now();
