#!/usr/bin/env bash
set -euo pipefail

REPO=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}
BASE_SHA='f4f3aca9759b5b7a60691017c2211152c011ea92'
RED_BRANCH='tdd/exact-sha-review-attestation-registry-v0-red-20260824'
RED_ROOT="$RUNNER_TEMP/exact-review-attestation-red-source"
BASE_ROOT="$RUNNER_TEMP/exact-review-attestation-red-base"
FILES=(
  tests/test_review_attestation_registry.py
  tests/test_review_attestation_registry_properties.py
  tests/test_review_attestation_registry_public_api.py
)
EXPECTED=(
  docs/exact-sha-review-attestation-registry-v0-red.md
  tests/test_review_attestation_registry.py
  tests/test_review_attestation_registry_properties.py
  tests/test_review_attestation_registry_public_api.py
)

run() {
  printf '+ %q ' "$@"
  printf '\n'
  "$@"
}

git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
run git fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*'
test "$(git rev-parse "origin/$RED_BRANCH")" != "$BASE_SHA"
test "$(git merge-base "$BASE_SHA" "origin/$RED_BRANCH")" = "$BASE_SHA"

rm -rf "$RED_ROOT" "$BASE_ROOT"
run git worktree add -B "$RED_BRANCH" "$RED_ROOT" "origin/$RED_BRANCH"
pushd "$RED_ROOT" >/dev/null
run ruff check --fix "${FILES[@]}"
run ruff format "${FILES[@]}"
run ruff check "${FILES[@]}"
run ruff format --check "${FILES[@]}"
run python -m py_compile "${FILES[@]}"
run git diff --check
run git add "${FILES[@]}" docs/exact-sha-review-attestation-registry-v0-red.md
if ! git diff --cached --quiet; then
  run git commit -m 'test: normalize exact review attestation RED contract'
  run git push origin HEAD:"$RED_BRANCH"
fi
RED_SHA=$(git rev-parse HEAD)
mapfile -t CHANGED < <(git diff --name-only "$BASE_SHA"...HEAD | sort)
test "${#CHANGED[@]}" -eq "${#EXPECTED[@]}"
diff -u \
  <(printf '%s\n' "${EXPECTED[@]}" | sort) \
  <(printf '%s\n' "${CHANGED[@]}")
test -z "$(git diff --name-only "$BASE_SHA"...HEAD -- '.github/workflows/**' 'migrations/**' pyproject.toml 'src/nextgen_memory/corrective_retrieval_*')"
run git diff --check "$BASE_SHA"...HEAD
popd >/dev/null

run git worktree add --detach "$BASE_ROOT" "$BASE_SHA"
mkdir -p "$BASE_ROOT/tests" "$BASE_ROOT/docs"
for file in "${FILES[@]}"; do
  cp "$RED_ROOT/$file" "$BASE_ROOT/$file"
done
cp \
  "$RED_ROOT/docs/exact-sha-review-attestation-registry-v0-red.md" \
  "$BASE_ROOT/docs/exact-sha-review-attestation-registry-v0-red.md"
pushd "$BASE_ROOT" >/dev/null
test ! -e src/nextgen_memory/review_attestation_registry.py
if grep -F 'review_attestation_registry' src/nextgen_memory/__init__.py; then
  echo 'base package root unexpectedly exports the absent module' >&2
  exit 1
fi

for file in "${FILES[@]}"; do
  output="/tmp/$(basename "$file" .py)-review-attestation-red.txt"
  set +e
  PYTHONPATH="$PWD/src" python -m pytest --collect-only -q "$file" \
    > "$output" 2>&1
  rc=$?
  set -e
  test "$rc" -ne 0
  FILE="$file" OUTPUT="$output" python - <<'PY'
from __future__ import annotations

import os
import re
from pathlib import Path

file = os.environ['FILE']
text = Path(os.environ['OUTPUT']).read_text(
    encoding='utf-8',
    errors='replace',
)
modules = set(
    re.findall(
        r"ModuleNotFoundError: No module named '([^']+)'",
        text,
    )
)
expected = {'nextgen_memory.review_attestation_registry'}
if modules != expected:
    raise SystemExit(
        f'{file}: unexpected missing-module set: {sorted(modules)!r}'
    )
for marker in (
    'SyntaxError',
    'IndentationError',
    'NameError',
    'ERROR at setup',
    'fixture ',
):
    if marker in text:
        raise SystemExit(f'{file}: unintended RED marker: {marker}')
PY
  printf '%s: intended module-absence RED proven\n' "$file"
done
popd >/dev/null

BODY=$(cat <<EOF
## Exact-SHA review attestation registry RED accepted

- immutable base: \`$BASE_SHA\`;
- tests-only RED branch: \`$RED_BRANCH\`;
- RED SHA: \`$RED_SHA\`;
- exact paths: four;
- Ruff, formatting, and syntax: clean;
- each test file independently fails collection only because \`nextgen_memory.review_attestation_registry\` is absent;
- implementation, exports, persistence, authentication, merge, activation, and release behavior: absent.
EOF
)
gh api "repos/$REPO/issues/165/comments" --raw-field body="$BODY" >/dev/null
SELF_PR=$(python - <<'PY'
import json
import os
from pathlib import Path

payload = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
print(payload['pull_request']['number'])
PY
)
gh api --method PATCH "repos/$REPO/pulls/$SELF_PR" -f state=closed >/dev/null
printf 'red_sha=%s\n' "$RED_SHA"
