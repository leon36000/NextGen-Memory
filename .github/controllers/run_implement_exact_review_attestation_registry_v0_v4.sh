#!/usr/bin/env bash
set -euo pipefail

SOURCE="$GITHUB_WORKSPACE/controller/.github/controllers/implement_exact_review_attestation_registry_v0.sh"
TARGET="$RUNNER_TEMP/implement_exact_review_attestation_registry_v0_v4.sh"
cp "$SOURCE" "$TARGET"

python - <<'PY'
from __future__ import annotations

import os
from pathlib import Path

path = Path(os.environ["RUNNER_TEMP"]) / (
    "implement_exact_review_attestation_registry_v0_v4.sh"
)
lines = path.read_text(encoding="utf-8").splitlines()
out: list[str] = []
counts = {
    "red_v3_variable": 0,
    "red_contract_overlay": 0,
    "reference_red_v3": 0,
    "pin_ruff": 0,
    "summary_red_v3": 0,
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
                'git cat-file -e "$RED_V3_SHA^{commit}"',
                'test "$(git merge-base "$BASE_SHA" "$RED_V3_SHA")" = "$BASE_SHA"',
                'git checkout "$RED_V3_SHA" -- "${RED_PATHS[@]}"',
                "",
                "# RED v3 remains the exact product test contract.",
            )
        )
        counts["red_contract_overlay"] += 1
        continue

    if 'git show "$RED_V2_SHA:$path" > "$reference"' in line:
        out.append(line.replace("$RED_V2_SHA:$path", "$RED_V3_SHA:$path", 1))
        counts["reference_red_v3"] += 1
        continue

    if line == "run python -m pip install -e '.[dev]'":
        out.append(line)
        out.append("run python -m pip install 'ruff==0.16.4'")
        out.append("run ruff --version")
        counts["pin_ruff"] += 1
        continue

    if line.strip() == "'red_v2_sha': '4f0a74e0d39a181b682d2b135012184c255928bc',":
        out.append(line)
        indentation = line[: len(line) - len(line.lstrip())]
        out.append(
            indentation
            + "'red_v3_sha': '0a8e193269e425dd51f740b495579f949a237ce1',"
        )
        out.append(indentation + "'ruff_version': '0.16.4',")
        counts["summary_red_v3"] += 1
        continue

    if line == "- corrected immutable RED v2: \`$RED_V2_SHA\`;":
        out.append("- immutable RED v3: \`$RED_V3_SHA\`;")
        out.append("- payload source RED v2: \`$RED_V2_SHA\`;")
        counts["status_red_v3"] += 1
        continue

    out.append(line)

incorrect = {name: count for name, count in counts.items() if count != 1}
if incorrect:
    raise SystemExit(f"unexpected product-controller source shape: {incorrect}")

rendered = "\n".join(out) + "\n"
if 'git show "$RED_V2_SHA:$path" > "$reference"' in rendered:
    raise SystemExit("RED v2 is still used as the final test reference")
if "# RED v2 remains the exact product test contract." in rendered:
    raise SystemExit("RED v2 contract marker remains")
path.write_text(rendered, encoding="utf-8")
PY

bash -n "$TARGET"
bash "$TARGET" "$@"
