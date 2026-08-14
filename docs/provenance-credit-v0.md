# Provenance Credit v0

## Purpose

Provenance Credit v0 propagates a bounded fraction of already intervention-grounded direct memory credit to upstream provenance memories.

It does **not** infer causality from graph proximity. A memory receives inherited credit only when every traversed relation has an explicit reviewed policy permitting that sign and direction of propagation.

The component is pure Python and performs no database write.

## Position in the learning path

```text
Execution evidence
  → matched counterfactual outcomes
  → Post-Action Causal Credit v0
  → Interaction Credit v0
  → preferred direct credit
  → Provenance Credit v0
  → inherited structural evidence
```

Direct and inherited credit remain different evidence classes. Inherited evidence is never rewritten as a direct intervention result.

## Why ordinary graph spreading is unsafe

The canonical project graph contains heterogeneous relations:

- `supported_by`;
- `authorizes`;
- `constrained_by`;
- `explains`;
- `followed_by`;
- `implements`;
- `motivates`;
- `superseded_by`.

These relations do not all mean “causally produced.” For example, chronology or authorization should not automatically receive utility reward.

A naive breadth-first algorithm can also copy the complete incoming value to every child. Two children then receive twice the original propagation budget, four grandchildren can receive four times the budget, and so on.

Provenance Credit v0 therefore uses explicit typed policies and mass conservation.

## Initial relation policy

`project_relation_policies_v0()` returns the first reviewed policy set:

| Relation | Direction | Positive | Negative | v0 behavior |
|---|---|---:|---:|---|
| `supported_by` | forward | yes | no | propagates positive utility |
| `authorizes` | blocked | no | no | authority is not causal contribution |
| `constrained_by` | blocked | no | no | governance relation |
| `explains` | blocked | no | no | explanation may be retrospective |
| `followed_by` | blocked | no | no | chronology only |
| `implements` | blocked | no | no | current semantics are too broad |
| `motivates` | blocked | no | no | motivation is not measured effect |
| `superseded_by` | blocked | no | no | state transition only |

Unknown relations are recorded as `policy_missing`; they never inherit semantics from their name.

## Direct evidence selection

`select_preferred_direct_credits()` groups evidence by:

```text
space_id + root_memory_id + evidence_group_id
```

For one matched experiment group:

1. stable interaction credit is selected when present;
2. otherwise stable causal credit is selected;
3. same-priority conflicts fail closed;
4. exact retries are deduplicated;
5. values are never added or averaged across sources.

This prevents interaction and leave-one-out estimates from being double-counted.

## Propagation budget

For direct value `c`:

```text
positive budget = c × positive_budget_fraction   when c > 0
negative budget = c × negative_budget_fraction   when c < 0
```

Defaults:

```text
positive_budget_fraction = 0.50
negative_budget_fraction = 0.00
transmission_fraction = 0.50
maximum_depth = 4
minimum_absolute_mass = 0.0001
```

Negative propagation is therefore disabled by default.

## Mass-conserving traversal

The root distributes its propagation budget among admissible outgoing edges. It does not receive inherited credit itself.

At each reached non-root node with incoming mass `m`:

```text
retained = (1 - transmission_fraction) × m
transmitted = transmission_fraction × m
```

At a leaf or depth boundary, all remaining mass is retained.

Outgoing weights are:

```text
relation_weight × edge_confidence × effective_local_attribution
```

The transmitted mass is divided by normalized weights. Branches redistribute one fixed budget rather than multiplying it.

For each direct credit:

```text
propagation_budget
= propagated_value
+ dropped_value
+ unallocated_value
+ conservation_residual
```

The residual must remain within the configured tolerance or propagation fails.

## Hard gates

`ProvenanceNode` carries two hard gates:

- `authorized`;
- `currently_valid`.

A blocked target is removed before outgoing weights are normalized. Its share is therefore available to other admissible targets rather than being silently lost.

The following conditions fail closed:

- mixed spaces;
- unknown nodes;
- duplicate node or edge identities;
- self-edges;
- malformed probabilities or hashes;
- policy-oriented cycles;
- conflicting policies;
- direct root absent, unauthorized, or invalid.

