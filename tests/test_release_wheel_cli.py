from __future__ import annotations

import json
import zipfile
from pathlib import Path

from scripts.verify_release_wheel import main

FIXED_ZIP_TIME = (2020, 1, 2, 3, 4, 6)


def write_wheel(
    path: Path,
    *,
    timestamp: tuple[int, int, int, int, int, int] = FIXED_ZIP_TIME,
    domain_source: str = "VALUE = 1\n",
) -> Path:
    members = {
        "nextgen_memory/__init__.py": "__all__ = ('marker',)\nmarker = 'ok'\n",
        "nextgen_memory/domain.py": domain_source,
        "nextgen_memory-0.1.0.dist-info/METADATA": (
            "Metadata-Version: 2.4\n"
            "Name: nextgen-memory\n"
            "Version: 0.1.0\n\n"
        ),
        "nextgen_memory-0.1.0.dist-info/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ),
        "nextgen_memory-0.1.0.dist-info/RECORD": "",
    }
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            info = zipfile.ZipInfo(name, timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return path


def common_identity_args() -> list[str]:
    return [
        "--expected-name",
        "nextgen-memory",
        "--expected-version",
        "0.1.0",
        "--required-module",
        "nextgen_memory",
        "--required-module",
        "nextgen_memory.domain",
    ]


def test_cli_inspect_writes_one_canonical_json_document(
    tmp_path: Path,
    capsys,
) -> None:
    wheel = write_wheel(tmp_path / "nextgen_memory-0.1.0-py3-none-any.whl")

    result = main(["inspect", str(wheel), *common_identity_args()])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert captured.out.endswith("\n")
    assert captured.out.count("\n") == 1
    decoded = json.loads(captured.out)
    assert decoded["wheel_filename"] == wheel.name
    assert decoded["distribution"] == "nextgen-memory"
    assert decoded["version"] == "0.1.0"
    assert decoded["required_modules"] == [
        "nextgen_memory",
        "nextgen_memory.domain",
    ]
    assert captured.out == json.dumps(
        decoded,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    assert str(tmp_path) not in captured.out


def test_cli_compare_writes_reproducibility_report(tmp_path: Path, capsys) -> None:
    left = write_wheel(tmp_path / "left.whl")
    right = write_wheel(tmp_path / "right.whl")

    result = main(
        ["compare", str(left), str(right), *common_identity_args()]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    decoded = json.loads(captured.out)
    assert decoded["byte_reproducible"] is True
    assert decoded["semantic_reproducible"] is True
    assert decoded["differences"] == []


def test_cli_compare_can_report_bounded_difference_without_failing(
    tmp_path: Path,
    capsys,
) -> None:
    left = write_wheel(tmp_path / "left.whl")
    right = write_wheel(
        tmp_path / "right.whl",
        timestamp=(2021, 2, 3, 4, 5, 6),
    )

    result = main(
        [
            "compare",
            str(left),
            str(right),
            *common_identity_args(),
            "--allow-byte-difference",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    decoded = json.loads(captured.out)
    assert decoded["byte_reproducible"] is False
    assert decoded["semantic_reproducible"] is True
    assert decoded["differences"]
    assert str(tmp_path) not in captured.out


def test_cli_validates_source_date_epoch(capsys) -> None:
    result = main(["validate-source-date-epoch", "315532800"])

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "source_date_epoch": 315532800,
        "valid": True,
    }


def test_cli_invalid_wheel_fails_with_one_bounded_error_object(
    tmp_path: Path,
    capsys,
) -> None:
    private_parent = tmp_path / "private-repository-name"
    private_parent.mkdir()
    wheel = private_parent / "invalid.whl"
    wheel.write_text("raw-private-wheel-content", encoding="utf-8")

    result = main(["inspect", str(wheel), *common_identity_args()])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert captured.err.count("\n") == 1
    decoded = json.loads(captured.err)
    assert decoded == {
        "error_class": "wheel_validation_error",
        "message": "wheel validation failed",
    }
    assert "private-repository-name" not in captured.err
    assert "raw-private-wheel-content" not in captured.err


def test_cli_required_byte_difference_fails_with_bounded_report(
    tmp_path: Path,
    capsys,
) -> None:
    sentinel = "private-content-never-echo"
    left = write_wheel(tmp_path / "left.whl")
    right = write_wheel(
        tmp_path / "right.whl",
        domain_source=f"VALUE = 2\n# {sentinel}\n",
    )

    result = main(
        ["compare", str(left), str(right), *common_identity_args()]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    decoded = json.loads(captured.err)
    assert decoded["error_class"] == "wheel_reproducibility_error"
    assert decoded["byte_reproducible"] is False
    assert decoded["semantic_reproducible"] is False
    assert decoded["differences"]
    assert sentinel not in captured.err
    assert str(tmp_path) not in captured.err


def test_cli_invalid_source_date_is_bounded(capsys) -> None:
    result = main(["validate-source-date-epoch", "not-a-date"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error_class": "source_date_epoch_error",
        "message": "source date epoch validation failed",
    }


def test_cli_unexpected_failure_never_echoes_exception_text(
    monkeypatch,
    capsys,
) -> None:
    sentinel = "private-backend-exception-never-echo"

    def fail(*args, **kwargs):
        del args, kwargs
        raise RuntimeError(sentinel)

    monkeypatch.setattr(
        "scripts.verify_release_wheel.validate_source_date_epoch",
        fail,
    )

    result = main(["validate-source-date-epoch", "315532800"])

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error_class": "unexpected_error",
        "message": "wheel verification failed unexpectedly",
    }
    assert sentinel not in captured.err
