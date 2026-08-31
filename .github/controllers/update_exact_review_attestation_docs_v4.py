#!/usr/bin/env python3
"""Bind review-registry product documentation to the qualified RED v4."""

from __future__ import annotations

import argparse
from pathlib import Path

_RED_V2_BRANCH = "tdd/exact-sha-review-attestation-registry-v0-red-v2-20260825"
_RED_V4_BRANCH = "tdd/exact-sha-review-attestation-registry-v0-red-v4-20260825"
_RED_V2_SHA = "4f0a74e0d39a181b682d2b135012184c255928bc"
_RED_V4_SHA = "130db57eaa2fe0f9809bfa672c0467ce087a8089"
_PLAN_HEADING_V2 = (
    "### Task 1: Record the complete tests-only module-absence RED v2"
)
_PLAN_HEADING_V4 = (
    "### Task 1: Record the complete tests-only module-absence RED v4"
)
_SPEC_CONTEXT_SENTENCE = (
    " RED v4 additionally preserves the RED-v3 behavior and assertion contract "
    "while removing context-dependent package-root import classification through "
    "the standard-library importlib bootstrap."
)


def _replace_zero_or_one(source: str, old: str, new: str, *, label: str) -> str:
    old_count = source.count(old)
    new_count = source.count(new)
    if old_count == 1 and new_count == 0:
        return source.replace(old, new, 1)
    if old_count == 0 and new_count >= 1:
        return source
    raise SystemExit(
        f"{label}: expected one old form or an existing new form, "
        f"found old={old_count}, new={new_count}"
    )


def _update_plan(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    source = _replace_zero_or_one(
        source,
        _PLAN_HEADING_V2,
        _PLAN_HEADING_V4,
        label="plan RED heading",
    )
    source = source.replace(_RED_V2_BRANCH, _RED_V4_BRANCH)
    source = source.replace(_RED_V2_SHA, _RED_V4_SHA)
    if _RED_V2_BRANCH in source or _RED_V2_SHA in source:
        raise SystemExit("plan retains a qualified RED-v2 identity")
    if _PLAN_HEADING_V4 not in source:
        raise SystemExit("plan RED-v4 task heading is absent")
    if _RED_V4_BRANCH not in source:
        raise SystemExit("plan RED-v4 branch identity is absent")
    path.write_text(source, encoding="utf-8")


def _update_spec(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    source = source.replace(_RED_V2_BRANCH, _RED_V4_BRANCH)
    source = source.replace(_RED_V2_SHA, _RED_V4_SHA)
    anchor = (
        "All test files must be Ruff-clean and syntactically valid. Each "
        "independent collection must fail only because "
        "`nextgen_memory.review_attestation_registry` does not exist."
    )
    if source.count(anchor) != 1:
        raise SystemExit("spec tests-only RED anchor is absent or duplicated")
    if _SPEC_CONTEXT_SENTENCE not in source:
        source = source.replace(anchor, anchor + _SPEC_CONTEXT_SENTENCE, 1)
    if _RED_V2_BRANCH in source or _RED_V2_SHA in source:
        raise SystemExit("spec retains a qualified RED-v2 identity")
    if _RED_V4_BRANCH not in source or _RED_V4_SHA not in source:
        raise SystemExit("spec RED-v4 branch/SHA identity is absent")
    if source.count(_SPEC_CONTEXT_SENTENCE) != 1:
        raise SystemExit("spec RED-v4 context sentence is absent or duplicated")
    path.write_text(source, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--red-sha", required=True)
    arguments = parser.parse_args()
    if arguments.red_sha != _RED_V4_SHA:
        raise SystemExit("documentation updater is bound to another RED SHA")
    plan = Path(arguments.plan)
    spec = Path(arguments.spec)
    _update_plan(plan)
    _update_spec(spec)
    print(
        "exact_review_attestation_docs_red_v4_bound=1 "
        f"red_v4_sha={_RED_V4_SHA}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
