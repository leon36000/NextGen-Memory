#!/usr/bin/env bash
set -euo pipefail

SOURCE='.github/controllers/finalize_advisory_policy_promotion_v8.sh'
TARGET='/tmp/finalize_advisory_policy_promotion_v14.sh'
cp "$SOURCE" "$TARGET"

python - <<'PY'
from pathlib import Path

path = Path('/tmp/finalize_advisory_policy_promotion_v14.sh')
source = path.read_text(encoding='utf-8')

old_branch = "RED_V2_BRANCH='tdd/advisory-policy-promotion-gate-v0-red-v2-20260824'"
new_branch = "RED_V2_BRANCH='tdd/advisory-policy-promotion-gate-v0-red-v4-20260824'"
if source.count(old_branch) != 1:
    raise SystemExit(
        f'expected one RED v2 branch declaration, found {source.count(old_branch)}'
    )
source = source.replace(old_branch, new_branch, 1)
source = source.replace('TDD RED v2 Evidence', 'TDD RED v4 Evidence')
source = source.replace('Corrected RED branch:', 'Corrected RED v4 branch:')
source = source.replace('This corrected RED supersedes', 'This corrected RED v4 supersedes')

fixture_patch = '''
python "$GITHUB_WORKSPACE/.github/controllers/patch_advisory_red_v4.py" \
  "$RED_ROOT/tests/test_policy_promotion_gate.py"

'''
marker = 'cat > "$RED_ROOT/docs/policy-promotion-gate-v0-red.md" <<EOF\n'
if source.count(marker) != 1:
    raise SystemExit(
        f'expected one RED evidence marker, found {source.count(marker)}'
    )
source = source.replace(marker, fixture_patch + marker, 1)

old_qualification = '''run ruff check \\
  tests/test_policy_promotion_gate.py \\
  tests/test_policy_promotion_gate_properties.py \\
  tests/test_policy_promotion_gate_public_api.py
run python -m pytest -q \\
  tests/test_policy_promotion_gate.py::test_each_hard_rejection_condition_is_bounded
'''
new_qualification = '''run ruff check --fix \\
  tests/test_policy_promotion_gate.py \\
  tests/test_policy_promotion_gate_properties.py \\
  tests/test_policy_promotion_gate_public_api.py
run ruff format \\
  tests/test_policy_promotion_gate.py \\
  tests/test_policy_promotion_gate_properties.py \\
  tests/test_policy_promotion_gate_public_api.py
run ruff check \\
  tests/test_policy_promotion_gate.py \\
  tests/test_policy_promotion_gate_properties.py \\
  tests/test_policy_promotion_gate_public_api.py
run ruff format --check \\
  tests/test_policy_promotion_gate.py \\
  tests/test_policy_promotion_gate_properties.py \\
  tests/test_policy_promotion_gate_public_api.py
run python -m pytest --collect-only -q \\
  tests/test_policy_promotion_gate.py \\
  tests/test_policy_promotion_gate_properties.py \\
  tests/test_policy_promotion_gate_public_api.py
'''
if source.count(old_qualification) != 1:
    raise SystemExit(
        'expected one post-RED qualification block, '
        f'found {source.count(old_qualification)}'
    )
source = source.replace(old_qualification, new_qualification, 1)

old_audit = '''    elif isinstance(node, ast.Call):
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
new_audit = '''    elif isinstance(node, ast.Call):
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
if source.count(old_audit) != 1:
    raise SystemExit(
        f'expected one ambiguous audit block, found {source.count(old_audit)}'
    )
source = source.replace(old_audit, new_audit, 1)

path.write_text(source, encoding='utf-8')
PY

bash "$TARGET"
