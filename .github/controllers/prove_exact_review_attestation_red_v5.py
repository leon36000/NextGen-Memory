#!/usr/bin/env python3
"""Prove product-context sources preserve the exact immutable RED v5."""

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
_DYNAMIC_TARGET_PATHS = frozenset(_TEST_PATHS[:2])
_PUBLIC_API_PATH = _TEST_PATHS[2]
_TARGET_MODULE = "nextgen_memory.review_attestation_registry"


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


def _importlib_count(tree: ast.Module) -> int:
    return sum(
        1
        for node in tree.body
        if isinstance(node, ast.Import)
        and any(alias.name == "importlib" for alias in node.names)
    )


def _has_forbidden_weakening(source: str, *, path: str) -> None:
    for marker in (
        "# noqa",
        "pytest.mark.skip",
        "pytest.mark.xfail",
        "NotImplementedError",
    ):
        if marker in source:
            raise SystemExit(f"{path}: forbidden weakening marker: {marker}")


def _validate_dynamic_target_bootstrap(raw: bytes, *, path: str) -> None:
    source = raw.decode("utf-8", errors="strict")
    tree = ast.parse(source, filename=path)
    _has_forbidden_weakening(source, path=path)
    if _importlib_count(tree) != 1:
        raise SystemExit(f"{path}: importlib import is absent or duplicated")
    if any(
        isinstance(node, ast.ImportFrom) and node.module == _TARGET_MODULE
        for node in tree.body
    ):
        raise SystemExit(f"{path}: context-dependent static target import remains")

    bootstrap_count = 0
    bound_names: list[str] = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            target = node.targets[0].id
            if target == "_review_attestation_registry":
                if not (
                    isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and isinstance(node.value.func.value, ast.Name)
                    and node.value.func.value.id == "importlib"
                    and node.value.func.attr == "import_module"
                    and len(node.value.args) == 1
                    and isinstance(node.value.args[0], ast.Constant)
                    and node.value.args[0].value == _TARGET_MODULE
                ):
                    raise SystemExit(f"{path}: dynamic target bootstrap differs")
                bootstrap_count += 1
            elif (
                isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "_review_attestation_registry"
                and node.value.attr == target
            ):
                bound_names.append(target)
    if bootstrap_count != 1:
        raise SystemExit(f"{path}: dynamic target bootstrap is absent or duplicated")
    if not bound_names or len(bound_names) != len(set(bound_names)):
        raise SystemExit(f"{path}: dynamic public bindings are empty or duplicated")


def _validate_public_api_bootstrap(raw: bytes) -> None:
    source = raw.decode("utf-8", errors="strict")
    tree = ast.parse(source, filename=_PUBLIC_API_PATH)
    _has_forbidden_weakening(source, path=_PUBLIC_API_PATH)
    if _importlib_count(tree) != 1:
        raise SystemExit("public API importlib bootstrap is absent or duplicated")
    direct_root_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.Import)
        and any(alias.name == "nextgen_memory" for alias in node.names)
    ]
    if direct_root_imports:
        raise SystemExit("public API retains a context-dependent package-root import")
    target_imports = [
        node
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == _TARGET_MODULE
    ]
    if len(target_imports) != 1:
        raise SystemExit("public API target-module import is absent or duplicated")
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
        raise SystemExit("public API package-root dynamic import is absent or duplicated")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--red-sha", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()

    records: list[dict[str, object]] = []
    for path in _RED_PATHS:
        immutable = _git_show(arguments.red_sha, path)
        current = Path(path).read_bytes()
        record: dict[str, object] = {
            "path": path,
            "immutable_sha256": _sha256(immutable),
            "current_sha256": _sha256(current),
            "source_identical": immutable == current,
        }
        if path in _TEST_PATHS:
            immutable_ast = _ast_sha256(immutable, path=path)
            current_ast = _ast_sha256(current, path=path)
            record.update(
                {
                    "immutable_ast_sha256": immutable_ast,
                    "current_ast_sha256": current_ast,
                    "ast_identical": immutable_ast == current_ast,
                }
            )
        records.append(record)

    for path in _DYNAMIC_TARGET_PATHS:
        _validate_dynamic_target_bootstrap(Path(path).read_bytes(), path=path)
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
            "product-context RED v5 source drift: " + ", ".join(differing)
        )
    if not all_test_asts_identical:
        raise SystemExit("product-context RED v5 AST drift")

    report = {
        "schema": "m-head-exact-review-attestation-red-v5-preservation-v1",
        "red_v5_sha": arguments.red_sha,
        "paths": records,
        "all_sources_identical": True,
        "all_test_asts_identical": True,
        "focused_property_target_bootstrap_context_invariant": True,
        "public_api_root_bootstrap_context_invariant": True,
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
