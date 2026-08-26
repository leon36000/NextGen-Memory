#!/usr/bin/env python3
"""Bind review-registry product documentation to the qualified RED v5."""

from __future__ import annotations

import argparse
from pathlib import Path

_BASE_SHA = "f4f3aca9759b5b7a60691017c2211152c011ea92"
_RED_V5_BRANCH = "tdd/exact-sha-review-attestation-registry-v0-red-v5-20260825"
_RED_V5_SHA = "849df204e899d7570ef469d52307786cf242695a"
_OLD_BRANCHES = (
    "tdd/exact-sha-review-attestation-registry-v0-red-20260824",
    "tdd/exact-sha-review-attestation-registry-v0-red-v2-20260825",
    "tdd/exact-sha-review-attestation-registry-v0-red-v3-20260825",
    "tdd/exact-sha-review-attestation-registry-v0-red-v4-20260825",
)
_OLD_SHAS = (
    "4f0a74e0d39a181b682d2b135012184c255928bc",
    "0a8e193269e425dd51f740b495579f949a237ce1",
    "130db57eaa2fe0f9809bfa672c0467ce087a8089",
)
_PLAN_HEADINGS = (
    "### Task 1: Record the complete tests-only module-absence RED",
    "### Task 1: Record the complete tests-only module-absence RED v2",
    "### Task 1: Record the complete tests-only module-absence RED v3",
    "### Task 1: Record the complete tests-only module-absence RED v4",
)
_PLAN_HEADING_V5 = "### Task 1: Record the complete tests-only module-absence RED v5"
_PLAN_BASE_ANCHOR = f"- Exact base SHA: `{_BASE_SHA}`."
_PLAN_IDENTITY_LINES = (
    f"- Qualified tests-only RED branch: `{_RED_V5_BRANCH}`.\n"
    f"- Qualified tests-only RED SHA: `{_RED_V5_SHA}`."
)
_SPEC_BASE_ANCHOR = f"**Base SHA:** `{_BASE_SHA}`"
_SPEC_IDENTITY_LINES = (
    f"**Qualified RED branch:** `{_RED_V5_BRANCH}`\n"
    f"**Qualified RED SHA:** `{_RED_V5_SHA}`"
)
_SPEC_ANCHOR = (
    "All test files must be Ruff-clean and syntactically valid. Each "
    "independent collection must fail only because "
    "`nextgen_memory.review_attestation_registry` does not exist."
)
_SPEC_CONTEXT_SENTENCE = (
    " RED v5 preserves the accepted behavior and assertion contract while "
    "making all three test-module bootstraps context-invariant under the exact "
    "Ruff 0.16.4 product toolchain."
)


def _replace_old_identities(source: str) -> str:
    for branch in _OLD_BRANCHES:
        source = source.replace(branch, _RED_V5_BRANCH)
    for sha in _OLD_SHAS:
        source = source.replace(sha, _RED_V5_SHA)
    return source


def _require_no_obsolete_identity(source: str, *, label: str) -> None:
    for value in (*_OLD_BRANCHES, *_OLD_SHAS):
        if value in source:
            raise SystemExit(f"{label} retains obsolete RED identity: {value}")


def _update_plan(path: Path) -> None:
    source = _replace_old_identities(path.read_text(encoding="utf-8"))
    lines = source.splitlines(keepends=True)
    heading_indexes = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n") in (*_PLAN_HEADINGS, _PLAN_HEADING_V5)
    ]
    if len(heading_indexes) != 1:
        raise SystemExit(
            "plan must contain exactly one original, pre-v5, or v5 RED heading"
        )
    heading_index = heading_indexes[0]
    ending = "\n" if lines[heading_index].endswith("\n") else ""
    lines[heading_index] = _PLAN_HEADING_V5 + ending
    source = "".join(lines)
    if _PLAN_IDENTITY_LINES not in source:
        if source.count(_PLAN_BASE_ANCHOR) != 1:
            raise SystemExit("plan exact-base anchor is absent or duplicated")
        source = source.replace(
            _PLAN_BASE_ANCHOR,
            _PLAN_BASE_ANCHOR + "\n" + _PLAN_IDENTITY_LINES,
            1,
        )
    _require_no_obsolete_identity(source, label="plan")
    if source.count(_PLAN_HEADING_V5) != 1:
        raise SystemExit("plan RED-v5 task heading is absent or duplicated")
    if source.count(_RED_V5_BRANCH) < 1 or source.count(_RED_V5_SHA) < 1:
        raise SystemExit("plan RED-v5 branch/SHA identity is absent")
    path.write_text(source, encoding="utf-8")


def _update_spec(path: Path) -> None:
    source = _replace_old_identities(path.read_text(encoding="utf-8"))
    if _SPEC_IDENTITY_LINES not in source:
        if source.count(_SPEC_BASE_ANCHOR) != 1:
            raise SystemExit("spec exact-base anchor is absent or duplicated")
        source = source.replace(
            _SPEC_BASE_ANCHOR,
            _SPEC_BASE_ANCHOR + "\n" + _SPEC_IDENTITY_LINES,
            1,
        )
    if source.count(_SPEC_ANCHOR) != 1:
        raise SystemExit("spec tests-only RED anchor is absent or duplicated")
    prior_context = (
        " RED v4 additionally preserves the RED-v3 behavior and assertion "
        "contract while removing context-dependent package-root import "
        "classification through the standard-library importlib bootstrap."
    )
    source = source.replace(prior_context, "")
    if _SPEC_CONTEXT_SENTENCE not in source:
        source = source.replace(
            _SPEC_ANCHOR,
            _SPEC_ANCHOR + _SPEC_CONTEXT_SENTENCE,
            1,
        )
    _require_no_obsolete_identity(source, label="spec")
    if source.count(_RED_V5_BRANCH) < 1 or source.count(_RED_V5_SHA) < 1:
        raise SystemExit("spec RED-v5 branch/SHA identity is absent")
    if source.count(_SPEC_CONTEXT_SENTENCE) != 1:
        raise SystemExit("spec RED-v5 context sentence is absent or duplicated")
    path.write_text(source, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--red-sha", required=True)
    arguments = parser.parse_args()
    if arguments.red_sha != _RED_V5_SHA:
        raise SystemExit("documentation updater is bound to another RED SHA")
    _update_plan(Path(arguments.plan))
    _update_spec(Path(arguments.spec))
    print(
        "exact_review_attestation_docs_red_v5_bound=1 "
        f"red_v5_sha={_RED_V5_SHA}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
