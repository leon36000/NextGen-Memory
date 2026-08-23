from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.verify_no_stubs import Finding, main, scan_paths, scan_source


def kinds(source: str) -> list[str]:
    return [finding.kind for finding in scan_source(source, path="src/example.py")]


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("def unfinished():\n    pass\n", "function_stub"),
        (
            "async def unfinished():\n"
            "    \"\"\"documentation does not complete behavior\"\"\"\n"
            "    ...\n",
            "function_stub",
        ),
        ("class EmptyService:\n    pass\n", "class_stub"),
        (
            "def outer():\n"
            "    def inner():\n"
            "        pass\n"
            "    return inner\n",
            "function_stub",
        ),
        (
            "def unfinished():\n"
            "    raise NotImplementedError('later')\n",
            "not_implemented_error",
        ),
        ("# TODO: implement real behavior\nVALUE = 1\n", "todo_comment"),
        ("VALUE = 1  # FIXME remove fake success\n", "fixme_comment"),
    ],
)
def test_scanner_rejects_concrete_stub_patterns(source: str, expected: str) -> None:
    assert expected in kinds(source)


def test_scanner_accepts_narrow_language_level_abstractions() -> None:
    source = '''
from abc import abstractmethod as abstract
from typing import Protocol as Interface, overload as signature

class Reader(Interface):
    def read(self) -> str: ...

class AbstractWorker:
    @abstract
    def run(self) -> None:
        pass

@signature
def parse(value: int) -> int: ...

class DomainFailure(RuntimeError):
    pass

class ChildFailure(DomainFailure):
    pass

class Comparable:
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Comparable):
            return NotImplemented
        return True
'''

    assert scan_source(source, path="src/abstractions.py") == ()


def test_scanner_recognizes_module_aliases_for_protocol_abstract_and_overload() -> None:
    source = '''
import abc as contracts
import typing as types

class Reader(types.Protocol):
    def read(self) -> str: ...

class AbstractWorker:
    @contracts.abstractmethod
    def run(self) -> None: ...

@types.overload
def parse(value: int) -> int: ...
'''

    assert scan_source(source, path="src/aliases.py") == ()


def test_not_implemented_error_in_nested_concrete_scope_is_reported_once() -> None:
    source = '''
def outer():
    def inner():
        raise NotImplementedError
    return inner
'''

    findings = scan_source(source, path="src/nested.py")

    assert [finding.kind for finding in findings] == ["not_implemented_error"]
    assert findings[0].symbol == "outer.inner"


def test_todo_words_inside_strings_are_not_comments() -> None:
    source = '''
MESSAGE = "TODO is data, not a source comment"
def complete() -> str:
    return "FIXME is also data"
'''

    assert scan_source(source, path="src/strings.py") == ()


def test_syntax_error_fails_closed_without_echoing_source() -> None:
    sentinel = "private-query-secret"
    source = f"def broken(:\n    return '{sentinel}'\n"

    findings = scan_source(source, path="src/broken.py")

    assert len(findings) == 1
    assert findings[0].kind == "syntax_error"
    assert sentinel not in findings[0].to_json()


def test_scan_paths_is_deterministic_relative_and_ignores_non_python_files(
    tmp_path: Path,
) -> None:
    root = tmp_path / "private-parent" / "src"
    root.mkdir(parents=True)
    (root / "b.py").write_text("class B:\n    pass\n", encoding="utf-8")
    (root / "a.py").write_text("def a():\n    pass\n", encoding="utf-8")
    (root / "notes.txt").write_text("TODO should not be scanned", encoding="utf-8")

    first = scan_paths((root,))
    second = scan_paths((root,))

    assert first == second
    assert [finding.path for finding in first] == ["src/a.py", "src/b.py"]
    assert "private-parent" not in json.dumps(
        [finding.to_dict() for finding in first],
        sort_keys=True,
    )


def test_finding_json_is_canonical_and_contains_no_source_content() -> None:
    sentinel = "raw-secret-payload"
    finding = Finding(
        path="src/example.py",
        line=4,
        column=2,
        kind="function_stub",
        symbol="run",
    )

    payload = finding.to_json()

    assert json.loads(payload) == {
        "column": 2,
        "kind": "function_stub",
        "line": 4,
        "path": "src/example.py",
        "symbol": "run",
    }
    assert sentinel not in payload
    assert payload == finding.to_json()


def test_cli_returns_nonzero_and_prints_deterministic_json_on_findings(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "src"
    root.mkdir()
    (root / "bad.py").write_text("def unfinished():\n    pass\n", encoding="utf-8")

    exit_code = main([str(root)])
    output = capsys.readouterr().out

    assert exit_code == 1
    parsed = json.loads(output)
    assert parsed["finding_count"] == 1
    assert parsed["findings"][0]["path"] == "src/bad.py"
    assert output.endswith("\n")


def test_cli_returns_zero_for_complete_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "src"
    root.mkdir()
    (root / "good.py").write_text(
        "def complete() -> int:\n    return 1\n",
        encoding="utf-8",
    )

    assert main([str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "finding_count": 0,
        "findings": [],
    }
