#!/usr/bin/env bash
set -euo pipefail

CONTROLLER_ROOT=${1:?controller root required}
PRODUCT_ROOT=${2:?product root required}

PARENT_SHA='41b0b104e5a3f06c4d238060ad0fd3dd51dd4446'
FEATURE_SHA='e48227896b3dec41b43ab2d92b802714b65db1a1'
RED_SHA='4d6874caf519ad6f547d3217ccecc9fe58ac19e0'
CANDIDATE_BRANCH='candidate/exact-sha-merge-readiness-gate-v0-20260831'
RED_PATHS=(
  docs/exact-sha-merge-readiness-gate-v0-red.md
  tests/test_merge_readiness_gate.py
  tests/test_merge_readiness_gate_properties.py
  tests/test_merge_readiness_gate_public_api.py
)
PRODUCT_PATHS=(
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

run() {
  printf '+ '
  printf '%q ' "$@"
  printf '\n'
  "$@"
}

cd "$PRODUCT_ROOT"
run git fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*'
test "$(git rev-parse HEAD)" = "$FEATURE_SHA"
test "$(git merge-base "$PARENT_SHA" HEAD)" = "$PARENT_SHA"
run git cat-file -e "$RED_SHA^{commit}"
test "$(git merge-base "$FEATURE_SHA" "$RED_SHA")" = "$FEATURE_SHA"
test ! -e src/nextgen_memory/merge_readiness_gate.py
if grep -F 'merge_readiness_gate' src/nextgen_memory/__init__.py; then
  echo 'feature unexpectedly exports merge-readiness module before GREEN' >&2
  exit 1
fi

run git checkout "$RED_SHA" -- "${RED_PATHS[@]}"
run cp "$CONTROLLER_ROOT/.github/payloads/merge_readiness_gate.py" \
  src/nextgen_memory/merge_readiness_gate.py

cat > docs/exact-sha-merge-readiness-gate-v0.md <<'EOF'
# Exact-SHA Merge Readiness Gate v0

## Status

This component is a pure deterministic advisory boundary. It evaluates exact candidate identity, R4 review-registry evidence, verification evidence, ordered dependency readiness, branch controls, and bounded freshness policy. It returns `READY`, `HOLD`, or `BLOCKED` and never executes a merge.

## Precedence

Hard blocks suppress all holds. Identity drift, blocked/evidence-blocked review state, unauthenticated approval, verification failures, dependency duplication, and branch-control violations are `BLOCKED`. Missing, stale, or insufficient but non-contradictory evidence is `HOLD`. `READY` requires every exact identity and verification gate to pass.

## Review evidence

The gate consumes exact R4 `ExactShaReviewRequest`, `ReviewAttestationRegistrySummary`, and `ReviewAttestationDecision` instances. Their canonical identities are revalidated before use. An externally supplied authentication boolean and authenticated-envelope evidence digest are required for an approved review to become ready; this module verifies no signature itself.

## Verification and dependencies

Verification binds exact base/candidate/diff identities, static and compile status, full-suite status/count, artifact integrity, isolated wheel, integration rehearsal, cross-Python semantic identity, optional PostgreSQL replay, migration count, freshness, and artifact/checkpoint digests. Dependencies are an exact ordered non-empty tuple with contiguous ordinals and unique component/SHA identities.

## Safety boundary

`READY` is evidence only. The module has no GitHub client, network/database/filesystem/environment/clock/randomness/model/worker/task surface and cannot merge, migrate, deploy, write feedback, activate policy, or publish a release.
EOF

python - <<'PY'
from pathlib import Path

path = Path('src/nextgen_memory/__init__.py')
source = path.read_text(encoding='utf-8')
import_block = '''from .merge_readiness_gate import (
    ExactReviewReadinessEvidence,
    ExactShaMergeReadinessGate,
    MergeCandidateIdentity,
    MergeDependencyIdentity,
    MergeDependencyReadiness,
    MergeReadinessConfig,
    MergeReadinessReason,
    MergeReadinessRecord,
    MergeReadinessRequest,
    MergeReadinessState,
    MergeReadinessValidationError,
    MergeVerificationEvidence,
)
'''
anchor = 'from .mongodb_retrieval import (\n'
if import_block not in source:
    if source.count(anchor) != 1:
        raise SystemExit('package import anchor is absent or duplicated')
    source = source.replace(anchor, import_block + anchor, 1)

names = (
    'ExactReviewReadinessEvidence',
    'ExactShaMergeReadinessGate',
    'MergeCandidateIdentity',
    'MergeDependencyIdentity',
    'MergeDependencyReadiness',
    'MergeReadinessConfig',
    'MergeReadinessReason',
    'MergeReadinessRecord',
    'MergeReadinessRequest',
    'MergeReadinessState',
    'MergeReadinessValidationError',
    'MergeVerificationEvidence',
)
list_anchor = '    "MemoryCandidate",\n'
additions = ''.join(f'    "{name}",\n' for name in names)
if all(source.count(f'    "{name}",') == 0 for name in names):
    if source.count(list_anchor) != 1:
        raise SystemExit('__all__ insertion anchor is absent or duplicated')
    source = source.replace(list_anchor, additions + list_anchor, 1)
for name in names:
    if source.count(f'    "{name}",') != 1:
        raise SystemExit(f'public export count differs for {name}')
path.write_text(source, encoding='utf-8')
PY

run python -m pip install -e '.[dev]'
run python -m pip install 'ruff==0.16.4'
run ruff --version

for path in "${RED_PATHS[@]}"; do
  safe=${path//\//__}
  git show "$RED_SHA:$path" > "$RUNNER_TEMP/$safe.red"
done

run ruff check --fix \
  src/nextgen_memory/merge_readiness_gate.py \
  src/nextgen_memory/__init__.py
run ruff format \
  src/nextgen_memory/merge_readiness_gate.py \
  src/nextgen_memory/__init__.py
run ruff check \
  src/nextgen_memory/merge_readiness_gate.py \
  src/nextgen_memory/__init__.py \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py
run ruff format --check \
  src/nextgen_memory/merge_readiness_gate.py \
  src/nextgen_memory/__init__.py \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py
for path in "${RED_PATHS[@]}"; do
  safe=${path//\//__}
  run cmp "$path" "$RUNNER_TEMP/$safe.red"
done
run python -m compileall -q src scripts
run git diff --check

set -o pipefail
python -m pytest -q \
  tests/test_merge_readiness_gate.py \
  tests/test_merge_readiness_gate_properties.py \
  tests/test_merge_readiness_gate_public_api.py \
  2>&1 | tee /tmp/merge-readiness-focused.txt
python -m pytest -q 2>&1 | tee /tmp/merge-readiness-full.txt

python - <<'PY'
from __future__ import annotations

import ast
from pathlib import Path

path = Path('src/nextgen_memory/merge_readiness_gate.py')
source = path.read_text(encoding='utf-8')
tree = ast.parse(source, filename=str(path))
allowed_imports = {
    '__future__',
    'hashlib',
    'json',
    're',
    'dataclasses',
    'enum',
    'math',
    'uuid',
    'review_attestation_registry',
}
findings: list[str] = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.split('.')[0] not in allowed_imports:
                findings.append(f'import:{alias.name}')
    elif isinstance(node, ast.ImportFrom):
        module = (node.module or '').lstrip('.')
        if module.split('.')[0] not in allowed_imports:
            findings.append(f'importfrom:{node.module}')
    elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id in {'open', 'exec', 'eval', 'compile', '__import__'}:
            findings.append(f'call:{node.func.id}')
for marker in (
    'NotImplementedError',
    'TODO',
    'FIXME',
    '# noqa',
    'requests.',
    'httpx.',
    'subprocess.',
    'socket.',
    'pathlib.',
    'os.environ',
    'time.',
    'random.',
    'secrets.',
):
    if marker in source:
        findings.append(f'lexical:{marker}')
if findings:
    raise SystemExit(f'merge-readiness audit findings: {sorted(set(findings))!r}')
print('merge_readiness_audit_findings=0')
PY

wheelhouse="$RUNNER_TEMP/merge-readiness-wheelhouse"
venv="$RUNNER_TEMP/merge-readiness-wheel-venv"
rm -rf "$wheelhouse" "$venv"
mkdir -p "$wheelhouse"
run python -m pip wheel --no-deps . -w "$wheelhouse"
run python -m venv "$venv"
run "$venv/bin/python" -m pip install --no-deps "$wheelhouse"/*.whl
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

mapfile -t changed < <(git diff --name-only "$PARENT_SHA" | sort)
test "${#changed[@]}" -eq "${#PRODUCT_PATHS[@]}"
diff -u \
  <(printf '%s\n' "${PRODUCT_PATHS[@]}" | sort) \
  <(printf '%s\n' "${changed[@]}")
test -z "$(git diff --name-only "$PARENT_SHA" -- \
  '.github/workflows/**' 'migrations/**' pyproject.toml \
  'src/nextgen_memory/corrective_retrieval_*')"
run git diff --check "$PARENT_SHA"

run git config user.name 'github-actions[bot]'
run git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
run git add "${PRODUCT_PATHS[@]}"
run git diff --cached --check
run git commit -m 'feat: add exact-SHA merge readiness gate v0'
CANDIDATE_SHA=$(git rev-parse HEAD)
run git fetch --no-tags origin \
  '+refs/heads/feat/exact-sha-merge-readiness-gate-v0-r4-v2-20260831:refs/remotes/origin/feat/exact-sha-merge-readiness-gate-v0-r4-v2-20260831'
test "$(git rev-parse origin/feat/exact-sha-merge-readiness-gate-v0-r4-v2-20260831)" = "$FEATURE_SHA"
if git ls-remote --exit-code --heads origin "$CANDIDATE_BRANCH"; then
  remote_sha=$(git ls-remote --heads origin "$CANDIDATE_BRANCH" | awk '{print $1}')
  test "$remote_sha" = "$CANDIDATE_SHA"
else
  run git push origin HEAD:"refs/heads/$CANDIDATE_BRANCH"
fi

printf '{"schema":"m-head-merge-readiness-producer-v1","status":"green_candidate_published_unmerged","parent_sha":"%s","feature_sha":"%s","red_sha":"%s","candidate_sha":"%s","exact_path_count":9,"audit_findings":0,"merged":false}\n' \
  "$PARENT_SHA" "$FEATURE_SHA" "$RED_SHA" "$CANDIDATE_SHA" \
  > /tmp/merge-readiness-producer-summary.json
printf 'candidate_sha=%s\n' "$CANDIDATE_SHA"
