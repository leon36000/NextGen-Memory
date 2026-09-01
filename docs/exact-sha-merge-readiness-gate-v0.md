# Exact-SHA Merge Readiness Gate v0

## Status

This component is a pure deterministic advisory boundary. It evaluates exact candidate identity, R4 review-registry evidence, verification evidence, ordered dependency readiness, branch controls, and bounded freshness policy. It returns `READY`, `HOLD`, or `BLOCKED` and never executes a merge.

## Precedence

Hard blocks suppress all holds. Identity drift, blocked/evidence-blocked review state, unauthenticated approval, verification failures, dependency duplication, and branch-control violations are `BLOCKED`. Missing, stale, or insufficient but non-contradictory evidence is `HOLD`. `READY` requires every exact identity and verification gate to pass.

## Review evidence

The gate consumes exact R4 `ExactShaReviewRequest`, `ReviewAttestationRegistrySummary`, and `ReviewAttestationDecision` instances. Their canonical identities are revalidated before use. An externally supplied authentication boolean and authenticated-envelope evidence digest are required for an approved review to become ready; this module verifies no signature itself.

## Verification and dependencies

Verification binds exact base/candidate/diff identities, static and compile status, full-suite status/count, artifact integrity, isolated wheel, integration rehearsal, cross-Python semantic identity, optional PostgreSQL replay, migration count, freshness, and artifact/checkpoint digests. Dependencies are an exact ordered non-empty tuple with contiguous ordinals and unique component/SHA identities.

## Safety boundary

`READY` is evidence only. The module has no GitHub client, network/database/filesystem/environment/clock/randomness/model/worker/task surface and cannot merge, migrate, deploy, write feedback, activate policy, or publish a release.
