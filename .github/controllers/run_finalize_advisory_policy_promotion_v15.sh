#!/usr/bin/env bash
set -euo pipefail

BASE_SOURCE='.github/controllers/finalize_advisory_policy_promotion_v8.sh'
PATCHED_BASE='/tmp/finalize_advisory_policy_promotion_v15_base.sh'
WRAPPER_SOURCE='.github/controllers/run_finalize_advisory_policy_promotion_v14.sh'
PATCHED_WRAPPER='/tmp/run_finalize_advisory_policy_promotion_v15.sh'

cp "$BASE_SOURCE" "$PATCHED_BASE"
python - <<'PY'
from pathlib import Path

path = Path('/tmp/finalize_advisory_policy_promotion_v15_base.sh')
source = path.read_text(encoding='utf-8')
old = '''run git add -A
mapfile -t CHANGED < <(git diff --cached --name-only "$BASE_SHA" | sort)
'''
new = '''rm -rf wheelhouse
run git add -A
mapfile -t CHANGED < <(git diff --cached --name-only "$BASE_SHA" | sort)
'''
if source.count(old) != 1:
    raise SystemExit(
        f'expected one product staging block, found {source.count(old)}'
    )
path.write_text(source.replace(old, new, 1), encoding='utf-8')
PY

cp "$WRAPPER_SOURCE" "$PATCHED_WRAPPER"
python - <<'PY'
from pathlib import Path

path = Path('/tmp/run_finalize_advisory_policy_promotion_v15.sh')
source = path.read_text(encoding='utf-8')
old = "SOURCE='.github/controllers/finalize_advisory_policy_promotion_v8.sh'"
new = "SOURCE='/tmp/finalize_advisory_policy_promotion_v15_base.sh'"
if source.count(old) != 1:
    raise SystemExit(
        f'expected one base-controller source declaration, found {source.count(old)}'
    )
path.write_text(source.replace(old, new, 1), encoding='utf-8')
PY

bash "$PATCHED_WRAPPER"
