# Bounded Inherited Reranker v0 Design

**Date:** 2026-08-14  
**Status:** approved under the project owner's standing architecture delegation  
**Base:** `feat/learning-evidence-reader-v0`

## 1. Goal

Bounded Inherited Reranker v0 allows inherited provenance evidence to influence an already utility-reranked candidate list without being confused with direct task feedback and without acquiring enough authority to dominate relevance, eligibility, or direct causal evidence.

It consumes:

- `RerankedMemory` values produced by Utility-Aware Reranker v0;
- one exact `NodeLearningEvidence` snapshot per candidate;
- one explicit conservative configuration.

It returns a new ranked list with a complete inherited-evidence breakdown. It does not modify the existing reranker, reader, database views, or direct utility contracts.

## 2. Why an additive second-stage policy

Utility-Aware Reranker v0 already combines retrieval relevance with direct feedback and explicit harm evidence. Replacing it would risk:

- double-counting direct evidence;
- changing established score semantics;
- breaking no-feedback neutrality;
- hiding whether a score came from observed outcomes or graph inheritance.

The selected architecture preserves the base result verbatim and adds one bounded inherited component:

```text
base utility-aware score
+ explicitly bounded inherited component
= inherited-aware score
```

Direct fields from `NodeLearningEvidence` are retained for audit but are not scored again.

## 3. Core contracts

### 3.1 `InheritedEvidenceDisposition`

- `no_evidence`
- `below_minimum_count`
- `below_minimum_confidence`
- `applied`

The disposition explains why inherited evidence did or did not affect a score.

### 3.2 `BoundedInheritedRerankerConfig`

Immutable policy values:

- `inherited_weight`: non-negative multiplier, default `0.10`;
- `maximum_absolute_adjustment`: hard score cap, default `0.05`;
- `prior_contribution_count`: empirical-Bayes shrinkage prior, default `8.0`;
- `minimum_contribution_count`: hard evidence floor, default `2`;
- `minimum_structural_confidence`: hard confidence floor, default `0.50`;
- `value_scale`: positive scale for the signed `tanh` transform, default `0.25`;
- `uncertainty_floor`: positive numerical/evidence floor, default `0.05`;
- `policy_version`: `bounded-inherited-reranker-v0`.

All values are finite. Probability-like fields stay in `[0, 1]`. The maximum adjustment may not exceed the inherited weight.

### 3.3 `InheritedScoreBreakdown`

One immutable, fully explicit calculation:

- contribution count;
- signed value sum;
- absolute value sum;
- standard-error sum;
- minimum structural confidence;
- inherited mean value;
- signed saturated signal;
- count shrinkage;
- path coherence;
- uncertainty reliability;
- confidence reliability;
- uncapped component;
- applied component;
- disposition;
- policy version.

No field is inferred from free-form text.

### 3.4 `InheritedAwareRerankedMemory`

One immutable result containing:

- original `RerankedMemory` as `base`;
- inherited-aware final rank;
- inherited-aware final score;
- `InheritedScoreBreakdown`.

The original hit, base final rank, base final score, direct utility evidence, and base score breakdown remain reachable through `base`.

## 4. Fail-closed input contract

`BoundedInheritedReranker.rerank(...)` receives:

- canonical `space_id`;
- base results;
- a UUID-keyed mapping of learning evidence.

It requires:

1. every base result has one unique memory UUID;
2. base final ranks are unique, positive, and contiguous;
3. base final scores are finite;
4. evidence UUIDs exactly equal candidate UUIDs;
5. every evidence row matches the supplied space and mapping key;
6. no unexpected evidence is ignored;
7. all evidence values already satisfy `NodeLearningEvidence` invariants.

Missing or extra evidence raises `BoundedInheritedRerankerValidationError`. There is no fallback to direct-only ranking after a malformed combined-evidence read. A valid explicit neutral inherited record produces zero adjustment.

## 5. Conservative scoring equation

For inherited evidence with count `n`, signed sum `v`, absolute sum `a`, standard-error sum `s`, and minimum structural confidence `q`:

### Mean signal

```text
mean = v / n
signed_signal = tanh(mean / value_scale)
```

