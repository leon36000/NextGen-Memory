# Integrated Context Compiler v0 — TDD Evidence

## Approved design

The project owner approved `docs/superpowers/specs/2026-08-14-context-compiler-integrated-v0-design.md` before production implementation.

## Contract RED phase

The first implementation slice contains only:

- immutable compiler contract tests;
- the approved specification;
- the implementation plan.

Expected integrated RED result:

- Ruff passes;
- pytest fails during collection only because `nextgen_memory.integrated_context_compiler` does not exist;
- no production compiler module is present;
- no database, default-branch, merge, or deployment mutation occurs.

The exact workflow and job IDs will be added to the draft PR after GitHub Actions records the RED state.
