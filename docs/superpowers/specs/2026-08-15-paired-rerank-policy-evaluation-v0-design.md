# Paired Rerank Policy Evaluation v0 Design

**Date:** 2026-08-15
**Status:** approved under the project owner's standing architecture delegation
**Base:** `feat/inherited-rerank-telemetry-v0`

## 1. Goal

Paired Rerank Policy Evaluation v0 estimates whether one inherited-reranking policy improves downstream task outcomes relative to a control policy under matched replay conditions.

The unit of evaluation is the **policy pair**, not an individual memory. The component must never copy a task reward or failure verdict onto every memory that appeared in a ranking.

It answers:

- whether control and treatment were evaluated on the same routed candidate set and downstream continuation contract;
- the paired mean difference in task score, success, token use, and latency;
- the uncertainty around the paired score difference;
- whether the treatment appears promising, harmful, neutral, too costly, or still inconclusive;
- how frequently the treatment changed the top candidate or applied inherited adjustments;
- whether an exact retry recreates the same deterministic evaluation artifact.

V0 uses only explicit matched replays. It does not estimate propensities, reuse observational logs as randomized evidence, or train a policy.

## 2. Research basis

The design follows three findings from recent ranking-policy evaluation work:

1. Pairwise policy-value differences can have lower variance than estimating two absolute policy values independently when policy outcomes are positively correlated. This motivates estimating treatment-minus-control directly rather than subtracting two unrelated summaries. See Δ-OPE: https://arxiv.org/abs/2405.10024v1.
2. Safe ranking-policy improvement requires explicit limits on deviation and damage rather than trusting an unbiased-but-high-variance point estimate. This motivates separate harm and resource-cost gates. See Practical and Robust Safety Guarantees for Advanced Counterfactual Learning to Rank: https://arxiv.org/abs/2407.19943v1.
3. Confidence gates can fail when the uncertainty signal does not match the real source of error, especially under contextual drift. V0 therefore reports structural evidence only and never claims online safety from count-based uncertainty alone. See The Confidence Gate Theorem: https://arxiv.org/abs/2603.09947v1.

These papers motivate the structure but do not supply a ready-made estimator for deterministic LLM-agent replays. The v0 contract is deliberately narrower and fail-closed.

## 3. Selected approach

### 3.1 General observational off-policy evaluation

Deferred.

A general OPE estimator would require a stochastic logging policy, valid propensity scores, common support, and an explicit exposure model. The current deterministic reranking pipeline does not yet log those quantities.

### 3.2 Independent absolute policy summaries

Rejected.

Estimating a control mean and treatment mean independently ignores the covariance created by replaying the same task context, candidate set, model settings, and continuation contract. It also makes accidental unmatched comparisons easier.

### 3.3 Strict paired replay difference — selected

Each trial contains a control telemetry batch and treatment telemetry batch over the same base candidates, plus one outcome per arm. The evaluator calculates treatment-minus-control deltas within each pair and aggregates those paired deltas.

## 4. Existing contracts consumed

- `InheritedRerankTelemetryBatch` identifies the policy, candidate set, base/final ranks, adjustments, and router decision without raw query or memory content.
- `OutcomeMeasurement` supplies a bounded task score, success flag, tokens used, and latency.
- SHA-256 context and continuation fingerprints identify the matched task and downstream execution contract.

The evaluator does not re-run the reranker and does not inspect memory bodies.

## 5. Core contracts

### 5.1 `PairedRerankPolicyTrial`

One immutable matched replay pair:

- deterministic `trial_id`;
- `space_id`;
- `context_set_hash`;
- `continuation_set_hash`;
- `control_batch`;
- `treatment_batch`;
- `control_outcome`;
- `treatment_outcome`.

Validation requires:

1. all UUIDs and hashes are valid;
2. both batches belong to the same space as the trial;
3. both batches reference the same `router_decision_id`;
4. control and treatment policy fingerprints differ;
5. candidate UUID sets are identical;
6. base rank and base score are identical per candidate within a fixed tolerance;
7. control and treatment outcomes are `OutcomeMeasurement` values;
8. no raw query or arbitrary metadata is accepted.

