#!/usr/bin/env bash
set -euo pipefail

CANDIDATE_SHA='10c5b6d3d1c2a686d8f9926e2815dfe647de8c24'
PARENT_SHA='41b0b104e5a3f06c4d238060ad0fd3dd51dd4446'
RED_SHA='4d6874caf519ad6f547d3217ccecc9fe58ac19e0'
EVIDENCE_ROOT=${EVIDENCE_ROOT:?EVIDENCE_ROOT required}
PYTHON_VERSION=${PYTHON_VERSION:?PYTHON_VERSION required}
mkdir -p "$EVIDENCE_ROOT"

run() {
  printf '+ '
  printf '%q ' "$@"
  printf '\n'
  "$@"
}

run git fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*'
test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"
test "$(git merge-base "$PARENT_SHA" HEAD)" = "$PARENT_SHA"
test "$(git merge-base "$RED_SHA" HEAD)" = "$RED_SHA"

expected=(
  docs/exact-sha-merge-readiness-gate-v0-red.md
  docs/exact-sha-merge-readiness-gate-v0.md
  docs/superpowers/plans/2026-08-31-exact-sha-merge-readiness-gate-v0.md
  docs/superpowers/specs/2026-08-31-exact-sha-merge-readiness-gate-v0-design.md
  src/nextgen_memory/__init__.py
  src/nextgen_memory/merge_readiness_gate.py
  tests/test_merge_readiness_gate.py
  tests/test_merge_readiness_gate_properties.py
  tests/test_merge_readiness_gate_public_api.py
)
mapfile -t changed < <(git diff --name-only "$PARENT_SHA"...HEAD | sort)
test "${#changed[@]}" -eq 9
diff -u <(printf '%s\n' "${expected[@]}" | sort) <(printf '%s\n' "${changed[@]}")
test -z "$(git diff --name-only "$PARENT_SHA"...HEAD -- '.github/workflows/**' 'migrations/**' pyproject.toml 'src/nextgen_memory/corrective_retrieval_*')"
run git diff --check "$PARENT_SHA"...HEAD

red_paths=(
  docs/exact-sha-merge-readiness-gate-v0-red.md
  tests/test_merge_readiness_gate.py
  tests/test_merge_readiness_gate_properties.py
  tests/test_merge_readiness_gate_public_api.py
)
for path in "${red_paths[@]}"; do
  git show "$RED_SHA:$path" > "$EVIDENCE_ROOT/$(basename "$path").red"
  run cmp "$path" "$EVIDENCE_ROOT/$(basename "$path").red"
done

run python -m pip install -e '.[dev]'
run python -m pip install 'ruff==0.16.4'
run ruff --version
run ruff check .
run ruff format --check \
  src/nextgen_memory/merge_readiness_gate.py \
  src/nextgen_memory/__init__.py \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py
run python -m compileall -q src scripts

set -o pipefail
python -m pytest -q \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py \
  2>&1 | tee "$EVIDENCE_ROOT/focused.txt"
grep -F '61 passed' "$EVIDENCE_ROOT/focused.txt" >/dev/null
python -m pytest -q 2>&1 | tee "$EVIDENCE_ROOT/full.txt"
grep -F '587 passed' "$EVIDENCE_ROOT/full.txt" >/dev/null

python - <<'PY' > "$EVIDENCE_ROOT/audit.json"
from __future__ import annotations
import ast, json
from pathlib import Path
path = Path('src/nextgen_memory/merge_readiness_gate.py')
source = path.read_text(encoding='utf-8')
tree = ast.parse(source, filename=str(path))
allowed = {'__future__','hashlib','json','re','dataclasses','enum','math','uuid','review_attestation_registry'}
findings=[]
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.split('.')[0] not in allowed: findings.append(f'import:{alias.name}')
    elif isinstance(node, ast.ImportFrom):
        module=(node.module or '').lstrip('.')
        if module.split('.')[0] not in allowed: findings.append(f'importfrom:{node.module}')
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {'open','exec','eval','compile','__import__'}:
        findings.append(f'call:{node.func.id}')
for marker in ('NotImplementedError','TODO','FIXME','# noqa','requests.','httpx.','subprocess.','socket.','pathlib.','os.environ','time.','random.','secrets.'):
    if marker in source: findings.append(f'lexical:{marker}')
if findings: raise SystemExit(sorted(set(findings)))
print(json.dumps({'audit_findings':0},sort_keys=True,separators=(',',':')))
PY

cat > "$EVIDENCE_ROOT/semantic_probe.py" <<'PY'
from __future__ import annotations
import hashlib, json, runpy
from dataclasses import replace
ns = runpy.run_path('tests/test_merge_readiness_gate.py')
gate = ns['ExactShaMergeReadinessGate']()
config = ns['exact_config']()
ready_request = ns['exact_ready_request']()
ready = gate.evaluate(ready_request, config)
hold_request = replace(ready_request, verification=ns['exact_verification'](evidence_age_seconds=4000.0))
hold = gate.evaluate(hold_request, config)
deps = ns['exact_dependencies']()
blocked_candidate = ns['exact_candidate'](deps, observed_candidate_head_sha=ns['OTHER_GIT_SHA'])
blocked_request = ns['MergeReadinessRequest'](
    candidate=blocked_candidate,
    review=ns['exact_review_evidence'](),
    verification=ns['exact_verification'](),
    dependencies=deps,
)
blocked = gate.evaluate(blocked_request, config)
assert ready.state.value == 'READY'
assert hold.state.value == 'HOLD'
assert blocked.state.value == 'BLOCKED'
assert ns['CANDIDATE_SHA'] not in ready.render_json()
retry_bytes = ready.render_json().encode()
for _ in range(1000):
    assert gate.evaluate(ready_request, config).render_json().encode() == retry_bytes
