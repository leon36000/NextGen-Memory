#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 CONTROLLER_ROOT PRODUCT_ROOT" >&2
  exit 2
fi

CONTROLLER_ROOT=$1
PRODUCT_ROOT=$2
REPO=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}
BASE_SHA='f4f3aca9759b5b7a60691017c2211152c011ea92'
FEATURE_SHA='40fae50aadc7f77633708d71641018612b08f23b'
RED_V2_SHA='4f0a74e0d39a181b682d2b135012184c255928bc'
FEATURE_BRANCH='feat/exact-sha-review-attestation-registry-v0-20260824'
CANDIDATE_BRANCH='candidate/exact-sha-review-attestation-registry-v0-20260824'
PAYLOAD_DIRECTORY="$CONTROLLER_ROOT/.github/payloads/exact-review-attestation-v0"
PAYLOAD_B64="$RUNNER_TEMP/exact-review-attestation-product.b64"
PAYLOAD_ARCHIVE="$RUNNER_TEMP/exact-review-attestation-product.tar.gz"
PAYLOAD_ROOT="$RUNNER_TEMP/exact-review-attestation-product"
PAYLOAD_SHA256='0611520519ccbdf98d548158e1e9a4de972943d57be1d1eb2ebe6cb8239981e4'

EXPECTED_PATHS=(
  docs/exact-sha-review-attestation-registry-v0-red.md
  docs/exact-sha-review-attestation-registry-v0.md
  docs/superpowers/plans/2026-08-24-exact-sha-review-attestation-registry-v0.md
  docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md
  src/nextgen_memory/__init__.py
  src/nextgen_memory/review_attestation_registry.py
  tests/test_review_attestation_registry.py
  tests/test_review_attestation_registry_properties.py
  tests/test_review_attestation_registry_public_api.py
)
PYTHON_PATHS=(
  src/nextgen_memory/__init__.py
  src/nextgen_memory/review_attestation_registry.py
  tests/test_review_attestation_registry.py
  tests/test_review_attestation_registry_properties.py
  tests/test_review_attestation_registry_public_api.py
)
RED_PATHS=(
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

verify_digest() {
  local expected=$1 path=$2
  local actual
  actual=$(sha256sum "$path" | awk '{print $1}')
  if [[ "$actual" != "$expected" ]]; then
    printf 'digest mismatch: %s expected=%s actual=%s\n' \
      "$path" "$expected" "$actual" >&2
    exit 1
  fi
}

# Reconstruct only after every uploaded fragment is proven exact.
verify_digest \
  d72d4a96bea9f27cccf85160531a795cf4572f26244fb7e6e3482b761175b597 \
  "$PAYLOAD_DIRECTORY/part-00.b64"
verify_digest \
  0d7f9096d34b4cd6a5966a9c13a62f90ff655555f528964ba7ead2830eda14b5 \
  "$PAYLOAD_DIRECTORY/part-01.b64"
verify_digest \
  02ae74818131449fce89fc8d1ab901480bc80b373069813481b87c20367ae9dc \
  "$PAYLOAD_DIRECTORY/part-02.b64"
verify_digest \
  ce0e5a3388b70439e35aa74ead146345607d8dd8526f98e7a35eb435d05d6def \
  "$PAYLOAD_DIRECTORY/part-03.b64"
verify_digest \
  662f803e2b0ac3f7627ddc14773c8939cb510387d8bda1d2d6f2427e159fc235 \
  "$PAYLOAD_DIRECTORY/part-04.b64"
cat "$PAYLOAD_DIRECTORY"/part-0{0,1,2,3,4}.b64 > "$PAYLOAD_B64"
test "$(wc -c < "$PAYLOAD_B64")" -eq 37752
base64 --decode "$PAYLOAD_B64" > "$PAYLOAD_ARCHIVE"
verify_digest "$PAYLOAD_SHA256" "$PAYLOAD_ARCHIVE"
rm -rf "$PAYLOAD_ROOT"
mkdir -p "$PAYLOAD_ROOT"

PAYLOAD_ARCHIVE="$PAYLOAD_ARCHIVE" PAYLOAD_ROOT="$PAYLOAD_ROOT" python - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import tarfile
from pathlib import Path, PurePosixPath

archive_path = Path(os.environ['PAYLOAD_ARCHIVE'])
destination = Path(os.environ['PAYLOAD_ROOT'])
expected_paths = {
    'docs/exact-sha-review-attestation-registry-v0-red.md',
    'docs/exact-sha-review-attestation-registry-v0.md',
    'docs/superpowers/plans/2026-08-24-exact-sha-review-attestation-registry-v0.md',
    'docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md',
    'src/nextgen_memory/__init__.py',
    'src/nextgen_memory/review_attestation_registry.py',
    'tests/test_review_attestation_registry.py',
    'tests/test_review_attestation_registry_properties.py',
    'tests/test_review_attestation_registry_public_api.py',
}
with tarfile.open(archive_path, 'r:gz') as archive:
    for member in archive.getmembers():
        normalized = member.name.removeprefix('./')
        pure = PurePosixPath(normalized)
        if pure.is_absolute() or '..' in pure.parts:
            raise SystemExit(f'unsafe payload member: {member.name}')
        if member.issym() or member.islnk() or member.isdev():
            raise SystemExit(f'unsupported payload member: {member.name}')
    archive.extractall(destination, filter='data')

manifest_path = destination / '.mhead-payload-manifest.json'
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
if manifest != {
    **manifest,
    'schema': 'm-head-exact-review-attestation-product-payload-v1',
    'base_sha': 'f4f3aca9759b5b7a60691017c2211152c011ea92',
    'feature_sha_before': '40fae50aadc7f77633708d71641018612b08f23b',
    'red_v2_sha': '4f0a74e0d39a181b682d2b135012184c255928bc',
    'exact_path_count': 9,
}:
    raise SystemExit('payload identity header differs')
files = manifest.get('files')
if not isinstance(files, list) or len(files) != 9:
    raise SystemExit('payload file manifest cardinality differs')
seen: set[str] = set()
for item in files:
    if not isinstance(item, dict) or set(item) != {'path', 'sha256', 'size'}:
        raise SystemExit('payload file manifest shape differs')
    path = item['path']
    if not isinstance(path, str) or path in seen or path not in expected_paths:
        raise SystemExit(f'payload path differs: {path!r}')
    seen.add(path)
    source = destination / path
    raw = source.read_bytes()
    if len(raw) != item['size']:
        raise SystemExit(f'payload size differs: {path}')
    if hashlib.sha256(raw).hexdigest() != item['sha256']:
        raise SystemExit(f'payload digest differs: {path}')
if seen != expected_paths:
    raise SystemExit('payload path set differs')
print(json.dumps(manifest, sort_keys=True))
PY

# Check out and lock the one permitted product writer.
cd "$PRODUCT_ROOT"
run git fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*'
test "$(git rev-parse HEAD)" = "$FEATURE_SHA"
test "$(git rev-parse "origin/$FEATURE_BRANCH")" = "$FEATURE_SHA"
test "$(git merge-base HEAD "$BASE_SHA")" = "$BASE_SHA"
git cat-file -e "$RED_V2_SHA^{commit}"
test "$(git merge-base "$BASE_SHA" "$RED_V2_SHA")" = "$BASE_SHA"
test -z "$(git status --porcelain)"

for path in "${EXPECTED_PATHS[@]}"; do
  mkdir -p "$(dirname "$path")"
  cp "$PAYLOAD_ROOT/$path" "$path"
done

# RED v2 remains the exact product test contract.
for path in "${RED_PATHS[@]}"; do
  reference="$RUNNER_TEMP/red-v2-${path//\//_}"
  git show "$RED_V2_SHA:$path" > "$reference"
  cmp "$reference" "$path"
done

run python -m pip install -e '.[dev]'
# Fix only source/export formatting. RED tests are immutable and checked below.
run ruff check --fix \
  src/nextgen_memory/__init__.py \
  src/nextgen_memory/review_attestation_registry.py
run ruff format \
  src/nextgen_memory/__init__.py \
  src/nextgen_memory/review_attestation_registry.py
run ruff check "${PYTHON_PATHS[@]}"
run ruff format --check "${PYTHON_PATHS[@]}"
run python -m compileall -q src scripts
for path in "${RED_PATHS[@]}"; do
  reference="$RUNNER_TEMP/red-v2-${path//\//_}"
  cmp "$reference" "$path"
done

set -o pipefail
run python -m pytest -q \
  tests/test_review_attestation_registry.py \
  tests/test_review_attestation_registry_properties.py \
  tests/test_review_attestation_registry_public_api.py \
  | tee /tmp/exact-review-attestation-focused.txt
run ruff check .
run python -m pytest -q | tee /tmp/exact-review-attestation-full.txt

FOCUSED_COUNT=$(python - <<'PY'
from pathlib import Path
import re
text = Path('/tmp/exact-review-attestation-focused.txt').read_text(encoding='utf-8')
matches = re.findall(r'(\d+) passed', text)
if not matches:
    raise SystemExit('focused pass count missing')
print(matches[-1])
PY
)
FULL_COUNT=$(python - <<'PY'
from pathlib import Path
import re
text = Path('/tmp/exact-review-attestation-full.txt').read_text(encoding='utf-8')
matches = re.findall(r'(\d+) passed', text)
if not matches:
    raise SystemExit('full pass count missing')
print(matches[-1])
PY
)
test "$FOCUSED_COUNT" -eq 61
test "$FULL_COUNT" -eq 515

# Pure-core dependency, privacy, side-effect, and stub audit.
python - <<'PY'
from __future__ import annotations

import ast
from pathlib import Path

module_path = Path('src/nextgen_memory/review_attestation_registry.py')
source = module_path.read_text(encoding='utf-8')
tree = ast.parse(source, filename=str(module_path))
allowed_roots = {
    '__future__',
    'collections',
    'dataclasses',
    'enum',
    'hashlib',
    'itertools',
    'json',
    're',
    'typing',
    'uuid',
}
forbidden_builtins = {'compile', 'eval', 'exec', 'open'}
forbidden_attributes = {
    'sleep', 'system', 'urlopen', 'uuid1', 'uuid4', 'write_bytes', 'write_text'
}
findings: list[str] = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.split('.', 1)[0] not in allowed_roots:
                findings.append(f'{node.lineno}:import:{alias.name}')
    elif isinstance(node, ast.ImportFrom):
        root = (node.module or '').split('.', 1)[0]
        if root not in allowed_roots:
            findings.append(f'{node.lineno}:import:{node.module}')
    elif isinstance(node, ast.Pass):
        findings.append(f'{node.lineno}:pass')
    elif (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    ):
        findings.append(f'{node.lineno}:executable_ellipsis')
    elif isinstance(node, ast.Raise):
        target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if (
            isinstance(target, ast.Name) and target.id == 'NotImplementedError'
        ) or (
            isinstance(target, ast.Attribute)
            and target.attr == 'NotImplementedError'
        ):
            findings.append(f'{node.lineno}:NotImplementedError')
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in forbidden_builtins:
            findings.append(f'{node.lineno}:call:{node.func.id}')
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden_attributes
        ):
            findings.append(f'{node.lineno}:call:{node.func.attr}')

