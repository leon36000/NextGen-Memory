# Post-Action Causal Credit v0

## Purpose

Post-Action Causal Credit v0 converts matched interventions into conservative memory-specific feedback. It prevents the system from rewarding every co-retrieved memory merely because a task succeeded.

The method evaluates:

```text
full memory bundle
no-memory baseline
full bundle minus memory A
full bundle minus memory B
...
```

Every variant must share a frozen context fingerprint. Each rerollout has its own continuation fingerprint so repeated trials can estimate uncertainty without storing prompts or outputs.

## Eligibility

A canonical memory is considered only when its `ngm.retrieval_events` row has:

- the requested `space_id`;
- the requested `router_decision_id`;
- a non-null canonical `node_id`;
- `selected_for_context = true`.

The pure assigner then requires `used_in_action = true`. Selected but unused memories receive an explicit `not_used` abstention rather than feedback.

## Paired attribution

For memory `m` in matched trial `t`:

```text
bundle_uplift_t(m) = full_score_t - no_memory_score_t
marginal_t(m)       = full_score_t - score_without_m_t
```

The aggregate effect is:

```text
mean_effect    = mean(marginal_t)
standard_error = sample_stddev(marginal_t) / sqrt(trial_count)
```

Default controls:

| Parameter | Value |
|---|---:|
| minimum matched trials | 2 |
| helpful threshold | +0.05 |
| decisive threshold | +0.20 |
| harmful threshold | -0.05 |
| neutral band | ±0.02 |
| maximum standard error | 0.10 |
| reward clip | ±1.00 |
| persist neutral verdicts | false |

Verdicts:

- **decisive**: effect ≥ 0.20 and removing the memory lowers the success rate;
- **helpful**: effect ≥ 0.05;
- **harmful**: effect ≤ -0.05;
- **neutral**: inside ±0.02 only when explicitly enabled;
- otherwise the system abstains.

Cost deltas use `full - without_memory`. Positive token or latency deltas mean the memory increased execution cost.

## Abstention

Node-level credit is withheld when:

- the memory was not selected;
- the memory was selected but not used;
- a leave-one-out result is missing;
- fewer than two matched trials exist;
- standard error exceeds the configured limit;
- the stable effect remains below a verdict threshold;
- the bundle is useful but every individual effect is neutral, indicating redundancy or interaction ambiguity.

The last guard is essential. Two memories may be substitutes: removing either one changes nothing even though removing the whole bundle hurts. v0 refuses to mislabel these memories as useless; future subset or Shapley estimation will handle such interactions.

## Feedback identity and persistence

Stable credits become deterministic `memory_feedback` rows:

```text
feedback_id = UUIDv5(
    credit_evaluation_id,
    "paired_leave_one_out_v0:<memory_id>"
)
```

Persisted causal fields include:

- canonical scope, node, and router-decision UUIDs;
- verdict and clipped marginal reward;
- full-run success majority;
- paired token and latency deltas;
- evidence key `paired_leave_one_out_v0`;
- immutable SHA-256 content hash;
- aggregate numeric evidence and context/continuation set hashes.

Notes are forbidden. No prompt, query, answer, command, output, diff, patch, environment, token, secret, or raw trace enters the causal feedback row.

The writer performs:

```text
parameterized INSERT ... ON CONFLICT DO NOTHING
→ SELECT deterministic IDs
→ exact immutable-payload comparison
```

Infrastructure or payload mismatch fails closed. Identical retries are accepted.

## Neon migration contract

`migrations/neon/0005_causal_credit_feedback.sql` additively introduces:

- `credit_evaluation_id`;
- `evidence_key`;
- `content_hash`;
- a partial unique causal identity;
- recursive safe-metadata validation;
- causal completeness constraints;
- schema metadata `post_action_causal_credit = 0.1.0`.

The base kernel already protects `ngm.memory_feedback` with the global `memory_feedback_immutable` trigger. The causal trigger is defense-in-depth; it does not weaken or replace the existing append-only rule.

## Temporary Neon verification — August 14, 2026

Migration testing used only:

```text
Branch name: verify-causal-credit-v0-20260814
Branch ID: br-autumn-sun-a6fwejjl
Parent: br-shy-waterfall-a6f4gqpl
```

The migration was applied twice successfully.

Positive path:

- one deterministic `helpful` causal row inserted;
- reward `0.10`;
- `ngm.node_utility.feedback_count = 1`;
- `ngm.node_utility.avg_reward = 0.10`;
- positive verdict count `1`;
- causal unique index present;
- completeness constraint present;
- schema version `0.1.0`.

Negative paths verified:

- conflicting immutable identity rejected;
- nested `stdout` metadata rejected;
- update rejected;
- delete rejected;
- non-null notes rejected;
- identical retry accepted through `DO NOTHING` and read-back verification.

The temporary branch was deleted. A fresh production check confirmed:

- `ngm.memory_feedback` still has zero rows;
- `credit_evaluation_id` is absent from production;
- `post_action_causal_credit` is absent from production schema metadata.

## Deterministic simulation

Run:

```bash
python scripts/simulate_causal_credit.py
```

The default experiment uses 5,000 tasks, one causal memory, four zero-effect shadows, three matched trials, evaluator noise `0.03`, and a high-noise zero-effect candidate.

Verified fixed-seed result:

| Metric | Result |
|---|---:|
| observed success rate | 0.8616 |
| global-reward shadow contamination | 0.8616 |
| leave-one-out causal detection | 1.0000 |
| leave-one-out shadow false credit | 0.0042 |
| noisy zero-effect abstention precision | 0.9194 |

The experiment demonstrates three properties:

1. broadcast task reward contaminates shadows at approximately the task-success rate;
2. paired leave-one-out localizes the true direct effect;
3. the uncertainty gate withholds noisy evidence instead of converting variance into reward.

## Research limitations

Leave-one-out estimates direct marginal contribution, not full interaction value. It can miss:

- redundant substitute memories;
- synergistic pairs;
- long provenance chains;
- effects that change the action policy before the measured checkpoint.

Future work should compare:

- adaptive subset sampling;
- approximate Shapley estimation;
- provenance-DAG propagation;
- local rerollouts from intermediate memory states;
- learned credit estimators trained only against intervention-grounded labels.

## Deployment gate

Production deployment remains blocked until explicit owner approval. Before migration:

1. review the SQL and application writer together;
2. create a fresh Neon branch;
3. apply the migration twice;
4. rerun positive and negative smoke tests;
5. verify production feedback counts before deployment;
6. deploy writers in dark/read-back mode;
7. enable actual feedback writes only after payload comparison telemetry is clean.
