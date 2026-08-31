#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 PRODUCT_ROOT MATRIX_ROOT" >&2
  exit 2
fi

PRODUCT_ROOT=$1
MATRIX_ROOT=$2
REPO=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}
RUN_ID=${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}
BASE_SHA='f4f3aca9759b5b7a60691017c2211152c011ea92'
CANDIDATE_SHA='008005072f412ecda1bf461f4e875de72c5b808f'
RED_SHA='849df204e899d7570ef469d52307786cf242695a'
EVIDENCE_BRANCH='evidence/exact-sha-review-attestation-registry-v0-r2-00800507-green-20260830'
EVIDENCE_PATH='evidence/exact-sha-review-attestation-registry-v0-r2-00800507-green-20260830.json'
CHECKPOINT_BRANCH='evidence/exact-sha-review-attestation-registry-v0-r2-00800507-checkpoint-20260830'
CHECKPOINT_PATH='evidence/exact-sha-review-attestation-registry-v0-r2-00800507-checkpoint-20260830.json'

python - "$MATRIX_ROOT" "$BASE_SHA" "$CANDIDATE_SHA" "$RED_SHA" "$RUN_ID" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
base_sha = sys.argv[2]
candidate_sha = sys.argv[3]
red_sha = sys.argv[4]
run_id = int(sys.argv[5])
reports = sorted(root.rglob("verification.json"))
semantics = sorted(root.rglob("semantic.json"))
if len(reports) != 2 or len(semantics) != 2:
    raise SystemExit(
        f"expected two reports/semantics, got reports={len(reports)} semantics={len(semantics)}"
    )
if semantics[0].read_bytes() != semantics[1].read_bytes():
    raise SystemExit("semantic evidence differs across Python versions")
docs = [json.loads(path.read_text(encoding="utf-8")) for path in reports]
versions = {".".join(doc["python_version"].split(".")[:2]) for doc in docs}
if versions != {"3.12", "3.13"}:
    raise SystemExit(f"unexpected Python matrix: {sorted(versions)!r}")
for doc in docs:
    expected = {
        "base_sha": base_sha,
        "candidate_sha": candidate_sha,
        "red_v5_sha": red_sha,
        "exact_path_count": 9,
        "focused_test_count": 61,
        "full_test_count": 515,
        "generated_trace_count": 5000,
        "exact_retry_count": 1000,
        "hash_seed_invariant": True,
        "audit_findings": 0,
        "isolated_wheel_import": True,
    }
    for key, value in expected.items():
        if doc.get(key) != value:
            raise SystemExit(f"verification mismatch {key}: {doc.get(key)!r} != {value!r}")
for key in (
    "semantic_sha256", "focused_test_count", "full_test_count",
    "generated_trace_count", "exact_retry_count", "hash_seed_invariant",
    "audit_findings", "isolated_wheel_import",
):
    if len({json.dumps(doc[key], sort_keys=True) for doc in docs}) != 1:
        raise SystemExit(f"cross-Python drift: {key}")
semantic_raw = semantics[0].read_bytes()
semantic = json.loads(semantic_raw)
expected_states = [
    "pending", "pending", "approved", "evidence_blocked", "blocked",
]
actual_states = [entry["decision"]["state"] for entry in semantic["states"]]
if actual_states != expected_states:
    raise SystemExit(f"semantic state sequence differs: {actual_states!r}")
