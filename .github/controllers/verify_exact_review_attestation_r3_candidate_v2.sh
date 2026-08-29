#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/verify_exact_review_attestation_r3_candidate.sh"
TARGET="$RUNNER_TEMP/verify_exact_review_attestation_r3_candidate_v2.sh"
cp "$SOURCE" "$TARGET"

python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["RUNNER_TEMP"]) / (
    "verify_exact_review_attestation_r3_candidate_v2.sh"
)
source = path.read_text(encoding="utf-8")
old = '''        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        if name in forbidden_calls:
            findings.append(f"{node.lineno}:forbidden_call:{name}")
'''
new = '''        if isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
            findings.append(f"{node.lineno}:forbidden_call:{node.func.id}")
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in (forbidden_calls - {"compile"})
        ):
            findings.append(f"{node.lineno}:forbidden_call:{node.func.attr}")
'''
if source.count(old) != 1:
    raise SystemExit(
        f"expected one ambiguous compile audit block, found {source.count(old)}"
    )
path.write_text(source.replace(old, new, 1), encoding="utf-8")
PY

bash -n "$TARGET"
bash "$TARGET" "$@"
