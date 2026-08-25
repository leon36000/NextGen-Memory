#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/implement_exact_review_attestation_registry_v0.sh"
TARGET="$RUNNER_TEMP/implement_exact_review_attestation_registry_v0_v2.sh"
cp "$SOURCE" "$TARGET"

python - <<'PY'
from pathlib import Path

path = Path(__import__('os').environ['RUNNER_TEMP']) / (
    'implement_exact_review_attestation_registry_v0_v2.sh'
)
source = path.read_text(encoding='utf-8')
marker = '''for path in "${EXPECTED_PATHS[@]}"; do
  mkdir -p "$(dirname "$path")"
  cp "$PAYLOAD_ROOT/$path" "$path"
done

# RED v2 remains the exact product test contract.
'''
replacement = '''for path in "${EXPECTED_PATHS[@]}"; do
  mkdir -p "$(dirname "$path")"
  cp "$PAYLOAD_ROOT/$path" "$path"
done

# Ruff UP047 requires Python 3.12 PEP 695 generic-function syntax.
python - <<'PYPEP695'
from pathlib import Path

module_path = Path('src/nextgen_memory/review_attestation_registry.py')
module = module_path.read_text(encoding='utf-8')
replacements = (
    ('from typing import TypeVar\n', ''),
    ('_T = TypeVar("_T")\n', ''),
    (
        'def _require_enum(name: str, value: object, enum_type: type[_T]) -> _T:',
        'def _require_enum[_T](name: str, value: object, enum_type: type[_T]) -> _T:',
    ),
    (
        'def _bounded_unique(\n',
        'def _bounded_unique[_T](\n',
    ),
)
for old, new in replacements:
    if module.count(old) != 1:
        raise SystemExit(f'expected one exact PEP 695 source block: {old!r}')
    module = module.replace(old, new, 1)
module_path.write_text(module, encoding='utf-8')
PYPEP695

# RED v2 remains the exact product test contract.
'''
if source.count(marker) != 1:
    raise SystemExit(
        f'expected one payload-overlay marker, found {source.count(marker)}'
    )
path.write_text(source.replace(marker, replacement, 1), encoding='utf-8')
PY

bash "$TARGET" "$@"