summary = {
    "schema": "m-head-exact-review-attestation-r2-green-v1",
    "status": "green_review_pending_unmerged",
    "repository": "leon36000/NextGen-Memory",
    "base": {
        "branch": "candidate/advisory-policy-promotion-gate-v0-20260824",
        "sha": base_sha,
    },
    "candidate": {
        "branch": "candidate/exact-sha-review-attestation-registry-v0-r2-20260830",
        "sha": candidate_sha,
        "exact_path_count": 9,
    },
    "qualified_red": {
        "branch": "tdd/exact-sha-review-attestation-registry-v0-red-v5-20260825",
        "sha": red_sha,
        "source_preserved_byte_for_byte": True,
    },
    "verification": {
        "run_id": run_id,
        "python_versions": sorted(doc["python_version"] for doc in docs),
        "focused_test_count_each": 61,
        "full_test_count_each": 515,
        "generated_trace_count_each": 5000,
        "exact_retry_count": 1000,
        "semantic_sha256": hashlib.sha256(semantic_raw).hexdigest(),
        "cross_python_semantic_evidence_identical": True,
        "hash_seed_invariant": True,
        "audit_findings": 0,
        "isolated_wheel_import": True,
        "wheel_sha256_by_python": {
            ".".join(doc["python_version"].split(".")[:2]): doc["wheel_sha256"]
            for doc in docs
        },
    },
    "contract": {
        "pure_in_memory_registry": True,
        "advisory_only": True,
        "states": ["pending", "approved", "evidence_blocked", "blocked"],
        "hard_blocker_precedence": True,
        "exact_request_retry_idempotent": True,
        "exact_attestation_retry_idempotent": True,
        "signature_verification_claim": False,
        "persistence_surface": False,
        "database_or_network_surface": False,
        "merge_surface": False,
        "feedback_write_surface": False,
        "activation_surface": False,
    },
    "review": {
        "required_model": "GPT-5.6 Sol",
        "verdict": "pending",
        "merge_allowed": False,
    },
    "safety": {
        "actual_product_merge_performed": False,
        "merged": False,
        "production_database_contacted": False,
        "production_migration_applied": False,
        "production_application_data_written": False,
        "feedback_written": False,
        "policy_activated": False,
        "release_published": False,
        "tests_weakened": False,
        "stubs_added": False,
        "sol_verdict_fabricated": False,
    },
    "next_action": (
        "Create the canonical product PR and perform an independent GPT-5.6 Sol "
        "review bound to candidate SHA 008005072f412ecda1bf461f4e875de72c5b808f."
    ),
}
(root / "cross-python-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
print((root / "cross-python-summary.json").read_text(encoding="utf-8"), end="")
PY

# Bind live matrix artifact IDs/digests after both uploads completed.
ARTIFACTS=$(gh api --method GET "repos/$REPO/actions/runs/$RUN_ID/artifacts" -f per_page=100)
printf '%s' "$ARTIFACTS" | jq \
  '[.artifacts[] | select(.name | startswith("exact-review-attestation-r2-python-")) | {id,name,digest,expired,size_in_bytes,created_at,expires_at}] | sort_by(.name)' \
  > /tmp/exact-review-r2-artifacts.json
test "$(jq 'length' /tmp/exact-review-r2-artifacts.json)" -eq 2
test "$(jq '[.[] | select(.expired == true)] | length' /tmp/exact-review-r2-artifacts.json)" -eq 0

python - "$MATRIX_ROOT/cross-python-summary.json" /tmp/exact-review-r2-artifacts.json <<'PY'
from __future__ import annotations
import json
import sys
from pathlib import Path
path = Path(sys.argv[1])
summary = json.loads(path.read_text(encoding="utf-8"))
summary["verification"]["artifacts"] = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
path.write_text(
    json.dumps(summary, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY

SUMMARY="$MATRIX_ROOT/cross-python-summary.json"

git -C "$PRODUCT_ROOT" config user.name 'github-actions[bot]'
git -C "$PRODUCT_ROOT" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$PRODUCT_ROOT" fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*'
test "$(git -C "$PRODUCT_ROOT" rev-parse HEAD)" = "$CANDIDATE_SHA"
test "$(git -C "$PRODUCT_ROOT" rev-parse origin/candidate/exact-sha-review-attestation-registry-v0-r2-20260830)" = "$CANDIDATE_SHA"

if git -C "$PRODUCT_ROOT" ls-remote --exit-code --heads origin "$EVIDENCE_BRANCH" >/dev/null 2>&1; then
  git -C "$PRODUCT_ROOT" switch --detach "origin/$EVIDENCE_BRANCH"
  cmp "$SUMMARY" "$PRODUCT_ROOT/$EVIDENCE_PATH"
else
  git -C "$PRODUCT_ROOT" switch -C "$EVIDENCE_BRANCH" "$CANDIDATE_SHA"
  mkdir -p "$PRODUCT_ROOT/evidence"
  cp "$SUMMARY" "$PRODUCT_ROOT/$EVIDENCE_PATH"
  git -C "$PRODUCT_ROOT" add "$EVIDENCE_PATH"
  git -C "$PRODUCT_ROOT" diff --cached --check
  git -C "$PRODUCT_ROOT" commit -m 'evidence: certify exact review attestation registry R2'
  git -C "$PRODUCT_ROOT" push origin HEAD:"refs/heads/$EVIDENCE_BRANCH"
fi
EVIDENCE_COMMIT=$(git -C "$PRODUCT_ROOT" rev-parse HEAD)

python - "$SUMMARY" /tmp/exact-review-r2-checkpoint.json "$EVIDENCE_COMMIT" <<'PY'
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
summary_path = Path(sys.argv[1])
raw = summary_path.read_bytes()
summary = json.loads(raw)
checkpoint = {
    "checkpoint_key": "m-head:exact-sha-review-attestation-registry-v0:r2-green:00800507",
    "status": summary["status"],
    "repository": summary["repository"],
    "evidence_branch": "evidence/exact-sha-review-attestation-registry-v0-r2-00800507-green-20260830",
    "evidence_commit": sys.argv[2],
    "evidence_sha256": hashlib.sha256(raw).hexdigest(),
    "base": summary["base"],
    "candidate": summary["candidate"],
    "qualified_red": summary["qualified_red"],
    "verification": summary["verification"],
    "contract": summary["contract"],
    "review": summary["review"],
    "safety": summary["safety"],
    "next_action": summary["next_action"],
}
Path(sys.argv[2] if False else "/tmp/exact-review-r2-checkpoint.json").write_text(
    json.dumps(checkpoint, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY

if git -C "$PRODUCT_ROOT" ls-remote --exit-code --heads origin "$CHECKPOINT_BRANCH" >/dev/null 2>&1; then
  git -C "$PRODUCT_ROOT" switch --detach "origin/$CHECKPOINT_BRANCH"
  cmp /tmp/exact-review-r2-checkpoint.json "$PRODUCT_ROOT/$CHECKPOINT_PATH"
else
  git -C "$PRODUCT_ROOT" switch -C "$CHECKPOINT_BRANCH" "$EVIDENCE_COMMIT"
  cp /tmp/exact-review-r2-checkpoint.json "$PRODUCT_ROOT/$CHECKPOINT_PATH"
  git -C "$PRODUCT_ROOT" add "$CHECKPOINT_PATH"
  git -C "$PRODUCT_ROOT" diff --cached --check
  git -C "$PRODUCT_ROOT" commit -m 'evidence: checkpoint exact review attestation registry R2'
  git -C "$PRODUCT_ROOT" push origin HEAD:"refs/heads/$CHECKPOINT_BRANCH"
fi
CHECKPOINT_COMMIT=$(git -C "$PRODUCT_ROOT" rev-parse HEAD)

BODY=$(cat <<EOF
## Exact-SHA Review Attestation Registry v0 R2 verification GREEN

- base: \`$BASE_SHA\`;
- candidate: \`$CANDIDATE_SHA\` on \`candidate/exact-sha-review-attestation-registry-v0-r2-20260830\`;
- qualified RED v5: \`$RED_SHA\`, byte-preserved;
- exact surface: nine paths;
- Python 3.12/3.13: 61 focused + 515 full tests each;
- generated traces: 5,000 each;
- exact retries: 1,000;
- cross-Python semantic evidence: byte-identical;
- audit findings: 0;
- isolated wheel import: green;
- evidence: \`$EVIDENCE_BRANCH\` at \`$EVIDENCE_COMMIT\`;
- checkpoint: \`$CHECKPOINT_BRANCH\` at \`$CHECKPOINT_COMMIT\`;
- review verdict: pending; merge allowed: false.
EOF
)
gh api "repos/$REPO/issues/165/comments" --raw-field body="$BODY" >/dev/null
printf 'evidence_commit=%s\ncheckpoint_commit=%s\n' "$EVIDENCE_COMMIT" "$CHECKPOINT_COMMIT"
