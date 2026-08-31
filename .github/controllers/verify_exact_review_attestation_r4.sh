#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 PRODUCT_ROOT EVIDENCE_ROOT" >&2
  exit 2
fi

PRODUCT_ROOT=$1
EVIDENCE_ROOT=$2
BASE_SHA='f4f3aca9759b5b7a60691017c2211152c011ea92'
PARENT_SHA='f4d9388c14dd1f746f904b3724767f73f82786fd'
CANDIDATE_SHA='41b0b104e5a3f06c4d238060ad0fd3dd51dd4446'
export BASE_SHA PARENT_SHA CANDIDATE_SHA EVIDENCE_ROOT
mkdir -p "$EVIDENCE_ROOT"
cd "$PRODUCT_ROOT"

run() {
  printf '+ %q ' "$@"
  printf '\n'
  "$@"
}

# Exact immutable graph and nine-path product surface.
test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"
test "$(git merge-base HEAD "$PARENT_SHA")" = "$PARENT_SHA"
test "$(git merge-base HEAD "$BASE_SHA")" = "$BASE_SHA"
mapfile -t PARENT_DELTA < <(git diff --name-only "$PARENT_SHA"...HEAD | sort)
EXPECTED_PARENT=(
  docs/exact-sha-review-attestation-registry-v0.md
  docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md
  src/nextgen_memory/review_attestation_registry.py
  tests/test_review_attestation_registry.py
)
test "${#PARENT_DELTA[@]}" -eq "${#EXPECTED_PARENT[@]}"
diff -u <(printf '%s\n' "${EXPECTED_PARENT[@]}" | sort) <(printf '%s\n' "${PARENT_DELTA[@]}")
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

test -z "$(git status --porcelain)"
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

# The exact five post-init tamper cases must remain independently GREEN.
INTEGRITY_TESTS=(
  tests/test_review_attestation_registry.py::test_request_tampering_before_registration_is_rejected
  tests/test_review_attestation_registry.py::test_request_tampering_after_registration_cannot_change_decision
  tests/test_review_attestation_registry.py::test_reviewer_tampering_is_rejected_before_attestation_identity_is_built
  tests/test_review_attestation_registry.py::test_attestation_tampering_before_record_is_rejected
  tests/test_review_attestation_registry.py::test_attestation_tampering_after_record_cannot_rewrite_registry_history
)
run python -m pytest -q "${INTEGRITY_TESTS[@]}" | tee /tmp/exact-review-r4-integrity.txt

FOCUSED=(
  tests/test_review_attestation_registry.py
  tests/test_review_attestation_registry_properties.py
  tests/test_review_attestation_registry_public_api.py
)
run python -m pytest -q "${FOCUSED[@]}" | tee /tmp/exact-review-r4-focused.txt
run python -m pytest -q | tee /tmp/exact-review-r4-full.txt

python - <<'PY'
from __future__ import annotations
import re
from pathlib import Path

def passed(path: str) -> int:
    values = re.findall(r"(\d+) passed", Path(path).read_text(encoding="utf-8"))
    if not values:
        raise SystemExit(f"missing pytest pass count: {path}")
    return int(values[-1])

counts = {
    "integrity": passed("/tmp/exact-review-r4-integrity.txt"),
    "focused": passed("/tmp/exact-review-r4-focused.txt"),
    "full": passed("/tmp/exact-review-r4-full.txt"),
}
expected = {"integrity": 5, "focused": 72, "full": 526}
if counts != expected:
    raise SystemExit(f"test count drift: {counts!r} != {expected!r}")
print(counts)
PY

# Standard-library/privacy/side-effect/stub audit. Attribute re.compile is allowed;
# only the builtin compile call is forbidden.
python - <<'PY'
from __future__ import annotations
import ast
from pathlib import Path

path = Path("src/nextgen_memory/review_attestation_registry.py")
source = path.read_text(encoding="utf-8")
tree = ast.parse(source, filename=str(path))
allowed_roots = {
    "__future__", "collections", "dataclasses", "enum", "hashlib",
    "itertools", "json", "re", "uuid",
}
forbidden_builtins = {"eval", "exec", "compile", "open"}
forbidden_attributes = {
    "sleep", "system", "urlopen", "uuid1", "uuid4", "write_bytes", "write_text",
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
            if alias.name.split(".", 1)[0] not in allowed_roots:
                findings.append(f"{node.lineno}:import:{alias.name}")
    elif isinstance(node, ast.ImportFrom):
        root = (node.module or "").split(".", 1)[0]
        if node.level == 0 and root not in allowed_roots:
            findings.append(f"{node.lineno}:import:{node.module}")
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in forbidden_builtins:
            findings.append(f"{node.lineno}:call:{node.func.id}")
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in forbidden_attributes
        ):
            findings.append(f"{node.lineno}:call:{node.func.attr}")

