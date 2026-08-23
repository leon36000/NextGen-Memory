# Release Wheel Integrity and Reproducibility v1 — Design

**Date:** 2026-08-23
**Status:** approved implementation direction
**Issue:** #94
**Base:** `937385e4d9235841a38fb28d079fcc0c7c3abe79`

## Objective

Qualify one pure-Python wheel as a safe release artifact without changing runtime behavior or publishing a package. The gate must distinguish three claims:

1. **functional integrity:** the wheel is structurally safe, carries the expected package and metadata, installs outside the checkout, imports from the isolated environment, exposes the package-root API, and passes `pip check`;
2. **same-interpreter byte reproducibility:** two clean builds of the same exact source SHA under the same Python interpreter and pinned toolchain produce the same wheel bytes;
3. **cross-interpreter byte identity:** Python 3.12 and 3.13 happen to produce the same wheel bytes under the fixed toolchain. This is recorded independently and is never inferred from same-interpreter success.

Only the first two claims are required by the v1 gate. Cross-interpreter identity is reported as additional evidence and may be false without being mislabeled as same-interpreter failure.

## Components

### Dependency-free wheel inspector

`scripts/verify_release_wheel.py` reads a wheel directly with `zipfile`. It never extracts the archive and never imports its code.

The inspector validates:

- the input is one regular non-symlink `.whl` file;
- archive member names are canonical POSIX relative names;
- no member is absolute, empty, NUL-containing, backslash-separated, traversal-based, dot-component-based, duplicate, or case-colliding;
- no VCS, test, cache, compiled-code, credential, key, certificate, local-environment, or editor payload is present;
- exactly one `METADATA`, `WHEEL`, and `RECORD` file exists in one `.dist-info` directory;
- metadata is valid UTF-8 email metadata with exact normalized distribution name and exact version;
- the package root and every explicitly required top-level module exist;
- the wheel hash and individual member hashes are computed from exact bytes.

The inspector emits a frozen, slotted report containing allowlisted evidence only:

- wheel filename, SHA-256, size, distribution, version;
- member/package counts;
- sorted required modules;
- SHA-256 values for `METADATA`, `WHEEL`, and `RECORD`;
- no filesystem parent path, archive content, metadata summary, source code, environment value, command output, or credential.

### Reproducibility comparator

The same module compares two already-inspected wheels.

For equal bytes, it returns a deterministic report with `byte_reproducible=true` and `semantic_reproducible=true`.

For differing bytes, it fails closed with a bounded diagnostic built only from validated archive evidence:

- relative member name;
- presence on left/right;
- uncompressed size, compressed size, CRC-32, ZIP timestamp, and SHA-256 on each side;
- no member contents, filesystem paths, command output, environment, or repository paths.

Semantic equality means that both wheels have the same validated distribution/version, member set, member hashes, safe metadata identity, required modules, and wheel tag metadata. Byte equality remains a separate field.

### Source-date contract

The build workflow derives `SOURCE_DATE_EPOCH` from `git show -s --format=%ct <exact SHA>`. The value must be a canonical decimal integer within the ZIP-compatible range beginning at 1980-01-01 UTC. Empty, signed, whitespace-padded, non-decimal, pre-1980, or out-of-range values fail closed. The implementation never falls back to wall-clock time.

### Read-only GitHub Actions gate

`.github/workflows/release-wheel-integrity.yml` is pull-request-only, path-filtered, and has `contents: read` permission. It uses no repository secret and has no publication surface.

For Python 3.12 and 3.13 independently, it:

1. proves the exact checked-out SHA;
2. installs pinned build tools and development dependencies;
3. runs Ruff, focused release tests, compileall, and the complete suite;
4. archives the exact Git tree into two separate clean source directories;
5. derives one commit-bound `SOURCE_DATE_EPOCH`;
6. builds one wheel in each directory with identical environment and `--no-isolation`;
7. requires exactly one wheel per build;
8. inspects both wheels and requires same-interpreter byte and semantic reproducibility;
9. installs one wheel into a virtual environment outside the checkout;
10. runs isolated imports from a temporary directory, verifies `nextgen_memory.__file__` is under that virtual environment, resolves every name in `nextgen_memory.__all__`, and runs `pip check`;
11. uploads only the two wheels and canonical safe JSON reports for bounded retention.

A final matrix-summary job compares the successful Python 3.12 and 3.13 outputs and records `cross_python_byte_identical` separately. It must not rewrite same-interpreter status.

## Failure model

`WheelValidationError` and `WheelReproducibilityError` use fixed bounded messages. They never embed archive contents, filesystem paths, raw metadata values beyond normalized distribution/version, environment values, tool output, or credentials.

The CLI writes exactly one canonical JSON object on success and one canonical bounded JSON error object to stderr on failure. It exits nonzero on invalid artifacts or failed same-interpreter reproducibility.

## File boundaries

- `scripts/verify_release_wheel.py`: archive validation, safe reports, comparison, source-date validation, and CLI;
- `tests/test_release_wheel_integrity.py`: inspector/comparator/source-date/CLI adversarial contracts;
- `tests/test_release_wheel_workflow.py`: static workflow permissions, path filters, build isolation, install/import, and report separation;
- `.github/workflows/release-wheel-integrity.yml`: executable cross-version release gate;
- `docs/superpowers/plans/2026-08-23-release-wheel-integrity-v1.md`: implementation sequence.

`src/nextgen_memory/`, migrations, package-root exports, runtime dependencies, and database contracts remain unchanged.

## Non-goals

- publishing to PyPI or another registry;
- signing, provenance attestations, or SBOM generation;
- claiming reproducibility on macOS, Windows, alternate architectures, or unpinned toolchains;
- accepting cross-Python byte identity as a substitute for same-interpreter double-build proof;
- extracting or executing untrusted wheel contents during inspection;
- changing runtime package semantics to make packaging tests pass.

## Merge gate

The exact candidate SHA requires focused RED→GREEN evidence, repository-wide Python 3.12/3.13 CI, exact raw-SHA workflow verification, bounded artifact review, and genuine blind GPT-5.6 Sol `APPROVE`. No package publication or production operation is coupled to merge.