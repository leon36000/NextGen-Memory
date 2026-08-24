#!/usr/bin/env bash
set -euo pipefail

REPO="${GITHUB_REPOSITORY}"
TARGET_BRANCH='feat/advisory-policy-promotion-gate-v0-20260824'
BASE_BRANCH='candidate/paired-replay-experiment-registry-v0-20260824'
ORIGINAL_RED_BRANCH='tdd/advisory-policy-promotion-gate-v0-red-20260824'
RED_V2_BRANCH='tdd/advisory-policy-promotion-gate-v0-red-v2-20260824'
CANDIDATE_BRANCH='candidate/advisory-policy-promotion-gate-v0-20260824'

run() {
  printf '+ %q ' "$@"
  printf '\n'
  "$@"
}

git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
run git fetch --no-tags origin '+refs/heads/*:refs/remotes/origin/*'
BASE_SHA=$(git rev-parse "origin/$BASE_BRANCH")
ORIGINAL_RED_SHA=$(git rev-parse "origin/$ORIGINAL_RED_BRANCH")
TARGET_SHA=$(git rev-parse "origin/$TARGET_BRANCH")
test "$BASE_SHA" = '91d14e9ff9f8c89d05cb2349b012a6681bf3d828'
test "$(git merge-base "$BASE_SHA" "$ORIGINAL_RED_SHA")" = "$BASE_SHA"
test "$(git merge-base "$BASE_SHA" "$TARGET_SHA")" = "$BASE_SHA"

printf 'base_sha=%s\noriginal_red_sha=%s\ntarget_sha=%s\n' \
  "$BASE_SHA" "$ORIGINAL_RED_SHA" "$TARGET_SHA"

# Build a corrected tests-only RED without rewriting the original immutable RED.
RED_ROOT="$RUNNER_TEMP/advisory-policy-promotion-red-v2"
rm -rf "$RED_ROOT"
run git worktree add --detach "$RED_ROOT" "$BASE_SHA"
mkdir -p "$RED_ROOT/docs" "$RED_ROOT/tests"
for path in \
  docs/policy-promotion-gate-v0-red.md \
  tests/test_policy_promotion_gate.py \
  tests/test_policy_promotion_gate_properties.py \
  tests/test_policy_promotion_gate_public_api.py; do
  git show "$ORIGINAL_RED_SHA:$path" > "$RED_ROOT/$path"
done

ROOT="$RED_ROOT" python - <<'PY'
from pathlib import Path
import os

path = Path(os.environ["ROOT"]) / "tests/test_policy_promotion_gate.py"
source = path.read_text(encoding="utf-8")
old = "request(evaluation=paired_evidence(registry_completed_trial_count=23)),"
new = '''request(
    evaluation=paired_evidence(
        registry_completed_trial_count=23,
        registry_active_count=1,
    )
),'''
if source.count(old) != 1:
    raise SystemExit(
        f"expected one invalid registry mismatch fixture, found {source.count(old)}"
    )
path.write_text(source.replace(old, new, 1), encoding="utf-8")
PY

cat > "$RED_ROOT/docs/policy-promotion-gate-v0-red.md" <<EOF
# Advisory Policy Promotion Gate v0 — TDD RED v2 Evidence

