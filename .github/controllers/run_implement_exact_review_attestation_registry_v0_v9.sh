#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/run_implement_exact_review_attestation_registry_v0_v8.sh"
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
old = '''if rendered.count('all_test_asts_identical') != 1:
    raise SystemExit("RED-v3 AST preservation proof is absent")
'''
new = '''if rendered.count('prove_exact_review_attestation_red_ast.py') != 1:
    raise SystemExit("standalone RED-v3 AST preservation proof is absent")
'''
if source.count(old) != 1:
    raise SystemExit(
        f"expected one obsolete AST-text assertion, found {source.count(old)}"
    )
path.write_text(source.replace(old, new, 1), encoding="utf-8")
PY

bash -n "$TARGET"
python -m py_compile \
  "$GITHUB_WORKSPACE/controller/.github/controllers/prove_exact_review_attestation_red_ast.py"
bash "$TARGET" "$@"
