# Bounded Inherited Reranker v0

## Purpose

Bounded Inherited Reranker v0 lets inherited provenance evidence influence an already utility-aware ranked list without being mistaken for direct causal feedback.

It is an additive second stage:

```text
retrieval relevance
  → direct-aware Utility-Aware Reranker v0
  → bounded inherited adjustment
  → inherited-aware final rank
```

The existing `RerankedMemory` remains unchanged and is retained inside every result. The new component does not modify eligibility, routing, retrieval, direct utility, or database state.

## Evidence boundary

The reranker consumes one `NodeLearningEvidence` snapshot for every candidate:

```python
NodeLearningEvidence(
    direct=DirectUtilityEvidence(...),
    inherited=InheritedUtilityEvidence(...),
)
```

Only the nested `inherited` evidence is scored. The nested `direct` evidence is available for audit but is deliberately ignored by the inherited component because the base utility-aware score has already consumed direct evidence.

This prevents double counting.

## Contracts

### `BoundedInheritedRerankerConfig`

Default policy:

```text
inherited_weight = 0.10
maximum_absolute_adjustment = 0.05
prior_contribution_count = 8.0
minimum_contribution_count = 2
minimum_structural_confidence = 0.50
value_scale = 0.25
uncertainty_floor = 0.05
policy_version = bounded-inherited-reranker-v0
```

The hard adjustment cap cannot exceed the inherited weight. Scale and uncertainty-floor values must be positive. Count, confidence, and every numeric value are validated before scoring.

### `InheritedEvidenceDisposition`

Every candidate receives one explicit disposition:

- `no_evidence`;
- `below_minimum_count`;
- `below_minimum_confidence`;
- `applied`.

A gated candidate still receives a complete breakdown so weak evidence remains observable without changing its score.

### `InheritedScoreBreakdown`

The breakdown records:

- contribution count;
- signed and absolute inherited value sums;
- conservative standard-error sum;
- minimum structural confidence;
- inherited mean;
- saturated signed signal;
- count shrinkage;
- path coherence;
- uncertainty reliability;
- confidence reliability;
- uncapped component;
- applied component;
- disposition and policy version.

No direct reward or direct verdict component appears in this breakdown.

### `InheritedAwareRerankedMemory`

One result contains:

```python
InheritedAwareRerankedMemory(
    base=RerankedMemory(...),
    final_rank=...,
    final_score=...,
    inherited_breakdown=InheritedScoreBreakdown(...),
)
```

`base` is the exact original object, including its original rank, direct-aware score, and direct score breakdown.

## Scoring equation

For inherited evidence with:

- `n`: contribution count;
- `v`: signed value sum;
- `a`: absolute value sum;
- `s`: conservative standard-error sum;
- `q`: minimum structural confidence;

### Signed saturated signal

```text
mean = v / n
signed_signal = tanh(mean / value_scale)
```

The `tanh` transform prevents an arbitrarily large inherited value from creating an unbounded adjustment.

### Empirical-Bayes count shrinkage

```text
count_shrinkage = n / (n + prior_contribution_count)
```

A small number of provenance paths therefore receives limited influence even when their value is large.

### Path coherence

```text
path_coherence = abs(v) / a      when a > 0
path_coherence = 1               when a = 0 and v = 0
```

Opposing paths increase the absolute mass while cancelling the signed mass, reducing the final component.

### Uncertainty reliability

```text
uncertainty_reliability = 1 / (1 + s / (a + uncertainty_floor))
```

Larger conservative uncertainty reduces inherited influence.

### Structural reliability

```text
confidence_reliability = q
```

The policy uses the minimum structural confidence, not an optimistic average.

### Applied component

```text
uncapped = (
    inherited_weight
    × signed_signal
    × count_shrinkage
    × path_coherence
    × uncertainty_reliability
    × confidence_reliability
)

applied = clamp(
    uncapped,
    -maximum_absolute_adjustment,
    +maximum_absolute_adjustment,
)

final_score = base.final_score + applied
```

## Hard neutral gates

The applied component is exactly zero when:

