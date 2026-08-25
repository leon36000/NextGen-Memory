#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/run_implement_exact_review_attestation_registry_v0_v7.sh"
TARGET="$RUNNER_TEMP/run_implement_exact_review_attestation_registry_v0_v8.sh"
cp "$SOURCE" "$TARGET"

python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["RUNNER_TEMP"]) / (
    "run_implement_exact_review_attestation_registry_v0_v8.sh"
)
source = path.read_text(encoding="utf-8")
start_marker = "new_post_ruff = '''run python -m compileall -q src scripts\n"
end_marker = "\nif rendered.count(old_post_ruff) != 1:"
start = source.index(start_marker)
end = source.index(end_marker, start)
replacement = """new_post_ruff = '''run python -m compileall -q src scripts
RED_DOC_REFERENCE="$RUNNER_TEMP/red-v3-doc.md"
git show "$RED_V3_SHA:docs/exact-sha-review-attestation-registry-v0-red.md" > "$RED_DOC_REFERENCE"
cmp "$RED_DOC_REFERENCE" docs/exact-sha-review-attestation-registry-v0-red.md
run python "$CONTROLLER_ROOT/.github/controllers/prove_exact_review_attestation_red_ast.py" --red-sha "$RED_V3_SHA" --output /tmp/exact-review-attestation-red-v3-ast-preservation.json
RED_AST_SHA=$(sha256sum /tmp/exact-review-attestation-red-v3-ast-preservation.json | awk '{print $1}')
test -n "$RED_AST_SHA"
'''"""
source = source[:start] + replacement + source[end:]
if "python - <<'PYAST'" in source:
    raise SystemExit("embedded AST heredoc remains after v8 patch")
if source.count("prove_exact_review_attestation_red_ast.py") != 1:
    raise SystemExit("standalone AST prover call is absent or duplicated")
path.write_text(source, encoding="utf-8")
PY

bash -n "$TARGET"
python -m py_compile \
  "$GITHUB_WORKSPACE/controller/.github/controllers/prove_exact_review_attestation_red_ast.py"
bash "$TARGET" "$@"
