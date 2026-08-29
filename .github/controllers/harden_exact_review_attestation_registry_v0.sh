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
PARENT_CANDIDATE_SHA='008005072f412ecda1bf461f4e875de72c5b808f'
ADVERSARIAL_RED_SHA='7a59141d6f890df574be42198be88a200e307846'
FIX_BRANCH='fix/exact-sha-review-attestation-registry-v0-privacy-boundary-20260829'
CANDIDATE_BRANCH='candidate/exact-sha-review-attestation-registry-v0-r3-20260829'
MODULE='src/nextgen_memory/review_attestation_registry.py'
FOCUSED=(
  tests/test_review_attestation_registry.py
  tests/test_review_attestation_registry_properties.py
  tests/test_review_attestation_registry_public_api.py
)
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

run() {
  printf '+ %q ' "$@"
  printf '\n'
  "$@"
}

passed_count() {
  python - "$1" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
matches = re.findall(r"(\d+) passed", text)
if not matches:
    raise SystemExit(f"missing pytest pass count in {sys.argv[1]}")
print(matches[-1])
PY
}

cd "$PRODUCT_ROOT"
run git fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*'
test "$(git rev-parse HEAD)" = "$ADVERSARIAL_RED_SHA"
test "$(git merge-base "$BASE_SHA" HEAD)" = "$BASE_SHA"
test "$(git merge-base "$PARENT_CANDIDATE_SHA" HEAD)" = "$PARENT_CANDIDATE_SHA"
test -z "$(git status --porcelain)"
run git diff --check "$BASE_SHA"...HEAD

run python -m pip install -e '.[dev]'
run python -m pip install 'ruff==0.16.4'
run ruff --version
run ruff check "$MODULE" "${FOCUSED[@]}"
run ruff format --check "$MODULE" "${FOCUSED[@]}"
run python -m compileall -q src scripts

# Reproduce the accepted adversarial RED before changing product code.
set +e
python -m pytest -q \
  tests/test_review_attestation_registry.py::test_collection_iteration_failures_are_bounded_and_privacy_safe \
  tests/test_review_attestation_registry.py::test_reviewer_subclass_cannot_inject_raw_payload \
  tests/test_review_attestation_registry.py::test_registry_rejects_contract_subclasses_before_mutation \
  tests/test_review_attestation_registry.py::test_primitive_subclasses_are_rejected_before_overridden_behavior \
  2>&1 | tee /tmp/exact-review-attestation-adversarial-red.txt
RED_RC=${PIPESTATUS[0]}
set -e
test "$RED_RC" -ne 0
grep -Eq '6 failed' /tmp/exact-review-attestation-adversarial-red.txt
grep -F 'SECRET-ITERATOR-SENTINEL' /tmp/exact-review-attestation-adversarial-red.txt >/dev/null
grep -F 'reviewer must be an exact ReviewerIdentity' /tmp/exact-review-attestation-adversarial-red.txt >/dev/null
grep -F 'request must be an exact ExactShaReviewRequest' /tmp/exact-review-attestation-adversarial-red.txt >/dev/null
grep -F 'SECRET-REPOSITORY-SENTINEL' /tmp/exact-review-attestation-adversarial-red.txt >/dev/null

run python \
  "$CONTROLLER_ROOT/.github/controllers/patch_exact_review_attestation_privacy_boundary.py" \
  "$MODULE"
run ruff check --fix "$MODULE"
run ruff format "$MODULE"
run ruff check "$MODULE" "${FOCUSED[@]}"
run ruff format --check "$MODULE" "${FOCUSED[@]}"
run python -m compileall -q src scripts
run git diff --check
mapfile -t UNCOMMITTED < <(git diff --name-only | sort)
test "${#UNCOMMITTED[@]}" -eq 1
test "${UNCOMMITTED[0]}" = "$MODULE"

# The six adversarial cases must all turn GREEN with no message disclosure.
run python -m pytest -q \
  tests/test_review_attestation_registry.py::test_collection_iteration_failures_are_bounded_and_privacy_safe \
  tests/test_review_attestation_registry.py::test_reviewer_subclass_cannot_inject_raw_payload \
  tests/test_review_attestation_registry.py::test_registry_rejects_contract_subclasses_before_mutation \
  tests/test_review_attestation_registry.py::test_primitive_subclasses_are_rejected_before_overridden_behavior \
  | tee /tmp/exact-review-attestation-adversarial-green.txt
test "$(passed_count /tmp/exact-review-attestation-adversarial-green.txt)" -eq 6

run python -m pytest -q "${FOCUSED[@]}" \
  | tee /tmp/exact-review-attestation-focused-r3.txt
