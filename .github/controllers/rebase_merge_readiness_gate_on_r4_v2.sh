#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/rebase_merge_readiness_gate_on_r4.sh"
TARGET="$RUNNER_TEMP/rebase_merge_readiness_gate_on_r4_v2.sh"
cp "$SOURCE" "$TARGET"

python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["RUNNER_TEMP"]) / "rebase_merge_readiness_gate_on_r4_v2.sh"
source = path.read_text(encoding="utf-8")

required_replacements = (
    (
        "feat/exact-sha-merge-readiness-gate-v0-r4-20260831",
        "feat/exact-sha-merge-readiness-gate-v0-r4-v2-20260831",
    ),
    (
        "tdd/exact-sha-merge-readiness-gate-v0-red-r4-20260831",
        "tdd/exact-sha-merge-readiness-gate-v0-red-r4-v2-20260831",
    ),
)
for old, new in required_replacements:
    if old not in source:
        raise SystemExit(f"required R4-v1 branch marker is absent: {old}")
    source = source.replace(old, new)

first_anchor = '''    for old, new in replacements:
        source = source.replace(old, new)
    source = "\\n".join(line.rstrip() for line in source.splitlines()) + "\\n"
'''
first_replacement = '''    for old, new in replacements:
        source = source.replace(old, new)
    prose_replacements = (
        ("existing exact r3 public types", "existing exact r4 public types"),
        ("the r3 Review Attestation Registry", "the r4 Review Attestation Registry"),
        ("commit above r3", "commit above r4"),
        ("exact r3 base", "exact r4 base"),
    )
    for old, new in prose_replacements:
        source = source.replace(old, new)
    source = "\\n".join(line.rstrip() for line in source.splitlines()) + "\\n"
'''
if source.count(first_anchor) != 1:
    raise SystemExit(
        "expected one feature-document replacement anchor, "
        f"found {source.count(first_anchor)}"
    )
source = source.replace(first_anchor, first_replacement, 1)

second_anchor = '''for old, new in replacements:
    source = source.replace(old, new)
section = """
'''
second_replacement = '''for old, new in replacements:
    source = source.replace(old, new)
source = source.replace("immutable r3 base", "immutable r4 base")
section = """
'''
if source.count(second_anchor) != 1:
    raise SystemExit(
        "expected one RED-document replacement anchor, "
        f"found {source.count(second_anchor)}"
    )
source = source.replace(second_anchor, second_replacement, 1)

for forbidden in (
    "FEATURE_BRANCH='feat/exact-sha-merge-readiness-gate-v0-r4-20260831'",
    "RED_BRANCH='tdd/exact-sha-merge-readiness-gate-v0-red-r4-20260831'",
):
    if forbidden in source:
        raise SystemExit(f"obsolete R4-v1 target remains: {forbidden}")
if source.count("r4-v2-20260831") < 6:
    raise SystemExit("R4-v2 branch identities are not fully bound")
if source.count("prose_replacements") != 2:
    raise SystemExit("R4 prose correction is absent or duplicated")
path.write_text(source, encoding="utf-8")
PY

bash -n "$TARGET"
bash "$TARGET" "$@"
