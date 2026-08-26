#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/run_implement_exact_review_attestation_registry_v0_v10.sh"
TARGET="$RUNNER_TEMP/run_implement_exact_review_attestation_registry_v0_v11.sh"
cp "$SOURCE" "$TARGET"

python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["RUNNER_TEMP"]) / (
    "run_implement_exact_review_attestation_registry_v0_v11.sh"
)
source = path.read_text(encoding="utf-8")
required_replacements = (
    ("RED_V4_SHA", "RED_V5_SHA"),
    (
        "130db57eaa2fe0f9809bfa672c0467ce087a8089",
        "849df204e899d7570ef469d52307786cf242695a",
    ),
    (
        "prove_exact_review_attestation_red_v4.py",
        "prove_exact_review_attestation_red_v5.py",
    ),
    (
        "update_exact_review_attestation_docs_v4.py",
        "update_exact_review_attestation_docs_v5.py",
    ),
    (
        "exact-review-attestation-red-v4-preservation.json",
        "exact-review-attestation-red-v5-preservation.json",
    ),
    ("red_v4", "red_v5"),
    ("red-v4", "red-v5"),
    ("RED v4", "RED v5"),
    ("RED-v4", "RED-v5"),
)
for old, new in required_replacements:
    if old not in source:
        raise SystemExit(f"producer-v10 RED-v4 marker is absent: {old}")
    source = source.replace(old, new)

for forbidden in (
    "RED_V4_SHA",
    "130db57eaa2fe0f9809bfa672c0467ce087a8089",
    "prove_exact_review_attestation_red_v4.py",
    "update_exact_review_attestation_docs_v4.py",
    "exact-review-attestation-red-v4-preservation.json",
    "red_v4",
    "red-v4",
    "RED v4",
    "RED-v4",
):
    if forbidden in source:
        raise SystemExit(f"obsolete RED-v4 producer marker remains: {forbidden}")
if source.count("849df204e899d7570ef469d52307786cf242695a") != 2:
    raise SystemExit("RED-v5 SHA wrapper cardinality differs")
if source.count("prove_exact_review_attestation_red_v5.py") != 3:
    raise SystemExit("RED-v5 source prover wrapper cardinality differs")
if source.count("update_exact_review_attestation_docs_v5.py") != 3:
    raise SystemExit("RED-v5 docs updater wrapper cardinality differs")
if source.count("exact-review-attestation-red-v5-preservation.json") != 3:
    raise SystemExit("RED-v5 preservation path wrapper cardinality differs")
if source.count("'red_v5_sha':") != 1:
    raise SystemExit("producer summary RED-v5 identity is absent or duplicated")
if source.count("'red_v5_test_ast_preserved': True,") != 1:
    raise SystemExit("producer summary RED-v5 preservation flag is absent")
path.write_text(source, encoding="utf-8")
PY

bash -n "$TARGET"
python -m py_compile \
  "$GITHUB_WORKSPACE/controller/.github/controllers/prove_exact_review_attestation_red_v5.py" \
  "$GITHUB_WORKSPACE/controller/.github/controllers/update_exact_review_attestation_docs_v5.py"
bash "$TARGET" "$@"
