#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 PRODUCT_ROOT EVIDENCE_ROOT CANDIDATE_SHA BASE_SHA" >&2
  exit 2
fi

PRODUCT_ROOT=$1
EVIDENCE_ROOT=$2
CANDIDATE_SHA=$3
BASE_SHA=$4
mkdir -p "$EVIDENCE_ROOT"
cd "$PRODUCT_ROOT"

run() {
  printf '+ %q ' "$@"
  printf '\n'
  "$@"
}

# Exact immutable checkout, ancestry, and product surface.
test "$(git rev-parse HEAD)" = "$CANDIDATE_SHA"
test "$(git merge-base HEAD "$BASE_SHA")" = "$BASE_SHA"
mapfile -t CHANGED < <(git diff --name-only "$BASE_SHA"...HEAD | sort)
EXPECTED=(
  docs/policy-promotion-gate-v0-red.md
  docs/superpowers/plans/2026-08-24-advisory-policy-promotion-gate-v0.md
  docs/superpowers/specs/2026-08-24-advisory-policy-promotion-gate-v0-design.md
  src/nextgen_memory/__init__.py
  src/nextgen_memory/policy_promotion_gate.py
  tests/test_policy_promotion_gate.py
  tests/test_policy_promotion_gate_properties.py
  tests/test_policy_promotion_gate_public_api.py
)
test "${#CHANGED[@]}" -eq "${#EXPECTED[@]}"
diff -u <(printf '%s\n' "${EXPECTED[@]}" | sort) <(printf '%s\n' "${CHANGED[@]}")
test -z "$(git diff --name-only "$BASE_SHA"...HEAD -- '.github/workflows/**' 'migrations/**' pyproject.toml 'src/nextgen_memory/corrective_retrieval_*')"
run git diff --check "$BASE_SHA"...HEAD
test -z "$(git status --porcelain)"

run python -m pip install -e '.[dev]'
run ruff check .
run python -m compileall -q src scripts

FOCUSED=(
  tests/test_policy_promotion_gate.py
  tests/test_policy_promotion_gate_properties.py
  tests/test_policy_promotion_gate_public_api.py
)
run python -m pytest -q "${FOCUSED[@]}" | tee /tmp/advisory-promotion-focused.txt
run python -m pytest -q | tee /tmp/advisory-promotion-full.txt

# The exact candidate is expected to expose the complete, non-weakened suite.
python - <<'PY'
from pathlib import Path
import re


def passed(path: str) -> int:
    matches = re.findall(r"(\d+) passed", Path(path).read_text(encoding="utf-8"))
    if not matches:
        raise SystemExit(f"missing pytest pass count in {path}")
    return int(matches[-1])

focused = passed("/tmp/advisory-promotion-focused.txt")
full = passed("/tmp/advisory-promotion-full.txt")
if focused != 61:
    raise SystemExit(f"focused test count drifted: {focused} != 61")
if full != 454:
    raise SystemExit(f"full test count drifted: {full} != 454")
PY

# Dependency, privacy, side-effect, and no-stub audit. Attribute calls such as
# re.compile are distinct from the forbidden builtin compile call.
python - <<'PY'
from __future__ import annotations

import ast
from pathlib import Path

module_path = Path("src/nextgen_memory/policy_promotion_gate.py")
source = module_path.read_text(encoding="utf-8")
tree = ast.parse(source, filename=str(module_path))
forbidden_roots = {
    "asyncio",
    "datetime",
    "httpx",
    "os",
    "pathlib",
    "psycopg",
    "pymongo",
    "random",
    "requests",
    "socket",
    "sqlalchemy",
    "subprocess",
    "temporalio",
    "time",
    "urllib",
}
forbidden_builtins = {
    "compile",
    "eval",
    "exec",
    "open",
}
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
    if isinstance(node, ast.Pass):
        findings.append(f"{node.lineno}:pass")
    elif isinstance(node, ast.Constant) and node.value is Ellipsis:
        findings.append(f"{node.lineno}:ellipsis")
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
    elif isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name.split(".", 1)[0] in forbidden_roots:
                findings.append(f"{node.lineno}:import:{alias.name}")
    elif isinstance(node, ast.ImportFrom):
        if node.level == 0 and (node.module or "").split(".", 1)[0] in forbidden_roots:
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
    "postgresql://",
    "mongodb://",
    "http://",
    "https://",
    "password",
    "credential",
    "# todo",
    "# fixme",
    "raw_query",
    "raw_prompt",
    "response_text",
    "memory_body",
    "lease_timestamp",
    "worker_identity",
    "activate_policy(",
    "write_feedback(",
):
    if marker in lowered:
        findings.append(f"text:{marker}")

