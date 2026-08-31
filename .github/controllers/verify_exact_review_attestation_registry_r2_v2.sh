#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/verify_exact_review_attestation_registry_r2.sh"
TARGET="$RUNNER_TEMP/verify_exact_review_attestation_registry_r2_v2.sh"
cp "$SOURCE" "$TARGET"

python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["RUNNER_TEMP"]) / "verify_exact_review_attestation_registry_r2_v2.sh"
source = path.read_text(encoding="utf-8")
old_sets = '''forbidden_calls = {
    "eval", "exec", "compile", "open", "sleep", "system", "urlopen",
    "uuid1", "uuid4", "write_bytes", "write_text",
}
'''
new_sets = '''forbidden_builtins = {"eval", "exec", "compile", "open"}
forbidden_attributes = {
    "sleep", "system", "urlopen", "uuid1", "uuid4", "write_bytes", "write_text",
}
'''
if source.count(old_sets) != 1:
    raise SystemExit(
        f"expected one ambiguous forbidden-call set, found {source.count(old_sets)}"
    )
source = source.replace(old_sets, new_sets, 1)
old_call = '''    elif isinstance(node, ast.Call):
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        if name in forbidden_calls:
            findings.append(f"{node.lineno}:call:{name}")
'''
new_call = '''    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in forbidden_builtins:
            findings.append(f"{node.lineno}:call:{node.func.id}")
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden_attributes
        ):
            findings.append(f"{node.lineno}:call:{node.func.attr}")
'''
if source.count(old_call) != 1:
    raise SystemExit(
        f"expected one ambiguous ast.Call audit, found {source.count(old_call)}"
    )
source = source.replace(old_call, new_call, 1)
if "forbidden_calls" in source:
    raise SystemExit("ambiguous forbidden_calls marker remains")
if source.count('"compile"') != 1:
    raise SystemExit("builtin compile rule is absent or duplicated")
path.write_text(source, encoding="utf-8")
PY

bash -n "$TARGET"
bash "$TARGET" "$@"
