#!/usr/bin/env bash
set -euo pipefail

SOURCE='.github/controllers/finalize_advisory_policy_promotion_v8.sh'
TARGET='/tmp/finalize_advisory_policy_promotion_v9.sh'
cp "$SOURCE" "$TARGET"

python - <<'PY'
from pathlib import Path

path = Path('/tmp/finalize_advisory_policy_promotion_v9.sh')
source = path.read_text(encoding='utf-8')
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
run python -m pytest -q \\
  tests/test_policy_promotion_gate.py::test_each_hard_rejection_condition_is_bounded
'''
if source.count(old) != 1:
    raise SystemExit(
        f'expected one post-RED normalization block, found {source.count(old)}'
    )
path.write_text(source.replace(old, new, 1), encoding='utf-8')
PY

bash "$TARGET"
