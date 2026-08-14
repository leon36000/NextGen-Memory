# Post-Action Causal Credit v0 Design

## Status and authorization

The project owner approved continuation after Utility-Aware Reranker v0. This design implements the next announced tranche: determine which memories changed a completed task outcome and write conservative, append-only feedback without broadcasting the global reward to every retrieved memory.

Work is isolated on `feat/post-action-causal-credit-v0`, stacked on `feat/utility-aware-reranker-v0`. It must not merge, retarget to `main`, or modify the production Neon schema without a later explicit owner decision.

## Research basis

The selected design combines the strongest recurring ideas in recent memory-credit work:

- **Context-matched interventions:** Causal Memory Intervention and C3 compare variants under a frozen context instead of comparing unrelated trajectories.
- **Local rerollouts:** Memory-R2 argues that comparisons are fair only when alternatives start from the same intermediate memory state.
- **Memory-specific local utility:** HiMPO uses replacement counterfactuals and suppresses memory credit when local evidence is entangled with downstream failures.
- **Evidence anchoring:** Fine-Mem and AttriMem trace outcome support to the memory contents or operations actually used.
- **Structural propagation later, not now:** MemQ propagates credit over provenance DAGs, but direct single-step causal evidence must be trustworthy before propagation is introduced.

The v0 implementation therefore uses paired, fixed-context leave-one-out evaluation for directly used memories and abstains when evidence is missing, unstable, or causally ambiguous.

## Problem

The current system can:

1. retrieve scope-safe candidates;
2. mark candidates selected for context;
3. record whether a candidate was used in the action;
4. rerank with historical aggregate utility.

It cannot yet tell whether a selected memory caused improvement, caused harm, or merely accompanied a successful task. Copying the task reward to the entire retrieval bundle would contaminate shadow memories and corrupt `ngm.node_utility`.

## Goals

1. Represent deterministic, matched counterfactual trials containing:
   - full-memory outcome;
   - no-memory baseline outcome;
   - leave-one-memory-out outcomes for targeted memories.
2. Attribute node-level credit only to memories that were both selected for context and marked `used_in_action`.
3. Use paired marginal effects under identical context and continuation fingerprints.
4. Require a configurable minimum number of matched trials and a bounded standard error before writing feedback.
5. Classify only stable effects as `decisive`, `helpful`, or `harmful`; optionally record `neutral` effects, disabled by default.
6. Withhold credit for missing ablations, unused memories, high-variance effects, and ambiguous interactions.
7. Generate deterministic, idempotent `memory_feedback` rows with no raw prompts, outputs, notes, or secrets.
8. Extend `memory_feedback` additively with a causal-evaluation identity, evidence key, and immutable content hash.
9. Verify the migration only on a temporary Neon branch, then delete that branch.
10. Provide a deterministic simulation comparing bundle reward, leave-one-out credit, and uncertainty abstention.

## Non-goals

- No Shapley-value estimator, Monte Carlo subset attribution, or provenance-DAG propagation.
- No learned critic, reward model, neural reranker, or policy update.
- No automatic execution of expensive ablations; v0 consumes externally evaluated outcomes.
- No mutation of `retrieval_events.used_in_action`; callers remain responsible for recording actual use.
- No context compiler, token packing, latent-memory injection, or Temporal workflow.
- No production migration or live feedback write.

## Approaches considered

### A. Broadcast terminal reward to all retrieved memories

Rejected. It is cheap but recreates the memory-reward trap and cannot distinguish causal memories from correlated shadows.

### B. Evidence-only attribution

Trace only which memory was quoted or referenced in the answer. This improves over broadcast reward but still confuses evidence presence with outcome causality and cannot identify harmful memories.

### C. Paired leave-one-out under frozen context — selected

Evaluate the full bundle, no-memory baseline, and a variant with one used memory removed. The marginal effect is computed from matched trials with identical context and continuation fingerprints. This is linear in the number of targeted memories, easy to audit, and compatible with current telemetry.

