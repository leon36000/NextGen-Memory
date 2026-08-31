#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 WORKSPACE" >&2
  exit 2
fi

WORKSPACE=$1
REPO=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}
SELF_PR=${SELF_PR:?SELF_PR is required}
PARENT_SHA='41b0b104e5a3f06c4d238060ad0fd3dd51dd4446'
R3_SHA='f4d9388c14dd1f746f904b3724767f73f82786fd'
SOURCE_FEATURE_SHA='c5e14f8d8db744b457b1f3f84cac249b1d7d5c70'
SOURCE_RED_SHA='6f7f9adbfe4020cbf4135206162ec4335b8d8373'
FEATURE_BRANCH='feat/exact-sha-merge-readiness-gate-v0-r4-20260831'
RED_BRANCH='tdd/exact-sha-merge-readiness-gate-v0-red-r4-20260831'
AST_REPORT='/tmp/merge-readiness-red-r4-ast.json'
SUMMARY='/tmp/merge-readiness-r4-rebase-summary.json'

cd "$WORKSPACE"
git fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*'
test "$(git rev-parse HEAD)" = "$PARENT_SHA"
test "$(git merge-base "$R3_SHA" "$PARENT_SHA")" = "$R3_SHA"
test "$(git merge-base "$R3_SHA" "$SOURCE_FEATURE_SHA")" = "$R3_SHA"
test "$(git merge-base "$SOURCE_FEATURE_SHA" "$SOURCE_RED_SHA")" = "$SOURCE_FEATURE_SHA"

if git ls-remote --exit-code --heads origin "$FEATURE_BRANCH"; then
  echo "feature branch already exists: $FEATURE_BRANCH" >&2
  exit 1
fi
if git ls-remote --exit-code --heads origin "$RED_BRANCH"; then
  echo "RED branch already exists: $RED_BRANCH" >&2
  exit 1
fi

git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'

# Publish the R4-based design and implementation plan.
git switch -C "$FEATURE_BRANCH" "$PARENT_SHA"
OLD_SPEC='docs/superpowers/specs/2026-08-30-exact-sha-merge-readiness-gate-v0-design.md'
OLD_PLAN='docs/superpowers/plans/2026-08-30-exact-sha-merge-readiness-gate-v0.md'
NEW_SPEC='docs/superpowers/specs/2026-08-31-exact-sha-merge-readiness-gate-v0-design.md'
NEW_PLAN='docs/superpowers/plans/2026-08-31-exact-sha-merge-readiness-gate-v0.md'
git checkout "$SOURCE_FEATURE_SHA" -- "$OLD_SPEC" "$OLD_PLAN"
mkdir -p "$(dirname "$NEW_SPEC")" "$(dirname "$NEW_PLAN")"
git mv "$OLD_SPEC" "$NEW_SPEC"
git mv "$OLD_PLAN" "$NEW_PLAN"

SPEC="$NEW_SPEC" PLAN="$NEW_PLAN" python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

r3_branch = "candidate/exact-sha-review-attestation-registry-v0-r3-20260829"
r3_sha = "f4d9388c14dd1f746f904b3724767f73f82786fd"
r4_branch = "candidate/exact-sha-review-attestation-registry-v0-r4-20260831"
r4_sha = "41b0b104e5a3f06c4d238060ad0fd3dd51dd4446"
old_feature = "feat/exact-sha-merge-readiness-gate-v0-20260830"
new_feature = "feat/exact-sha-merge-readiness-gate-v0-r4-20260831"
old_red = "tdd/exact-sha-merge-readiness-gate-v0-red-20260830"
old_red_v2 = "tdd/exact-sha-merge-readiness-gate-v0-red-v2-20260831"
new_red = "tdd/exact-sha-merge-readiness-gate-v0-red-r4-20260831"
old_candidate = "candidate/exact-sha-merge-readiness-gate-v0-20260830"
new_candidate = "candidate/exact-sha-merge-readiness-gate-v0-r4-20260831"
old_spec_path = (
    "docs/superpowers/specs/"
    "2026-08-30-exact-sha-merge-readiness-gate-v0-design.md"
)
old_plan_path = (
    "docs/superpowers/plans/"
    "2026-08-30-exact-sha-merge-readiness-gate-v0.md"
)
new_spec_path = (
    "docs/superpowers/specs/"
    "2026-08-31-exact-sha-merge-readiness-gate-v0-design.md"
)
new_plan_path = (
    "docs/superpowers/plans/"
    "2026-08-31-exact-sha-merge-readiness-gate-v0.md"
)

