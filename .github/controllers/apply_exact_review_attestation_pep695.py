from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: apply_exact_review_attestation_pep695.py MODULE_PATH"
        )

    path = Path(sys.argv[1])
    lines = path.read_text(encoding="utf-8").splitlines()
    transformed: list[str] = []
    removed_import = 0
    removed_typevar = 0
    converted_enum = 0
    converted_bounded = 0

    for line in lines:
        if line == "from typing import TypeVar":
            removed_import += 1
            continue
        if line == '_T = TypeVar("_T")':
            removed_typevar += 1
            continue
        if line.startswith("def _require_enum("):
            line = line.replace(
                "def _require_enum(",
                "def _require_enum[_T](",
                1,
            )
            converted_enum += 1
        if line == "def _bounded_unique(":
            line = "def _bounded_unique[_T]("
            converted_bounded += 1
        transformed.append(line)

    counts = {
        "removed TypeVar import": removed_import,
        "removed TypeVar binding": removed_typevar,
        "converted _require_enum": converted_enum,
        "converted _bounded_unique": converted_bounded,
    }
    incorrect = {name: count for name, count in counts.items() if count != 1}
    if incorrect:
        raise SystemExit(f"unexpected PEP 695 source shape: {incorrect}")

    rendered = "\n".join(transformed) + "\n"
    if "TypeVar" in rendered:
        raise SystemExit("TypeVar remains after PEP 695 conversion")
    if "def _require_enum[_T](" not in rendered:
        raise SystemExit("_require_enum PEP 695 declaration is absent")
    if "def _bounded_unique[_T](" not in rendered:
        raise SystemExit("_bounded_unique PEP 695 declaration is absent")

    compile(rendered, str(path), "exec")
    path.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