### D. Shapley or subset-sampling attribution

Better for interactions and redundancy, but evaluator cost grows rapidly and the project lacks enough validated rollouts to justify this complexity. It remains a future research tranche.

## Architecture

```text
router decision + retrieval events
  -> CreditTargetReader
  -> selected AND used canonical memories

matched counterfactual trials
  -> CausalCreditAssigner
  -> stable per-memory marginal effects
  -> verdict/reward/cost deltas or abstention reason

attributed credits
  -> CausalFeedbackBuilder
  -> deterministic MemoryFeedbackRecord[]
  -> MemoryFeedbackWriter
  -> ngm.memory_feedback
```

### Components

#### `causal_credit.py`

Defines immutable contracts and pure attribution logic:

- `OutcomeMeasurement`
- `CounterfactualTrial`
- `CreditTarget`
- `CausalCreditConfig`
- `CreditAbstentionReason`
- `AttributedMemoryCredit`
- `CausalCreditAssigner`

#### `credit_targets.py`

Reads scoped retrieval-use evidence from `ngm.retrieval_events` for one router decision. It returns canonical targets and rejects duplicate nodes or inconsistent rows.

#### `causal_feedback.py`

Builds deterministic feedback records and persists them using parameterized SQL. Exact task payloads remain outside Neon.

#### `migrations/neon/0005_causal_credit_feedback.sql`

Adds nullable causal-credit columns to `memory_feedback`, a partial unique index, safe metadata checks, strict idempotency conflict handling, and immutability for causal-credit rows only. Legacy non-causal feedback behavior remains unchanged.

#### `scripts/simulate_causal_credit.py`

Compares global reward broadcast, paired leave-one-out, and abstention under noisy trials.

## Data contracts

### Outcome measurement

```text
score: finite float in [-1, 1]
task_success: bool
tokens: non-negative integer
latency_ms: finite non-negative float
```

Scores are normalized by the external evaluator before entering the assigner.

### Counterfactual trial

Each trial contains:

- unique `trial_key`;
- 64-character lowercase `context_hash`;
- 64-character lowercase `continuation_hash`;
- full-memory outcome;
- no-memory outcome;
- mapping from removed `memory_id` to the corresponding outcome.

A trial is rejected if fingerprints are malformed or if an ablation key is not a UUID.

### Credit target

A target contains:

- canonical `memory_id`;
- retrieval event ID;
- router decision ID;
- `selected_for_context`;
- `used_in_action`.

Node-level attribution is attempted only when both booleans are true.

## Attribution model

For memory `m` and matched trials `t`:

```text
bundle_uplift_t(m) = full_score_t - no_memory_score_t
marginal_t(m)       = full_score_t - score_without_m_t
```

Aggregate statistics:

```text
mean_effect    = mean(marginal_t)
standard_error = sample_stddev(marginal_t) / sqrt(n)
mean_bundle_uplift = mean(bundle_uplift_t)
```

Cost deltas use the same paired direction:

```text
token_delta      = round(mean(full_tokens - without_m_tokens))
latency_delta_ms = mean(full_latency_ms - without_m_latency_ms)
```

Positive token or latency deltas mean the memory increased cost.

### Default configuration

| Parameter | Value |
|---|---:|
| minimum matched trials | 2 |
| helpful threshold | +0.05 |
| decisive threshold | +0.20 |
| harmful threshold | -0.05 |
| neutral band | ±0.02 |
| maximum standard error | 0.10 |
| reward clip | 1.00 |
| record neutral | false |

### Verdict mapping

- `decisive`: mean effect ≥ decisive threshold and removing the memory lowers mean success rate.
- `helpful`: mean effect ≥ helpful threshold.
- `harmful`: mean effect ≤ harmful threshold.
- `neutral`: absolute effect ≤ neutral band, only when `record_neutral=true`.
- otherwise: abstain.

Reward is the clipped mean marginal effect. `task_success` records the majority full-memory success result.