trace_hasher = hashlib.sha256()
counts = {'BLOCKED':0,'HOLD':0,'READY':0}
for index in range(5000):
    mode=index % 3
    if mode == 0:
        record=gate.evaluate(ready_request, config)
    elif mode == 1:
        request=replace(ready_request, verification=ns['exact_verification'](evidence_age_seconds=4000.0 + (index % 29)))
        record=gate.evaluate(request, config)
    else:
        request=replace(ready_request, verification=ns['exact_verification'](static_analysis_passed=False))
        record=gate.evaluate(request, config)
    counts[record.state.value]+=1
    trace_hasher.update(str(index).encode())
    trace_hasher.update(record.render_json().encode())
payload={
    'candidate_sha': '10c5b6d3d1c2a686d8f9926e2815dfe647de8c24',
    'parent_sha': '41b0b104e5a3f06c4d238060ad0fd3dd51dd4446',
    'red_sha': '4d6874caf519ad6f547d3217ccecc9fe58ac19e0',
    'ready': json.loads(ready.render_json()),
    'hold': json.loads(hold.render_json()),
    'blocked': json.loads(blocked.render_json()),
    'trace_count': 5000,
    'trace_counts': counts,
    'trace_sha256': trace_hasher.hexdigest(),
    'retry_count': 1000,
    'retry_sha256': hashlib.sha256(retry_bytes * 1000).hexdigest(),
    'record_privacy_candidate_sha_absent': True,
}
print(json.dumps(payload,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')))
PY

for seed in 1 7 31 101; do
  PYTHONHASHSEED="$seed" PYTHONPATH="$PWD/src" python "$EVIDENCE_ROOT/semantic_probe.py" > "$EVIDENCE_ROOT/semantic-$seed.json"
done
run cmp "$EVIDENCE_ROOT/semantic-1.json" "$EVIDENCE_ROOT/semantic-7.json"
run cmp "$EVIDENCE_ROOT/semantic-1.json" "$EVIDENCE_ROOT/semantic-31.json"
run cmp "$EVIDENCE_ROOT/semantic-1.json" "$EVIDENCE_ROOT/semantic-101.json"
cp "$EVIDENCE_ROOT/semantic-1.json" "$EVIDENCE_ROOT/semantic.json"
rm "$EVIDENCE_ROOT/semantic_probe.py" "$EVIDENCE_ROOT/semantic-1.json" "$EVIDENCE_ROOT/semantic-7.json" "$EVIDENCE_ROOT/semantic-31.json" "$EVIDENCE_ROOT/semantic-101.json"

wheelhouse="$EVIDENCE_ROOT/wheelhouse"
venv="$EVIDENCE_ROOT/venv"
mkdir -p "$wheelhouse"
run python -m pip wheel --no-deps . -w "$wheelhouse"
wheel=$(find "$wheelhouse" -maxdepth 1 -name '*.whl' -print -quit)
test -n "$wheel"
wheel_sha=$(sha256sum "$wheel" | awk '{print $1}')
run python -m venv "$venv"
run "$venv/bin/python" -m pip install --no-deps "$wheel"
run "$venv/bin/python" -m pip check
(
  cd "$RUNNER_TEMP"
  "$venv/bin/python" - <<'PY'
import nextgen_memory
from nextgen_memory import ExactShaMergeReadinessGate, MergeReadinessState
assert ExactShaMergeReadinessGate.__module__ == 'nextgen_memory.merge_readiness_gate'
assert MergeReadinessState.READY.value == 'READY'
assert nextgen_memory.__all__.count('ExactShaMergeReadinessGate') == 1
PY
)
rm -rf "$venv"
cp "$wheel" "$EVIDENCE_ROOT/merge-readiness.whl"
rm -rf "$wheelhouse"

semantic_sha=$(sha256sum "$EVIDENCE_ROOT/semantic.json" | awk '{print $1}')
printf '{"schema":"m-head-merge-readiness-r4v3-verifier-runtime-v1","python":"%s","candidate_sha":"%s","parent_sha":"%s","red_sha":"%s","focused_tests":61,"full_tests":587,"generated_traces":5000,"exact_retries":1000,"hash_seed_invariant":true,"audit_findings":0,"isolated_wheel_import":true,"semantic_sha256":"%s","wheel_sha256":"%s"}\n' \
  "$PYTHON_VERSION" "$CANDIDATE_SHA" "$PARENT_SHA" "$RED_SHA" "$semantic_sha" "$wheel_sha" \
  > "$EVIDENCE_ROOT/summary.json"
rm -f "$EVIDENCE_ROOT"/*.red
printf 'verification_runtime=%s semantic_sha256=%s wheel_sha256=%s\n' "$PYTHON_VERSION" "$semantic_sha" "$wheel_sha"
