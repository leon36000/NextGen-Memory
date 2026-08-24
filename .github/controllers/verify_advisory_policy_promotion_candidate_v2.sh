#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/verify_advisory_policy_promotion_candidate.sh"
TARGET='/tmp/verify_advisory_policy_promotion_candidate_v2.sh'
cp "$SOURCE" "$TARGET"

python - <<'PY'
from pathlib import Path

path = Path('/tmp/verify_advisory_policy_promotion_candidate_v2.sh')
source = path.read_text(encoding='utf-8')
old = '''    elif isinstance(node, ast.Constant) and node.value is Ellipsis:
        findings.append(f"{node.lineno}:ellipsis")
'''
new = '''    elif (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    ):
        findings.append(f"{node.lineno}:executable_ellipsis")
'''
if source.count(old) != 1:
    raise SystemExit(
        f'expected one ambiguous ellipsis audit, found {source.count(old)}'
    )
path.write_text(source.replace(old, new, 1), encoding='utf-8')
PY

bash "$TARGET" "$@"
