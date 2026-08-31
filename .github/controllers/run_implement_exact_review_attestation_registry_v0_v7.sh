#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/implement_exact_review_attestation_registry_v0.sh"
TARGET="$RUNNER_TEMP/implement_exact_review_attestation_registry_v0_v7.sh"
cp "$SOURCE" "$TARGET"

python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["RUNNER_TEMP"]) / (
    "implement_exact_review_attestation_registry_v0_v7.sh"
)
lines = path.read_text(encoding="utf-8").splitlines()
out: list[str] = []
red_v2_field_occurrences = 0
reference_name_occurrences = 0
counts = {
    "red_v3_variable": 0,
    "pep695_before_validation": 0,
    "red_contract_overlay": 0,
    "reference_red_v3": 0,
    "pin_ruff": 0,
    "summary_red_v3": 0,
    "summary_ast_digest": 0,
    "summary_env_ast_digest": 0,
    "status_red_v3": 0,
}

for line in lines:
    if line == "RED_V2_SHA='4f0a74e0d39a181b682d2b135012184c255928bc'":
        out.append(line)
        out.append("RED_V3_SHA='0a8e193269e425dd51f740b495579f949a237ce1'")
        counts["red_v3_variable"] += 1
        continue

    if line == "# RED v2 remains the exact product test contract.":
        out.extend(
            (
                'python "$CONTROLLER_ROOT/.github/controllers/apply_exact_review_attestation_pep695.py" "$PRODUCT_ROOT/src/nextgen_memory/review_attestation_registry.py"',
                'git cat-file -e "$RED_V3_SHA^{commit}"',
                'test "$(git merge-base "$BASE_SHA" "$RED_V3_SHA")" = "$BASE_SHA"',
                'git checkout "$RED_V3_SHA" -- "${RED_PATHS[@]}"',
                "",
                "# RED v3 is the exact semantic test contract. Product-context import",
                "# grouping may change source bytes only when the implementation exists;",
                "# post-Ruff AST identity is proven before any test runs.",
            )
        )
        counts["pep695_before_validation"] += 1
        counts["red_contract_overlay"] += 1
        continue

    if 'git show "$RED_V2_SHA:$path" > "$reference"' in line:
        out.append(line.replace("$RED_V2_SHA:$path", "$RED_V3_SHA:$path", 1))
        counts["reference_red_v3"] += 1
        continue

    if 'reference="$RUNNER_TEMP/red-v2-' in line:
        out.append(line.replace("red-v2-", "red-v3-", 1))
        reference_name_occurrences += 1
        continue

    if line == "run python -m pip install -e '.[dev]'":
        out.append(line)
        out.append("run python -m pip install 'ruff==0.16.4'")
        out.append("run ruff --version")
        counts["pin_ruff"] += 1
        continue

    if line.strip() == "'red_v2_sha': '4f0a74e0d39a181b682d2b135012184c255928bc',":
        red_v2_field_occurrences += 1
        out.append(line)
        if red_v2_field_occurrences == 2:
            indentation = line[: len(line) - len(line.lstrip())]
            out.append(
                indentation
                + "'red_v3_sha': '0a8e193269e425dd51f740b495579f949a237ce1',"
            )
            out.append(indentation + "'ruff_version': '0.16.4',")
            out.append(indentation + "'red_v3_test_ast_preserved': True,")
            out.append(
                indentation
                + "'product_context_import_formatting_only': True,"
            )
            counts["summary_red_v3"] += 1
        continue

    if line.strip() == "'ruff_clean': True,":
        out.append(line)
        indentation = line[: len(line) - len(line.lstrip())]
        out.append(
            indentation
            + "'red_v3_test_ast_preservation_sha256': "
            + "os.environ['RED_AST_SHA'],"
        )
        counts["summary_ast_digest"] += 1
        continue

    if line.startswith('FOCUSED_COUNT="$FOCUSED_COUNT" FULL_COUNT='):
        if 'RED_AST_SHA=' in line:
            raise SystemExit('RED_AST_SHA is already present in producer environment')
        out.append(line.removesuffix(' \\') + ' RED_AST_SHA="$RED_AST_SHA" \\')
        counts["summary_env_ast_digest"] += 1
        continue

    if "corrected immutable RED v2" in line and "$RED_V2_SHA" in line:
        out.append(
            line.replace("corrected immutable RED v2", "immutable RED v3")
            .replace("$RED_V2_SHA", "$RED_V3_SHA")
        )
        out.append(line.replace("corrected immutable RED v2", "payload source RED v2"))
        out.append("- RED-v3 test AST preserved after product-context formatting: true;")
        counts["status_red_v3"] += 1
        continue

    out.append(line)

if red_v2_field_occurrences != 2:
    raise SystemExit(
        "expected exactly two red_v2_sha fields "
        f"(payload manifest and producer summary), found {red_v2_field_occurrences}"
    )
if reference_name_occurrences != 2:
    raise SystemExit(
        f"expected two RED reference-name blocks, found {reference_name_occurrences}"
    )
incorrect = {name: count for name, count in counts.items() if count != 1}
if incorrect:
    raise SystemExit(f"unexpected product-controller source shape: {incorrect}")

