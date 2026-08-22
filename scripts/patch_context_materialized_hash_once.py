from __future__ import annotations

import re
from pathlib import Path


def replace_once(path: Path, source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(f"unexpected pattern count in {path}: {old!r}")
    return source.replace(old, new, 1)


def patch_contract() -> None:
    path = Path("src/nextgen_memory/context_compiler_contracts.py")
    source = path.read_text(encoding="utf-8")
    if "content_hash must match normalized materialized content" in source:
        return
    source = replace_once(
        path,
        source,
        "import json\nimport re\n",
        "import hashlib\nimport json\nimport re\n",
    )
    old = (
        "        object.__setattr__(\n"
        "            self,\n"
        "            \"content\",\n"
        "            _normalize_required_text(\"content\", self.content),\n"
        "        )\n"
        "        _validate_hash(\"content_hash\", self.content_hash)\n"
    )
    new = (
        "        normalized_content = _normalize_required_text(\n"
        "            \"content\",\n"
        "            self.content,\n"
        "        )\n"
        "        object.__setattr__(self, \"content\", normalized_content)\n"
        "        _validate_hash(\"content_hash\", self.content_hash)\n"
        "        expected_content_hash = hashlib.sha256(\n"
        "            normalized_content.encode(\"utf-8\")\n"
        "        ).hexdigest()\n"
        "        if self.content_hash != expected_content_hash:\n"
        "            raise ContextCompilerValidationError(\n"
        "                \"content_hash must match normalized materialized content\"\n"
        "            )\n"
    )
    source = replace_once(path, source, old, new)
    path.write_text(source.rstrip() + "\n", encoding="utf-8")


def patch_helper(path: Path, defaults: tuple[str, ...]) -> None:
    source = path.read_text(encoding="utf-8")
    if "import hashlib\n" not in source:
        source = replace_once(
            path,
            source,
            "from __future__ import annotations\n\n",
            "from __future__ import annotations\n\nimport hashlib\n",
        )
    for old in defaults:
        source = source.replace(old, "")
    if 'if "content_hash" not in overrides:' not in source:
        helper = (
            "    values.update(overrides)\n"
            "    if \"content_hash\" not in overrides:\n"
            "        content = values.get(\"content\")\n"
            "        normalized_content = (\n"
            "            content.strip() if isinstance(content, str) else \"\"\n"
            "        )\n"
            "        values[\"content_hash\"] = hashlib.sha256(\n"
            "            normalized_content.encode(\"utf-8\")\n"
            "        ).hexdigest()\n"
            "    return IntegratedContextEvidence(**values)\n"
        )
        source = replace_once(
            path,
            source,
            "    values.update(overrides)\n"
            "    return IntegratedContextEvidence(**values)\n",
            helper,
        )
    path.write_text(source.rstrip() + "\n", encoding="utf-8")


def patch_fixtures() -> None:
    patch_helper(
        Path("tests/test_context_compiler_contracts.py"),
        ('        "content_hash": "a" * 64,\n',),
    )
    patch_helper(
        Path("tests/test_context_compiler.py"),
        (
            '    character = "0123456789abcdef"[index % 16]\n',
            '        "content_hash": character * 64,\n',
        ),
    )
    patch_helper(
        Path("tests/test_context_exact_solver.py"),
        (
            '    character = "0123456789abcdef"[index % 16]\n',
            '        "content_hash": character * 64,\n',
        ),
    )
    patch_helper(
        Path("tests/test_context_heuristic_solver.py"),
        (
            '    character = "0123456789abcdef"[index % 16]\n',
            '        "content_hash": character * 64,\n',
        ),
    )
    patch_helper(
        Path("tests/test_context_objective.py"),
        ('        "content_hash": suffix * 64,\n',),
    )

    path = Path("tests/test_context_compiler_contracts.py")
    source = path.read_text(encoding="utf-8")
    source = source.replace('        content_hash="b" * 64,\n', "")
    path.write_text(source.rstrip() + "\n", encoding="utf-8")

    path = Path("tests/test_context_compiler.py")
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        '                evidence(1, content="different", content_hash="f" * 64),\n',
        '                evidence(1, content="different"),\n',
    )
    source = source.replace('        content_hash="f" * 64,\n', "")
    path.write_text(source.rstrip() + "\n", encoding="utf-8")

    path = Path("tests/test_context_objective.py")
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        '                evidence(MEMORY_A, content="conflict", content_hash="f" * 64),\n',
        '                evidence(MEMORY_A, content="conflict"),\n',
    )
    source = source.replace('        content_hash="f" * 64,\n', "")
    source = source.replace(
        "def test_content_dedup_preserves_structural_anchor_and_rejects_hash_collision() -> None:\n",
        "def test_content_dedup_preserves_structural_anchor() -> None:\n",
    )
    collision = re.compile(
        r"\n    with pytest\.raises\("
        r"ContextCompilerValidationError, match=\"content_hash\"\):\n"
        r"        canonicalize_context_problem\(\n"
        r"            request\(\),\n"
        r"            \(\n"
        r"                evidence\(MEMORY_A, content=\"first\", content_hash=\"e\" \* 64\),\n"
        r"                evidence\(MEMORY_B, content=\"second\", content_hash=\"e\" \* 64\),\n"
        r"            \),\n"
        r"            \(\),\n"
        r"        \)\n"
    )
    source, count = collision.subn("", source, count=1)
    if count not in (0, 1):
        raise SystemExit("unexpected obsolete hash-collision assertion count")
    path.write_text(source.rstrip() + "\n", encoding="utf-8")

    path = Path("tests/test_context_compiler_properties.py")
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        '        f"context-property:{case_index}:{item_index}".encode()\n',
        '        f"property evidence {case_index}:{item_index}".encode("utf-8")\n',
    )
    source = source.replace(
        "        content_hash=content_hash(20_000, 0),\n",
        '        content_hash=hashlib.sha256(b"base").hexdigest(),\n',
    )
    path.write_text(source.rstrip() + "\n", encoding="utf-8")

    path = Path("tests/test_context_exact_solver.py")
    source = path.read_text(encoding="utf-8")
    source = source.replace(
        '            character = "0123456789abcdef"[(case_index + index) % 16]\n',
        '            content = f"case-{case_index}-item-{index}"\n',
    )
    source = source.replace(
        '                    content=f"case-{case_index}-item-{index}",\n'
        '                    content_hash=character * 63 + f"{index % 16:x}",\n',
        '                    content=content,\n'
        '                    content_hash=hashlib.sha256(\n'
        '                        content.encode("utf-8")\n'
        '                    ).hexdigest(),\n',
    )
    path.write_text(source.rstrip() + "\n", encoding="utf-8")

    suspicious = re.compile(
        r"content_hash\s*(?::|=)[^\n]*[\"'][0-9a-f][\"']\s*\*\s*64"
    )
    for candidate in Path("tests").glob("test_context*.py"):
        matches = suspicious.findall(candidate.read_text(encoding="utf-8"))
        if matches:
            raise SystemExit(f"fake valid digest remains in {candidate}: {matches}")