The trial exposes deterministic deltas:

```text
score_delta = treatment.score - control.score
success_delta = int(treatment.success) - int(control.success)
token_delta = treatment.tokens_used - control.tokens_used
latency_delta_ms = treatment.latency_ms - control.latency_ms
```

It also exposes policy-behavior diagnostics:

- whether treatment changed the top candidate relative to control;
- treatment applied-observation count;
- treatment absolute adjustment sum;
- control and treatment telemetry batch UUIDs.

### 5.2 `PairedPolicyEvaluationConfig`

Immutable conservative evaluation controls:

- `minimum_pairs`, default `8`;
- `confidence_z`, default `1.96`;
- `minimum_promising_effect`, default `0.02`;
- `harmful_effect_threshold`, default `-0.02`;
- `neutral_effect_band`, default `0.01`;
- `maximum_standard_error`, default `0.10`;
- `maximum_token_increase_ratio`, default `0.05`;
- `maximum_latency_increase_ratio`, default `0.10`;
- `minimum_success_delta`, default `0.0`;
- `policy_version`, default `paired-rerank-policy-evaluation-v0`.

Threshold relationships are validated:

```text
harmful_effect_threshold < 0
neutral_effect_band >= 0
minimum_promising_effect >= neutral_effect_band
maximum resource ratios >= 0
```

The config does not contain a learned coefficient.

### 5.3 `PairedPolicyVerdict`

- `insufficient_evidence`
- `harmful`
- `too_costly`
- `promising`
- `neutral`
- `inconclusive`

### 5.4 `PairedPolicyAbstentionReason`

- `insufficient_pairs`
- `standard_error_too_high`

An abstention is represented explicitly rather than converted to a neutral verdict.

### 5.5 `PairedRerankPolicyEvaluation`

One immutable deterministic evaluation:

- evaluation UUID;
- space UUID;
- control and treatment policy fingerprints/versions;
- trial count;
- paired score mean, sample standard deviation, standard error, and confidence interval;
- paired success mean;
- paired token and latency mean deltas;
- token and latency increase ratios relative to control totals;
- treatment top-change rate;
- treatment applied-observation rate;
- treatment mean absolute adjustment;
- verdict;
- optional abstention reason;
- config version and fingerprint;
- ordered trial UUIDs;
- deterministic content hash.

Direct or inherited memory credit is not part of this result.

## 6. Exact matching contract

For every candidate memory UUID, control and treatment telemetry must contain the same:

- base rank;
- base score within `1e-12`;
- base candidate membership.

The treatment may change final ranks and scores only through its own bounded policy. The evaluator does not require identical final rankings.

Control and treatment must share one `router_decision_id`. This proves they began from the same routed scope and candidate source. Context and continuation hashes prove the same replay input and downstream execution settings.

If these conditions fail, the trial cannot be constructed.

## 7. Trial normalization and conflicts

`PairedRerankPolicyEvaluator.evaluate(...)` accepts an unordered trial sequence.

- exact duplicate trial values are deduplicated;
- the same `trial_id` with different immutable content fails closed;
- all trials must share one space, control policy fingerprint, treatment policy fingerprint, and config-compatible outcome metric;
- control and treatment roles cannot be reversed across trials;
- output trial IDs are lexically sorted.

A control policy may be a zero-adjustment bounded policy or another reviewed bounded policy. V0 does not assume a special policy name.

## 8. Paired estimator

For paired score deltas `d_i`:

```text
mean_delta = mean(d_i)
sample_variance = sum((d_i - mean_delta)^2) / (n - 1)  when n > 1
sample_standard_deviation = sqrt(sample_variance)
standard_error = sample_standard_deviation / sqrt(n)
confidence_interval = mean_delta ± confidence_z × standard_error
```