rendered = "\n".join(out) + "\n"
pep_call = (
    'python "$CONTROLLER_ROOT/.github/controllers/'
    'apply_exact_review_attestation_pep695.py" '
    '"$PRODUCT_ROOT/src/nextgen_memory/review_attestation_registry.py"'
)
if rendered.count(pep_call) != 1:
    raise SystemExit("PEP 695 transform call is absent or duplicated")
if rendered.index(pep_call) > rendered.index("run ruff check --fix"):
    raise SystemExit("PEP 695 transform runs after Ruff")

old_format_block = '''# Fix only source/export formatting. RED tests are immutable and checked below.
run ruff check --fix \\
  src/nextgen_memory/__init__.py \\
  src/nextgen_memory/review_attestation_registry.py
run ruff format \\
  src/nextgen_memory/__init__.py \\
  src/nextgen_memory/review_attestation_registry.py
run ruff check "${PYTHON_PATHS[@]}"
run ruff format --check "${PYTHON_PATHS[@]}"
'''
new_format_block = '''# Normalize the complete Python surface under product context. The RED-v3 test
# semantics remain immutable and are proven by parsed-AST identity below.
run ruff check --fix "${PYTHON_PATHS[@]}"
run ruff format "${PYTHON_PATHS[@]}"
run ruff check "${PYTHON_PATHS[@]}"
run ruff format --check "${PYTHON_PATHS[@]}"
'''
if rendered.count(old_format_block) != 1:
    raise SystemExit(
        "expected one source-only Ruff block, "
        f"found {rendered.count(old_format_block)}"
    )
rendered = rendered.replace(old_format_block, new_format_block, 1)

old_post_ruff = '''run python -m compileall -q src scripts
for path in "${RED_PATHS[@]}"; do
  reference="$RUNNER_TEMP/red-v3-${path//\//_}"
  cmp "$reference" "$path"
done
'''
new_post_ruff = '''run python -m compileall -q src scripts
RED_DOC_REFERENCE="$RUNNER_TEMP/red-v3-doc.md"
git show "$RED_V3_SHA:docs/exact-sha-review-attestation-registry-v0-red.md" \\
  > "$RED_DOC_REFERENCE"
cmp "$RED_DOC_REFERENCE" docs/exact-sha-review-attestation-registry-v0-red.md
RED_V3_SHA="$RED_V3_SHA" python - <<'PYAST'
from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

red_sha = os.environ['RED_V3_SHA']
tests = (
    Path('tests/test_review_attestation_registry.py'),
    Path('tests/test_review_attestation_registry_properties.py'),
    Path('tests/test_review_attestation_registry_public_api.py'),
)
manifest: dict[str, object] = {}
for path in tests:
    red_source = subprocess.check_output(
        ('git', 'show', f'{red_sha}:{path.as_posix()}'),
        text=True,
    )
    product_source = path.read_text(encoding='utf-8')
    red_ast = ast.dump(
        ast.parse(red_source, filename=f'{red_sha}:{path}'),
        annotate_fields=True,
        include_attributes=False,
    )
    product_ast = ast.dump(
        ast.parse(product_source, filename=str(path)),
        annotate_fields=True,
        include_attributes=False,
    )
    if product_ast != red_ast:
        raise SystemExit(f'product formatting changed RED-v3 AST: {path}')
    manifest[path.as_posix()] = {
        'red_source_sha256': hashlib.sha256(
            red_source.encode('utf-8')
        ).hexdigest(),
        'product_source_sha256': hashlib.sha256(
            product_source.encode('utf-8')
        ).hexdigest(),
        'ast_sha256': hashlib.sha256(red_ast.encode('utf-8')).hexdigest(),
        'source_bytes_identical': product_source == red_source,
        'ast_identical': True,
    }
report = {
    'schema': 'm-head-exact-review-attestation-red-v3-ast-preservation-v1',
    'red_v3_sha': red_sha,
    'ruff_version': '0.16.4',
    'product_context_import_formatting_only': True,
    'all_test_asts_identical': True,
    'tests': manifest,
}
destination = Path('/tmp/exact-review-attestation-red-v3-ast-preservation.json')
destination.write_text(
    json.dumps(
        report,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(',', ':'),
    ) + '\n',
    encoding='utf-8',
)
print(destination.read_text(encoding='utf-8'), end='')
PYAST
RED_AST_SHA=$(sha256sum \\
  /tmp/exact-review-attestation-red-v3-ast-preservation.json \\
  | awk '{print $1}')
test -n "$RED_AST_SHA"
'''
if rendered.count(old_post_ruff) != 1:
    raise SystemExit(
        "expected one post-Ruff RED byte-comparison block, "
        f"found {rendered.count(old_post_ruff)}"
    )
rendered = rendered.replace(old_post_ruff, new_post_ruff, 1)

if 'git show "$RED_V2_SHA:$path" > "$reference"' in rendered:
    raise SystemExit("RED v2 is still used as the final test reference")
if "# RED v2 remains the exact product test contract." in rendered:
    raise SystemExit("RED v2 contract marker remains")
if rendered.count('run ruff check --fix "${PYTHON_PATHS[@]}"') != 1:
    raise SystemExit("complete product-context Ruff normalization is absent")
if rendered.count('all_test_asts_identical') != 1:
    raise SystemExit("RED-v3 AST preservation proof is absent")
path.write_text(rendered, encoding="utf-8")
PY

bash -n "$TARGET"
bash "$TARGET" "$@"