`tanh` prevents arbitrarily large inherited values from creating arbitrarily large score changes.

### Count shrinkage

```text
count_shrinkage = n / (n + prior_contribution_count)
```

A small number of paths therefore receives little influence even when their inherited value is large.

### Path coherence

```text
coherence = abs(v) / a       when a > 0
coherence = 1                when a = 0 and v = 0
```

Opposing inherited paths cancel in the signed sum and reduce coherence. A large absolute mass with near-zero signed mass receives almost no adjustment.

### Uncertainty reliability

```text
uncertainty_reliability = 1 / (1 + s / (a + uncertainty_floor))
```

Higher conservative standard-error mass reduces influence. The floor prevents unstable division near zero.

### Confidence reliability

```text
confidence_reliability = q
```

The policy uses the minimum path confidence, not an optimistic average.

### Uncapped and applied components

```text
uncapped = (
    inherited_weight
    × signed_signal
    × count_shrinkage
    × coherence
    × uncertainty_reliability
    × confidence_reliability
)

applied = clamp(
    uncapped,
    -maximum_absolute_adjustment,
    +maximum_absolute_adjustment,
)
```

The final score is:

```text
base.final_score + applied
```

## 6. Hard neutral gates

The component is exactly zero when:

- contribution count is zero;
- count is below `minimum_contribution_count`;
- structural confidence is below `minimum_structural_confidence`.

The full breakdown is still returned. This preserves observability without allowing weak inherited evidence to move ranking.

## 7. Deterministic ranking

Candidates are evaluated independently and sorted by:

1. inherited-aware final score descending;
2. base final rank ascending;
3. lexical memory UUID.

Final ranks are contiguous from one. Input list order and evidence mapping order do not affect the result.

## 8. Security and authority boundary

Inherited evidence cannot:

- admit an ineligible memory;
- bypass scope or sensitivity filters;
- replace direct utility evidence;
- create authorization;
- trigger retrieval;
- alter the original base result;
- exceed the hard adjustment cap.

The policy operates only after routing, eligibility, retrieval, and direct-aware reranking.

## 9. No double-counting rule

`NodeLearningEvidence.direct` is not included in the new component. Its only permitted uses in v0 are:

- proving that the combined snapshot belongs to the expected memory;
- audit and debugging;
- future consistency checks.

The inherited breakdown contains no direct reward or verdict component. The final object retains the complete base breakdown and the inherited breakdown as separate nested values.

## 10. Telemetry boundary

V0 returns typed values only. It does not write telemetry.

A later adapter may persist:

- memory UUID;
- base score;
- inherited component;
- disposition;
- reliability factors;
- policy version;
- final rank and score.

It must not persist query text or memory content.

## 11. Testing strategy

The suite must cover:

1. configuration validation and immutability;
2. no-evidence neutrality;
3. minimum-count and minimum-confidence gates;
4. signed positive and negative adjustments;
5. count shrinkage monotonicity;
6. uncertainty penalty monotonicity;
7. confidence monotonicity;
8. path-coherence penalty under cancellation;
9. `tanh` saturation and hard cap;
10. exact evidence-set matching;
11. scope, duplicate UUID, rank, and finite-score failures;
12. deterministic tie-breaking and input permutation invariance;
13. original base result remains unchanged;
14. direct evidence does not change inherited component;
15. 10,000 deterministic generated cases preserving the cap, neutrality, monotonic constraints, and rank determinism;
16. a deterministic simulation comparing naive inherited addition with the bounded policy on sparse, conflicting, uncertain, and high-confidence evidence.

## 12. Non-goals

V0 does not:

- modify Utility-Aware Reranker v0;
- learn weights;
- combine direct and inherited evidence in one opaque feature;
- query Neon;
- write telemetry;
- change candidate eligibility;
- consume path-level raw records;
- promote migration `0006`;
- guarantee global ranking optimality.

## 13. Success criteria

The feature is complete when inherited evidence can change ranking only through the explicit bounded equation, neutral or weak evidence cannot move a score, all evidence classes remain separately inspectable, 10,000 generated cases preserve the hard invariants, and the full repository passes Python 3.12/3.13 verification without database mutation.