lowered = source.lower()
for marker in (
    "postgresql://", "mongodb://", "http://", "https://", "password",
    "credential", "raw_query", "raw_prompt", "response_text", "memory_body",
    "reviewer_email", "reviewer_name", "merge_pull_request", "activate_policy(",
    "write_feedback(", "# todo", "# fixme",
):
    if marker in lowered:
        findings.append(f"text:{marker}")
for test_path in map(Path, (
    "tests/test_review_attestation_registry.py",
    "tests/test_review_attestation_registry_properties.py",
    "tests/test_review_attestation_registry_public_api.py",
)):
    text = test_path.read_text(encoding="utf-8").lower()
    for marker in ("pytest.mark.skip", "pytest.mark.xfail", "# noqa"):
        if marker in text:
            findings.append(f"{test_path}:text:{marker}")
if findings:
    raise SystemExit("\n".join(findings))
print("exact_review_attestation_r4_audit_findings=0")
PY

# Fresh semantic and post-init-tamper evidence under two independent hash seeds.
cat > /tmp/generate_exact_review_r4_semantics.py <<'PY'
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
    ReviewAttestationValidationError,
    ReviewAttestationVerdict,
    ReviewerIdentity,
    ReviewFindingCode,
    ReviewModel,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def make_request(*, minimum_approvals: int = 2) -> ExactShaReviewRequest:
    return ExactShaReviewRequest(
        repository="leon36000/NextGen-Memory",
        pull_request_number=185,
        base_sha=sys.argv[2],
        candidate_sha=sys.argv[3],
        diff_sha256=digest("r4-diff"),
        review_packet_sha256=digest("r4-packet"),
        acceptance_criteria_sha256=digest("r4-criteria"),
        required_model=ReviewModel.GPT_5_6_SOL,
        trusted_reviewer_fingerprints={digest("reviewer:a"), digest("reviewer:b")},
        minimum_approvals=minimum_approvals,
    )


def make_attestation(
    request: ExactShaReviewRequest,
    fingerprint: str,
    suffix: str,
    *,
    verdict: ReviewAttestationVerdict = ReviewAttestationVerdict.APPROVE,
    findings: object = (),
) -> ExactShaReviewAttestation:
    return ExactShaReviewAttestation(
        request_id=request.id,
        request_content_hash=request.content_hash,
        repository=request.repository,
        pull_request_number=request.pull_request_number,
        candidate_sha=request.candidate_sha,
        reviewer=ReviewerIdentity(
            model=ReviewModel.GPT_5_6_SOL,
            reviewer_key_fingerprint=fingerprint,
        ),
        verdict=verdict,
        finding_codes=findings,
        review_artifact_sha256=digest(f"review:{suffix}"),
        evidence_artifact_sha256s={digest(f"evidence:{suffix}:a"), digest(f"evidence:{suffix}:b")},
        authenticated_envelope_sha256=digest(f"envelope:{suffix}"),
    )


def integrity_failure(callable_object: object) -> str:
    try:
        callable_object()  # type: ignore[operator]
    except ReviewAttestationValidationError as exc:
        if "integrity" not in str(exc).lower():
            raise SystemExit(f"unbounded integrity error message: {exc}") from exc
        if exc.__cause__ is not None or exc.__context__ is not None:
            raise SystemExit("integrity error leaked exception context") from exc
        return str(exc)
    raise SystemExit("tampered value was accepted")

fingerprints = tuple(sorted((digest("reviewer:a"), digest("reviewer:b"))))
registry = InMemoryExactShaReviewAttestationRegistry()
request = registry.register_request(make_request())
a = make_attestation(request, fingerprints[0], "a")
b = make_attestation(request, fingerprints[1], "b")
registry.record_attestation(a)
pending = registry.decision(request.id)
registry.record_attestation(b)
approved = registry.decision(request.id)
if pending.state is not ReviewAdvisoryState.PENDING:
    raise SystemExit("one approval was not pending")
if approved.state is not ReviewAdvisoryState.APPROVED:
    raise SystemExit("two approvals were not approved")

# Separate objects prove post-init tamper rejection without corrupting the normal path.
tampered_request = make_request()
object.__setattr__(tampered_request, "minimum_approvals", 1)
request_failure = integrity_failure(
    lambda: InMemoryExactShaReviewAttestationRegistry().register_request(tampered_request)
)

