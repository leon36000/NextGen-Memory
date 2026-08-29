#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 6 ]]; then
  echo "usage: $0 PRODUCT_ROOT EVIDENCE_ROOT CANDIDATE_SHA BASE_SHA R2_SHA RED_SHA" >&2
  exit 2
fi

PRODUCT_ROOT=$1
EVIDENCE_ROOT=$2
CANDIDATE_SHA=$3
BASE_SHA=$4
R2_SHA=$5
RED_SHA=$6
export EVIDENCE_ROOT CANDIDATE_SHA BASE_SHA R2_SHA RED_SHA
mkdir -p "$EVIDENCE_ROOT"
cd "$PRODUCT_ROOT"

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

# Freeze exact graph and product surface.
test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"
test "$(git rev-parse HEAD^)" = "$RED_SHA"
test "$(git rev-parse "$RED_SHA^")" = "$R2_SHA"
test "$(git merge-base "$BASE_SHA" HEAD)" = "$BASE_SHA"
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
diff -u <(printf '%s\n' "${EXPECTED[@]}" | sort) \
  <(printf '%s\n' "${CHANGED[@]}")
test -z "$(git diff --name-only "$BASE_SHA"...HEAD -- \
  '.github/workflows/**' 'migrations/**' pyproject.toml \
  'src/nextgen_memory/corrective_retrieval_*')"
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

# Prove the accepted adversarial contract and all package behavior.
run python -m pytest -q \
  tests/test_review_attestation_registry.py::test_collection_iteration_failures_are_bounded_and_privacy_safe \
  tests/test_review_attestation_registry.py::test_reviewer_subclass_cannot_inject_raw_payload \
  tests/test_review_attestation_registry.py::test_registry_rejects_contract_subclasses_before_mutation \
  tests/test_review_attestation_registry.py::test_primitive_subclasses_are_rejected_before_overridden_behavior \
  | tee /tmp/exact-review-attestation-r3-adversarial.txt
ADVERSARIAL_COUNT=$(passed_count /tmp/exact-review-attestation-r3-adversarial.txt)
test "$ADVERSARIAL_COUNT" -eq 6

FOCUSED=(
  tests/test_review_attestation_registry.py
  tests/test_review_attestation_registry_properties.py
  tests/test_review_attestation_registry_public_api.py
)
run python -m pytest -q "${FOCUSED[@]}" \
  | tee /tmp/exact-review-attestation-r3-focused.txt
FOCUSED_COUNT=$(passed_count /tmp/exact-review-attestation-r3-focused.txt)
test "$FOCUSED_COUNT" -eq 67
run python -m pytest -q | tee /tmp/exact-review-attestation-r3-full.txt
FULL_COUNT=$(passed_count /tmp/exact-review-attestation-r3-full.txt)
test "$FULL_COUNT" -eq 521

# Confirm the generated-property contract is executed rather than described only.
run python - <<'PY'
from __future__ import annotations

import ast
from pathlib import Path

path = Path("tests/test_review_attestation_registry_properties.py")
tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
loops = [
    node
    for node in ast.walk(tree)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Name)
    and node.func.id == "range"
    and any(
        isinstance(argument, ast.Constant) and argument.value == 5_000
        for argument in node.args
    )
]
if len(loops) != 1:
    raise SystemExit(f"expected one 5,000-trace loop, found {len(loops)}")
print("generated_trace_loop_count=5000")
PY

# Strict dependency, privacy, side-effect, and stub audit.
run python - <<'PY'
from __future__ import annotations

import ast
import sys
from pathlib import Path

path = Path("src/nextgen_memory/review_attestation_registry.py")
source = path.read_text(encoding="utf-8")
tree = ast.parse(source, filename=str(path))
forbidden_calls = {
    "compile",
    "connect",
    "eval",
    "exec",
    "getenv",
    "now",
    "open",
    "popen",
    "putenv",
    "request",
    "sleep",
    "system",
    "time",
    "urlopen",
    "utcnow",
    "uuid1",
    "uuid4",
    "write_bytes",
    "write_text",
}
findings: list[str] = []
for node in ast.walk(tree):
    if isinstance(node, ast.Import):
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root not in sys.stdlib_module_names:
                findings.append(f"{node.lineno}:non_stdlib_import:{root}")
    elif isinstance(node, ast.ImportFrom):
        root = (node.module or "").split(".", 1)[0]
        if node.level == 0 and root not in sys.stdlib_module_names and root != "__future__":
            findings.append(f"{node.lineno}:non_stdlib_import:{root}")
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
        name = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else None
        )
        if name in forbidden_calls:
            findings.append(f"{node.lineno}:forbidden_call:{name}")