## Negative-credit gate

Negative credit cannot propagate merely because a task failed.

All of these conditions are required:

1. `negative_budget_fraction > 0`;
2. the relation policy explicitly permits negative propagation;
3. that policy requires local attribution;
4. the edge contains a bounded `local_attribution` value;
5. the edge contains an `evidence_id` proving the local attribution.

This prevents tool failures, reasoning failures, chronology, and mere provenance membership from becoming inherited blame.

## Uncertainty

For one path contribution with effective multiplier `w` relative to the direct value:

```text
propagated_standard_error = abs(w) × direct_standard_error
```

When several paths converge on one target, target summaries:

- sum path values;
- sum path standard errors conservatively;
- retain the path count.

The implementation does not assume converging paths are statistically independent.

Structural evidence remains separate:

- product of edge confidences;
- minimum edge confidence;
- exact relation path;
- exact edge UUID path;
- deterministic SHA-256 path fingerprint.

## Result model

`ProvenanceCreditResult` contains:

- selected direct credits;
- path-specific inherited contributions;
- conservative per-target summaries;
- blocked edges and reasons;
- root abstentions;
- one signed mass ledger per direct credit.

`render_json()` produces canonical compact JSON with identifiers, typed relations, hashes, and numeric evidence only. It contains no query text, prompt, answer, command, output, source content, secret, token, patch, environment, or free-form note.

## Controlled simulation

Run:

```bash
python -m scripts.simulate_provenance_credit
```

The fixed experiment compares a relation-blind, branch-copying baseline with the conservative propagator.

Expected safety result:

| Metric | Naive | Conservative |
|---|---:|---:|
| propagated mass for a two-child branch | 1.00 | 0.50 |
| branch inflation ratio | 2.00× | 1.00× |
| false credit through `followed_by` | 0.50 | 0.00 |
| false inherited negative blame | 0.50 | 0.00 |
| maximum conservation residual | not enforced | 0.00 |

The simulation JSON is deterministic for a fixed configuration.

## Randomized verification

`tests/test_provenance_credit_properties.py` generates 5,000 deterministic DAGs and verifies:

- input-order invariance;
- byte-identical JSON under permutation;
- exact mass accounting;
- bounded inherited value;
- scope isolation;
- hard authorization and validity gates;
- no inherited credit on the direct root;
- bounded depth;
- exact path lengths;
- conservative target aggregation.

## Minimal example

```python
from uuid import uuid4

from nextgen_memory import (
    ConservativeProvenancePropagator,
    CreditSourceKind,
    DirectCreditEvidence,
    ProvenanceEdge,
    ProvenanceNode,
    TypedProvenanceGraph,
    project_relation_policies_v0,
)

space_id = uuid4()
root_id = uuid4()
source_id = uuid4()

graph = TypedProvenanceGraph(
    nodes=(
        ProvenanceNode(root_id, space_id),
        ProvenanceNode(source_id, space_id),
    ),
    edges=(
        ProvenanceEdge(
            edge_id=uuid4(),
            space_id=space_id,
            from_node_id=root_id,
            to_node_id=source_id,
            relation="supported_by",
            confidence=0.9,
        ),
    ),
)

direct = DirectCreditEvidence(
    direct_credit_id=uuid4(),
    evidence_group_id=uuid4(),
    space_id=space_id,
    root_memory_id=root_id,
    source_kind=CreditSourceKind.INTERACTION,
    value=1.0,
    standard_error=0.1,
    trial_count=3,
    context_set_hash="a" * 64,
    continuation_set_hash="b" * 64,
)

result = ConservativeProvenancePropagator().propagate(
    graph,
    (direct,),
    project_relation_policies_v0(),
)

assert result.mass_ledgers[0].conservation_residual == 0.0
```

## Non-goals

Provenance Credit v0 does not:

- create direct causal credit;
- write inherited feedback to Neon;
- modify `node_utility`;
- infer relation semantics;
- learn relation weights;
- propagate authorization or poisoning risk;
- repair graph cycles;
- merge direct and inherited evidence;
- modify a database schema.