FOCUSED_COUNT=$(passed_count /tmp/exact-review-attestation-focused-r3.txt)
test "$FOCUSED_COUNT" -eq 67

run python -m pytest -q | tee /tmp/exact-review-attestation-full-r3.txt
FULL_COUNT=$(passed_count /tmp/exact-review-attestation-full-r3.txt)
test "$FULL_COUNT" -eq 521

# Strict standard-library, privacy, side-effect, and no-stub audit.
run python - <<'PY'
from __future__ import annotations

import ast
from pathlib import Path

path = Path("src/nextgen_memory/review_attestation_registry.py")
source = path.read_text(encoding="utf-8")
tree = ast.parse(source, filename=str(path))
allowed_roots = {
    "__future__",
    "collections",
    "dataclasses",
    "enum",
    "hashlib",
    "itertools",
    "json",
    "re",
    "uuid",
}
forbidden_calls = {"compile", "eval", "exec", "open"}
forbidden_attributes = {
    "sleep",
    "system",
    "urlopen",
    "uuid1",
    "uuid4",
    "write_bytes",
    "write_text",
}
findings: list[str] = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.split(".", 1)[0] not in allowed_roots:
                findings.append(f"{node.lineno}:import:{alias.name}")
    elif isinstance(node, ast.ImportFrom):
        root = (node.module or "").split(".", 1)[0]
        if node.level == 0 and root not in allowed_roots:
            findings.append(f"{node.lineno}:import:{node.module}")
    elif isinstance(node, ast.Pass):
        findings.append(f"{node.lineno}:pass")
    elif (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    ):
        findings.append(f"{node.lineno}:executable_ellipsis")
    elif isinstance(node, ast.Raise):
        target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if (
            isinstance(target, ast.Name)
            and target.id == "NotImplementedError"
        ) or (
            isinstance(target, ast.Attribute)
            and target.attr == "NotImplementedError"
        ):
            findings.append(f"{node.lineno}:NotImplementedError")
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in forbidden_calls:
            findings.append(f"{node.lineno}:call:{node.func.id}")
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden_attributes
        ):
            findings.append(f"{node.lineno}:call:{node.func.attr}")

lowered = source.lower()
for marker in (
    "postgresql://",
    "mongodb://",
    "http://",
    "https://",
    "password",
    "credential",
    "raw_review",
    "raw_prompt",
    "raw_query",
    "memory_body",
    "response_text",
    "activate_policy(",
    "write_feedback(",
    "# todo",
    "# fixme",
):
    if marker in lowered:
        findings.append(f"text:{marker}")
for test_path in (
    Path("tests/test_review_attestation_registry.py"),
    Path("tests/test_review_attestation_registry_properties.py"),
    Path("tests/test_review_attestation_registry_public_api.py"),
):
    test_source = test_path.read_text(encoding="utf-8").lower()
    for marker in ("pytest.mark.skip", "pytest.mark.xfail", "# noqa"):
        if marker in test_source:
            findings.append(f"{test_path}:text:{marker}")
if findings:
    raise SystemExit("\n".join(findings))
print("exact_review_attestation_privacy_audit_findings=0")
PY

# Build and import the exact wheel outside the checkout.
rm -rf /tmp/exact-review-attestation-r3-wheelhouse \
  /tmp/exact-review-attestation-r3-venv
mkdir -p /tmp/exact-review-attestation-r3-wheelhouse
run python -m pip wheel --no-deps . \
  -w /tmp/exact-review-attestation-r3-wheelhouse
WHEEL=$(find /tmp/exact-review-attestation-r3-wheelhouse \
  -maxdepth 1 -type f -name '*.whl' -print -quit)
test -n "$WHEEL"
run python -m venv /tmp/exact-review-attestation-r3-venv
run /tmp/exact-review-attestation-r3-venv/bin/python -m pip install \
  --no-deps "$WHEEL"
run /tmp/exact-review-attestation-r3-venv/bin/python - <<'PY'
import nextgen_memory
from nextgen_memory import (
    ExactShaReviewAttestation,
    ExactShaReviewRequest,
    InMemoryExactShaReviewAttestationRegistry,
    ReviewerIdentity,
)

assert ExactShaReviewAttestation is not None
assert ExactShaReviewRequest is not None
assert InMemoryExactShaReviewAttestationRegistry is not None
assert ReviewerIdentity is not None
for name in (
    "ExactShaReviewAttestation",
    "ExactShaReviewRequest",
    "InMemoryExactShaReviewAttestationRegistry",
    "ReviewerIdentity",
):
    assert name in nextgen_memory.__all__
PY
run /tmp/exact-review-attestation-r3-venv/bin/python -m pip check
cp "$WHEEL" /tmp/exact-review-attestation-privacy-r3.whl
WHEEL_SHA=$(sha256sum /tmp/exact-review-attestation-privacy-r3.whl \
  | awk '{print $1}')