for environment_key in ("SPEC", "PLAN"):
    path = Path(os.environ[environment_key])
    source = path.read_text(encoding="utf-8")
    replacements = (
        ("**Date:** 2026-08-30", "**Date:** 2026-08-31"),
        (r3_branch, r4_branch),
        (r3_sha, r4_sha),
        (old_feature, new_feature),
        (old_red_v2, new_red),
        (old_red, new_red),
        (old_candidate, new_candidate),
        (old_spec_path, new_spec_path),
        (old_plan_path, new_plan_path),
    )
    for old, new in replacements:
        source = source.replace(old, new)
    source = "\n".join(line.rstrip() for line in source.splitlines()) + "\n"
    if r3_branch in source or r3_sha in source:
        raise SystemExit(f"{path}: R3 identity remains")
    if r4_branch not in source or r4_sha not in source:
        raise SystemExit(f"{path}: R4 identity is absent")
    path.write_text(source, encoding="utf-8")

spec = Path(os.environ["SPEC"])
source = spec.read_text(encoding="utf-8")
section = """

## R4 parent integrity boundary

The parent registry is exact SHA `41b0b104e5a3f06c4d238060ad0fd3dd51dd4446`. It revalidates canonical review identities before serialization or registry use and stores request/attestation identity snapshots separately from exposed references. Merge-readiness review evidence is trusted only after these R4 integrity checks and the gate's own request/summary/decision consistency checks succeed. Any post-construction mutation therefore fails closed.
"""
if "## R4 parent integrity boundary" not in source:
    source += section
source = "\n".join(line.rstrip() for line in source.splitlines()) + "\n"
spec.write_text(source, encoding="utf-8")
PY

git add "$NEW_SPEC" "$NEW_PLAN"
git diff --cached --check
git commit -m 'docs: rebase merge readiness design on review registry R4'
FEATURE_SHA=$(git rev-parse HEAD)
mapfile -t FEATURE_DELTA < <(git diff --name-only "$PARENT_SHA"...HEAD | sort)
EXPECTED_FEATURE=("$NEW_PLAN" "$NEW_SPEC")
test "${#FEATURE_DELTA[@]}" -eq 2
diff -u <(printf '%s\n' "${EXPECTED_FEATURE[@]}" | sort) \
  <(printf '%s\n' "${FEATURE_DELTA[@]}")
git push origin HEAD:"refs/heads/$FEATURE_BRANCH"

# Publish the R4-based tests-only RED with canonical formatting.
git switch -C "$RED_BRANCH" "$FEATURE_SHA"
RED_PATHS=(
  docs/exact-sha-merge-readiness-gate-v0-red.md
  tests/test_merge_readiness_gate.py
  tests/test_merge_readiness_gate_properties.py
  tests/test_merge_readiness_gate_public_api.py
)
git checkout "$SOURCE_RED_SHA" -- "${RED_PATHS[@]}"

DOC="${RED_PATHS[0]}" python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["DOC"])
source = path.read_text(encoding="utf-8")
replacements = (
    ("**Date:** 2026-08-30", "**Date:** 2026-08-31"),
    (
        "candidate/exact-sha-review-attestation-registry-v0-r3-20260829",
        "candidate/exact-sha-review-attestation-registry-v0-r4-20260831",
    ),
    (
        "f4d9388c14dd1f746f904b3724767f73f82786fd",
        "41b0b104e5a3f06c4d238060ad0fd3dd51dd4446",
    ),
    (
        "feat/exact-sha-merge-readiness-gate-v0-20260830",
        "feat/exact-sha-merge-readiness-gate-v0-r4-20260831",
    ),
    (
        "tdd/exact-sha-merge-readiness-gate-v0-red-v2-20260831",
        "tdd/exact-sha-merge-readiness-gate-v0-red-r4-20260831",
    ),
    (
        "tdd/exact-sha-merge-readiness-gate-v0-red-20260830",
        "tdd/exact-sha-merge-readiness-gate-v0-red-r4-20260831",
    ),
)
for old, new in replacements:
    source = source.replace(old, new)
section = """

## R4 rebase and canonical formatting

This RED preserves the complete behavior contract from the earlier draft while rebasing onto immutable Review Attestation Registry R4 `41b0b104e5a3f06c4d238060ad0fd3dd51dd4446`. The three test modules receive only canonical Ruff formatting; their parsed ASTs are compared to the source draft before publication. No fixture, assertion, reason, generated case, retry, privacy boundary, or expected state changes.
"""
if "## R4 rebase and canonical formatting" not in source:
    source += section
source = "\n".join(line.rstrip() for line in source.splitlines()) + "\n"
path.write_text(source, encoding="utf-8")
PY

