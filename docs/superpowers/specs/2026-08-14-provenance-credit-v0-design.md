# Provenance Credit v0 Design

**Date:** 2026-08-14
**Status:** approved for implementation
**Base:** `feat/interaction-credit-v0`

## 1. Goal

Provenance Credit v0 propagates a bounded fraction of already intervention-grounded direct memory credit to upstream provenance memories without converting graph proximity into causal proof.

The component answers:

- which typed relations may carry positive or negative utility credit;
- in which direction each relation is traversed;
- how a fixed propagation budget is divided without creating value at branches;
- which memories receive inherited credit and through which exact paths;
- which edges or nodes were blocked and why;
- whether propagated mass, dropped mass, and unallocated mass conserve the declared budget.

The component does not generate direct credit. Direct credit remains owned by Post-Action Causal Credit v0 and Interaction Credit v0.

## 2. Safety principle

> Co-location, chronology, authorization, implementation, and explanation are not causal contribution by themselves.

The live project graph currently contains heterogeneous relations such as `supported_by`, `followed_by`, `superseded_by`, `authorizes`, `constrained_by`, `implements`, `motivates`, and `explains`. No relation receives propagation semantics implicitly.

Every traversable relation requires an explicit immutable policy. Unknown relations fail closed.

## 3. Selected approach

V0 uses typed, positive-first, mass-conserving propagation.

Rejected alternatives:

- uniform BFS/TD propagation over every edge, because branches can multiply credit and heterogeneous relations can create false attribution;
- learned GNN relation weights, because intervention-grounded production feedback is not yet large or calibrated enough;
- direct/propagated credit fusion, because inherited structural evidence must never be reported as direct causal evidence.

## 4. Core contracts

### 4.1 `ProvenanceNode`

An immutable canonical graph node:

- `memory_id`;
- `space_id`;
- `authorized` hard gate;
- `currently_valid` hard gate.

Authorization and validity are not soft weights. A blocked node is not re-enabled by high relevance or positive credit.

### 4.2 `ProvenanceEdge`

An immutable typed edge:

- canonical `edge_id` and `space_id`;
- `from_node_id` and `to_node_id`;
- normalized `relation`;
- bounded `confidence`;
- optional bounded `local_attribution`;
- optional `evidence_id` proving local attribution.

Raw evidence text, prompts, outputs, secrets, and notes are not part of the contract.

### 4.3 `ProvenanceRelationPolicy`

An explicit policy for one relation:

- traversal direction: `forward`, `reverse`, or `blocked`;
- positive-credit permission;
- negative-credit permission;
- bounded relation weight;
- optional requirement for local attribution evidence;
- optional relation-specific maximum depth.

The initial project policy allows positive propagation through `supported_by`. Relations including `followed_by`, `superseded_by`, `authorizes`, `constrained_by`, `implements`, `motivates`, and `explains` are blocked in v0.

### 4.4 `DirectCreditEvidence`

A direct, intervention-grounded root signal:

- deterministic `direct_credit_id`;
- `evidence_group_id` identifying one comparable experiment/game;
- `space_id` and root `memory_id`;
- source kind: `interaction` or `causal`;
- finite signed value;
- non-negative standard error;
- positive trial count;
- context and continuation hashes.

The selector chooses at most one direct signal per `(space, root memory, evidence group)`:

1. stable interaction credit;
2. otherwise stable causal credit.

Same-priority conflicts fail closed. Values are never added together.

### 4.5 `PropagationConfig`

Global conservative controls:

- positive budget fraction, default `0.50`;
- negative budget fraction, default `0.00`;
- transmission fraction, default `0.50`;
- maximum depth, default `4`;
- minimum absolute transmitted mass, default `0.0001`;
- conservation tolerance;
- policy version.

### 4.6 Results

`PropagatedCreditContribution` records one retained path contribution with:

- direct/root/target identities;
- signed propagated value;
- propagated standard error;
- structural confidence and minimum edge confidence;
- depth;
- relation and edge paths;
- deterministic path fingerprint.

`BlockedPropagation` records hard-gate and policy exclusions.

`ProvenanceCreditAbstention` records why a root signal produced no inherited credit.

`PropagationMassLedger` records:

- direct value;
- signed propagation budget;
- total inherited contribution;
- dropped below-floor mass;
- unallocated root mass;
- conservation residual.

`ProvenanceCreditResult` preserves direct evidence and inherited evidence separately.

## 5. Graph validation