For one pair, sample standard deviation and standard error are `0.0`, but the default minimum-pair gate prevents deployment conclusions.

Success, token, and latency deltas are aggregated as paired means. Resource ratios use totals:

```text
token_increase_ratio = total_token_delta / max(total_control_tokens, 1)
latency_increase_ratio = total_latency_delta / max(total_control_latency_ms, 1)
```

Ratios may be negative when treatment saves resources.

## 9. Verdict ordering

Verdicts are evaluated in this order:

1. **insufficient evidence** when `n < minimum_pairs`;
2. **insufficient evidence** when standard error exceeds `maximum_standard_error`;
3. **harmful** when the confidence-interval upper bound is at or below `harmful_effect_threshold`;
4. **too costly** when token or latency increase ratio exceeds its configured maximum and the lower confidence bound has not established the promising-effect threshold;
5. **promising** when the confidence-interval lower bound is at or above `minimum_promising_effect`, paired success mean is at least `minimum_success_delta`, and resource limits pass;
6. **neutral** when the full confidence interval lies inside `[-neutral_effect_band, +neutral_effect_band]` and resource limits pass;
7. **inconclusive** otherwise.

The ordering prevents a positive point estimate with an uncertain lower bound from hiding resource regressions, while a confidently beneficial treatment can be reported as promising only when all gates pass.

## 10. Deterministic identity

### Config fingerprint

SHA-256 of every config field.

### Trial content hash

SHA-256 of:

- trial and space UUIDs;
- context/continuation hashes;
- control/treatment telemetry batch UUID and content hash;
- control/treatment outcome fields.

### Evaluation identity

The evaluator hashes:

- space UUID;
- control/treatment policy identity;
- config fingerprint;
- lexically ordered trial content hashes;
- all computed aggregate fields and verdict.

The evaluation UUID is UUID5 under a fixed namespace and the evaluation content hash.

Exact retries and trial-order permutations therefore produce byte-identical JSON and IDs.

## 11. Privacy boundary

The contracts contain only:

- UUIDs and SHA-256 fingerprints;
- bounded task scores and success flags;
- token and latency counts;
- aggregate telemetry batch identities and summaries;
- statistical aggregates and verdicts.

They exclude:

- query, prompt, answer, or memory content;
- command, stdout, stderr, patch, or environment;
- secret, API key, token string, or connection URL;
- individual memory credit or feedback notes;
- arbitrary metadata mappings.

## 12. Testing strategy

The suite must cover:

1. immutable trial, config, and evaluation contracts;
2. exact candidate/base-ranking match validation;
3. policy-role consistency;
4. outcome and hash validation;
5. exact paired delta calculations;
6. sample standard deviation, standard error, and confidence interval;
7. every verdict and abstention reason;
8. resource ratio gates;
9. top-change, applied-observation, and adjustment diagnostics;
10. exact retry and input-order invariance;
11. exact duplicate deduplication and conflicting trial-ID rejection;
12. no individual memory credit in the output;
13. at least 5,000 deterministic generated experiments preserving matching, identities, statistics, verdict ordering, and privacy;
14. a deterministic simulation showing paired standard error below an unpaired estimator under correlated outcomes and all six verdict classes;
15. stable root-package exports.

## 13. Non-goals

V0 does not:

- support observational propensity-weighted OPE;
- claim randomized online causality;
- attribute outcomes to memories;
- write feedback, telemetry, or database rows;
- deploy or select a policy automatically;
- learn thresholds or coefficients;
- handle temporal-drift calibration;
- alter routing, retrieval, reranking, or context compilation;
- merge any pull request.

## 14. Success criteria

The feature is complete when matched control/treatment replays can be validated, paired differences and uncertainty can be computed deterministically, weak or costly evidence cannot receive a promising verdict, the result contains no memory-level reward leakage, 5,000 generated experiments pass, and the complete repository is green on Python 3.12 and 3.13 without database or protected-policy changes.