lowered = source.lower()
for marker in (
    'postgresql://', 'mongodb://', 'http://', 'https://', 'password',
    'credential', '# todo', '# fixme', 'raw_query', 'raw_prompt',
    'response_text', 'memory_body', 'worker_identity', 'lease_timestamp',
    'activate_policy(', 'write_feedback(', 'merge_pull_request(',
):
    if marker in lowered:
        findings.append(f'text:{marker}')
for path in (
    Path('tests/test_review_attestation_registry.py'),
    Path('tests/test_review_attestation_registry_properties.py'),
    Path('tests/test_review_attestation_registry_public_api.py'),
):
    test_source = path.read_text(encoding='utf-8').lower()
    for marker in ('pytest.mark.skip', 'pytest.mark.xfail', '# noqa'):
        if marker in test_source:
            findings.append(f'{path}:text:{marker}')
if findings:
    raise SystemExit('\n'.join(findings))
print('exact_review_attestation_audit_findings=0')
PY

# Exact wheel import outside the checkout.
WHEELHOUSE="$RUNNER_TEMP/exact-review-attestation-wheelhouse"
VENV="$RUNNER_TEMP/exact-review-attestation-wheel-venv"
rm -rf "$WHEELHOUSE" "$VENV"
mkdir -p "$WHEELHOUSE"
run python -m pip wheel --no-deps . -w "$WHEELHOUSE"
WHEEL=$(find "$WHEELHOUSE" -maxdepth 1 -type f -name '*.whl')
test -n "$WHEEL"
run python -m venv "$VENV"
run "$VENV/bin/python" -m pip install --no-deps "$WHEEL"
"$VENV/bin/python" - <<'PY'
import nextgen_memory
from nextgen_memory import (
    ExactShaReviewAttestation,
    ExactShaReviewRequest,
    InMemoryExactShaReviewAttestationRegistry,
    ReviewAdvisoryState,
    ReviewAttestationConflictError,
    ReviewAttestationDecision,
    ReviewAttestationRegistrySummary,
    ReviewAttestationStateError,
    ReviewAttestationValidationError,
    ReviewAttestationVerdict,
    ReviewFindingCode,
    ReviewerIdentity,
    ReviewModel,
)