def patch_properties() -> None:
    path = Path("tests/test_context_compiler_properties.py")
    source = path.read_text(encoding="utf-8")
    old = '        f"context-property:{case_index}:{item_index}".encode()\n'
    new = '        f"property evidence {case_index}:{item_index}".encode("utf-8")\n'
    if old in source:
        source = source.replace(old, new, 1)
    if new not in source:
        raise SystemExit("unexpected property content-hash helper")
    path.write_text(source.rstrip() + "\n", encoding="utf-8")


def patch_design() -> None:
    path = Path(
        "docs/superpowers/specs/2026-08-14-context-compiler-integrated-v0-design.md"
    )
    source = path.read_text(encoding="utf-8")
    if "materialized `content_hash` equal to SHA-256" in source:
        return
    source = replace_once(
        path,
        source,
        "- exact `content`, canonical `content_hash`, and `backend_ref`;\n",
        "- exact `content`, materialized `content_hash` equal to SHA-256 of the normalized UTF-8 content, and `backend_ref`;\n",
    )
    marker = (
        "`direct_credit` and `inherited_credit` remain distinct fields in every "
        "objective and audit artifact. The compiler never adds them upstream or "
        "rewrites their provenance.\n"
    )
    addition = marker + (
        "\nAt the compiler boundary, `content_hash` is the SHA-256 hash of "
        "the exact normalized materialized content admitted to the packet. The "
        "upstream Neon canonical content hash remains a separate cross-store "
        "identity signal and must not be substituted for this materialized-content "
        "hash. A mismatch fails before canonicalization or optimization.\n"
    )
    source = replace_once(path, source, marker, addition)
    source = replace_once(
        path,
        source,
        "- content hashes, UUIDs, token estimates, ranks, signals, weights, or interaction statistics are invalid;\n",
        "- content hashes are malformed or do not match normalized materialized content, or UUIDs, token estimates, ranks, signals, weights, or interaction statistics are invalid;\n",
    )
    path.write_text(source.rstrip() + "\n", encoding="utf-8")


def main() -> None:
    patch_contract()
    patch_fixtures()
    patch_properties()
    patch_design()
    Path(__file__).unlink()


if __name__ == "__main__":
    main()
