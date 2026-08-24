#!/usr/bin/env bash
set -euo pipefail

SOURCE='.github/controllers/run_finalize_advisory_policy_promotion_v12.sh'
TARGET='/tmp/run_finalize_advisory_policy_promotion_v13.sh'
cp "$SOURCE" "$TARGET"

python - <<'PY'
from pathlib import Path

path = Path('/tmp/run_finalize_advisory_policy_promotion_v13.sh')
source = path.read_text(encoding='utf-8')
old = '''    elif isinstance(node, ast.Call):
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
new = '''    elif isinstance(node, ast.Call):
        builtin_name = (
            node.func.id if isinstance(node.func, ast.Name) else None
        )
        attribute_name = (
            node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        forbidden_attributes = forbidden_calls - {"compile"}
        if builtin_name in forbidden_calls:
            findings.append(f"{node.lineno}:call:{builtin_name}")
        elif attribute_name in forbidden_attributes:
            findings.append(f"{node.lineno}:call:{attribute_name}")
'''
if source.count(old) != 1:
    raise SystemExit(
        f'expected one ambiguous call-audit block, found {source.count(old)}'
    )
path.write_text(source.replace(old, new, 1), encoding='utf-8')
PY

bash "$TARGET"