for test_path in (
    Path("tests/test_policy_promotion_gate.py"),
    Path("tests/test_policy_promotion_gate_properties.py"),
    Path("tests/test_policy_promotion_gate_public_api.py"),
):
    test_source = test_path.read_text(encoding="utf-8").lower()
    for marker in (
        "pytest.mark.skip",
        "pytest.mark.xfail",
        "# noqa",
        "notimplementederror",
    ):
        if marker in test_source:
            findings.append(f"{test_path}:text:{marker}")

if findings:
    raise SystemExit("\n".join(findings))
print("advisory_policy_promotion_audit_findings=0")
PY

# Generate one bounded semantic matrix under two independent hash seeds.
cat > /tmp/generate_advisory_policy_promotion_evidence.py <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from uuid import UUID

from nextgen_memory.paired_rerank_policy_evaluation import PairedPolicyVerdict
from nextgen_memory.policy_promotion_gate import (
    AdvisoryPolicyPromotionGate,
    PairedPolicyEvidence,
    PolicyIdentity,
    PolicyOperationalReadiness,
    PolicyPromotionDecision,
    PolicyPromotionGateConfig,
    PolicyPromotionReason,
    PolicyPromotionRequest,
    PolicyPromotionValidationError,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


base_sha = sys.argv[2]
candidate_sha = sys.argv[3]
current = PolicyIdentity(
    policy_version="control-v1",
    policy_fingerprint=digest("control-policy"),
    source_sha=base_sha,
)
candidate = PolicyIdentity(
    policy_version="treatment-v1",
    policy_fingerprint=digest("treatment-policy"),
    source_sha=candidate_sha,
)
config = PolicyPromotionGateConfig(
    minimum_matched_pairs=20,
    minimum_score_lower_bound=0.0,
    maximum_score_standard_error=0.05,
    maximum_mean_token_delta=10.0,
    maximum_mean_latency_delta_ms=20.0,
    maximum_harm_rate=0.05,
    maximum_evidence_age_seconds=3600.0,
    minimum_reviewer_count=2,
)
ready = PolicyOperationalReadiness(
    tests_passed=True,
    integration_passed=True,
    artifact_integrity_passed=True,
    rollback_ready=True,
    safety_violation=False,
    reviewer_count=2,
    evidence_age_seconds=60.0,
)


def evidence(**overrides: object) -> PairedPolicyEvidence:
    values: dict[str, object] = {
        "evaluation_id": UUID("00000000-0000-5000-8000-00000000f401"),
        "evaluation_content_hash": digest("evaluation"),
        "control_policy_version": current.policy_version,
        "control_policy_fingerprint": current.policy_fingerprint,
        "treatment_policy_version": candidate.policy_version,
        "treatment_policy_fingerprint": candidate.policy_fingerprint,
        "evaluated_base_sha": current.source_sha,
        "evaluated_candidate_sha": candidate.source_sha,
        "verdict": PairedPolicyVerdict.PROMISING,
        "matched_pair_count": 24,
        "mean_score_effect": 0.08,
        "score_confidence_lower_bound": 0.04,
        "score_confidence_upper_bound": 0.12,
        "score_standard_error": 0.02,
        "mean_token_delta": 4.0,
        "mean_latency_delta_ms": 8.0,
        "harm_rate": 0.01,
        "registry_summary_content_hash": digest("registry-summary"),
        "registry_pair_count": 24,
        "registry_completed_trial_count": 24,
        "registry_failed_count": 0,
        "registry_cancelled_count": 0,
        "registry_active_count": 0,
    }
    values.update(overrides)
    return PairedPolicyEvidence(**values)  # type: ignore[arg-type]


def request(
    *,
    evaluation: PairedPolicyEvidence,
    readiness: PolicyOperationalReadiness = ready,
) -> PolicyPromotionRequest:
    return PolicyPromotionRequest(
        current_policy=current,
        candidate_policy=candidate,
        evaluation=evaluation,
        readiness=readiness,
    )


gate = AdvisoryPolicyPromotionGate()
promote_request = request(evaluation=evidence())
failed_request = request(
    evaluation=evidence(
        registry_pair_count=25,
        registry_completed_trial_count=24,
        registry_failed_count=1,
    )
)
cancelled_request = request(
    evaluation=evidence(
        registry_pair_count=25,
        registry_completed_trial_count=24,
        registry_cancelled_count=1,
    )
)
safety_request = request(
    evaluation=evidence(),
    readiness=PolicyOperationalReadiness(
        tests_passed=False,
        integration_passed=False,
        artifact_integrity_passed=False,
        rollback_ready=False,
        safety_violation=True,
        reviewer_count=0,
        evidence_age_seconds=7200.0,
    ),
)
records = {
    "promote": gate.evaluate(promote_request, config),
    "hold_cancelled": gate.evaluate(cancelled_request, config),
    "hold_failed": gate.evaluate(failed_request, config),
    "reject_safety": gate.evaluate(safety_request, config),
}
if records["promote"].decision is not PolicyPromotionDecision.PROMOTE:
    raise SystemExit("complete promising evidence did not promote")
if records["promote"].reasons != (PolicyPromotionReason.ALL_GATES_PASSED,):
    raise SystemExit("promote reasons differ")
for name in ("hold_failed", "hold_cancelled"):
    record = records[name]
    if record.decision is not PolicyPromotionDecision.HOLD:
        raise SystemExit(f"{name} did not hold")
    if PolicyPromotionReason.REGISTRY_INCOMPLETE not in record.reasons:
        raise SystemExit(f"{name} lacks registry_incomplete")
if records["reject_safety"].decision is not PolicyPromotionDecision.REJECT:
    raise SystemExit("safety violation did not reject")
if records["reject_safety"].reasons != (PolicyPromotionReason.SAFETY_VIOLATION,):
    raise SystemExit("hard-reject precedence leaked hold reasons")

for field_name in (
    "maximum_mean_token_delta",
    "maximum_mean_latency_delta_ms",
):
    kwargs = config.to_dict()
    kwargs.pop("gate_policy_version", None)
    kwargs[field_name] = -0.001
    try:
        PolicyPromotionGateConfig(**kwargs)
    except PolicyPromotionValidationError:
        continue
    raise SystemExit(f"negative threshold was accepted: {field_name}")

expected = records["promote"].render_json()
for _ in range(1000):
    retry = gate.evaluate(promote_request, config).render_json()
    if retry != expected:
        raise SystemExit("exact retry changed canonical JSON")

payload = {
    "base_sha": base_sha,
    "candidate_sha": candidate_sha,
    "config_content_hash": config.content_hash,
    "records": {
        name: json.loads(record.render_json())
        for name, record in sorted(records.items())
    },
    "retry_count": 1000,
}
raw = json.dumps(
    payload,
    ensure_ascii=False,
    allow_nan=False,
    sort_keys=True,
    separators=(",", ":"),
) + "\n"
for forbidden in (
    "raw_query",
    "raw_prompt",
    "memory_body",
    "response_text",
    "credential",
    "worker_identity",
    "activate_policy",
    "write_feedback",
):
    if forbidden in raw.lower():
        raise SystemExit(f"semantic evidence leaked forbidden text: {forbidden}")
Path(sys.argv[1]).write_text(raw, encoding="utf-8")
PY

PYTHONHASHSEED=1 python /tmp/generate_advisory_policy_promotion_evidence.py \
  "$EVIDENCE_ROOT/semantic.json" "$BASE_SHA" "$CANDIDATE_SHA"
PYTHONHASHSEED=999 python /tmp/generate_advisory_policy_promotion_evidence.py \
  /tmp/advisory-promotion-semantic-seed-999.json "$BASE_SHA" "$CANDIDATE_SHA"
cmp "$EVIDENCE_ROOT/semantic.json" /tmp/advisory-promotion-semantic-seed-999.json

# Build and import the exact wheel outside the checkout.
WHEELHOUSE="$RUNNER_TEMP/advisory-promotion-wheelhouse-${PYTHON_VERSION:-python}"
VENV="$RUNNER_TEMP/advisory-promotion-wheel-venv-${PYTHON_VERSION:-python}"
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
    AdvisoryPolicyPromotionGate,
    PairedPolicyEvidence,
    PolicyIdentity,
    PolicyOperationalReadiness,
    PolicyPromotionDecision,
    PolicyPromotionGateConfig,
    PolicyPromotionReason,
    PolicyPromotionRecord,
    PolicyPromotionRequest,
    PolicyPromotionValidationError,
)

