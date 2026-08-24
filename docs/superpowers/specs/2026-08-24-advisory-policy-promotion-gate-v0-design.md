# Advisory Policy Promotion Gate v0 Design

**Date:** 2026-08-24
**Status:** implementation candidate
**Base:** `candidate/paired-replay-experiment-registry-v0-20260824`

The gate converts immutable matched-policy evidence and bounded operational readiness into one advisory `promote`, `hold`, or `reject` record. Hard safety, identity, registry/evaluation, harmful-verdict, negative-effect, and token/latency/harm breaches reject before any hold condition. In the absence of rejection, insufficient evidence, non-positive lower confidence, excess uncertainty, stale evidence, any active, failed, or cancelled registry pair, or operational/reviewer gaps hold. Promotion requires a complete `promising` evaluation.

All identifiers, counts, rates, confidence bounds, thresholds, and booleans are validated before evaluation. Token and latency thresholds are non-negative. Canonical JSON, SHA-256, and UUID5 bind all material inputs. No free-form content or activation, persistence, database, network, clock, environment, feedback, migration, deployment, merge, or release surface belongs in v0.