**Date:** 2026-08-24
**Base branch:** \`$BASE_BRANCH\`
**Base SHA:** \`$BASE_SHA\`
**Original RED SHA:** \`$ORIGINAL_RED_SHA\`
**Corrected RED branch:** \`$RED_V2_BRANCH\`

The three tests-only contract files are Ruff-clean and syntactically valid. The registry/evaluation mismatch fixture preserves a valid registry partition by pairing 23 completed trials with one active pair. Against the immutable base, every test file independently reaches only the absence of \`nextgen_memory.policy_promotion_gate\`; the implementation and package-root exports are absent.

This corrected RED supersedes the original test tree for product qualification without rewriting the original immutable evidence.
EOF

pushd "$RED_ROOT" >/dev/null
RED_FILES=(
  tests/test_policy_promotion_gate.py
  tests/test_policy_promotion_gate_properties.py
  tests/test_policy_promotion_gate_public_api.py
)
run ruff format "${RED_FILES[@]}"
run ruff check --fix "${RED_FILES[@]}"
run ruff check "${RED_FILES[@]}"
run ruff format --check "${RED_FILES[@]}"
run python -m py_compile "${RED_FILES[@]}"
run git diff --check
test ! -e src/nextgen_memory/policy_promotion_gate.py
if grep -F 'policy_promotion_gate' src/nextgen_memory/__init__.py; then
  echo 'immutable base unexpectedly exports absent module' >&2
  exit 1
fi

for file in "${RED_FILES[@]}"; do
  output="/tmp/$(basename "$file" .py)-red-v2.txt"
  set +e
  PYTHONPATH="$PWD/src" python -m pytest --collect-only -q "$file" > "$output" 2>&1
  rc=$?
  set -e
  test "$rc" -ne 0
  FILE="$file" OUTPUT="$output" python - <<'PY'
from __future__ import annotations

import os
import re
from pathlib import Path

text = Path(os.environ["OUTPUT"]).read_text(
    encoding="utf-8",
    errors="replace",
)
modules = set(
    re.findall(
        r"ModuleNotFoundError: No module named '([^']+)'",
        text,
    )
)
if modules != {"nextgen_memory.policy_promotion_gate"}:
    raise SystemExit(
        f"{os.environ['FILE']}: unexpected missing modules {sorted(modules)!r}"
    )
for marker in (
    "SyntaxError",
    "IndentationError",
    "NameError",
    "ERROR at setup",
):
    if marker in text:
        raise SystemExit(
            f"{os.environ['FILE']}: unintended RED marker {marker}"
        )
PY
done

run git add \
  docs/policy-promotion-gate-v0-red.md \
  tests/test_policy_promotion_gate.py \
  tests/test_policy_promotion_gate_properties.py \
  tests/test_policy_promotion_gate_public_api.py
run git diff --cached --check
mapfile -t RED_CHANGED < <(git diff --cached --name-only | sort)
RED_EXPECTED=(
  docs/policy-promotion-gate-v0-red.md
  tests/test_policy_promotion_gate.py
  tests/test_policy_promotion_gate_properties.py
  tests/test_policy_promotion_gate_public_api.py
)
test "${#RED_CHANGED[@]}" -eq "${#RED_EXPECTED[@]}"
diff -u \
  <(printf '%s\n' "${RED_EXPECTED[@]}" | sort) \
  <(printf '%s\n' "${RED_CHANGED[@]}")
PROPOSED_RED_TREE=$(git write-tree)
REMOTE_RED_SHA=$(git ls-remote --heads origin "$RED_V2_BRANCH" | awk '{print $1}')
if [[ -n "$REMOTE_RED_SHA" ]]; then
  run git fetch --no-tags origin "+refs/heads/$RED_V2_BRANCH:refs/remotes/origin/$RED_V2_BRANCH"
  test "$(git rev-parse "origin/$RED_V2_BRANCH^{tree}")" = "$PROPOSED_RED_TREE"
  RED_V2_SHA="$REMOTE_RED_SHA"
else
  run git commit -m 'test: correct advisory promotion gate RED fixture'
  RED_V2_SHA=$(git rev-parse HEAD)
  run git push origin "$RED_V2_SHA:refs/heads/$RED_V2_BRANCH"
fi
popd >/dev/null
run git worktree remove --force "$RED_ROOT"
printf 'red_v2_sha=%s\n' "$RED_V2_SHA"

# Move to the real product branch and bind it to RED v2.
run git switch -C "$TARGET_BRANCH" "origin/$TARGET_BRANCH"
run git checkout "$RED_V2_SHA" -- \
  docs/policy-promotion-gate-v0-red.md \
  tests/test_policy_promotion_gate.py \
  tests/test_policy_promotion_gate_properties.py \
  tests/test_policy_promotion_gate_public_api.py
run python -m pip install -e '.[dev]'
run ruff check \
  tests/test_policy_promotion_gate.py \
  tests/test_policy_promotion_gate_properties.py \
  tests/test_policy_promotion_gate_public_api.py
run python -m pytest -q \
  tests/test_policy_promotion_gate.py::test_each_hard_rejection_condition_is_bounded

# Add two semantic contracts and prove the current implementation fails them.
python - <<'PY'
from pathlib import Path

path = Path("tests/test_policy_promotion_gate.py")
source = path.read_text(encoding="utf-8")
marker = "def test_cost_thresholds_must_be_nonnegative() -> None:"
if marker not in source:
    source += '''


@pytest.mark.parametrize(
    "field_name",
    ("maximum_mean_token_delta", "maximum_mean_latency_delta_ms"),
)
def test_cost_thresholds_must_be_nonnegative(field_name: str) -> None:
    with pytest.raises(PolicyPromotionValidationError, match=field_name):
        config(**{field_name: -0.001})


@pytest.mark.parametrize(
    "terminal_counts",
    (
        {"registry_failed_count": 1},
        {"registry_cancelled_count": 1},
    ),
)
def test_terminal_non_complete_registry_state_holds(
    terminal_counts: dict[str, int],
) -> None:
    values: dict[str, object] = {
        "registry_pair_count": 25,
        "registry_completed_trial_count": 24,
        "registry_failed_count": 0,
        "registry_cancelled_count": 0,
        "registry_active_count": 0,
    }
    values.update(terminal_counts)

    record = evaluate(request(evaluation=paired_evidence(**values)))

    assert record.decision is PolicyPromotionDecision.HOLD
    assert PolicyPromotionReason.REGISTRY_INCOMPLETE in record.reasons
'''
path.write_text(source, encoding="utf-8")
PY
run ruff format tests/test_policy_promotion_gate.py
run ruff check --fix tests/test_policy_promotion_gate.py
run ruff check tests/test_policy_promotion_gate.py

set +e
python -m pytest -q \
  tests/test_policy_promotion_gate.py::test_cost_thresholds_must_be_nonnegative \
  tests/test_policy_promotion_gate.py::test_terminal_non_complete_registry_state_holds \
  > /tmp/semantic-red-v2.txt 2>&1
SEMANTIC_RED_RC=$?
set -e
cat /tmp/semantic-red-v2.txt
test "$SEMANTIC_RED_RC" -ne 0
grep -F 'test_cost_thresholds_must_be_nonnegative' /tmp/semantic-red-v2.txt >/dev/null
grep -F 'test_terminal_non_complete_registry_state_holds' /tmp/semantic-red-v2.txt >/dev/null
grep -F 'failed' /tmp/semantic-red-v2.txt >/dev/null

# Apply the smallest implementation changes that satisfy the new RED contracts.
python - <<'PY'
from pathlib import Path

path = Path("src/nextgen_memory/policy_promotion_gate.py")
source = path.read_text(encoding="utf-8")
replacements = (
    (
        'maximum_mean_token_delta = _finite_number(\n'
        '            "maximum_mean_token_delta", self.maximum_mean_token_delta\n'
        '        )',
        'maximum_mean_token_delta = _nonnegative_number(\n'
        '            "maximum_mean_token_delta", self.maximum_mean_token_delta\n'
        '        )',
    ),
    (
        'maximum_mean_latency_delta_ms = _finite_number(\n'
        '            "maximum_mean_latency_delta_ms",\n'
        '            self.maximum_mean_latency_delta_ms,\n'
        '        )',
        'maximum_mean_latency_delta_ms = _nonnegative_number(\n'
        '            "maximum_mean_latency_delta_ms",\n'
        '            self.maximum_mean_latency_delta_ms,\n'
        '        )',
    ),
)
for old, new in replacements:
    if new not in source:
        if source.count(old) != 1:
            raise SystemExit(f"expected one exact threshold block: {old!r}")
        source = source.replace(old, new, 1)

old_registry = (
    "        if evidence.registry_active_count > 0:\n"
    "            hold_reasons.append(PolicyPromotionReason.REGISTRY_INCOMPLETE)"
)
new_registry = (
    "        if (\n"
    "            evidence.registry_active_count > 0\n"
    "            or evidence.registry_failed_count > 0\n"
    "            or evidence.registry_cancelled_count > 0\n"
    "        ):\n"
    "            hold_reasons.append(PolicyPromotionReason.REGISTRY_INCOMPLETE)"
)
if new_registry not in source:
    if source.count(old_registry) != 1:
        raise SystemExit("expected one exact registry-incomplete block")
    source = source.replace(old_registry, new_registry, 1)
path.write_text(source, encoding="utf-8")
PY
run ruff format src/nextgen_memory/policy_promotion_gate.py
run ruff check --fix src/nextgen_memory/policy_promotion_gate.py
run python -m pytest -q \
  tests/test_policy_promotion_gate.py::test_cost_thresholds_must_be_nonnegative \
  tests/test_policy_promotion_gate.py::test_terminal_non_complete_registry_state_holds

# Add the package-root API without weakening existing exports.
python - <<'PY'
from __future__ import annotations

import ast
from pathlib import Path

path = Path("src/nextgen_memory/__init__.py")
source = path.read_text(encoding="utf-8")
required = {
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
}
block = '''from .policy_promotion_gate import (
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
'''
if "from .policy_promotion_gate import (" not in source:
    markers = (
        "from .paired_replay_experiment_registry import (",
        "from .paired_rerank_policy_evaluation import (",
    )
    marker = next((item for item in markers if source.count(item) == 1), None)
    if marker is None:
        raise SystemExit("no unambiguous package import marker")
    source = source.replace(marker, block + marker, 1)

module = ast.parse(source)
values = None
for statement in module.body:
    if (
        isinstance(statement, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        )
        and isinstance(statement.value, (ast.List, ast.Tuple))
    ):
        values = [
            item.value
            for item in statement.value.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        ]
        break
if values is None:
    raise SystemExit("package __all__ is not a literal list or tuple")
start = source.index("__all__ = [")
end = source.index("\n]", start) + 2
replacement = "__all__ = [\n" + "".join(
    f'    "{name}",\n' for name in sorted(set(values).union(required))
) + "]"
source = source[:start] + replacement + source[end:]
ast.parse(source)
path.write_text(source, encoding="utf-8")
PY

# Record design and execution contracts.
mkdir -p docs/superpowers/specs docs/superpowers/plans
cat > docs/superpowers/specs/2026-08-24-advisory-policy-promotion-gate-v0-design.md <<'EOF'
# Advisory Policy Promotion Gate v0 Design

**Date:** 2026-08-24
**Status:** implementation candidate
**Base:** `candidate/paired-replay-experiment-registry-v0-20260824`

The gate converts immutable matched-policy evidence and bounded operational readiness into one advisory `promote`, `hold`, or `reject` record. Hard safety, identity, registry/evaluation, harmful-verdict, negative-effect, and token/latency/harm breaches reject before any hold condition. In the absence of rejection, insufficient evidence, non-positive lower confidence, excess uncertainty, stale evidence, any active, failed, or cancelled registry pair, or operational/reviewer gaps hold. Promotion requires a complete `promising` evaluation.

All identifiers, counts, rates, confidence bounds, thresholds, and booleans are validated before evaluation. Token and latency thresholds are non-negative. Canonical JSON, SHA-256, and UUID5 bind all material inputs. No free-form content or activation, persistence, database, network, clock, environment, feedback, migration, deployment, merge, or release surface belongs in v0.
EOF

cat > docs/superpowers/plans/2026-08-24-advisory-policy-promotion-gate-v0.md <<'EOF'
# Advisory Policy Promotion Gate v0 — Implementation Plan

**Date:** 2026-08-24
**Base:** `candidate/paired-replay-experiment-registry-v0-20260824`

1. Preserve the original RED and create RED v2 with a valid registry-partition mismatch fixture.
2. Prove new RED tests for non-negative cost thresholds and failed/cancelled registry states.
3. Apply only the minimal threshold and registry-completeness fixes.
4. Export the bounded public API and canonical identities.
5. Run malformed-input, threshold-neighborhood, generated-property, retry, hash-seed, full-suite, audit, and isolated-wheel checks.
6. Publish an immutable candidate only after every check passes.
7. Require independent Python 3.12/3.13 exact-SHA verification and genuine GPT-5.6 Sol approval before merge.

Merge, deployment, migration, feedback, activation, and release remain separate operations.
EOF

# Normalize and execute the complete product verification.
PRODUCT_FILES=(
  src/nextgen_memory/__init__.py
  src/nextgen_memory/policy_promotion_gate.py
  tests/test_policy_promotion_gate.py
  tests/test_policy_promotion_gate_properties.py
  tests/test_policy_promotion_gate_public_api.py
)
run ruff format "${PRODUCT_FILES[@]}"
run ruff check --fix "${PRODUCT_FILES[@]}"
run ruff check "${PRODUCT_FILES[@]}"
run ruff format --check "${PRODUCT_FILES[@]}"
run python -m compileall -q src scripts
run python -m pytest -q \
  tests/test_policy_promotion_gate.py \
  tests/test_policy_promotion_gate_properties.py \
  tests/test_policy_promotion_gate_public_api.py
run ruff check .
run python -m pytest -q
run git diff --check

python - <<'PY'
from __future__ import annotations

import ast
from pathlib import Path

source = Path("src/nextgen_memory/policy_promotion_gate.py").read_text(
    encoding="utf-8"
)
tree = ast.parse(source)
forbidden_roots = {
    "asyncio", "datetime", "httpx", "os", "pathlib", "psycopg",
    "pymongo", "random", "requests", "socket", "sqlalchemy",
    "subprocess", "temporalio", "time", "urllib",
}
forbidden_calls = {
    "eval", "exec", "compile", "open", "sleep", "system",
    "urlopen", "uuid1", "uuid4", "write_bytes", "write_text",
}
findings = []
for node in ast.walk(tree):
    if isinstance(node, ast.Pass):
        findings.append(f"{node.lineno}:pass")
    elif isinstance(node, ast.Raise):
        exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
        if (
            isinstance(exc, ast.Name) and exc.id == "NotImplementedError"
        ) or (
            isinstance(exc, ast.Attribute) and exc.attr == "NotImplementedError"
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
    "postgresql://", "mongodb://", "http://", "https://",
    "password", "credential", "# todo", "# fixme", "raw_query",
    "raw_prompt", "response_text", "memory_body", "lease_timestamp",
    "worker_identity", "activate_policy(", "write_feedback(",
):
    if marker in lowered:
        findings.append(f"text:{marker}")
if findings:
    raise SystemExit("\n".join(findings))
print("policy_promotion_gate_audit_findings=0")
PY

rm -rf wheelhouse "$RUNNER_TEMP/promotion-wheel-venv"
run python -m pip wheel --no-deps . -w wheelhouse
WHEEL=$(find wheelhouse -maxdepth 1 -type f -name '*.whl')
test -n "$WHEEL"
run python -m venv "$RUNNER_TEMP/promotion-wheel-venv"
run "$RUNNER_TEMP/promotion-wheel-venv/bin/python" -m pip install --no-deps "$WHEEL"
"$RUNNER_TEMP/promotion-wheel-venv/bin/python" - <<'PY'
import nextgen_memory
from nextgen_memory import AdvisoryPolicyPromotionGate, PolicyPromotionDecision

assert AdvisoryPolicyPromotionGate is not None
assert PolicyPromotionDecision.PROMOTE.value == "promote"
assert "AdvisoryPolicyPromotionGate" in nextgen_memory.__all__
PY
run "$RUNNER_TEMP/promotion-wheel-venv/bin/python" -m pip check

# Strip all transport files and prove the final candidate is exactly eight paths.
rm -f \
  .github/workflows/finalize-advisory-policy-promotion-gate-v7.yml \
  .github/workflows/finalize-policy-promotion-gate-once.yml \
  .github/workflows/record-policy-promotion-gate-red-once.yml \
  .github/workflows/record-policy-promotion-gate-red-v3-once.yml \
  .github/workflows/record-policy-promotion-gate-red-v4-once.yml \
  .github/workflows/record-policy-promotion-gate-red-v5-once.yml
run git add -A
mapfile -t CHANGED < <(git diff --cached --name-only "$BASE_SHA" | sort)
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
test -z "$(git diff --cached --name-only "$BASE_SHA" -- '.github/workflows/**' 'migrations/**' pyproject.toml 'src/nextgen_memory/corrective_retrieval_*')"
run git diff --cached --check

run git commit -m 'feat: add advisory policy promotion gate v0'
PRODUCT_SHA=$(git rev-parse HEAD)
run git push origin HEAD:"$TARGET_BRANCH"
EXISTING_CANDIDATE=$(git ls-remote --heads origin "$CANDIDATE_BRANCH" | awk '{print $1}')
if [[ -n "$EXISTING_CANDIDATE" ]]; then
  test "$EXISTING_CANDIDATE" = "$PRODUCT_SHA"
else
  run git push origin "$PRODUCT_SHA:refs/heads/$CANDIDATE_BRANCH"
fi

BODY=$(cat <<EOF
## Advisory policy promotion gate producer GREEN

- base: \`$BASE_SHA\`;
- corrected tests-only RED v2: \`$RED_V2_SHA\`;
- product: \`$PRODUCT_SHA\`;
- exact eight-path product surface;
- corrected valid registry-partition mismatch fixture;
- semantic RED→GREEN for non-negative cost thresholds and failed/cancelled registry states;
- focused/full tests, strict audit, and isolated wheel import: green;
- activation, persistence, feedback, migration, deployment, merge, and release: none;
- exact Python 3.12/3.13 verification and genuine GPT-5.6 Sol review remain mandatory.
EOF
)
gh api "repos/$REPO/issues/23/comments" --raw-field body="$BODY" >/dev/null
SELF_PR=$(python - <<'PY'
import json
import os
from pathlib import Path

payload = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
print(payload["pull_request"]["number"])
PY
)
gh api --method PATCH "repos/$REPO/pulls/$SELF_PR" -f state=closed >/dev/null
printf 'product_sha=%s\nred_v2_sha=%s\n' "$PRODUCT_SHA" "$RED_V2_SHA"