assert ExactShaReviewAttestation is not None
assert ExactShaReviewRequest is not None
assert InMemoryExactShaReviewAttestationRegistry is not None
assert ReviewAdvisoryState.APPROVED.value == 'approved'
assert ReviewAttestationConflictError is not None
assert ReviewAttestationDecision is not None
assert ReviewAttestationRegistrySummary is not None
assert ReviewAttestationStateError is not None
assert ReviewAttestationValidationError is not None
assert ReviewAttestationVerdict.APPROVE.value == 'APPROVE'
assert ReviewFindingCode.CONTRACT_VIOLATION.value == 'contract_violation'
assert ReviewerIdentity is not None
assert ReviewModel.GPT_5_6_SOL.value == 'gpt-5.6-sol'
for name in (
    'ExactShaReviewAttestation',
    'ExactShaReviewRequest',
    'InMemoryExactShaReviewAttestationRegistry',
    'ReviewAdvisoryState',
    'ReviewAttestationConflictError',
    'ReviewAttestationDecision',
    'ReviewAttestationRegistrySummary',
    'ReviewAttestationStateError',
    'ReviewAttestationValidationError',
    'ReviewAttestationVerdict',
    'ReviewFindingCode',
    'ReviewerIdentity',
    'ReviewModel',
):
    assert nextgen_memory.__all__.count(name) == 1