### Abstention reasons

- memory not selected;
- memory not used;
- missing leave-one-out outcome;
- insufficient matched trials;
- duplicate trial key;
- unstable/high-variance effect;
- effect below classification threshold;
- interaction ambiguity.

### Interaction ambiguity guard

Leave-one-out is unreliable for redundant bundles. If the bundle has a material positive uplift but every targeted memory has an effect inside the neutral band, the assigner does not emit node-level neutral feedback. It reports `interaction_ambiguous` for the evaluation. This avoids punishing memories that are individually redundant but collectively sufficient.

## Feedback persistence

### Proposed additive columns

`memory_feedback` gains nullable:

- `credit_evaluation_id`;
- `evidence_key`;
- `content_hash`.

Causal rows require all three plus `node_id` and `router_decision_id`. The evidence key for v0 is `paired_leave_one_out_v0`.

### Deterministic identity

```text
feedback_id = UUIDv5(
  credit_evaluation_id,
  "paired_leave_one_out_v0:<memory_id>"
)
```

### Idempotency

A partial unique index protects `(space_id, credit_evaluation_id, node_id)` for causal rows. Identical retries are accepted. Reuse with different immutable content raises a conflict.

### Metadata

Allowed metadata contains numeric and identifier-only evidence:

- credit version;
- trial count;
- mean full score;
- mean no-memory score;
- mean without-memory score;
- mean bundle uplift;
- mean marginal effect;
- standard error;
- context/continuation set hashes.

The migration rejects raw or sensitive keys recursively, including query, prompt, command, stdout, stderr, notes, secrets, tokens, diffs, patches, and environment payloads.

## Error handling

- Missing or malformed evaluation data fails before attribution.
- Infrastructure failures propagate; they are not converted to neutral feedback.
- Missing ablations create explicit abstentions, not fabricated zero effects.
- Duplicate router-decision/node rows fail closed.
- Writer verification compares the stored immutable payload after insertion.
- Production schema remains unchanged until separate explicit approval.

## Testing

### Pure attribution

Tests must prove:

1. stable positive effects become helpful;
2. large effects that change success become decisive;
3. stable negative effects become harmful;
4. unused or unselected memories are withheld;
5. missing ablations are withheld;
6. one trial is insufficient by default;
7. high standard error causes abstention;
8. duplicate trial keys fail;
9. redundant positive bundles trigger interaction ambiguity rather than neutral punishment;
10. token and latency deltas have the documented sign.

### Retrieval target reader

Tests verify parameterized scope and router-decision filtering, canonical UUID mapping, deterministic order, and duplicate/out-of-scope rejection.

### Feedback builder/writer

Tests verify deterministic IDs, canonical content hashes, verdict/reward mapping, safe metadata, exact SQL parameters, identical retry behavior, and conflicting retry rejection.

### Migration

Contract tests inspect additive columns, partial unique index, safe metadata function, idempotency helper, and causal-row immutability. A temporary Neon branch must pass positive and negative smoke cases and be deleted afterward.

### Simulation

With a fixed seed, bundle broadcast must contaminate correlated shadows, paired leave-one-out must localize direct effects, and noisy effects must be withheld when their standard error exceeds the configured limit.

## Security and privacy

- No raw query, prompt, action, answer, command, output, note, or secret is persisted by this feature.
- Every read and write includes canonical `space_id`.
- Only canonical node UUIDs from scoped retrieval events can receive feedback.
- Context and continuation are represented only by cryptographic fingerprints.
- Causal feedback rows are immutable once inserted.

## Future evolution

After direct credit is reliable, later work may add:

- subset/Shapley estimation for redundancy and synergy;
- provenance-DAG propagation with structural discounting;
- adaptive ablation scheduling under a compute budget;
- Temporal orchestration for durable rerollouts;
- learned credit estimators trained against the paired-intervention dataset;
- alternating updates of retrieval policy and memory utility.
