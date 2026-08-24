#!/usr/bin/env bash
set -euo pipefail

SOURCE='.github/controllers/finalize_advisory_policy_promotion_v8.sh'
TARGET='/tmp/finalize_advisory_policy_promotion_v11.sh'
cp "$SOURCE" "$TARGET"

python - <<'PY'
from pathlib import Path

path = Path('/tmp/finalize_advisory_policy_promotion_v11.sh')
source = path.read_text(encoding='utf-8')

old_branch = "RED_V2_BRANCH='tdd/advisory-policy-promotion-gate-v0-red-v2-20260824'"
new_branch = "RED_V2_BRANCH='tdd/advisory-policy-promotion-gate-v0-red-v3-20260824'"
if source.count(old_branch) != 1:
    raise SystemExit(f'expected one RED v2 branch declaration, found {source.count(old_branch)}')
source = source.replace(old_branch, new_branch, 1)
source = source.replace('TDD RED v2 Evidence', 'TDD RED v3 Evidence')
source = source.replace('Corrected RED branch:', 'Corrected RED v3 branch:')
source = source.replace('This corrected RED supersedes', 'This corrected RED v3 supersedes')

fixture_patch = """
ROOT="$RED_ROOT" python - <<'PYFIX'
from pathlib import Path
import os

path = Path(os.environ["ROOT"]) / "tests/test_policy_promotion_gate.py"
source = path.read_text(encoding="utf-8")
old = "request(evaluation=paired_evidence(mean_score_effect=-0.001)),"
new = (
    "request(\\n"
    "    evaluation=paired_evidence(\\n"
    "        mean_score_effect=-0.001,\\n"
    "        score_confidence_lower_bound=-0.01,\\n"
    "        score_confidence_upper_bound=0.01,\\n"
    "    )\\n"
    "),"
)
if source.count(old) != 1:
    raise SystemExit(
        f"expected one invalid negative-effect fixture, found {source.count(old)}"
    )
path.write_text(source.replace(old, new, 1), encoding="utf-8")
PYFIX

"""
marker = 'cat > "$RED_ROOT/docs/policy-promotion-gate-v0-red.md" <<EOF\n'
if source.count(marker) != 1:
    raise SystemExit(f'expected one RED evidence marker, found {source.count(marker)}')
source = source.replace(marker, fixture_patch + marker, 1)

old = '''run ruff check \\
  tests/test_policy_promotion_gate.py \\
  tests/test_policy_promotion_gate_properties.py \\
  tests/test_policy_promotion_gate_public_api.py
run python -m pytest -q \\
  tests/test_policy_promotion_gate.py::test_each_hard_rejection_condition_is_bounded
'''
new = '''run ruff check --fix \\
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
if source.count(old) != 1:
    raise SystemExit(
        f'expected one post-RED qualification block, found {source.count(old)}'
    )
source = source.replace(old, new, 1)

path.write_text(source, encoding='utf-8')
PY

bash "$TARGET"