lowered = source.lower()
for marker in (
    "postgresql://",
    "mongodb://",
    "http://",
    "https://",
    "password",
    "credential",
    "private_key",
    "secret_key",
    "access_token",
    "api_key",
    "reviewer_email",
    "reviewer_name",
    "raw_payload",
    "raw_review",
    "query_text",
    "command_output",
    "memory_body",
    "activate_policy(",
    "write_feedback(",
    "# todo",
    "# fixme",
):
    if marker in lowered:
        findings.append(f"text:{marker}")
for required in (
    "reviewer must be an exact ReviewerIdentity",
    "request must be an exact ExactShaReviewRequest",
    "attestation must be an exact ExactShaReviewAttestation",
    "except Exception:",
):
    if required not in source:
        findings.append(f"missing_hardening:{required}")
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
print("exact_review_attestation_r3_audit_findings=0")
PY

# Produce one behavior-bound semantic matrix under independent hash seeds.
cat > /tmp/generate_exact_review_attestation_r3_semantic.py <<'PY'
from __future__ import annotations

import hashlib
import json
import os
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


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


candidate_sha = sys.argv[2]
base_sha = sys.argv[3]
reviewers = tuple(digest(f"reviewer:{index}") for index in range(4))
request = ExactShaReviewRequest(
    repository="leon36000/NextGen-Memory",
    pull_request_number=185,
    base_sha=base_sha,
    candidate_sha=candidate_sha,
    diff_sha256=digest("candidate-diff"),
    review_packet_sha256=digest("review-packet"),
    acceptance_criteria_sha256=digest("acceptance-criteria"),
    required_model=ReviewModel.GPT_5_6_SOL,
    trusted_reviewer_fingerprints=set(reviewers),
    minimum_approvals=2,
)


def attestation(
    index: int,
    verdict: ReviewAttestationVerdict,
    findings: tuple[ReviewFindingCode, ...] = (),
) -> ExactShaReviewAttestation:
    return ExactShaReviewAttestation(
        request_id=request.id,
        request_content_hash=request.content_hash,
        repository=request.repository,
        pull_request_number=request.pull_request_number,
        candidate_sha=request.candidate_sha,
        reviewer=ReviewerIdentity(
            model=ReviewModel.GPT_5_6_SOL,
            reviewer_key_fingerprint=reviewers[index],
        ),
        verdict=verdict,
        finding_codes=set(findings),
        review_artifact_sha256=digest(f"review-artifact:{index}:{verdict.value}"),
        evidence_artifact_sha256s={
            digest(f"evidence:{index}:a"),
            digest(f"evidence:{index}:b"),
        },
        authenticated_envelope_sha256=digest(f"envelope:{index}:{verdict.value}"),
    )


approve_a = attestation(0, ReviewAttestationVerdict.APPROVE)
approve_b = attestation(1, ReviewAttestationVerdict.APPROVE)
evidence_blocker = attestation(
    2,
    ReviewAttestationVerdict.BLOCKED_BY_EVIDENCE,
    (ReviewFindingCode.MISSING_ARTIFACT,),
)
changes_blocker = attestation(
    3,
    ReviewAttestationVerdict.CHANGES_REQUIRED,
    (ReviewFindingCode.PRIVACY_RISK,),
)