PY
run "$VENV/bin/python" -m pip check
WHEEL_SHA=$(sha256sum "$WHEEL" | awk '{print $1}')
cp "$WHEEL" /tmp/exact-review-attestation-wheel.whl

# Remove generated metadata before proving the immutable product surface.
git restore --worktree --staged src/nextgen_memory.egg-info 2>/dev/null || true
rm -rf build dist wheelhouse
find . -type d -name '__pycache__' -prune -exec rm -rf {} +
rm -rf .pytest_cache .ruff_cache

run git add "${EXPECTED_PATHS[@]}"
mapfile -t STAGED_PATHS < <(git diff --cached --name-only "$BASE_SHA" | sort)
test "${#STAGED_PATHS[@]}" -eq "${#EXPECTED_PATHS[@]}"
diff -u \
  <(printf '%s\n' "${EXPECTED_PATHS[@]}" | sort) \
  <(printf '%s\n' "${STAGED_PATHS[@]}")
test -z "$(git diff --cached --name-only "$BASE_SHA" -- '.github/workflows/**' 'migrations/**' pyproject.toml 'src/nextgen_memory/corrective_retrieval_*')"
run git diff --cached --check
test -z "$(git status --porcelain | awk '$1 == "??" {print}')"

run git config user.name 'github-actions[bot]'
run git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
run git commit -m 'feat: add exact-SHA review attestation registry v0'
PRODUCT_SHA=$(git rev-parse HEAD)
PRODUCT_TREE=$(git rev-parse 'HEAD^{tree}')
run git push origin HEAD:"$FEATURE_BRANCH"
EXISTING_CANDIDATE=$(git ls-remote --heads origin "$CANDIDATE_BRANCH" | awk '{print $1}')
if [[ -n "$EXISTING_CANDIDATE" ]]; then
  test "$EXISTING_CANDIDATE" = "$PRODUCT_SHA"
else
  run git push origin "$PRODUCT_SHA:refs/heads/$CANDIDATE_BRANCH"
fi

