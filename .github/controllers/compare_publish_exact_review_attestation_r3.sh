#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 6 ]]; then
  echo "usage: $0 PRODUCT_ROOT DOWNLOAD_ROOT CANDIDATE_SHA BASE_SHA R2_SHA RED_SHA" >&2
  exit 2
fi

PRODUCT_ROOT=$1
DOWNLOAD_ROOT=$2
CANDIDATE_SHA=$3
BASE_SHA=$4
R2_SHA=$5
RED_SHA=$6
REPO=${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}
RUN_ID=${GITHUB_RUN_ID:?GITHUB_RUN_ID is required}

python - "$DOWNLOAD_ROOT" "$CANDIDATE_SHA" "$BASE_SHA" "$R2_SHA" "$RED_SHA" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
candidate_sha, base_sha, r2_sha, red_sha = sys.argv[2:]
manifests = sorted(root.rglob("manifest.json"))
semantics = sorted(root.rglob("semantic.json"))
wheels = sorted(root.rglob("*.whl"))
if len(manifests) != 2:
    raise SystemExit(f"expected two manifests, found {len(manifests)}")
if len(semantics) != 2:
    raise SystemExit(f"expected two semantic documents, found {len(semantics)}")
if len(wheels) != 2:
    raise SystemExit(f"expected two wheels, found {len(wheels)}")
if semantics[0].read_bytes() != semantics[1].read_bytes():
    raise SystemExit("cross-Python semantic evidence differs")
documents = [json.loads(path.read_text(encoding="utf-8")) for path in manifests]
versions = {".".join(document["python_version"].split(".")[:2]) for document in documents}
if versions != {"3.12", "3.13"}:
    raise SystemExit(f"unexpected Python versions: {sorted(versions)!r}")
for document in documents:
    expected = {
        "base_sha": base_sha,
        "r2_sha": r2_sha,
        "red_sha": red_sha,
        "candidate_sha": candidate_sha,
        "exact_path_count": 9,
        "adversarial_test_count": 6,
        "focused_test_count": 67,
        "full_test_count": 521,
        "generated_trace_count": 5_000,
        "exact_retry_count": 1_000,
        "hash_seed_invariant": True,
        "audit_findings": 0,
        "isolated_wheel_import": True,
    }
    for key, value in expected.items():
        if document.get(key) != value:
            raise SystemExit(
                f"manifest {document.get('python_version')} differs for {key}: "
                f"{document.get(key)!r} != {value!r}"
            )
    privacy = document.get("privacy_hardening", {})
    if privacy != {
        "iteration_exceptions_sanitized": True,
        "exact_contract_types": True,
        "primitive_subclasses_rejected": True,
        "exception_context_absent": True,
    }:
        raise SystemExit("privacy hardening manifest differs")
    safety = document.get("safety", {})
    if any(safety.get(key) is not False for key in safety):
        raise SystemExit("a safety field is not false")
for key in (
    "base_sha",
    "r2_sha",
    "red_sha",
    "candidate_sha",
    "exact_path_count",
    "adversarial_test_count",
    "focused_test_count",
    "full_test_count",
    "generated_trace_count",
    "exact_retry_count",
    "hash_seed_invariant",
    "semantic_sha256",
    "audit_findings",
    "isolated_wheel_import",
    "privacy_hardening",
):
    values = {json.dumps(document[key], sort_keys=True) for document in documents}
    if len(values) != 1:
        raise SystemExit(f"cross-Python manifest drift: {key}")

semantic = json.loads(semantics[0].read_text(encoding="utf-8"))
if semantic.get("schema") != "m-head-exact-review-attestation-r3-semantic-v1":
    raise SystemExit("semantic schema differs")
if semantic.get("candidate_sha") != candidate_sha or semantic.get("base_sha") != base_sha:
    raise SystemExit("semantic exact-SHA binding differs")
if semantic.get("exact_retry_count") != 1_000:
    raise SystemExit("semantic retry count differs")
expected_states = {
    "pending": "pending",
    "approved": "approved",
    "evidence_blocked": "evidence_blocked",
    "blocked": "blocked",
}
actual_states = {
    name: payload["decision"]["state"]
    for name, payload in semantic.get("states", {}).items()
}
if actual_states != expected_states:
    raise SystemExit(f"semantic decision matrix differs: {actual_states!r}")
privacy = semantic.get("privacy", {})
if privacy != {
    "iterator_error": "trusted reviewers must be a bounded iterable",
    "exception_context_absent": True,
    "hostile_subclasses_rejected": True,
}:
    raise SystemExit("semantic privacy evidence differs")