- no inherited contribution exists;
- contribution count is below `minimum_contribution_count`;
- minimum structural confidence is below the configured threshold.

These gates execute before the component is applied. The underlying evidence and diagnostic factors remain visible.

## Fail-closed input behavior

`BoundedInheritedReranker.rerank()` requires:

1. a canonical UUID `space_id`;
2. unique candidate memory UUIDs;
3. positive, unique, contiguous base ranks;
4. finite base final scores;
5. an evidence mapping whose UUID set exactly equals the candidate UUID set;
6. mapping keys equal to each snapshot's `memory_id`;
7. every snapshot belong to the supplied space;
8. every value satisfy `NodeLearningEvidence` invariants.

Missing evidence does not fall back to direct-only ranking. Extra evidence is not ignored. A valid neutral inherited snapshot is the only zero-evidence representation.

## Deterministic ranking

Candidates are sorted by:

1. inherited-aware final score descending;
2. base final rank ascending;
3. lexical memory UUID.

Final ranks are contiguous from one. Candidate input order and evidence-mapping order do not affect the output.

## Security and authority boundary

Inherited evidence cannot:

- admit an ineligible memory;
- bypass scope, sensitivity, or authorization checks;
- trigger retrieval;
- overwrite direct evidence;
- change the original base object;
- exceed the configured hard cap;
- write feedback or telemetry;
- alter a database schema.

The component runs only after routing, eligibility, retrieval, and direct-aware reranking.

## Deterministic simulation

Run:

```bash
python scripts/simulate_bounded_inherited_reranker_v0.py
```

The simulation compares naive `base_score + inherited_mean` with the bounded policy across five scenarios.

| Scenario | Naive behavior | Bounded behavior |
|---|---|---|
| One rare, very large path | false promotion | count gate, no adjustment |
| Low structural confidence | false promotion | confidence gate, no adjustment |
| Strongly conflicting paths | false promotion | coherence penalty |
| High uncertainty | false promotion | uncertainty penalty |
| Many consistent, confident paths | promotion | promotion retained, capped |

Expected aggregate result:

```text
scenario_count = 5
naive_false_promotions = 4
bounded_false_promotions = 0
bounded_strong_promotions = 1
maximum_absolute_adjustment = 0.05
```

## Generated verification

`tests/test_bounded_inherited_reranker_properties.py` executes 10,000 deterministic ranking cases and verifies:

- finite scores;
- hard adjustment cap;
- exact candidate/evidence set equality;
- unique memories and contiguous ranks;
- neutral count/confidence gates;
- deterministic input and mapping permutations;
- preservation of the original base object;
- direct-evidence invariance;
- applied evidence meets minimum count and confidence rules.

An additional 2,000 generated direct-evidence permutations prove that changing only `NodeLearningEvidence.direct` never changes the inherited breakdown or inherited-aware score.

## Privacy boundary

The component accepts typed aggregates and UUIDs only. It does not consume or emit:

- query text;
- prompts or answers;
- memory bodies;
- commands, stdout, or stderr;
- patches or environment values;
- secrets, tokens, or free-form feedback notes.

A future telemetry adapter may persist numeric breakdown fields, UUIDs, ranks, scores, disposition, and policy version, but not raw query or memory content.

## Minimal example

```python
from nextgen_memory import (
    BoundedInheritedReranker,
    NodeLearningEvidence,
)

results = BoundedInheritedReranker().rerank(
    space_id=space_id,
    base_results=utility_aware_results,
    learning_evidence=evidence_by_memory_id,
)

for result in results:
    print(
        result.base.hit.memory_id,
        result.final_rank,
        result.final_score,
        result.inherited_breakdown.applied_component,
        result.inherited_breakdown.disposition,
    )
```

## Non-goals

V0 does not:

- modify Utility-Aware Reranker v0;
- modify `NodeUtilityReader`;
- query Neon;
- write telemetry or feedback;
- learn coefficients;
- consume path-level raw provenance rows;
- combine direct and inherited evidence into one opaque feature;
- change candidate eligibility;
- promote migration `0006`;
- guarantee globally optimal ranking.
