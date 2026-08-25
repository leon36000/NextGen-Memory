#!/usr/bin/env python3
"""Bind review-registry product documentation to the qualified RED v5."""

from __future__ import annotations

import argparse
from pathlib import Path

_RED_V2_BRANCH = "tdd/exact-sha-review-attestation-registry-v0-red-v2-20260825"
_RED_V4_BRANCH = "tdd/exact-sha-review-attestation-registry-v0-red-v4-20260825"
_RED_V5_BRANCH = "tdd/exact-sha-review-attestation-registry-v0-red-v5-20260825"
_RED_V2_SHA = "4f0a74e0d39a181b682d2b135012184c255928bc"
_RED_V4_SHA = "130db57eaa2fe0f9809bfa672c0467ce087a8089"
_RED_V5_SHA = "849df204e899d7570ef469d52307786cf242695a"
_PLAN_HEADINGS = (
    "### Task 1: Record the complete tests-only module-absence RED v2",
    "### Task 1: Record the complete tests-only module-absence RED v4",
)
_PLAN_HEADING_V5 = (
    "### Task 1: Record the complete tests-only module-absence RED v5"
)
_SPEC_CONTEXT_SENTENCE = (
    " RED v5 preserves the accepted behavior and assertion contract while "
    "making all three test-module bootstraps context-invariant under the exact "
    "Ruff 0.16.4 product toolchain."
)


def _update_plan(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    if _PLAN_HEADING_V5 not in source:
        matching = [heading for heading in _PLAN_HEADINGS if heading in source]
        if len(matching) != 1:
            raise SystemExit(
                "plan must contain exactly one qualified pre-v5 RED heading"
            )
        source = source.replace(matching[0], _PLAN_HEADING_V5, 1)
    for old, new in (
        (_RED_V2_BRANCH, _RED_V5_BRANCH),
        (_RED_V4_BRANCH, _RED_V5_BRANCH),
        (_RED_V2_SHA, _RED_V5_SHA),
        (_RED_V4_SHA, _RED_V5_SHA),
    ):
        source = source.replace(old, new)
    for forbidden in (_RED_V2_BRANCH, _RED_V4_BRANCH, _RED_V2_SHA, _RED_V4_SHA):
        if forbidden in source:
            raise SystemExit(f"plan retains obsolete qualified RED identity: {forbidden}")
    if _PLAN_HEADING_V5 not in source:
        raise SystemExit("plan RED-v5 task heading is absent")
    if _RED_V5_BRANCH not in source or _RED_V5_SHA not in source:
        raise SystemExit("plan RED-v5 branch/SHA identity is absent")
    path.write_text(source, encoding="utf-8")


def _update_spec(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    for old, new in (
        (_RED_V2_BRANCH, _RED_V5_BRANCH),
        (_RED_V4_BRANCH, _RED_V5_BRANCH),
        (_RED_V2_SHA, _RED_V5_SHA),
        (_RED_V4_SHA, _RED_V5_SHA),
    ):
        source = source.replace(old, new)
    anchor = (
        "All test files must be Ruff-clean and syntactically valid. Each "
        "independent collection must fail only because "
        "`nextgen_memory.review_attestation_registry` does not exist."
    )
    if source.count(anchor) != 1:
        raise SystemExit("spec tests-only RED anchor is absent or duplicated")
    prior_context = (
        " RED v4 additionally preserves the RED-v3 behavior and assertion "
        "contract while removing context-dependent package-root import "
        "classification through the standard-library importlib bootstrap."
    )
    source = source.replace(prior_context, "")
    if _SPEC_CONTEXT_SENTENCE not in source:
        source = source.replace(anchor, anchor + _SPEC_CONTEXT_SENTENCE, 1)
    for forbidden in (_RED_V2_BRANCH, _RED_V4_BRANCH, _RED_V2_SHA, _RED_V4_SHA):
        if forbidden in source:
            raise SystemExit(f"spec retains obsolete qualified RED identity: {forbidden}")
    if _RED_V5_BRANCH not in source or _RED_V5_SHA not in source:
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
