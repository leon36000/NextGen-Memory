#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/implement_exact_review_attestation_registry_v0.sh"
TARGET="$RUNNER_TEMP/implement_exact_review_attestation_registry_v0_v3.sh"
cp "$SOURCE" "$TARGET"

python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["RUNNER_TEMP"]) / (
    "implement_exact_review_attestation_registry_v0_v3.sh"
)
source = path.read_text(encoding="utf-8")
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

python "$CONTROLLER_ROOT/.github/controllers/apply_exact_review_attestation_pep695.py" "$PRODUCT_ROOT/src/nextgen_memory/review_attestation_registry.py"

# RED v2 remains the exact product test contract.
'''
if source.count(marker) != 1:
    raise SystemExit(
        f"expected one exact payload-overlay marker, found {source.count(marker)}"
    )
path.write_text(source.replace(marker, replacement, 1), encoding="utf-8")
PY

bash -n "$TARGET"
bash "$TARGET" "$@"