assert AdvisoryPolicyPromotionGate is not None
assert PairedPolicyEvidence is not None
assert PolicyIdentity is not None
assert PolicyOperationalReadiness is not None
assert PolicyPromotionDecision.PROMOTE.value == "promote"
assert PolicyPromotionGateConfig is not None
assert PolicyPromotionReason.ALL_GATES_PASSED.value == "all_gates_passed"
assert PolicyPromotionRecord is not None
assert PolicyPromotionRequest is not None
assert PolicyPromotionValidationError is not None
for name in (
    "AdvisoryPolicyPromotionGate",
    "PairedPolicyEvidence",
    "PolicyIdentity",
    "PolicyOperationalReadiness",
    "PolicyPromotionDecision",
    "PolicyPromotionGateConfig",
    "PolicyPromotionReason",
    "PolicyPromotionRecord",
    "PolicyPromotionRequest",
    "PolicyPromotionValidationError",
):
    assert name in nextgen_memory.__all__
PY
run "$VENV/bin/python" -m pip check
cp "$WHEEL" "$EVIDENCE_ROOT/"
WHEEL_COPY=$(find "$EVIDENCE_ROOT" -maxdepth 1 -type f -name '*.whl')
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
    matches = re.findall(r"(\d+) passed", Path(path).read_text(encoding="utf-8"))
    if not matches:
        raise SystemExit(f"missing pytest pass count in {path}")
    return int(matches[-1])

root = Path(os.environ["EVIDENCE_ROOT"])
semantic = root / "semantic.json"
report = {
    "schema": "m-head-advisory-policy-promotion-verification-v1",
    "base_sha": os.environ["BASE_SHA"],
    "candidate_sha": os.environ["CANDIDATE_SHA"],
    "python_version": ".".join(map(str, sys.version_info[:3])),
    "focused_test_count": passed("/tmp/advisory-promotion-focused.txt"),
    "full_test_count": passed("/tmp/advisory-promotion-full.txt"),
    "exact_path_count": 8,
    "semantic_sha256": hashlib.sha256(semantic.read_bytes()).hexdigest(),
    "wheel_sha256": (root / "wheel.sha256").read_text(encoding="utf-8").strip(),
    "hash_seed_invariant": True,
    "exact_retry_count": 1000,
    "audit_findings": 0,
    "isolated_wheel_import": True,
}
(root / "verification.json").write_text(
    json.dumps(
        report,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n",
    encoding="utf-8",
)
print((root / "verification.json").read_text(encoding="utf-8"), end="")
PY

test -z "$(git status --porcelain)"