The typed graph fails closed when:

- node or edge identifiers are duplicated;
- nodes span multiple spaces;
- an edge spans spaces or references an unknown node;
- relation names are empty;
- confidence or local attribution is non-finite or outside `[0, 1]`;
- an edge carries attribution without an evidence UUID;
- the policy-oriented traversable graph contains a cycle for the current sign.

Input order does not affect canonical nodes, edges, paths, fingerprints, or results.

## 6. Propagation algorithm

For one direct value `c`, the signed propagation budget is:

```text
budget = c * positive_budget_fraction    when c > 0
budget = c * negative_budget_fraction    when c < 0
```

Zero budget produces an explicit abstention.

The root does not receive inherited credit. Its budget is distributed among admissible outgoing typed edges. At every reached non-root node with incoming mass `m`:

```text
retained = (1 - transmission_fraction) * m
transmitted = transmission_fraction * m
```

At a leaf, depth limit, or node with no admissible outgoing edge, all remaining mass is retained at that node.

Outgoing edge weight is:

```text
relation_weight * edge.confidence * effective_local_attribution
```

where `effective_local_attribution` is the supplied value or `1.0` when the policy does not require it.

The transmitted mass is divided by normalized edge weights. Branching therefore redistributes a fixed budget rather than multiplying it.

Mass whose absolute value is below the configured floor is recorded as dropped instead of silently disappearing.

## 7. Uncertainty

For one path contribution with effective direct-value multiplier `w`:

```text
propagated_standard_error = abs(w) * direct_standard_error
```

Multiple paths are never treated as statistically independent. Per-target summaries, when requested, sum absolute path standard errors conservatively.

Structural confidence remains distinct from statistical uncertainty:

- product of edge confidences;
- minimum edge confidence;
- exact relation path;
- exact edge path.

## 8. Negative credit

Negative propagation is disabled globally by default.

To enable one negative path, all conditions must hold:

- `negative_budget_fraction > 0`;
- every traversed relation policy allows negative credit;
- every such policy requires local attribution;
- the edge supplies both `local_attribution` and `evidence_id`.

A task failure, chronology edge, or provenance presence alone cannot propagate blame.

## 9. Initial policy helper

`project_relation_policies_v0()` returns explicit policies for the relations already present in the project graph:

- `supported_by`: forward, positive only, weight `1.0`;
- `authorizes`, `constrained_by`, `explains`, `followed_by`, `implements`, `motivates`, `superseded_by`: blocked.

Future relations such as `derived_from`, `summarized_from`, or `produced_from` require separate reviewed policies before use.

## 10. Determinism and privacy

All set-like inputs are normalized. Outputs are sorted by direct credit, depth, target UUID, and path fingerprint. JSON serialization is canonical and contains identifiers, typed relations, numeric evidence, and hashes only.

No raw query, prompt, answer, command, output, source text, secret, token, patch, environment, or feedback note enters the contracts.

## 11. Testing strategy

The suite must prove:

1. only explicitly permitted relations propagate;
2. blocked chronology/governance relations do not propagate;
3. branches conserve mass;
4. converging paths remain separate and deterministic;
5. direct and inherited credit are never merged;
6. interaction direct credit takes precedence over causal credit within one evidence group;
7. same-priority direct conflicts fail closed;
8. negative credit is disabled by default;
9. enabled negative propagation requires local attribution evidence;
10. unauthorized and invalid nodes are hard-blocked;
11. cross-space edges and oriented cycles fail closed;
12. uncertainty scales conservatively;
13. depth and floor accounting are explicit;
14. result JSON is byte-identical under input permutation;
15. at least 5,000 deterministic random DAGs preserve conservation, scope, acyclicity, and ordering invariants.

A simulation compares naive branch-multiplying BFS with the mass-conserving propagator and measures false propagated credit.

## 12. Non-goals

V0 does not:

- persist inherited feedback;
- mutate `memory_feedback` or `node_utility`;
- infer relation semantics from relation names;
- learn relation weights;
- propagate authorization or provenance risk;
- repair graph cycles;
- execute counterfactual rollouts;
- merge direct and inherited credit;
- modify Neon or MongoDB schemas.

## 13. Success criteria

The feature is complete when the contracts and algorithm are immutable, deterministic, privacy-safe, positive-first, cycle-safe, mass-conserving, explicitly uncertain, and verified on Python 3.12 and 3.13 without a database migration or default-branch mutation.
