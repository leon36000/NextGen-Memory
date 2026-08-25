#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/run_implement_exact_review_attestation_registry_v0_v7.sh"
TARGET="$RUNNER_TEMP/run_implement_exact_review_attestation_registry_v0_v9.sh"
cp "$SOURCE" "$TARGET"

python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["RUNNER_TEMP"]) / (
    "run_implement_exact_review_attestation_registry_v0_v9.sh"
)
source = path.read_text(encoding="utf-8")

replacements = (
    ("RED_V3_SHA", "RED_V4_SHA"),
    (
        "0a8e193269e425dd51f740b495579f949a237ce1",
        "130db57eaa2fe0f9809bfa672c0467ce087a8089",
    ),
    ("red_v3", "red_v4"),
    ("red-v3", "red-v4"),
    ("RED v3", "RED v4"),
    ("RED-v3", "RED-v4"),
)
for old, new in replacements:
    if old not in source:
        raise SystemExit(f"expected producer-v7 marker is absent: {old}")
    source = source.replace(old, new)

start_marker = "new_post_ruff = '''run python -m compileall -q src scripts\n"
end_marker = "\nif rendered.count(old_post_ruff) != 1:"
start = source.index(start_marker)
end = source.index(end_marker, start)
replacement = """new_post_ruff = '''run python -m compileall -q src scripts
run python "$CONTROLLER_ROOT/.github/controllers/prove_exact_review_attestation_red_v4.py" --red-sha "$RED_V4_SHA" --output /tmp/exact-review-attestation-red-v4-preservation.json
RED_AST_SHA=$(sha256sum /tmp/exact-review-attestation-red-v4-preservation.json | awk '{print $1}')
test -n "$RED_AST_SHA"
'''"""
source = source[:start] + replacement + source[end:]

old_guard = '''if rendered.count('all_test_asts_identical') != 1:
    raise SystemExit("RED-v4 AST preservation proof is absent")
'''
new_guard = '''source_prover_call = (
    'run python "$CONTROLLER_ROOT/.github/controllers/'
    'prove_exact_review_attestation_red_v4.py" '
    '--red-sha "$RED_V4_SHA" '
    '--output /tmp/exact-review-attestation-red-v4-preservation.json'
)
if rendered.count(source_prover_call) != 1:
    raise SystemExit("exact RED-v4 source/AST preservation proof is absent")
'''
if source.count(old_guard) != 1:
    raise SystemExit(
        "expected one embedded RED-v4 AST guard after identity upgrade, "
        f"found {source.count(old_guard)}"
    )
source = source.replace(old_guard, new_guard, 1)

for forbidden in (
    "RED_V3_SHA",
    "red_v3",
    "red-v3",
    "RED v3",
    "RED-v3",
    "0a8e193269e425dd51f740b495579f949a237ce1",
    "python - <<'PYAST'",
):
    if forbidden in source:
        raise SystemExit(f"obsolete RED-v3 producer marker remains: {forbidden}")
if source.count("130db57eaa2fe0f9809bfa672c0467ce087a8089") != 2:
    raise SystemExit(
        "RED-v4 SHA is absent or duplicated unexpectedly: "
        f"{source.count('130db57eaa2fe0f9809bfa672c0467ce087a8089')}"
    )
if source.count("prove_exact_review_attestation_red_v4.py") != 2:
    raise SystemExit(
        "RED-v4 source prover call/guard is absent or duplicated: "
        f"{source.count('prove_exact_review_attestation_red_v4.py')}"
    )
if source.count("exact-review-attestation-red-v4-preservation.json") < 3:
    raise SystemExit("RED-v4 preservation evidence is not fully bound")
path.write_text(source, encoding="utf-8")
PY

bash -n "$TARGET"
python -m py_compile \
  "$GITHUB_WORKSPACE/controller/.github/controllers/prove_exact_review_attestation_red_v4.py"
bash "$TARGET" "$@"
