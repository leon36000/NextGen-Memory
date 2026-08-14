# Utility-Aware Reranker v0

## Purpose

Atlas hybrid search estimates lexical and semantic relevance. Utility-Aware Reranker v0 adds a second, deterministic decision layer that asks whether a memory has accumulated credible evidence of helping, harming, or wasting resources.

The first version is intentionally non-learned. The project currently has no durable feedback observations in `ngm.memory_feedback`; therefore `ngm.node_utility` supplies neutral zero-evidence snapshots. This prevents cold-start memories from receiving invented utility and gives the project a stable baseline before training a learned controller.

## End-to-end path

```text
scope-safe Atlas hybrid retrieval
  -> bounded candidate oversampling
  -> scoped aggregate utility lookup in Neon
  -> evidence-shrunk utility and harm signals
  -> bounded token and latency penalties
  -> deterministic reranking
  -> original result limit
```

The decorator expands a query by a default factor of four, capped at 100 Atlas hits. It raises `num_candidates` to at least ten times the expanded limit, capped at 10,000. The original immutable `ResearchRetrievalQuery` is never modified.

## Utility evidence

`UtilityEvidence` contains only aggregate fields:

- canonical `memory_id`;
- total feedback count;
- average numerical reward, when available;
- helpful/decisive count;
- harmful/stale/incorrect count;
- most recent feedback timestamp.

The parameterized reader selects these fields from `ngm.node_utility` using both canonical `space_id` and a UUID array. It rejects duplicate rows, unexpected memory IDs, wrong spaces, missing fields, invalid counts, and non-finite values.

No feedback note, raw output, prompt, query, source payload, or secret is read by the reranker.

## Scoring

For a candidate `m`, positive retrieval scores are normalized by the maximum positive score in the candidate set. If every score is non-positive, reciprocal rank is used.

Let:

- `n` be total feedback count;
- `p` be positive verdict count;
- `h` be harmful verdict count;
- `s` be prior strength, default `4.0`;
- `r` be average reward clipped to `[-1, 1]`.

```text
reward_signal = r * n / (n + s)

verdict_signal =
    ((p - h) / (p + h))
  * ((p + h) / (p + h + s))

harm_risk =
    (h / (p + h))
  * ((p + h) / (p + h + s))
```

Utility is the mean of the available reward and verdict signals. With no evidence it is exactly zero.

Costs are bounded:

```text
token_cost   = min(estimated_tokens / 512, 1)
latency_cost = min(estimated_latency_ms / 100, 1)
```

The default final score is:

```text
final_score =
    1.00 * relevance
  + 0.35 * utility
  - 0.75 * harm_risk
  - 0.08 * token_cost
  - 0.07 * latency_cost
```

Every result preserves the raw signals and signed weighted contributions in `UtilityScoreBreakdown`. Ties are resolved by original rank and then canonical memory UUID.

## Why the prior is strong

A single positive event yields a verdict utility signal of `1 / (1 + 4) = 0.2`. Its weighted contribution is only `0.07`, which cannot overpower a large retrieval-relevance gap. Repeated consistent evidence may move near-tied candidates, while repeated harm receives both a negative utility contribution and an independent risk penalty.

This is conservative by design. A later learned reranker must outperform this baseline under counterfactual evaluation, not merely fit historical bundle rewards.

## Error behavior

- Atlas errors propagate.
- Utility-provider errors propagate.
- There is no implicit lexical-only, vector-only, neutral-provider, or unscoped fallback.
- A missing row is neutral because absence of evidence is a valid data state.
- Evidence returned for an unrequested memory fails closed.
- All non-finite or inconsistent values fail before ranking.

## Reward-trap simulation

Run:

```bash
python scripts/simulate_memory_reward_trap.py
```

The fixed-seed default experiment contains 5,000 task bundles. Each bundle has one causal memory and four always-co-retrieved shadow memories. Successful tasks occur with probability `0.85`.

Verified deterministic result:

| Metric | Naive bundle reward | Counterfactual credit |
|---|---:|---:|
| Shadow contamination rate | 0.8436 | 0.0000 |
| Causal memory ranked first | 0.1952 | 0.8436 |

Observed success rate: `0.8436`.

Naive propagation rewards all shadows whenever the task succeeds. Counterfactual attribution updates only the memory whose removal changes the outcome, leaving shadows at the neutral prior.

## Training gate for a learned reranker

A learned model should not replace v0 until the project has:

1. enough task outcomes with explicit memory-use telemetry;
2. counterfactual or leave-one-out evidence for a meaningful subset;
3. train/evaluation splits isolated by task, user, project, and time;
4. calibrated harm and abstention metrics;
5. evidence that the learned model improves quality/cost without increasing memory-induced regressions;
6. reproducible gains over this deterministic baseline on multiple backbones and domains.

## Deferred work

- post-action credit assignment and writes to `memory_feedback`;
- provenance-DAG propagation;
- temporal decay and environment compatibility;
- redundancy-aware context packing;
- learned routing and alternating co-evolution;
- latent-memory injection.