tampered_reviewer = ReviewerIdentity(
    model=ReviewModel.GPT_5_6_SOL,
    reviewer_key_fingerprint=fingerprints[0],
)
object.__setattr__(tampered_reviewer, "reviewer_key_fingerprint", fingerprints[1])
reviewer_failure = integrity_failure(
    lambda: ExactShaReviewAttestation(
        request_id=request.id,
        request_content_hash=request.content_hash,
        repository=request.repository,
        pull_request_number=request.pull_request_number,
        candidate_sha=request.candidate_sha,
        reviewer=tampered_reviewer,
        verdict=ReviewAttestationVerdict.APPROVE,
        finding_codes=(),
        review_artifact_sha256=digest("review:tampered-reviewer"),
        evidence_artifact_sha256s=(digest("evidence:tampered-reviewer"),),
        authenticated_envelope_sha256=digest("envelope:tampered-reviewer"),
    )
)

tamper_registry = InMemoryExactShaReviewAttestationRegistry()
tamper_request = tamper_registry.register_request(make_request(minimum_approvals=1))
tampered_attestation = make_attestation(tamper_request, fingerprints[0], "tampered")
tamper_registry.record_attestation(tampered_attestation)
object.__setattr__(tampered_attestation, "verdict", ReviewAttestationVerdict.CHANGES_REQUIRED)
object.__setattr__(
    tampered_attestation,
    "finding_codes",
    (ReviewFindingCode.CONTRACT_VIOLATION,),
)
stored_failure = integrity_failure(lambda: tamper_registry.decision(tamper_request.id))

normal_summary = registry.summary(request.id).render_json()
normal_decision = registry.decision(request.id).render_json()
for _ in range(1000):
    if registry.summary(request.id).render_json() != normal_summary:
        raise SystemExit("summary retry drift")
    if registry.decision(request.id).render_json() != normal_decision:
        raise SystemExit("decision retry drift")

payload = {
    "schema": "m-head-exact-review-attestation-r4-semantics-v1",
    "base_sha": sys.argv[2],
    "candidate_sha": sys.argv[3],
    "normal": {
        "request": json.loads(request.render_json()),
        "attestations": [json.loads(a.render_json()), json.loads(b.render_json())],
        "pending": json.loads(pending.render_json()),
        "approved": json.loads(approved.render_json()),
        "summary": json.loads(normal_summary),
    },
    "tamper_rejections": {
        "request": request_failure,
        "reviewer": reviewer_failure,
        "stored_attestation": stored_failure,
    },
    "exact_retry_count": 1000,
}
raw = json.dumps(
    payload,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
) + "\n"
Path(sys.argv[1]).write_text(raw, encoding="utf-8")
PY

PYTHONHASHSEED=1 python /tmp/generate_exact_review_r4_semantics.py \
  "$EVIDENCE_ROOT/semantic.json" "$BASE_SHA" "$CANDIDATE_SHA"
PYTHONHASHSEED=999 python /tmp/generate_exact_review_r4_semantics.py \
  /tmp/exact-review-r4-seed999.json "$BASE_SHA" "$CANDIDATE_SHA"
cmp "$EVIDENCE_ROOT/semantic.json" /tmp/exact-review-r4-seed999.json

# Build/install exact wheel outside checkout.
WHEELHOUSE="$RUNNER_TEMP/exact-review-r4-wheelhouse-${PYTHON_VERSION:-python}"
VENV="$RUNNER_TEMP/exact-review-r4-wheel-venv-${PYTHON_VERSION:-python}"
rm -rf "$WHEELHOUSE" "$VENV"
mkdir -p "$WHEELHOUSE"
run python -m pip wheel --no-deps . -w "$WHEELHOUSE"
WHEEL=$(find "$WHEELHOUSE" -maxdepth 1 -type f -name '*.whl' -print -quit)
test -n "$WHEEL"
run python -m venv "$VENV"
run "$VENV/bin/python" -m pip install --no-deps "$WHEEL"
"$VENV/bin/python" - <<'PY'
import nextgen_memory
from nextgen_memory import InMemoryExactShaReviewAttestationRegistry, ReviewAdvisoryState
assert InMemoryExactShaReviewAttestationRegistry is not None
assert ReviewAdvisoryState.APPROVED.value == "approved"
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
    "schema": "m-head-exact-review-attestation-r4-verification-v1",
    "base_sha": os.environ["BASE_SHA"],
    "parent_sha": os.environ["PARENT_SHA"],
    "candidate_sha": os.environ["CANDIDATE_SHA"],
    "python_version": ".".join(map(str, sys.version_info[:3])),
    "exact_path_count": 9,
    "r4_parent_delta_path_count": 4,
    "post_init_integrity_test_count": passed("/tmp/exact-review-r4-integrity.txt"),
    "focused_test_count": passed("/tmp/exact-review-r4-focused.txt"),
    "full_test_count": passed("/tmp/exact-review-r4-full.txt"),
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

test -z "$(git status --porcelain)"
