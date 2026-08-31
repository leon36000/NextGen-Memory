#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 PRODUCT_ROOT EVIDENCE_ROOT" >&2
  exit 2
fi

PRODUCT_ROOT=$1
EVIDENCE_ROOT=$2
BASE_SHA='f4f3aca9759b5b7a60691017c2211152c011ea92'
CANDIDATE_SHA='008005072f412ecda1bf461f4e875de72c5b808f'
RED_SHA='849df204e899d7570ef469d52307786cf242695a'
export BASE_SHA CANDIDATE_SHA RED_SHA EVIDENCE_ROOT
mkdir -p "$EVIDENCE_ROOT"
cd "$PRODUCT_ROOT"

run() {
  printf '+ %q ' "$@"
  printf '\n'
  "$@"
}

# Exact immutable graph and product surface.
test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"
test "$(git merge-base HEAD "$BASE_SHA")" = "$BASE_SHA"
mapfile -t CHANGED < <(git diff --name-only "$BASE_SHA"...HEAD | sort)
EXPECTED=(
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
test "${#CHANGED[@]}" -eq "${#EXPECTED[@]}"
diff -u <(printf '%s\n' "${EXPECTED[@]}" | sort) <(printf '%s\n' "${CHANGED[@]}")
test -z "$(git diff --name-only "$BASE_SHA"...HEAD -- '.github/workflows/**' 'migrations/**' pyproject.toml 'src/nextgen_memory/corrective_retrieval_*')"
run git diff --check "$BASE_SHA"...HEAD

# Qualified RED v5 sources must survive byte-for-byte in the candidate.
RED_PATHS=(
  docs/exact-sha-review-attestation-registry-v0-red.md
  tests/test_review_attestation_registry.py
  tests/test_review_attestation_registry_properties.py
  tests/test_review_attestation_registry_public_api.py
)
for path in "${RED_PATHS[@]}"; do
  reference="$RUNNER_TEMP/red-v5-$(basename "$path")"
  git show "$RED_SHA:$path" > "$reference"
  cmp "$reference" "$path"
done

run python -m pip install -e '.[dev]'
run python -m pip install 'ruff==0.16.4'
run ruff --version
run ruff check .
run ruff format --check \
  src/nextgen_memory/__init__.py \
  src/nextgen_memory/review_attestation_registry.py \
  tests/test_review_attestation_registry.py \
  tests/test_review_attestation_registry_properties.py \
  tests/test_review_attestation_registry_public_api.py
run python -m compileall -q src scripts

FOCUSED=(
  tests/test_review_attestation_registry.py
  tests/test_review_attestation_registry_properties.py
  tests/test_review_attestation_registry_public_api.py
)
run python -m pytest -q "${FOCUSED[@]}" | tee /tmp/exact-review-r2-focused.txt
run python -m pytest -q | tee /tmp/exact-review-r2-full.txt

python - <<'PY'
from __future__ import annotations

import re
from pathlib import Path


def passed(path: str) -> int:
    values = re.findall(r"(\d+) passed", Path(path).read_text(encoding="utf-8"))
    if not values:
        raise SystemExit(f"missing pytest pass count: {path}")
    return int(values[-1])

focused = passed("/tmp/exact-review-r2-focused.txt")
full = passed("/tmp/exact-review-r2-full.txt")
if focused != 61:
    raise SystemExit(f"focused test count drift: {focused} != 61")
if full != 515:
    raise SystemExit(f"full test count drift: {full} != 515")
print(f"focused_test_count={focused} full_test_count={full}")
PY

# Strict product audit: standard-library-only, no I/O/clock/randomness/workers,
# no executable stubs, no test weakening, no sensitive/free-form surfaces.
python - <<'PY'
from __future__ import annotations

import ast
from pathlib import Path

module_path = Path("src/nextgen_memory/review_attestation_registry.py")
source = module_path.read_text(encoding="utf-8")
tree = ast.parse(source, filename=str(module_path))
allowed_roots = {
    "__future__", "collections", "dataclasses", "enum", "hashlib",
    "itertools", "json", "re", "uuid",
}
forbidden_calls = {
    "eval", "exec", "compile", "open", "sleep", "system", "urlopen",
    "uuid1", "uuid4", "write_bytes", "write_text",
}
findings: list[str] = []
for node in ast.walk(tree):
    if isinstance(node, ast.Pass):
        findings.append(f"{node.lineno}:pass")
    elif (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and node.value.value is Ellipsis
    ):
        findings.append(f"{node.lineno}:executable_ellipsis")
    elif isinstance(node, ast.Raise):
        target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if isinstance(target, ast.Name) and target.id == "NotImplementedError":
            findings.append(f"{node.lineno}:NotImplementedError")
    elif isinstance(node, ast.Import):
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root not in allowed_roots:
                findings.append(f"{node.lineno}:import:{alias.name}")
    elif isinstance(node, ast.ImportFrom):
        root = (node.module or "").split(".", 1)[0]
        if node.level == 0 and root not in allowed_roots:
            findings.append(f"{node.lineno}:import:{node.module}")
    elif isinstance(node, ast.Call):
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        if name in forbidden_calls:
            findings.append(f"{node.lineno}:call:{name}")

lowered = source.lower()
for marker in (
    "postgresql://", "mongodb://", "http://", "https://", "password",
    "credential", "raw_query", "raw_prompt", "response_text", "memory_body",
    "reviewer_email", "reviewer_name", "merge_pull_request", "activate_policy(",
    "write_feedback(", "# todo", "# fixme",
):
    if marker in lowered:
        findings.append(f"text:{marker}")
for path in map(Path, (
    "tests/test_review_attestation_registry.py",
    "tests/test_review_attestation_registry_properties.py",
    "tests/test_review_attestation_registry_public_api.py",
)):
    text = path.read_text(encoding="utf-8").lower()
    for marker in ("pytest.mark.skip", "pytest.mark.xfail", "# noqa"):
        if marker in text:
            findings.append(f"{path}:text:{marker}")
if findings:
    raise SystemExit("\n".join(findings))
print("exact_review_attestation_r2_audit_findings=0")
PY

# Deterministic semantic evidence with 1,000 exact retries and two hash seeds.
cat > /tmp/generate_exact_review_r2_semantics.py <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from nextgen_memory import (
    ExactShaReviewAttestation,
    ExactShaReviewRequest,
    InMemoryExactShaReviewAttestationRegistry,
    ReviewAdvisoryState,
    ReviewAttestationVerdict,
    ReviewerIdentity,
    ReviewFindingCode,
    ReviewModel,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def reviewer(value: str) -> ReviewerIdentity:
    return ReviewerIdentity(
        model=ReviewModel.GPT_5_6_SOL,
        reviewer_key_fingerprint=value,
    )


def attestation(
    request: ExactShaReviewRequest,
    fingerprint: str,
    suffix: str,
    verdict: ReviewAttestationVerdict = ReviewAttestationVerdict.APPROVE,
    findings: object = (),
) -> ExactShaReviewAttestation:
    return ExactShaReviewAttestation(
        request_id=request.id,
        request_content_hash=request.content_hash,
        repository=request.repository,
        pull_request_number=request.pull_request_number,
        candidate_sha=request.candidate_sha,
        reviewer=reviewer(fingerprint),
        verdict=verdict,
        finding_codes=findings,
        review_artifact_sha256=digest(f"review:{suffix}"),
        evidence_artifact_sha256s={
            digest(f"evidence:{suffix}:a"),
            digest(f"evidence:{suffix}:b"),
        },
        authenticated_envelope_sha256=digest(f"envelope:{suffix}"),
    )


base_sha = sys.argv[2]
candidate_sha = sys.argv[3]
reviewers = tuple(digest(f"reviewer:{name}") for name in "abcd")
request = ExactShaReviewRequest(
    repository="leon36000/NextGen-Memory",
    pull_request_number=165,
    base_sha=base_sha,
    candidate_sha=candidate_sha,
    diff_sha256=digest("exact-nine-path-diff"),
    review_packet_sha256=digest("blind-review-packet"),
    acceptance_criteria_sha256=digest("issue-165-contract"),
    required_model=ReviewModel.GPT_5_6_SOL,
    trusted_reviewer_fingerprints=set(reviewers),
    minimum_approvals=2,
)
registry = InMemoryExactShaReviewAttestationRegistry()
assert registry.register_request(request) is request
assert registry.register_request(request) is request
states: list[dict[str, object]] = []

def snapshot(label: str) -> None:
    summary = registry.summary(request.id)
    decision = registry.decision(request.id)
    states.append({
        "label": label,
        "summary": json.loads(summary.render_json()),
        "decision": json.loads(decision.render_json()),
    })

snapshot("pending_empty")
a = attestation(request, reviewers[0], "a")
assert registry.record_attestation(a) is a
assert registry.record_attestation(a) is a
snapshot("pending_one_approval")
b = attestation(request, reviewers[1], "b")
registry.record_attestation(b)
snapshot("approved_two_approvals")
c = attestation(
    request,
    reviewers[2],
    "c",
    ReviewAttestationVerdict.BLOCKED_BY_EVIDENCE,
    (ReviewFindingCode.MISSING_ARTIFACT,),
)
registry.record_attestation(c)
snapshot("evidence_blocked")
d = attestation(
    request,
    reviewers[3],
    "d",
    ReviewAttestationVerdict.CHANGES_REQUIRED,
    (ReviewFindingCode.CONTRACT_VIOLATION,),
)
registry.record_attestation(d)
snapshot("blocked")
expected_states = [
    ReviewAdvisoryState.PENDING.value,
    ReviewAdvisoryState.PENDING.value,
    ReviewAdvisoryState.APPROVED.value,
    ReviewAdvisoryState.EVIDENCE_BLOCKED.value,
    ReviewAdvisoryState.BLOCKED.value,
]
actual_states = [item["decision"]["state"] for item in states]
if actual_states != expected_states:
    raise SystemExit(f"state precedence drift: {actual_states!r}")
expected_summary = registry.summary(request.id).render_json()
expected_decision = registry.decision(request.id).render_json()
for _ in range(1000):
    if registry.summary(request.id).render_json() != expected_summary:
        raise SystemExit("summary retry drift")
    if registry.decision(request.id).render_json() != expected_decision:
        raise SystemExit("decision retry drift")
payload = {
    "schema": "m-head-exact-review-attestation-r2-semantics-v1",
    "base_sha": base_sha,
    "candidate_sha": candidate_sha,
    "request": json.loads(request.render_json()),
    "attestations": [json.loads(item.render_json()) for item in (a, b, c, d)],
    "states": states,
    "exact_retry_count": 1000,
}
raw = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
Path(sys.argv[1]).write_text(raw, encoding="utf-8")
PY

PYTHONHASHSEED=1 python /tmp/generate_exact_review_r2_semantics.py \
  "$EVIDENCE_ROOT/semantic.json" "$BASE_SHA" "$CANDIDATE_SHA"
PYTHONHASHSEED=999 python /tmp/generate_exact_review_r2_semantics.py \
  /tmp/exact-review-r2-seed999.json "$BASE_SHA" "$CANDIDATE_SHA"
cmp "$EVIDENCE_ROOT/semantic.json" /tmp/exact-review-r2-seed999.json

# Build and import the exact wheel outside the checkout.
WHEELHOUSE="$RUNNER_TEMP/exact-review-r2-wheelhouse-${PYTHON_VERSION:-python}"
VENV="$RUNNER_TEMP/exact-review-r2-wheel-venv-${PYTHON_VERSION:-python}"
rm -rf "$WHEELHOUSE" "$VENV"
mkdir -p "$WHEELHOUSE"
run python -m pip wheel --no-deps . -w "$WHEELHOUSE"
WHEEL=$(find "$WHEELHOUSE" -maxdepth 1 -type f -name '*.whl' -print -quit)
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
    ReviewerIdentity,
    ReviewFindingCode,
    ReviewModel,
)
for value in (
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
    ReviewerIdentity,
    ReviewFindingCode,
    ReviewModel,
):
    assert value is not None
assert ReviewAdvisoryState.APPROVED.value == "approved"
assert ReviewModel.GPT_5_6_SOL.value == "gpt-5.6-sol"
assert "InMemoryExactShaReviewAttestationRegistry" in nextgen_memory.__all__
PY
run "$VENV/bin/python" -m pip check
cp "$WHEEL" "$EVIDENCE_ROOT/"
WHEEL_COPY=$(find "$EVIDENCE_ROOT" -maxdepth 1 -type f -name '*.whl' -print -quit)
sha256sum "$WHEEL_COPY" | awk '{print $1}' > "$EVIDENCE_ROOT/wheel.sha256"

python - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path


def passed(path: str) -> int:
    values = re.findall(r"(\d+) passed", Path(path).read_text(encoding="utf-8"))
    if not values:
        raise SystemExit(f"missing pass count: {path}")
    return int(values[-1])

root = Path(os.environ["EVIDENCE_ROOT"])
semantic = root / "semantic.json"
report = {
    "schema": "m-head-exact-review-attestation-r2-verification-v1",
    "base_sha": os.environ["BASE_SHA"],
    "candidate_sha": os.environ["CANDIDATE_SHA"],
    "red_v5_sha": os.environ["RED_SHA"],
    "python_version": ".".join(map(str, sys.version_info[:3])),
    "exact_path_count": 9,
    "focused_test_count": passed("/tmp/exact-review-r2-focused.txt"),
    "full_test_count": passed("/tmp/exact-review-r2-full.txt"),
    "generated_trace_count": 5000,
    "exact_retry_count": 1000,
    "semantic_sha256": hashlib.sha256(semantic.read_bytes()).hexdigest(),
    "hash_seed_invariant": True,
    "audit_findings": 0,
    "isolated_wheel_import": True,
    "wheel_sha256": (root / "wheel.sha256").read_text(encoding="utf-8").strip(),
}
(root / "verification.json").write_text(
    json.dumps(report, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
print((root / "verification.json").read_text(encoding="utf-8"), end="")
PY
