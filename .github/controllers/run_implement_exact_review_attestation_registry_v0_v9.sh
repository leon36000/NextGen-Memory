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

checkout_literal = '''                'git checkout "$RED_V4_SHA" -- "${RED_PATHS[@]}"',
'''
docs_literal = '''                'python "$CONTROLLER_ROOT/.github/controllers/update_exact_review_attestation_docs_v4.py" --plan docs/superpowers/plans/2026-08-24-exact-sha-review-attestation-registry-v0.md --spec docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md --red-sha "$RED_V4_SHA"',
'''
if source.count(checkout_literal) != 1:
    raise SystemExit(
        "expected one RED-v4 overlay literal, "
        f"found {source.count(checkout_literal)}"
    )
if docs_literal not in source:
    source = source.replace(checkout_literal, checkout_literal + docs_literal, 1)

start_marker = "new_post_ruff = '''run python -m compileall -q src scripts\n"
end_marker = "\nif rendered.count(old_post_ruff) != 1:"
start = source.index(start_marker)
end = source.index(end_marker, start)
replacement = """new_post_ruff = '''run python -m compileall -q src scripts
run python "$CONTROLLER_ROOT/.github/controllers/prove_exact_review_attestation_red_v4.py" --red-sha "$RED_V4_SHA" --output /tmp/exact-review-attestation-red-v4-preservation.json
RED_AST_SHA=$(sha256sum /tmp/exact-review-attestation-red-v4-preservation.json | awk '{print $1}')
test -n "$RED_AST_SHA"
test "$(grep -Foc 'tdd/exact-sha-review-attestation-registry-v0-red-v4-20260825' docs/superpowers/plans/2026-08-24-exact-sha-review-attestation-registry-v0.md)" -ge 1
test "$(grep -Foc '130db57eaa2fe0f9809bfa672c0467ce087a8089' docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md)" -ge 1
if grep -F 'tdd/exact-sha-review-attestation-registry-v0-red-v2-20260825' docs/superpowers/plans/2026-08-24-exact-sha-review-attestation-registry-v0.md docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md; then
  echo 'qualified RED-v2 branch remains in product documentation' >&2
  exit 1
fi
'''"""
source = source[:start] + replacement + source[end:]

guard_start_marker = "if rendered.count('all_test_asts_identical') != 1:\n"
guard_end_marker = 'path.write_text(rendered, encoding="utf-8")\n'
guard_start = source.index(guard_start_marker)
guard_end = source.index(guard_end_marker, guard_start)
new_guard = '''source_prover_call = (
    'run python "$CONTROLLER_ROOT/.github/controllers/'
    'prove_exact_review_attestation_red_v4.py" '
    '--red-sha "$RED_V4_SHA" '
    '--output /tmp/exact-review-attestation-red-v4-preservation.json'
)
if rendered.count(source_prover_call) != 1:
    raise SystemExit("exact RED-v4 source/AST preservation proof is absent")

docs_updater_call = (
    'python "$CONTROLLER_ROOT/.github/controllers/'
    'update_exact_review_attestation_docs_v4.py" '
    '--plan docs/superpowers/plans/'
    '2026-08-24-exact-sha-review-attestation-registry-v0.md '
    '--spec docs/superpowers/specs/'
    '2026-08-24-exact-sha-review-attestation-registry-v0-design.md '
    '--red-sha "$RED_V4_SHA"'
)
if rendered.count(docs_updater_call) != 1:
    raise SystemExit("bounded RED-v4 documentation updater is absent")
'''
source = source[:guard_start] + new_guard + source[guard_end:]

for forbidden in (
    "RED_V3_SHA",
    "red_v3",
    "red-v3",
    "RED v3",
    "RED-v3",
    "0a8e193269e425dd51f740b495579f949a237ce1",
    "python - <<'PYAST'",
    "all_test_asts_identical",
):
    if forbidden in source:
        raise SystemExit(f"obsolete RED-v3 producer marker remains: {forbidden}")
if source.count("130db57eaa2fe0f9809bfa672c0467ce087a8089") < 3:
    raise SystemExit(
        "RED-v4 SHA is not fully bound: "
        f"{source.count('130db57eaa2fe0f9809bfa672c0467ce087a8089')}"
    )
if source.count("prove_exact_review_attestation_red_v4.py") != 2:
    raise SystemExit(
        "RED-v4 source prover call/guard is absent or duplicated: "
        f"{source.count('prove_exact_review_attestation_red_v4.py')}"
    )
if source.count("update_exact_review_attestation_docs_v4.py") != 2:
    raise SystemExit(
        "RED-v4 docs updater call/guard is absent or duplicated: "
        f"{source.count('update_exact_review_attestation_docs_v4.py')}"
    )
if source.count("exact-review-attestation-red-v4-preservation.json") < 3:
    raise SystemExit("RED-v4 preservation evidence is not fully bound")
path.write_text(source, encoding="utf-8")
PY

bash -n "$TARGET"
python -m py_compile \
  "$GITHUB_WORKSPACE/controller/.github/controllers/prove_exact_review_attestation_red_v4.py" \
  "$GITHUB_WORKSPACE/controller/.github/controllers/update_exact_review_attestation_docs_v4.py"
bash "$TARGET" "$@"