def evaluate(values: tuple[ExactShaReviewAttestation, ...]) -> dict[str, object]:
    registry = InMemoryExactShaReviewAttestationRegistry()
    first = registry.register_request(request)
    second = registry.register_request(request)
    if first is not second:
        raise SystemExit("exact request retry did not preserve object identity")
    for value in values:
        recorded = registry.record_attestation(value)
        retried = registry.record_attestation(value)
        if recorded is not retried:
            raise SystemExit("exact attestation retry did not preserve object identity")
    summary = registry.summary(request.id)
    decision = registry.decision(request.id)
    return {
        "summary": json.loads(summary.render_json()),
        "decision": json.loads(decision.render_json()),
        "attestation_content_hashes": [
            value.content_hash for value in registry.attestations(request.id)
        ],
    }


states = {
    "pending": evaluate(()),
    "approved": evaluate((approve_a, approve_b)),
    "evidence_blocked": evaluate((approve_a, approve_b, evidence_blocker)),
    "blocked": evaluate((approve_a, approve_b, evidence_blocker, changes_blocker)),
}
expected = {
    "pending": ReviewAdvisoryState.PENDING.value,
    "approved": ReviewAdvisoryState.APPROVED.value,
    "evidence_blocked": ReviewAdvisoryState.EVIDENCE_BLOCKED.value,
    "blocked": ReviewAdvisoryState.BLOCKED.value,
}
for name, state in states.items():
    actual = state["decision"]["state"]
    if actual != expected[name]:
        raise SystemExit(f"{name} decision differs: {actual!r}")

approved_registry = InMemoryExactShaReviewAttestationRegistry()
approved_registry.register_request(request)
approved_registry.record_attestation(approve_a)
approved_registry.record_attestation(approve_b)
expected_retry = approved_registry.decision(request.id).render_json()
for _ in range(1_000):
    if approved_registry.decision(request.id).render_json() != expected_retry:
        raise SystemExit("exact decision retry changed canonical JSON")

class ExplodingCollection:
    def __iter__(self) -> "ExplodingCollection":
        return self

    def __next__(self) -> object:
        raise RuntimeError("PRIVATE-ITERATOR-SENTINEL")

privacy_error = None
try:
    ExactShaReviewRequest(
        repository=request.repository,
        pull_request_number=request.pull_request_number,
        base_sha=request.base_sha,
        candidate_sha=request.candidate_sha,
        diff_sha256=request.diff_sha256,
        review_packet_sha256=request.review_packet_sha256,
        acceptance_criteria_sha256=request.acceptance_criteria_sha256,
        required_model=request.required_model,
        trusted_reviewer_fingerprints=ExplodingCollection(),
        minimum_approvals=1,
    )
except ReviewAttestationValidationError as exc:
    if exc.__cause__ is not None or exc.__context__ is not None:
        raise SystemExit("privacy-safe iterator error retained exception context")
    if "PRIVATE-ITERATOR-SENTINEL" in str(exc):
        raise SystemExit("privacy-safe iterator error exposed private text")
    privacy_error = str(exc)
if privacy_error != "trusted reviewers must be a bounded iterable":
    raise SystemExit(f"privacy-safe iterator category differs: {privacy_error!r}")

payload = {
    "schema": "m-head-exact-review-attestation-r3-semantic-v1",
    "base_sha": base_sha,
    "candidate_sha": candidate_sha,
    "request": json.loads(request.render_json()),
    "states": states,
    "exact_retry_count": 1_000,
    "privacy": {
        "iterator_error": privacy_error,
        "exception_context_absent": True,
        "hostile_subclasses_rejected": True,
    },
}
raw = json.dumps(
    payload,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
) + "\n"
for forbidden in (
    "PRIVATE-ITERATOR-SENTINEL",
    "raw_payload",
    "raw_review",
    "credential",
    "password",
    "api_key",
    "access_token",
):
    if forbidden in raw:
        raise SystemExit(f"semantic evidence leaked forbidden text: {forbidden}")
Path(sys.argv[1]).write_text(raw, encoding="utf-8")
PY

PYTHONHASHSEED=1 python /tmp/generate_exact_review_attestation_r3_semantic.py \
  "$EVIDENCE_ROOT/semantic.json" "$CANDIDATE_SHA" "$BASE_SHA"
PYTHONHASHSEED=999 python /tmp/generate_exact_review_attestation_r3_semantic.py \
  /tmp/exact-review-attestation-r3-semantic-seed-999.json \
  "$CANDIDATE_SHA" "$BASE_SHA"
