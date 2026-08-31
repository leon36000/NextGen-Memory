# Memory Policy Dataset v0 — TDD RED Evidence

**Date:** 2026-08-31  
**Base:** verified post-merge `main` recorded by `evidence/m-head-main-postmerge-checkpoint-20260831`  
**TDD branch:** `tdd/memory-policy-dataset-v0-red-20260831`

## Contract under test

The tests-only RED defines a pure, deterministic, privacy-bounded dataset layer for a later learned memory reranker. It requires:

- immutable candidate feature vectors containing only bounded numerical and hashed inputs;
- exact candidate observations with direct causal, matched replay, interaction-allocation, observational, or absent credit;
- labels `beneficial`, `neutral`, `harmful`, and `abstain`;
- absent, observational, low-confidence, or ambiguous evidence mapped to `abstain`, never automatically to `harmful`;
- direct and interaction credit accepted only for candidates selected and actually used;
- matched replay allowed to supervise an unselected counterfactual candidate;
- one immutable decision trace per exact trajectory/event key;
- exact retry idempotence and immutable conflict rejection before mutation;
- a hard 128-candidate iterator bound;
- train/validation/test assignment by each trajectory's maximum registered event ordinal;
- zero trajectory overlap across splits;
- trainable split lists containing only non-abstain examples;
- deterministic example and snapshot identities, JSON, JSONL, and process hash-seed behavior;
- at least 5,000 generated traces spanning every label and split;
- inference-safe feature payloads separated from target and audit fields;
- explicit package-root exports.

## Intended precise RED

The product module and package-root exports do not exist on the immutable base. Before implementation, all three test files must be Ruff 0.16.4 clean, formatting clean, and syntactically valid. Each test file must independently fail collection only because:

```text
nextgen_memory.memory_policy_dataset
```

Any syntax, fixture, setup, unrelated import, naming, or package-root failure invalidates the RED.

## Hard boundaries

The RED contains no implementation, stub, model, trainer, optimizer, inference runtime, filesystem/environment access, clock, randomness, network, database, worker, scheduler, feedback writer, merge action, policy activation, deployment, migration, or release behavior.

It contains no raw prompt, query, response, memory body, command output, credential, reviewer identity, account identity, arbitrary metadata, or source text.

No test may use `pass`, executable ellipsis, `NotImplementedError`, skip, xfail, opportunistic `noqa`, or weakened assertion.

## Next step after qualification

Only after this exact four-path RED is independently qualified may the feature branch overlay the same files and implement `src/nextgen_memory/memory_policy_dataset.py`. A later immutable product candidate must preserve the qualified tests and pass focused/full suites, 5,000 generated traces, process determinism, strict privacy/side-effect audit, isolated wheel import, and a Python 3.12/3.13 exact-SHA matrix.

Merging the dataset component will not authorize model training. The first learned reranker remains a separate milestone consuming only a versioned dataset snapshot with enough real trajectories and a chronological holdout.
