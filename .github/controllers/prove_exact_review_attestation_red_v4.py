#!/usr/bin/env python3
"""Prove product-context sources preserve the exact immutable RED v4."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

_RED_PATHS = (
    "docs/exact-sha-review-attestation-registry-v0-red.md",
    "tests/test_review_attestation_registry.py",
    "tests/test_review_attestation_registry_properties.py",
    "tests/test_review_attestation_registry_public_api.py",
)
_TEST_PATHS = _RED_PATHS[1:]
_PUBLIC_API_PATH = "tests/test_review_attestation_registry_public_api.py"


def _git_show(commit: str, path: str) -> bytes:
    return subprocess.check_output(("git", "show", f"{commit}:{path}"))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _ast_sha256(raw: bytes, *, path: str) -> str:
    source = raw.decode("utf-8", errors="strict")
    tree = ast.parse(source, filename=path)
    canonical = ast.dump(
        tree,
        annotate_fields=True,
        include_attributes=False,
    ).encode("utf-8")
    return _sha256(canonical)


def _validate_public_api_bootstrap(raw: bytes) -> None:
    source = raw.decode("utf-8", errors="strict")
    tree = ast.parse(source, filename=_PUBLIC_API_PATH)
    importlib_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.Import)
        and any(alias.name == "importlib" for alias in node.names)
    ]
    direct_root_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.Import)
        and any(alias.name == "nextgen_memory" for alias in node.names)
    ]
    target_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "nextgen_memory.review_attestation_registry"
    ]
    if len(importlib_imports) != 1:
        raise SystemExit("RED v4 importlib bootstrap is absent or duplicated")
    if direct_root_imports:
        raise SystemExit("RED v4 retains a context-dependent package-root import")
    if len(target_imports) != 1:
        raise SystemExit("RED v4 target-module import is absent or duplicated")
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "importlib"
        and node.func.attr == "import_module"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "nextgen_memory"
    ]
    if len(calls) != 1:
        raise SystemExit("RED v4 package-root dynamic import is absent or duplicated")
    for marker in ("# noqa", "pytest.mark.skip", "pytest.mark.xfail"):
        if marker in source:
            raise SystemExit(f"RED v4 contains forbidden weakening marker: {marker}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--red-sha", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()

    records: list[dict[str, object]] = []
    for path in _RED_PATHS:
        immutable = _git_show(arguments.red_sha, path)
        current = Path(path).read_bytes()
        immutable_sha = _sha256(immutable)
        current_sha = _sha256(current)
        source_identical = immutable == current
        record: dict[str, object] = {
            "path": path,
            "immutable_sha256": immutable_sha,
            "current_sha256": current_sha,
            "source_identical": source_identical,
        }
        if path in _TEST_PATHS:
            immutable_ast_sha = _ast_sha256(immutable, path=path)
            current_ast_sha = _ast_sha256(current, path=path)
            record.update(
                {
                    "immutable_ast_sha256": immutable_ast_sha,
                    "current_ast_sha256": current_ast_sha,
                    "ast_identical": immutable_ast_sha == current_ast_sha,
                }
            )
        records.append(record)

    _validate_public_api_bootstrap(Path(_PUBLIC_API_PATH).read_bytes())
    all_sources_identical = all(
        bool(record["source_identical"]) for record in records
    )
    all_test_asts_identical = all(
        bool(record["ast_identical"])
        for record in records
        if "ast_identical" in record
    )
    if not all_sources_identical:
        differing = [
            str(record["path"])
            for record in records
            if not bool(record["source_identical"])
        ]
        raise SystemExit(
            "product-context RED v4 source drift: " + ", ".join(differing)
        )
    if not all_test_asts_identical:
        raise SystemExit("product-context RED v4 AST drift")

    report = {
        "schema": "m-head-exact-review-attestation-red-v4-preservation-v1",
        "red_v4_sha": arguments.red_sha,
        "paths": records,
        "all_sources_identical": True,
        "all_test_asts_identical": True,
        "public_api_bootstrap_context_invariant": True,
        "assertions_weakened": False,
    }
    destination = Path(arguments.output)
    destination.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    print(destination.read_text(encoding="utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