cmp "$EVIDENCE_ROOT/semantic.json" \
  /tmp/exact-review-attestation-r3-semantic-seed-999.json
SEMANTIC_SHA=$(sha256sum "$EVIDENCE_ROOT/semantic.json" | awk '{print $1}')

# Build and import the exact wheel outside the checkout, including a privacy smoke test.
WHEELHOUSE="$RUNNER_TEMP/exact-review-attestation-r3-wheelhouse-${PYTHON_VERSION:-python}"
VENV="$RUNNER_TEMP/exact-review-attestation-r3-venv-${PYTHON_VERSION:-python}"
rm -rf "$WHEELHOUSE" "$VENV"
mkdir -p "$WHEELHOUSE"
run python -m pip wheel --no-deps . -w "$WHEELHOUSE"
WHEEL=$(find "$WHEELHOUSE" -maxdepth 1 -type f -name '*.whl' -print -quit)
test -n "$WHEEL"
run python -m venv "$VENV"
run "$VENV/bin/python" -m pip install --no-deps "$WHEEL"
run "$VENV/bin/python" - <<'PY'
from nextgen_memory import (
    ExactShaReviewRequest,
    InMemoryExactShaReviewAttestationRegistry,
    ReviewAttestationValidationError,
    ReviewModel,
)

assert InMemoryExactShaReviewAttestationRegistry is not None

class ExplodingCollection:
    def __iter__(self):
        return self

    def __next__(self):
        raise RuntimeError("PRIVATE-WHEEL-SENTINEL")

try:
    ExactShaReviewRequest(
        repository="leon36000/NextGen-Memory",
        pull_request_number=185,
        base_sha="1" * 40,
        candidate_sha="2" * 40,
        diff_sha256="3" * 64,
        review_packet_sha256="4" * 64,
        acceptance_criteria_sha256="5" * 64,
        required_model=ReviewModel.GPT_5_6_SOL,
        trusted_reviewer_fingerprints=ExplodingCollection(),
        minimum_approvals=1,
    )
except ReviewAttestationValidationError as exc:
    assert exc.__cause__ is None
    assert exc.__context__ is None
    assert "PRIVATE-WHEEL-SENTINEL" not in str(exc)
else:
    raise AssertionError("wheel accepted hostile iterator")
PY
run "$VENV/bin/python" -m pip check
cp "$WHEEL" "$EVIDENCE_ROOT/"
WHEEL_COPY=$(find "$EVIDENCE_ROOT" -maxdepth 1 -type f -name '*.whl' -print -quit)
WHEEL_SHA=$(sha256sum "$WHEEL_COPY" | awk '{print $1}')

python - <<PY
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

root = Path(os.environ["EVIDENCE_ROOT"])
manifest = {
    "schema": "m-head-exact-review-attestation-r3-python-verification-v1",
    "repository": "${GITHUB_REPOSITORY}",
    "base_sha": os.environ["BASE_SHA"],
    "r2_sha": os.environ["R2_SHA"],
    "red_sha": os.environ["RED_SHA"],
    "candidate_sha": os.environ["CANDIDATE_SHA"],
    "python_version": ".".join(map(str, sys.version_info[:3])),
    "exact_path_count": 9,
    "adversarial_test_count": int("$ADVERSARIAL_COUNT"),
    "focused_test_count": int("$FOCUSED_COUNT"),
    "full_test_count": int("$FULL_COUNT"),
    "generated_trace_count": 5_000,
    "exact_retry_count": 1_000,
    "hash_seed_invariant": True,
    "semantic_sha256": "$SEMANTIC_SHA",
    "audit_findings": 0,
    "isolated_wheel_import": True,
    "wheel_sha256": "$WHEEL_SHA",
    "privacy_hardening": {
        "iteration_exceptions_sanitized": True,
        "exact_contract_types": True,
        "primitive_subclasses_rejected": True,
        "exception_context_absent": True,
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
(root / "manifest.json").write_text(
    json.dumps(
        manifest,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n",
    encoding="utf-8",
)
print((root / "manifest.json").read_text(encoding="utf-8"), end="")
PY

test -z "$(git status --porcelain)"
