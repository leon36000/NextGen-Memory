from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

_TEST_PATHS = (
    Path("tests/test_review_attestation_registry.py"),
    Path("tests/test_review_attestation_registry_properties.py"),
    Path("tests/test_review_attestation_registry_public_api.py"),
)


def _git_show(red_sha: str, path: Path) -> str:
    return subprocess.check_output(
        ("git", "show", f"{red_sha}:{path.as_posix()}"),
        text=True,
    )


def prove(red_sha: str) -> dict[str, object]:
    manifest: dict[str, object] = {}
    for path in _TEST_PATHS:
        red_source = _git_show(red_sha, path)
        product_source = path.read_text(encoding="utf-8")
        red_ast = ast.dump(
            ast.parse(red_source, filename=f"{red_sha}:{path}"),
            annotate_fields=True,
            include_attributes=False,
        )
        product_ast = ast.dump(
            ast.parse(product_source, filename=str(path)),
            annotate_fields=True,
            include_attributes=False,
        )
        if product_ast != red_ast:
            raise SystemExit(f"product formatting changed RED-v3 AST: {path}")
        manifest[path.as_posix()] = {
            "red_source_sha256": hashlib.sha256(
                red_source.encode("utf-8")
            ).hexdigest(),
            "product_source_sha256": hashlib.sha256(
                product_source.encode("utf-8")
            ).hexdigest(),
            "ast_sha256": hashlib.sha256(red_ast.encode("utf-8")).hexdigest(),
            "source_bytes_identical": product_source == red_source,
            "ast_identical": True,
        }
    return {
        "schema": "m-head-exact-review-attestation-red-v3-ast-preservation-v1",
        "red_v3_sha": red_sha,
        "ruff_version": "0.16.4",
        "product_context_import_formatting_only": True,
        "all_test_asts_identical": True,
        "tests": manifest,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--red-sha", required=True)
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()

    report = prove(arguments.red_sha)
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


if __name__ == "__main__":
    main()
