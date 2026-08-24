#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 PRODUCT_ROOT DOWNLOAD_ROOT CANDIDATE_SHA BASE_SHA" >&2
  exit 2
fi

PRODUCT_ROOT=$1
DOWNLOAD_ROOT=$2
CANDIDATE_SHA=$3
BASE_SHA=$4
REPO=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}
RUN_ID=${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}

python - "$DOWNLOAD_ROOT" "$CANDIDATE_SHA" "$BASE_SHA" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
candidate_sha = sys.argv[2]
base_sha = sys.argv[3]
reports = sorted(root.rglob("verification.json"))
semantics = sorted(root.rglob("semantic.json"))
wheels = sorted(root.rglob("*.whl"))
if len(reports) != 2:
    raise SystemExit(f"expected two verification reports, found {len(reports)}")
if len(semantics) != 2:
    raise SystemExit(f"expected two semantic documents, found {len(semantics)}")
if len(wheels) != 2:
    raise SystemExit(f"expected two wheel files, found {len(wheels)}")
if semantics[0].read_bytes() != semantics[1].read_bytes():
    raise SystemExit("semantic evidence differs across Python versions")
documents = [json.loads(path.read_text(encoding="utf-8")) for path in reports]
versions = {".".join(doc["python_version"].split(".")[:2]) for doc in documents}
if versions != {"3.12", "3.13"}:
    raise SystemExit(f"unexpected Python evidence set: {sorted(versions)!r}")
for document in documents:
    if document.get("schema") != "m-head-advisory-policy-promotion-verification-v1":
        raise SystemExit("verification schema differs")
    if document.get("candidate_sha") != candidate_sha:
        raise SystemExit("candidate SHA drift")
    if document.get("base_sha") != base_sha:
        raise SystemExit("base SHA drift")
    if document.get("focused_test_count") != 61:
        raise SystemExit("focused test count differs")
    if document.get("full_test_count") != 454:
        raise SystemExit("full test count differs")
    if document.get("exact_path_count") != 8:
        raise SystemExit("exact path count differs")
    if document.get("hash_seed_invariant") is not True:
        raise SystemExit("hash-seed invariance is absent")
    if document.get("exact_retry_count") != 1000:
        raise SystemExit("exact retry evidence differs")
    if document.get("audit_findings") != 0:
        raise SystemExit("audit findings are nonzero")
    if document.get("isolated_wheel_import") is not True:
        raise SystemExit("isolated wheel import is absent")
for key in (
    "focused_test_count",
    "full_test_count",
    "exact_path_count",
    "semantic_sha256",
    "hash_seed_invariant",
    "exact_retry_count",
    "audit_findings",
    "isolated_wheel_import",
):
    values = {json.dumps(document[key], sort_keys=True) for document in documents}
    if len(values) != 1:
        raise SystemExit(f"cross-Python verification drift: {key}")

semantic = json.loads(semantics[0].read_text(encoding="utf-8"))
if semantic.get("candidate_sha") != candidate_sha:
    raise SystemExit("semantic candidate SHA drift")
if semantic.get("base_sha") != base_sha:
    raise SystemExit("semantic base SHA drift")
if semantic.get("retry_count") != 1000:
    raise SystemExit("semantic retry count differs")
expected_decisions = {
    "hold_cancelled": "hold",
    "hold_failed": "hold",
    "promote": "promote",
    "reject_safety": "reject",
}
actual_decisions = {
    name: record["decision"]
    for name, record in semantic["records"].items()
}
if actual_decisions != expected_decisions:
    raise SystemExit(f"decision matrix differs: {actual_decisions!r}")
for name in ("hold_cancelled", "hold_failed"):
    if "registry_incomplete" not in semantic["records"][name]["reasons"]:
        raise SystemExit(f"{name} lacks registry_incomplete")
if semantic["records"]["reject_safety"]["reasons"] != ["safety_violation"]:
    raise SystemExit("hard-reject precedence differs")
if semantic["records"]["promote"]["reasons"] != ["all_gates_passed"]:
    raise SystemExit("promote reasons differ")

