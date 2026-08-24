# Paired Replay Experiment Registry v0 — Implementation Plan

**Date:** 2026-08-24
**Base:** `candidate/paired-rerank-policy-evaluation-v0-20260824`
**Issue:** #132

## Goal

Implement a deterministic in-memory planner and registry that creates complete matched `PairedRerankPolicyTrial` values without executing models, persisting state, activating policy, or emitting feedback.

## Sequence

1. Prove a Ruff-clean module-absence RED.
2. Validate immutable experiment and budget contracts.
3. Generate seed-independent pair identities and balanced seed-driven arm order.
4. Register exact plans idempotently and expose one schedulable arm per pair.
5. Validate step, pair, experiment, space, policy, router decision, and budgets before mutation.
6. Complete one evaluator trial only after two matched arms.
7. Preserve terminal failure and cancellation with bounded codes.
8. Prove deterministic snapshots, summaries, 5,000 generated traces, and hash-seed invariance.
9. Require Python 3.12/3.13 exact-SHA verification, isolated wheel import, and blind GPT-5.6 Sol review before merge.

## Safety boundary

V0 contains no model execution, persistence, database, migration, network, filesystem write, workflow engine, lease, worker, feedback write, policy activation, raw content, arbitrary error text, stub, skipped test, or automatic merge.