# Commit only the minimal implementation fix; RED remains its own prior commit.
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
run git add "$MODULE"
run git diff --cached --check
run git commit -m 'fix: harden exact review attestation privacy boundary'
FIX_SHA=$(git rev-parse HEAD)
run git push origin HEAD:"refs/heads/$FIX_BRANCH"

mapfile -t CHANGED < <(git diff --name-only "$BASE_SHA"...HEAD | sort)
test "${#CHANGED[@]}" -eq "${#EXPECTED_PATHS[@]}"
diff -u <(printf '%s\n' "${EXPECTED_PATHS[@]}" | sort) \
  <(printf '%s\n' "${CHANGED[@]}")
test -z "$(git diff --name-only "$BASE_SHA"...HEAD -- \
  '.github/workflows/**' 'migrations/**' pyproject.toml \
  'src/nextgen_memory/corrective_retrieval_*')"
test -z "$(git status --porcelain)"

if git ls-remote --exit-code --heads origin "$CANDIDATE_BRANCH" >/dev/null; then
  EXISTING=$(git ls-remote --heads origin "$CANDIDATE_BRANCH" | awk '{print $1}')
  test "$EXISTING" = "$FIX_SHA"
else
  run git push origin HEAD:"refs/heads/$CANDIDATE_BRANCH"
fi

python - <<PY
from __future__ import annotations

import hashlib
import json
from pathlib import Path

module = Path("$MODULE")
summary = {
    "schema": "m-head-exact-review-attestation-privacy-hardening-r3-v1",
    "repository": "$REPO",
    "base_sha": "$BASE_SHA",
    "parent_candidate_sha": "$PARENT_CANDIDATE_SHA",
    "adversarial_red_sha": "$ADVERSARIAL_RED_SHA",
    "fix_branch": "$FIX_BRANCH",
    "candidate_branch": "$CANDIDATE_BRANCH",
    "candidate_sha": "$FIX_SHA",
    "exact_path_count": len(${#EXPECTED_PATHS[@]} * [None]),
    "adversarial_test_count": 6,
    "focused_test_count": int("$FOCUSED_COUNT"),
    "full_test_count": int("$FULL_COUNT"),
    "audit_findings": 0,
    "isolated_wheel_import": True,
    "wheel_sha256": "$WHEEL_SHA",
    "module_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
    "privacy_contract": {
        "iterator_exceptions_normalized_without_context": True,
        "reviewer_subclasses_rejected": True,
        "request_subclasses_rejected_before_mutation": True,
        "attestation_subclasses_rejected_before_mutation": True,
        "primitive_subclasses_rejected_before_overridden_behavior": True,
    },
    "review": {
        "required_model": "GPT-5.6 Sol",
        "verdict": "pending",
        "merge_allowed": False,
    },
    "safety": {
        "merged": False,
        "production_database_contacted": False,
        "production_migration_applied": False,
        "feedback_written": False,
        "policy_activated": False,
        "release_published": False,
        "tests_weakened": False,
        "stubs_added": False,
    },
}
Path("/tmp/exact-review-attestation-privacy-r3-summary.json").write_text(
    json.dumps(
        summary,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n",
    encoding="utf-8",
)
PY
run git diff "$PARENT_CANDIDATE_SHA"...HEAD -- \
  tests/test_review_attestation_registry.py "$MODULE" \
  > /tmp/exact-review-attestation-privacy-r3.patch

BODY=$(cat <<EOF
## Exact-SHA Review Attestation Registry privacy hardening r3 GREEN

- parent candidate: \`$PARENT_CANDIDATE_SHA\`;
- accepted adversarial RED: \`$ADVERSARIAL_RED_SHA\`;
- hardened candidate: \`$FIX_SHA\`;
- candidate branch: \`$CANDIDATE_BRANCH\`;
- adversarial RED before fix: 6 failures;
- adversarial GREEN after fix: 6 passes;
- focused tests: \`$FOCUSED_COUNT\`;
- complete tests: \`$FULL_COUNT\`;
- strict audit findings: \`0\`;
- isolated wheel SHA-256: \`$WHEEL_SHA\`;
- exact product surface: nine paths;
- merge allowed: \`false\`.

The fix rejects hostile primitive and contract subclasses before invoking overridden behavior, prevents reviewer payload injection, and normalizes collection-iteration failures into bounded privacy-safe validation errors. No persistence, database, migration, feedback, activation, deployment, merge, or release operation occurred.
EOF
)
gh api "repos/$REPO/issues/165/comments" --raw-field body="$BODY" >/dev/null
printf 'candidate_sha=%s\n' "$FIX_SHA"
