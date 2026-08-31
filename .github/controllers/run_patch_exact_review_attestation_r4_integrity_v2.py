#!/usr/bin/env python3
"""Run the R4 patcher with dataclass-aware class boundary detection."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--controller-root", required=True)
    parser.add_argument("--root", required=True)
    arguments = parser.parse_args()

    source_path = Path(arguments.controller_root) / (
        ".github/controllers/patch_exact_review_attestation_r4_integrity.py"
    )
    source = source_path.read_text(encoding="utf-8")
    old = '''    start_marker = f"class {class_name}:"
    start = source.index(start_marker)
    next_class = source.find("\\n\\nclass ", start + len(start_marker))
    end = len(source) if next_class == -1 else next_class
    segment = source[start:end]
'''
    new = '''    start_marker = f"class {class_name}:"
    start = source.index(start_marker)
    search_from = start + len(start_marker)
    boundaries = tuple(
        position
        for position in (
            source.find("\\n\\n@dataclass", search_from),
            source.find("\\n\\nclass ", search_from),
        )
        if position != -1
    )
    end = min(boundaries) if boundaries else len(source)
    segment = source[start:end]
'''
    if source.count(old) != 1:
        raise SystemExit(
            "expected exactly one obsolete class-boundary implementation, "
            f"found {source.count(old)}"
        )
    patched = source.replace(old, new, 1)
    if old in patched:
        raise SystemExit("obsolete class-boundary implementation remains")

    with tempfile.TemporaryDirectory() as temporary:
        patched_path = Path(temporary) / "patch_r4_integrity_v2.py"
        patched_path.write_text(patched, encoding="utf-8")
        subprocess.run(
            [sys.executable, str(patched_path), "--root", arguments.root],
            check=True,
        )

    root = Path(arguments.root)
    for relative_path in (
        "docs/exact-sha-review-attestation-registry-v0.md",
        "docs/superpowers/specs/2026-08-24-exact-sha-review-attestation-registry-v0-design.md",
    ):
        path = root / relative_path
        normalized = path.read_text(encoding="utf-8").rstrip() + "\n"
        path.write_text(normalized, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