summary = {
    "schema": "m-head-exact-review-attestation-r3-green-v1",
    "status": "green_review_pending_unmerged",
    "repository": "leon36000/NextGen-Memory",
    "base": {
        "branch": "candidate/advisory-policy-promotion-gate-v0-20260824",
        "sha": base_sha,
    },
    "parent_candidate": {
        "branch": "candidate/exact-sha-review-attestation-registry-v0-r2-20260826",
        "sha": r2_sha,
    },
    "adversarial_red": {
        "branch": "tdd/exact-sha-review-attestation-registry-v0-adversarial-red-20260826",
        "sha": red_sha,
        "failure_count": 6,
        "existing_pass_count": 55,
    },
    "candidate": {
        "branch": "candidate/exact-sha-review-attestation-registry-v0-r3-20260829",
        "sha": candidate_sha,
        "pull_request": 185,
        "exact_path_count": 9,
    },
    "verification": {
        "python_versions": sorted(versions),
        "adversarial_tests_each": 6,
        "focused_tests_each": 67,
        "full_tests_each": 521,
        "generated_traces_each": 5_000,
        "exact_retries_each": 1_000,
        "hash_seed_invariant": True,
        "cross_python_semantic_evidence_identical": True,
        "semantic_sha256": documents[0]["semantic_sha256"],
        "audit_findings": 0,
        "isolated_wheel_import": True,
        "wheel_sha256_by_python": {
            ".".join(document["python_version"].split(".")[:2]): document["wheel_sha256"]
            for document in documents
        },
    },
    "privacy_hardening": {
        "iteration_exceptions_sanitized": True,
        "exception_cause_and_context_absent": True,
        "reviewer_subclasses_rejected": True,
        "request_subclasses_rejected_before_mutation": True,
        "attestation_subclasses_rejected_before_mutation": True,
        "primitive_subclasses_rejected_before_overridden_behavior": True,
    },
    "contract": {
        "pure_in_memory_registry": True,
        "advisory_only": True,
        "states": ["pending", "approved", "evidence_blocked", "blocked"],
        "hard_blocker_precedence": True,
        "exact_retry_idempotent": True,
        "signature_verification_claim": False,
        "persistence_surface": False,
        "database_or_network_surface": False,
        "merge_surface": False,
    },
    "review": {
        "reviewer_runtime": "GPT-5.6 Pro",
        "verdict": "pending_independent_exact_sha_review",
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
  '[.artifacts[] | select(.name | startswith("exact-review-attestation-r3-python-")) | {id,name,digest,expired,size_in_bytes,created_at,expires_at}] | sort_by(.name)' \
  > /tmp/exact-review-attestation-r3-artifacts.json
test "$(jq 'length' /tmp/exact-review-attestation-r3-artifacts.json)" -eq 2
test "$(jq '[.[] | select(.expired == true)] | length' /tmp/exact-review-attestation-r3-artifacts.json)" -eq 0
test "$(jq '[.[] | select((.digest | type) != "string" or (.size_in_bytes | type) != "number")] | length' /tmp/exact-review-attestation-r3-artifacts.json)" -eq 0

python - "$DOWNLOAD_ROOT/cross-python-summary.json" \
  /tmp/exact-review-attestation-r3-artifacts.json "$RUN_ID" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
summary = json.loads(summary_path.read_text(encoding="utf-8"))
summary["verification"]["run_id"] = int(sys.argv[3])
summary["verification"]["artifacts"] = json.loads(
    Path(sys.argv[2]).read_text(encoding="utf-8")
)
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
EVIDENCE_BRANCH='evidence/exact-review-attestation-registry-v0-f4d9388c-green-20260829'
EVIDENCE_PATH='evidence/exact-review-attestation-registry-v0-f4d9388c-green-20260829.json'
CHECKPOINT_BRANCH='evidence/exact-review-attestation-registry-v0-f4d9388c-checkpoint-20260829'
CHECKPOINT_PATH='evidence/exact-review-attestation-registry-v0-f4d9388c-checkpoint-20260829.json'

git -C "$PRODUCT_ROOT" config user.name 'github-actions[bot]'
git -C "$PRODUCT_ROOT" config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git -C "$PRODUCT_ROOT" fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*'

if git -C "$PRODUCT_ROOT" ls-remote --exit-code --heads origin "$EVIDENCE_BRANCH" >/dev/null; then
  git -C "$PRODUCT_ROOT" switch --detach "origin/$EVIDENCE_BRANCH"
  cmp "$SUMMARY" "$PRODUCT_ROOT/$EVIDENCE_PATH"
else
  git -C "$PRODUCT_ROOT" switch -C "$EVIDENCE_BRANCH" "$CANDIDATE_SHA"
  mkdir -p "$PRODUCT_ROOT/evidence"
  cp "$SUMMARY" "$PRODUCT_ROOT/$EVIDENCE_PATH"
  git -C "$PRODUCT_ROOT" add "$EVIDENCE_PATH"
  git -C "$PRODUCT_ROOT" diff --cached --check
  git -C "$PRODUCT_ROOT" commit -m 'evidence: certify exact review attestation privacy r3'
  git -C "$PRODUCT_ROOT" push origin HEAD:"refs/heads/$EVIDENCE_BRANCH"
fi
EVIDENCE_COMMIT=$(git -C "$PRODUCT_ROOT" rev-parse HEAD)

python - "$SUMMARY" /tmp/exact-review-attestation-r3-checkpoint.json \
  "$EVIDENCE_BRANCH" "$EVIDENCE_COMMIT" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

summary_path = Path(sys.argv[1])
raw = summary_path.read_bytes()
summary = json.loads(raw)
checkpoint = {
    "checkpoint_key": "m-head:exact-sha-review-attestation-registry-v0:r3-green:f4d9388c:20260829",
    "status": summary["status"],
    "repository": summary["repository"],
    "evidence_branch": sys.argv[3],
    "evidence_commit": sys.argv[4],
    "evidence_sha256": hashlib.sha256(raw).hexdigest(),
    "base": summary["base"],
    "parent_candidate": summary["parent_candidate"],
    "adversarial_red": summary["adversarial_red"],
    "candidate": summary["candidate"],
    "verification": summary["verification"],
    "privacy_hardening": summary["privacy_hardening"],
    "contract": summary["contract"],
    "review": summary["review"],
    "safety": summary["safety"],
    "next_action": (
        "Perform a fresh independent exact-SHA technical review of PR #185. "
        "Any candidate movement invalidates all evidence. Merge, migration, "
        "deployment, feedback, activation, and release remain separate."
    ),
}
Path(sys.argv[2]).write_text(
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

if git -C "$PRODUCT_ROOT" ls-remote --exit-code --heads origin "$CHECKPOINT_BRANCH" >/dev/null; then
  git -C "$PRODUCT_ROOT" switch --detach "origin/$CHECKPOINT_BRANCH"
  cmp /tmp/exact-review-attestation-r3-checkpoint.json \
    "$PRODUCT_ROOT/$CHECKPOINT_PATH"
else
  git -C "$PRODUCT_ROOT" switch -C "$CHECKPOINT_BRANCH" "$EVIDENCE_COMMIT"
  cp /tmp/exact-review-attestation-r3-checkpoint.json \
    "$PRODUCT_ROOT/$CHECKPOINT_PATH"
  git -C "$PRODUCT_ROOT" add "$CHECKPOINT_PATH"
  git -C "$PRODUCT_ROOT" diff --cached --check
  git -C "$PRODUCT_ROOT" commit -m 'evidence: checkpoint exact review attestation privacy r3'
  git -C "$PRODUCT_ROOT" push origin HEAD:"refs/heads/$CHECKPOINT_BRANCH"
fi
CHECKPOINT_COMMIT=$(git -C "$PRODUCT_ROOT" rev-parse HEAD)

BODY=$(cat <<EOF
## Exact-SHA Review Attestation Registry r3 independent matrix GREEN

- candidate: \`$CANDIDATE_SHA\`;
- Python 3.12/3.13: success;
- adversarial tests: 6 per Python;
- focused tests: 67 per Python;
- full tests: 521 per Python;
- generated traces: 5,000 per Python;
- exact retries: 1,000 per Python;
- cross-Python semantic evidence: byte-identical;
- audit findings: 0;
- isolated wheels: green;
- evidence: \`$EVIDENCE_BRANCH\` at \`$EVIDENCE_COMMIT\`;
- checkpoint: \`$CHECKPOINT_BRANCH\` at \`$CHECKPOINT_COMMIT\`;
- independent exact-SHA review: pending;
- merge allowed: false.
EOF
)
gh api "repos/$REPO/issues/165/comments" --raw-field body="$BODY" >/dev/null
gh api "repos/$REPO/issues/185/comments" --raw-field body="$BODY" >/dev/null
cp "$SUMMARY" "$DOWNLOAD_ROOT/publish-summary.json"
printf 'evidence_commit=%s\ncheckpoint_commit=%s\n' \
  "$EVIDENCE_COMMIT" "$CHECKPOINT_COMMIT"