TEST_FILES=(
  tests/test_merge_readiness_gate.py
  tests/test_merge_readiness_gate_properties.py
  tests/test_merge_readiness_gate_public_api.py
)
ruff format "${TEST_FILES[@]}"
ruff check "${TEST_FILES[@]}"
ruff format --check "${TEST_FILES[@]}"
python -m py_compile "${TEST_FILES[@]}"

SOURCE_RED_SHA="$SOURCE_RED_SHA" AST_REPORT="$AST_REPORT" python - <<'PY'
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

paths = (
    "tests/test_merge_readiness_gate.py",
    "tests/test_merge_readiness_gate_properties.py",
    "tests/test_merge_readiness_gate_public_api.py",
)
records = []
for raw in paths:
    before_source = subprocess.check_output(
        ("git", "show", f"{os.environ['SOURCE_RED_SHA']}:{raw}"),
        text=True,
    )
    after_source = Path(raw).read_text(encoding="utf-8")
    before_ast = ast.dump(
        ast.parse(before_source, filename=raw),
        annotate_fields=True,
        include_attributes=False,
    )
    after_ast = ast.dump(
        ast.parse(after_source, filename=raw),
        annotate_fields=True,
        include_attributes=False,
    )
    if before_ast != after_ast:
        raise SystemExit(f"{raw}: Ruff formatting changed parsed AST")
    digest = hashlib.sha256(before_ast.encode("utf-8")).hexdigest()
    records.append(
        {
            "path": raw,
            "source_red_ast_sha256": digest,
            "r4_red_ast_sha256": digest,
            "ast_identical": True,
        }
    )
Path(os.environ["AST_REPORT"]).write_text(
    json.dumps(
        {"schema": "m-head-merge-readiness-red-r4-ast-v1", "paths": records},
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    + "\n",
    encoding="utf-8",
)
PY

git add "${RED_PATHS[@]}"
git diff --cached --check
git commit -m 'test: define R4-based exact-SHA merge readiness RED'
RED_SHA=$(git rev-parse HEAD)
mapfile -t RED_DELTA < <(git diff --name-only "$FEATURE_SHA"...HEAD | sort)
test "${#RED_DELTA[@]}" -eq 4
diff -u <(printf '%s\n' "${RED_PATHS[@]}" | sort) \
  <(printf '%s\n' "${RED_DELTA[@]}")
git push origin HEAD:"refs/heads/$RED_BRANCH"

FEATURE_SHA="$FEATURE_SHA" RED_SHA="$RED_SHA" SUMMARY="$SUMMARY" \
  AST_REPORT="$AST_REPORT" python - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path

summary = {
    "schema": "m-head-merge-readiness-r4-rebase-v1",
    "status": "r4_design_and_red_published_unmerged",
    "repository": "leon36000/NextGen-Memory",
    "parent": {
        "branch": "candidate/exact-sha-review-attestation-registry-v0-r4-20260831",
        "sha": "41b0b104e5a3f06c4d238060ad0fd3dd51dd4446",
    },
    "feature": {
        "branch": "feat/exact-sha-merge-readiness-gate-v0-r4-20260831",
        "sha": os.environ["FEATURE_SHA"],
        "exact_path_count": 2,
    },
    "red": {
        "branch": "tdd/exact-sha-merge-readiness-gate-v0-red-r4-20260831",
        "sha": os.environ["RED_SHA"],
        "exact_path_count": 4,
        "ast_evidence": json.loads(
            Path(os.environ["AST_REPORT"]).read_text(encoding="utf-8")
        ),
    },
    "safety": {
        "implementation_present": False,
        "package_export_present": False,
        "candidate_published": False,
        "merged": False,
        "tests_weakened": False,
        "stubs_added": False,
    },
    "next_action": (
        "Run an independent missing-module RED qualifier against exact R4, "
        "then implement only after RED acceptance."
    ),
}
Path(os.environ["SUMMARY"]).write_text(
    json.dumps(
        summary,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    + "\n",
    encoding="utf-8",
)
print(Path(os.environ["SUMMARY"]).read_text(encoding="utf-8"), end="")
PY

BODY=$(cat <<EOF
## Merge Readiness Gate design and RED rebased on R4

- exact parent: \`$PARENT_SHA\`;
- R4 feature branch: \`$FEATURE_BRANCH\`;
- feature SHA: \`$FEATURE_SHA\`;
- tests-only RED branch: \`$RED_BRANCH\`;
- RED SHA: \`$RED_SHA\`;
- three test ASTs preserved exactly after Ruff formatting;
- product implementation and exports: absent;
- merge allowed: false.
EOF
)
gh api "repos/$REPO/issues/166/comments" --raw-field body="$BODY" >/dev/null
gh api --method PATCH "repos/$REPO/pulls/$SELF_PR" -f state=closed >/dev/null