FOCUSED_COUNT="$FOCUSED_COUNT" FULL_COUNT="$FULL_COUNT" WHEEL_SHA="$WHEEL_SHA" \
PRODUCT_SHA="$PRODUCT_SHA" PRODUCT_TREE="$PRODUCT_TREE" python - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

summary = {
    'schema': 'm-head-exact-review-attestation-producer-v1',
    'status': 'producer_green_verifier_pending_unmerged',
    'repository': 'leon36000/NextGen-Memory',
    'base': {
        'branch': 'candidate/advisory-policy-promotion-gate-v0-20260824',
        'sha': 'f4f3aca9759b5b7a60691017c2211152c011ea92',
    },
    'feature': {
        'branch': 'feat/exact-sha-review-attestation-registry-v0-20260824',
        'previous_sha': '40fae50aadc7f77633708d71641018612b08f23b',
        'sha': os.environ['PRODUCT_SHA'],
        'tree_sha': os.environ['PRODUCT_TREE'],
    },
    'candidate': {
        'branch': 'candidate/exact-sha-review-attestation-registry-v0-20260824',
        'sha': os.environ['PRODUCT_SHA'],
        'exact_path_count': 9,
    },
    'tdd': {
        'red_v1_sha': 'a33775aec1a3c1de75133a92717a5bd7bf664e6e',
        'red_v2_sha': '4f0a74e0d39a181b682d2b135012184c255928bc',
        'red_v2_fixture_delta': 'lowercase_authenticated_envelope_sha256',
        'assertions_weakened': False,
    },
    'verification': {
        'payload_sha256': '0611520519ccbdf98d548158e1e9a4de972943d57be1d1eb2ebe6cb8239981e4',
        'focused_test_count': int(os.environ['FOCUSED_COUNT']),
        'full_test_count': int(os.environ['FULL_COUNT']),
        'generated_trace_count': 5000,
        'ruff_clean': True,
        'compileall_green': True,
        'audit_findings': 0,
        'isolated_wheel_import': True,
        'wheel_sha256': os.environ['WHEEL_SHA'],
    },
    'review': {
        'required_model': 'GPT-5.6 Sol',
        'verdict': 'not_requested_for_valid_candidate',
        'merge_allowed': False,
    },
    'safety': {
        'actual_product_merge_performed': False,
        'merged': False,
        'production_database_contacted': False,
        'production_migration_applied': False,
        'production_application_data_written': False,
        'feedback_written': False,
        'policy_activated': False,
        'release_published': False,
        'tests_weakened': False,
        'stubs_added': False,
        'sol_verdict_fabricated': False,
    },
    'next_action': (
        'Run an independent exact-SHA Python 3.12/3.13 verifier, compare '
        'cross-Python canonical evidence, publish immutable evidence/checkpoint '
        'branches, then create one canonical draft product PR and blind Sol packet.'
    ),
}
Path('/tmp/exact-review-attestation-producer-summary.json').write_text(
    json.dumps(
        summary,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(',', ':'),
    ) + '\n',
    encoding='utf-8',
)
PY
run git diff --binary "$BASE_SHA"..."$PRODUCT_SHA" \
  > /tmp/exact-review-attestation-product.patch

BODY=$(cat <<EOF
## Exact-SHA Review Attestation Registry v0 producer GREEN

- base: \`$BASE_SHA\`;
- corrected immutable RED v2: \`$RED_V2_SHA\`;
- feature candidate: \`$PRODUCT_SHA\`;
- exact product surface: nine paths;
- focused tests: \`$FOCUSED_COUNT\`;
- complete repository tests: \`$FULL_COUNT\`;
- generated traces: \`5,000\`;
- Ruff, compileall, strict audit, and isolated wheel: green;
- wheel SHA-256: \`$WHEEL_SHA\`;
- candidate branch: \`$CANDIDATE_BRANCH\`;
- independent Python 3.12/3.13 exact-SHA verification: pending;
- GPT-5.6 Sol verdict: not yet requested for this candidate;
- merge allowed: \`false\`.

No production database, migration, persistence, feedback, policy activation, deployment, merge, or release operation occurred.
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
printf 'product_sha=%s\nproduct_tree=%s\nfocused=%s\nfull=%s\nwheel_sha256=%s\n' \
  "$PRODUCT_SHA" "$PRODUCT_TREE" "$FOCUSED_COUNT" "$FULL_COUNT" "$WHEEL_SHA"
