#!/usr/bin/env bash
set -euo pipefail

V7_WRAPPER="$GITHUB_WORKSPACE/controller/.github/controllers/run_implement_exact_review_attestation_registry_v0_v7.sh"
V7_GENERATOR="$RUNNER_TEMP/generate_exact_review_attestation_registry_v7_only.sh"
V7_TARGET="$RUNNER_TEMP/implement_exact_review_attestation_registry_v0_v7.sh"
V10_TARGET="$RUNNER_TEMP/implement_exact_review_attestation_registry_v0_v10.sh"

python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

source_path = Path(os.environ["GITHUB_WORKSPACE"]) / (
    "controller/.github/controllers/"
    "run_implement_exact_review_attestation_registry_v0_v7.sh"
)
destination = Path(os.environ["RUNNER_TEMP"]) / (
    "generate_exact_review_attestation_registry_v7_only.sh"
)
source = source_path.read_text(encoding="utf-8")
trailer = 'bash "$TARGET" "$@"\n'
if source.count(trailer) != 1 or not source.endswith(trailer):
    raise SystemExit(
        "v7 wrapper execution trailer is absent, duplicated, or not terminal"
    )
source = source.removesuffix(trailer)
source += 'test -s "$TARGET"\nprintf "generated_v7_target=%s\\n" "$TARGET"\n'
destination.write_text(source, encoding="utf-8")
PY

bash -n "$V7_GENERATOR"
bash "$V7_GENERATOR"
test -s "$V7_TARGET"
cp "$V7_TARGET" "$V10_TARGET"

python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["RUNNER_TEMP"]) / (
    "implement_exact_review_attestation_registry_v0_v10.sh"
)
source = path.read_text(encoding="utf-8")

required_identity_replacements = (
    (
        "RED_V3_SHA='0a8e193269e425dd51f740b495579f949a237ce1'",
        "RED_V4_SHA='130db57eaa2fe0f9809bfa672c0467ce087a8089'",
    ),
    ("$RED_V3_SHA", "$RED_V4_SHA"),
)
for old, new in required_identity_replacements:
    if old not in source:
        raise SystemExit(f"required generated-v7 marker is absent: {old}")
    source = source.replace(old, new)

optional_identity_replacements = (
    ("red_v3", "red_v4"),
    ("red-v3", "red-v4"),
    ("RED v3", "RED v4"),
    ("RED-v3", "RED-v4"),
)
for old, new in optional_identity_replacements:
    source = source.replace(old, new)

checkout_line = 'git checkout "$RED_V4_SHA" -- "${RED_PATHS[@]}"\n'
docs_call = (
    'python "$CONTROLLER_ROOT/.github/controllers/'
    'update_exact_review_attestation_docs_v4.py" '
    '--plan docs/superpowers/plans/'
    '2026-08-24-exact-sha-review-attestation-registry-v0.md '
    '--spec docs/superpowers/specs/'
    '2026-08-24-exact-sha-review-attestation-registry-v0-design.md '
    '--red-sha "$RED_V4_SHA"\n'
)
if source.count(checkout_line) != 1:
    raise SystemExit(
        "expected one exact RED-v4 checkout line, "
        f"found {source.count(checkout_line)}"
    )
if docs_call not in source:
    source = source.replace(checkout_line, checkout_line + docs_call, 1)

post_ruff_start = "run python -m compileall -q src scripts\nRED_DOC_REFERENCE="
post_ruff_end = 'test -n "$RED_AST_SHA"\n'
start = source.index(post_ruff_start)
end = source.index(post_ruff_end, start) + len(post_ruff_end)
post_ruff = '''run python -m compileall -q src scripts
run python "$CONTROLLER_ROOT/.github/controllers/prove_exact_review_attestation_red_v4.py" \
  --red-sha "$RED_V4_SHA" \
  --output /tmp/exact-review-attestation-red-v4-preservation.json
RED_AST_SHA=$(sha256sum \
  /tmp/exact-review-attestation-red-v4-preservation.json \
  | awk '{print $1}')
test -n "$RED_AST_SHA"
test "$(grep -Foc 'tdd/exact-sha-review-attestation-registry-v0-red-v4-20260825' docs/superpowers/plans/2026-08-24-exact-sha-review-attestation-registry-v0.md)" -ge 1
test "$(grep -Foc '130db57eaa2fe0f9809bfa672c0467ce087a8089' docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md)" -ge 1
if grep -F 'tdd/exact-sha-review-attestation-registry-v0-red-v2-20260825' \
  docs/superpowers/plans/2026-08-24-exact-sha-review-attestation-registry-v0.md \
  docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md; then
  echo 'qualified RED-v2 branch remains in product documentation' >&2
  exit 1
fi
'''
source = source[:start] + post_ruff + source[end:]

for forbidden in (
    "RED_V3_SHA",
    "$RED_V3_SHA",
    "red_v3",
    "red-v3",
    "RED v3",
    "RED-v3",
    "0a8e193269e425dd51f740b495579f949a237ce1",
    "python - <<'PYAST'",
    "all_test_asts_identical",
    "red-v3-doc.md",
):
    if forbidden in source:
        raise SystemExit(f"obsolete RED-v3 target marker remains: {forbidden}")
if source.count("RED_V4_SHA='130db57eaa2fe0f9809bfa672c0467ce087a8089'") != 1:
    raise SystemExit("exact RED-v4 variable binding is absent or duplicated")
if source.count("prove_exact_review_attestation_red_v4.py") != 1:
    raise SystemExit("exact RED-v4 source prover call is absent or duplicated")
if source.count("update_exact_review_attestation_docs_v4.py") != 1:
    raise SystemExit("bounded RED-v4 docs updater call is absent or duplicated")
if source.count("exact-review-attestation-red-v4-preservation.json") < 2:
    raise SystemExit("RED-v4 preservation evidence is not fully bound")
if source.count("'red_v4_sha':") != 1:
    raise SystemExit("producer summary RED-v4 identity is absent or duplicated")
if source.count("'red_v4_test_ast_preserved': True,") != 1:
    raise SystemExit("producer summary RED-v4 preservation flag is absent")
path.write_text(source, encoding="utf-8")
PY

bash -n "$V10_TARGET"
python -m py_compile \
  "$GITHUB_WORKSPACE/controller/.github/controllers/prove_exact_review_attestation_red_v4.py" \
  "$GITHUB_WORKSPACE/controller/.github/controllers/update_exact_review_attestation_docs_v4.py"
bash "$V10_TARGET" "$@"