summary = {
    "schema": "m-head-advisory-policy-promotion-green-v1",
    "status": "green_review_pending_unmerged",
    "repository": "leon36000/NextGen-Memory",
    "base": {
        "branch": "candidate/paired-replay-experiment-registry-v0-20260824",
        "sha": base_sha,
    },
    "candidate": {
        "branch": "candidate/advisory-policy-promotion-gate-v0-20260824",
        "sha": candidate_sha,
        "exact_path_count": 8,
        "paths": [
            "docs/policy-promotion-gate-v0-red.md",
            "docs/superpowers/plans/2026-08-24-advisory-policy-promotion-gate-v0.md",
            "docs/superpowers/specs/2026-08-24-advisory-policy-promotion-gate-v0-design.md",
            "src/nextgen_memory/__init__.py",
            "src/nextgen_memory/policy_promotion_gate.py",
            "tests/test_policy_promotion_gate.py",
            "tests/test_policy_promotion_gate_properties.py",
            "tests/test_policy_promotion_gate_public_api.py",
        ],
    },
    "tdd": {
        "original_red_branch": "tdd/advisory-policy-promotion-gate-v0-red-20260824",
        "original_red_sha": "75540537f84a2a8bfed191d192c80f33ea81e112",
        "qualified_red_branch": "tdd/advisory-policy-promotion-gate-v0-red-v4-20260824",
        "qualified_red_sha": "99eaf5de73ac98d0490183e6772d7ffa36fb8e6a",
        "semantic_red_green": [
            "nonnegative_token_and_latency_thresholds",
            "failed_or_cancelled_registry_pairs_hold",
        ],
    },
    "verification": {
        "python_versions": ["3.12", "3.13"],
        "focused_test_count_each": documents[0]["focused_test_count"],
        "full_test_count_each": documents[0]["full_test_count"],
        "semantic_sha256": documents[0]["semantic_sha256"],
        "cross_python_semantic_evidence_identical": True,
        "hash_seed_invariant": True,
        "exact_retry_count": 1000,
        "audit_findings": 0,
        "isolated_wheel_import": True,
        "wheel_sha256_by_python": {
            ".".join(document["python_version"].split(".")[:2]): document["wheel_sha256"]
            for document in documents
        },
    },
    "contract": {
        "advisory_only": True,
        "decisions": ["promote", "hold", "reject"],
        "hard_rejection_precedence": True,
        "failed_registry_pair_blocks_promotion": True,
        "cancelled_registry_pair_blocks_promotion": True,
        "cost_thresholds_nonnegative": True,
        "automatic_policy_activation": False,
        "persistence_surface": False,
        "database_or_network_surface": False,
        "feedback_write_surface": False,
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
        "production_application_data_written": False,
        "feedback_written": False,
        "policy_activated": False,
        "release_published": False,
        "corrective_retrieval_changed": False,
        "tests_weakened": False,
        "stubs_added": False,
        "sol_verdict_fabricated": False,
    },
}
(root / "cross-python-summary.json").write_text(
    json.dumps(
        summary,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n",
    encoding="utf-8",
)
print((root / "cross-python-summary.json").read_text(encoding="utf-8"), end="")
PY

ARTIFACTS=$(gh api --method GET "repos/$REPO/actions/runs/$RUN_ID/artifacts" -f per_page=100)
printf '%s' "$ARTIFACTS" | jq \
  '[.artifacts[] | select(.name | startswith("advisory-policy-promotion-python-")) | {id,name,digest,expired,size_in_bytes,created_at,expires_at}] | sort_by(.name)' \
  > /tmp/advisory-promotion-artifacts.json
test "$(jq 'length' /tmp/advisory-promotion-artifacts.json)" -eq 2
test "$(jq '[.[] | select(.expired == true)] | length' /tmp/advisory-promotion-artifacts.json)" -eq 0
test "$(jq '[.[] | select((.digest | type) != "string" or (.size_in_bytes | type) != "number")] | length' /tmp/advisory-promotion-artifacts.json)" -eq 0

python - "$DOWNLOAD_ROOT/cross-python-summary.json" /tmp/advisory-promotion-artifacts.json "$RUN_ID" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
artifacts = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
run_id = int(sys.argv[3])
summary = json.loads(summary_path.read_text(encoding="utf-8"))
summary["verification"]["run_id"] = run_id
summary["verification"]["artifacts"] = artifacts
summary_path.write_text(
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

SUMMARY="$DOWNLOAD_ROOT/cross-python-summary.json"
EVIDENCE_BRANCH='evidence/advisory-policy-promotion-gate-v0-f4f3aca9-green-20260824'
EVIDENCE_PATH='evidence/advisory-policy-promotion-gate-v0-f4f3aca9-green-20260824.json'
CHECKPOINT_BRANCH='evidence/advisory-policy-promotion-gate-v0-f4f3aca9-checkpoint-20260824'
CHECKPOINT_PATH='evidence/advisory-policy-promotion-gate-v0-f4f3aca9-checkpoint-20260824.json'

git -C "$PRODUCT_ROOT" config user.name 'github-actions[bot]'
git -C "$PRODUCT_ROOT" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$PRODUCT_ROOT" fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*'

if git -C "$PRODUCT_ROOT" ls-remote --exit-code --heads origin "$EVIDENCE_BRANCH"; then
  git -C "$PRODUCT_ROOT" switch --detach "origin/$EVIDENCE_BRANCH"
  cmp "$SUMMARY" "$PRODUCT_ROOT/$EVIDENCE_PATH"
else
  git -C "$PRODUCT_ROOT" switch -C "$EVIDENCE_BRANCH" "$CANDIDATE_SHA"
  mkdir -p "$PRODUCT_ROOT/evidence"
  cp "$SUMMARY" "$PRODUCT_ROOT/$EVIDENCE_PATH"
  git -C "$PRODUCT_ROOT" add "$EVIDENCE_PATH"
  git -C "$PRODUCT_ROOT" diff --cached --check
  git -C "$PRODUCT_ROOT" commit -m 'evidence: certify advisory policy promotion gate v0'
  git -C "$PRODUCT_ROOT" push origin HEAD:"refs/heads/$EVIDENCE_BRANCH"
fi
EVIDENCE_COMMIT=$(git -C "$PRODUCT_ROOT" rev-parse HEAD)

python - "$SUMMARY" /tmp/advisory-promotion-checkpoint.json "$EVIDENCE_BRANCH" "$EVIDENCE_COMMIT" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
destination = Path(sys.argv[2])
evidence_branch = sys.argv[3]
evidence_commit = sys.argv[4]
raw = summary_path.read_bytes()
summary = json.loads(raw)
checkpoint = {
    "checkpoint_key": "m-head:advisory-policy-promotion-gate-v0:green-readback:f4f3aca9",
    "status": summary["status"],
    "repository": summary["repository"],
    "evidence_branch": evidence_branch,
    "evidence_commit": evidence_commit,
    "evidence_sha256": hashlib.sha256(raw).hexdigest(),
    "base": summary["base"],
    "candidate": summary["candidate"],
    "tdd": summary["tdd"],
    "verification": summary["verification"],
    "contract": summary["contract"],
    "review": summary["review"],
    "safety": summary["safety"],
    "next_action": (
        "Create the exact immutable candidate PR, obtain a genuine GPT-5.6 Sol "
        "verdict bound to f4f3aca9759b5b7a60691017c2211152c011ea92, "
        "and keep merge, deployment, feedback, activation, and release separate."
    ),
}
destination.write_text(
    json.dumps(
        checkpoint,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n",
    encoding="utf-8",
)
PY

if git -C "$PRODUCT_ROOT" ls-remote --exit-code --heads origin "$CHECKPOINT_BRANCH"; then
  git -C "$PRODUCT_ROOT" switch --detach "origin/$CHECKPOINT_BRANCH"
  cmp /tmp/advisory-promotion-checkpoint.json "$PRODUCT_ROOT/$CHECKPOINT_PATH"
else
  git -C "$PRODUCT_ROOT" switch -C "$CHECKPOINT_BRANCH" "$EVIDENCE_COMMIT"
  cp /tmp/advisory-promotion-checkpoint.json "$PRODUCT_ROOT/$CHECKPOINT_PATH"
  git -C "$PRODUCT_ROOT" add "$CHECKPOINT_PATH"
  git -C "$PRODUCT_ROOT" diff --cached --check
  git -C "$PRODUCT_ROOT" commit -m 'evidence: checkpoint advisory policy promotion gate v0'
  git -C "$PRODUCT_ROOT" push origin HEAD:"refs/heads/$CHECKPOINT_BRANCH"
fi
CHECKPOINT_COMMIT=$(git -C "$PRODUCT_ROOT" rev-parse HEAD)

BODY=$(cat <<EOF
## Advisory Policy Promotion Gate v0 exact matrix GREEN

- base: \`$BASE_SHA\`;
- immutable candidate: \`$CANDIDATE_SHA\`;
- Python 3.12/3.13 exact matrix: success;
- focused tests: 61 per Python;
- full tests: 454 per Python;
- cross-Python semantic evidence: byte-identical;
- exact retries: 1,000;
- failed/cancelled registry states: HOLD;
- negative token/latency thresholds: rejected;
- audit and isolated wheel import: green;
- evidence: \`$EVIDENCE_BRANCH\` at \`$EVIDENCE_COMMIT\`;
- checkpoint: \`$CHECKPOINT_BRANCH\` at \`$CHECKPOINT_COMMIT\`;
- merge allowed: false; exact-SHA GPT-5.6 Sol verdict pending;
- merge, deployment, feedback, activation, migration, and release: none.
EOF
)
gh api "repos/$REPO/issues/23/comments" --raw-field body="$BODY" >/dev/null

cp "$SUMMARY" "$DOWNLOAD_ROOT/publish-summary.json"
printf 'evidence_branch=%s\nevidence_commit=%s\ncheckpoint_branch=%s\ncheckpoint_commit=%s\n' \
  "$EVIDENCE_BRANCH" "$EVIDENCE_COMMIT" "$CHECKPOINT_BRANCH" "$CHECKPOINT_COMMIT"
