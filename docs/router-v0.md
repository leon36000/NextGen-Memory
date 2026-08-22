# Deterministic Memory-MoE Router v0

Router v0 is the first executable control-plane component of NextGen Memory. It is deliberately
non-neural: its purpose is to establish stable routing semantics and collect trustworthy
`request → route → retrieval → outcome` telemetry before training a learned router.

## Routing request

A `RoutingRequest` contains:

- a hard `RoutingScope` (`space_id`, project, optional repository/branch/principals,
  permissions, sensitivity clearance);
- task kind and plan phase;
- explicit evidence needs such as `current_state`, `historical`, `causal`, `failure`,
  `procedure`, or `research`;
- temporal intent, exactness requirement, risk, and uncertainty;
- total token, latency, and expert-count budgets;
- a minimum authority threshold used by candidate eligibility checks.

Upstream agents should provide explicit features rather than expecting this router to infer every
intent from natural language. A learned classifier can later produce the same stable contract.

## Two separate gates

### Expert eligibility

The router first determines which expert families may be activated. For example, `repository` is
ineligible without a repository scope and `repository:read`; `feedback` is maintenance-only and is
never injected into ordinary answer context.

### Memory-candidate eligibility

`evaluate_candidate_eligibility` runs before lexical or vector relevance. It rejects candidates on:

- space, project, repository, branch, user, or agent mismatch;
- missing permissions;
- sensitivity above the caller's clearance;
- authority below the request minimum;
- invalid temporal range;
- quarantine status.

A semantically perfect candidate that fails one of these checks remains inaccessible.

## Sparse selection and budgets

Eligible experts receive deterministic scores from task kind, plan phase, explicit evidence needs,
temporal intent, exactness, risk, and uncertainty. Selection is bounded by both `max_experts` and
the request token budget. Each selected expert receives a positive allocation, no allocation exceeds
the expert hard maximum, and the total never exceeds the request budget.

The decision also includes an ordered escalation list. A future evidence-gap controller can query
these experts progressively instead of retrieving from all stores at once.

## Telemetry

Passing a `RoutingDecisionSink` records a `RoutingTelemetryRecord`. The default record contains:

- SHA-256 of the query, not raw query text;
- sanitized routing features;
- eligible/selected experts;
- allocations, confidence, reasons, and escalation order.

This record maps directly to the canonical `ngm.router_decisions` control-plane schema.

## Deterministic decision identity

Router policy version `deterministic-v1` binds each `decision_id` to the
complete privacy-safe request policy and deterministic route outcome. The
identity includes the request UUID, SHA-256 fingerprints of the normalized
query and complete hard scope, all routing features and budgets, eligible
experts, ordered allocations and escalation, confidence, and policy version.

Raw query text and raw user or agent identifiers never enter the UUID5 name.
The complete safe payload is serialized as canonical sorted JSON and hashed;
the UUID5 name contains only the policy version and the final SHA-256 digest.
Set-like fields are sorted while execution-order fields preserve order.

Historical `deterministic-v0` rows remain historical evidence. New v1
decisions receive new identities; no existing row is rewritten.

## Non-goals of v0

- no embedding or LLM-based routing;
- no retrieval execution;
- no autonomous write admission;
- no utility learning before downstream outcome data exists;
- no claim that heuristic scores are optimal.

These omissions are intentional. Router v0 is a safe baseline and data-collection policy.
