# Utility-Aware Reranker v0 Design

## Status and authorization

The project owner approved continuation after the retrieval-scope and execution-ledger milestones. This specification implements the next previously announced tranche: a deterministic, explainable utility-aware reranker. It is isolated on `feat/utility-aware-reranker-v0`, stacked on `feat/retrieval-scope-safe-v2`, and must not merge or mutate `main` without a later explicit owner decision.

## Problem

Atlas hybrid retrieval answers which memories are lexically and semantically relevant. It does not answer whether a memory has historically helped, harmed, wasted tokens, or increased latency in comparable executions.

Promoting every retrieved memory after a successful task creates the memory-reward trap described by the project's RoMeRL, MemQ, MemRL, and CoEvo-Mem research sources: co-retrieved but non-causal memories inherit credit and eventually become indistinguishable from genuinely useful experience.

The current Neon schema already exposes `ngm.node_utility`, a scoped view over `ngm.memory_feedback`, with feedback count, average reward, positive count, negative count, and last-feedback time. The view is currently empty, so the first reranker must treat missing evidence as neutral rather than inventing utility.

## Goals

1. Rerank scope-safe retrieval candidates using relevance, evidence-backed utility, harm risk, token cost, and latency cost.
2. Apply strong prior shrinkage so one positive observation cannot dominate retrieval relevance.
3. Penalize repeated harmful evidence conservatively.
4. Preserve a complete, deterministic score breakdown for audit and later supervision.
5. Read utility only through the existing scoped Neon view; introduce no schema migration.
6. Oversample Atlas candidates before reranking, then return the caller's original result limit.
7. Remain dependency-free at import time and testable without network access.
8. Demonstrate the reward-contamination failure mode with a reproducible simulation.

## Non-goals

- No learned reranker, neural router, online policy update, Q-learning, or co-evolution.
- No write to `memory_feedback` or post-action credit assignment.
- No context token packing, redundancy/MMR selection, or latent-memory injection.
- No production database migration.
- No fallback to unscoped retrieval if Atlas or Neon fails.

## Approaches considered

### A. Deterministic evidence-shrunk reranker — selected

A pure scoring model combines relevance with a conservative utility posterior, explicit harm risk, and bounded cost penalties. It is reproducible, fast, explainable, and can generate trustworthy training features for a later learned controller.

### B. Pairwise learned reranker

Potentially more expressive, but the project does not yet have enough counterfactual feedback to train it without learning the same reward contamination we are trying to prevent.

### C. LLM-as-reranker

Easy to prototype but too slow, expensive, difficult to calibrate, and opaque for the hot path. It also risks allowing prose plausibility to override canonical utility evidence.

## Architecture

```text
ResearchRetrievalQuery(limit=L)
  -> oversampled scoped Atlas query(limit=min(100, L * factor))
  -> ResearchRetrievalHit[]
  -> NodeUtilityProvider.get_many(space_id, memory_ids)
  -> UtilityRerankCandidate[]
  -> UtilityAwareReranker
  -> RerankedMemory[]
  -> top L
```

### Components

- `utility_reranker.py`
  - immutable utility evidence, candidate, score-breakdown, and result contracts;
  - deterministic `UtilityAwareReranker`;
  - `UtilityAwareResearchRetriever` decorator over an existing scoped retriever and utility provider.
- `neon_utility.py`
  - parameterized SQL constant for `ngm.node_utility`;
  - dependency-injected reader that returns immutable evidence keyed by canonical memory UUID.
- `scripts/simulate_memory_reward_trap.py`
  - fixed-seed comparison of naive bundle reward propagation against individual causal updates.

## Scoring model

For candidate `m`:

```text
relevance(m) = max(retrieval_score(m), 0) / max_positive_retrieval_score
```

If no candidate has a positive retrieval score, relevance falls back to reciprocal rank.

Let:

- `n` = total feedback count;
- `p` = positive verdict count;
- `h` = harmful/stale/incorrect verdict count;
- `s` = configurable prior strength;
- `r` = average reward clipped to `[-1, 1]` when present.

Reward evidence:

```text
reward_signal = r * n / (n + s)
```

Verdict evidence:

```text
verdict_signal = ((p - h) / (p + h)) * ((p + h) / (p + h + s))
```

The utility signal is the mean of the available reward and verdict signals. If neither exists, utility is exactly zero.

Harm risk is independent and conservative:

```text
harm_risk = (h / (p + h)) * ((p + h) / (p + h + s))
```

Costs are bounded:

```text
token_cost   = min(estimated_tokens / token_reference, 1)
latency_cost = min(estimated_latency_ms / latency_reference_ms, 1)
```

Final score:

```text
final =
    relevance_weight * relevance
  + utility_weight   * utility
  - harm_weight      * harm_risk
  - token_weight     * token_cost
  - latency_weight   * latency_cost
```

Default configuration:

| Parameter | Value |
|---|---:|
| prior strength | 4.0 |
| relevance weight | 1.00 |
| utility weight | 0.35 |
| harm weight | 0.75 |
| token-cost weight | 0.08 |
| latency-cost weight | 0.07 |
| token reference | 512 |
| latency reference | 100 ms |
| Atlas oversample factor | 4 |

The final deterministic ordering is `final_score DESC`, then original rank, then canonical memory UUID.

## Utility evidence contract

`UtilityEvidence` contains:

- `memory_id`;
- `feedback_count`;
- `avg_reward`;
- `positive_count`;
- `negative_count`;
- `last_feedback_at`.

Counts must be non-negative and `positive_count + negative_count <= feedback_count`. Average reward must be finite but is clipped by the scorer. Missing rows are represented as neutral zero-evidence snapshots.

The SQL reader must filter both `space_id` and the canonical memory-ID array. It must reject duplicate or mismatched rows rather than silently merging them.

## Error handling

- Invalid counts, costs, weights, timestamps, hashes, or mismatched memory IDs fail before scoring.
- Atlas retrieval errors propagate; the decorator must not silently return lexical-only, vector-only, or unscoped results.
- Utility-provider errors propagate; the caller may explicitly choose a neutral provider, but failure is never converted implicitly into neutral evidence.
- Missing utility rows are neutral because absence is a valid state, not an infrastructure failure.
- Non-finite intermediate or final values fail closed.

## Testing

Unit tests must prove:

1. no-feedback candidates preserve relevance ordering;
2. one positive event cannot overpower a clearly stronger relevance signal;
3. repeated helpful evidence can move a near-tied candidate upward;
4. harmful evidence demotes a highly relevant candidate;
5. token and latency penalties are bounded and visible in the breakdown;
6. ties are deterministic;
7. SQL is scoped and parameterized;
8. missing rows become neutral, while duplicate/mismatched rows fail;
9. oversampling is bounded and the original limit is restored;
10. the reward-trap simulation contaminates distractors under naive bundle reward but not under individual causal updates.

Integrated verification requires Ruff and the complete pytest suite on Python 3.12 and 3.13.

## Security and privacy

- No raw query, prompt, command, output, note, or secret enters reranker telemetry or utility evidence.
- The provider reads only aggregate utility fields already exposed by `ngm.node_utility`.
- Canonical `space_id` remains mandatory at retrieval and utility lookup.
- Score breakdowns contain numeric evidence and canonical IDs, not source payloads.

## Future evolution

After enough counterfactual evidence exists, this deterministic scorer becomes a baseline and feature generator for a learned reranker. Provenance-aware credit propagation, context-aware utility, temporal decay, redundancy-aware selection, and alternating co-evolution remain separate future specifications.
