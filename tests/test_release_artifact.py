from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from scripts.verify_release_artifact import (
    WheelValidationError,
    inspect_wheel,
    main,
)


def write_wheel(
    path: Path,
    *,
    distribution: str = "nextgen-memory",
    version: str = "0.1.0",
    members: dict[str, bytes | str] | None = None,
    duplicate: tuple[str, bytes | str] | None = None,
) -> Path:
    payload: dict[str, bytes | str] = {
        "nextgen_memory/__init__.py": "__all__ = ('marker',)\nmarker = 'ok'\n",
        "nextgen_memory/domain.py": "VALUE = 1\n",
        f"nextgen_memory-{version}.dist-info/METADATA": (
            "Metadata-Version: 2.4\n"
            f"Name: {distribution}\n"
            f"Version: {version}\n"
            "Summary: synthetic fixture\n\n"
        ),
        f"nextgen_memory-{version}.dist-info/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: synthetic-test\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ),
        f"nextgen_memory-{version}.dist-info/RECORD": "",
    }
    if members:
        payload.update(members)

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in payload.items():
            archive.writestr(name, content)
        if duplicate:
            archive.writestr(*duplicate)
    return path


def test_inspector_accepts_valid_wheel_and_emits_deterministic_safe_report(
    tmp_path: Path,
) -> None:
    sentinel_parent = tmp_path / "private-query-secret-parent"
    sentinel_parent.mkdir()
    wheel = write_wheel(sentinel_parent / "nextgen_memory-0.1.0-py3-none-any.whl")

    first = inspect_wheel(
        wheel,
        expected_name="nextgen-memory",
        expected_version="0.1.0",
        required_modules=("nextgen_memory", "nextgen_memory.domain"),
    )
    second = inspect_wheel(
        wheel,
        expected_name="nextgen-memory",
        expected_version="0.1.0",
        required_modules=("nextgen_memory.domain", "nextgen_memory"),
    )

    assert first == second
    assert first.distribution == "nextgen-memory"
    assert first.version == "0.1.0"
    assert first.wheel_filename == wheel.name
    assert len(first.wheel_sha256) == 64
    assert first.member_count == 5
    assert first.package_member_count == 2
    payload = first.to_json()
    assert json.loads(payload)["required_modules"] == [
        "nextgen_memory",
        "nextgen_memory.domain",
    ]
    assert "private-query-secret-parent" not in payload
    assert "synthetic fixture" not in payload
    assert "marker = 'ok'" not in payload
    assert payload == second.to_json()


def test_distribution_name_uses_normalized_comparison(tmp_path: Path) -> None:
    wheel = write_wheel(
        tmp_path / "nextgen_memory-0.1.0-py3-none-any.whl",
        distribution="NextGen.Memory",
    )

    report = inspect_wheel(
        wheel,
        expected_name="nextgen_memory",
        expected_version="0.1.0",
        required_modules=("nextgen_memory",),
    )

    assert report.distribution == "nextgen-memory"


@pytest.mark.parametrize(
    ("expected_name", "expected_version", "message"),
    [
        ("another-project", "0.1.0", "distribution"),
        ("nextgen-memory", "9.9.9", "version"),
    ],
)
def test_inspector_rejects_wrong_metadata_identity(
    tmp_path: Path,
    expected_name: str,
    expected_version: str,
    message: str,
) -> None:
    wheel = write_wheel(tmp_path / "nextgen_memory-0.1.0-py3-none-any.whl")

    with pytest.raises(WheelValidationError, match=message):
        inspect_wheel(
            wheel,
            expected_name=expected_name,
            expected_version=expected_version,
            required_modules=("nextgen_memory",),
        )


@pytest.mark.parametrize(
    "unsafe_name",
    [
        "/absolute.py",
        "../escape.py",
        "nextgen_memory/../../escape.py",
        "nextgen_memory\\windows.py",
        "nextgen_memory//double.py",
    ],
)
def test_inspector_rejects_unsafe_archive_paths(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    wheel = write_wheel(
        tmp_path / "nextgen_memory-0.1.0-py3-none-any.whl",
        members={unsafe_name: "unsafe"},
    )

    with pytest.raises(WheelValidationError, match="archive path"):
        inspect_wheel(
            wheel,
            expected_name="nextgen-memory",
            expected_version="0.1.0",
            required_modules=("nextgen_memory",),
        )


@pytest.mark.parametrize(
    "forbidden_name",
    [
        "tests/test_private.py",
        "nextgen_memory/tests/test_internal.py",
        "nextgen_memory/__pycache__/domain.pyc",
        "nextgen_memory/domain.pyc",
        ".git/config",
        "secrets/id_rsa",
        "config/.env",
        "certs/private.pem",
    ],
)
def test_inspector_rejects_forbidden_release_payloads(
    tmp_path: Path,
    forbidden_name: str,
) -> None:
    wheel = write_wheel(
        tmp_path / "nextgen_memory-0.1.0-py3-none-any.whl",
        members={forbidden_name: "forbidden"},
    )

    with pytest.raises(WheelValidationError, match="forbidden"):
        inspect_wheel(
            wheel,
            expected_name="nextgen-memory",
            expected_version="0.1.0",
            required_modules=("nextgen_memory",),
        )


def test_inspector_rejects_duplicate_archive_members(tmp_path: Path) -> None:
    wheel = write_wheel(
        tmp_path / "nextgen_memory-0.1.0-py3-none-any.whl",
        duplicate=("nextgen_memory/domain.py", "SECOND = True\n"),
    )

    with pytest.raises(WheelValidationError, match="duplicate"):
        inspect_wheel(
            wheel,
            expected_name="nextgen-memory",
            expected_version="0.1.0",
            required_modules=("nextgen_memory",),
        )


@pytest.mark.parametrize(
    ("members", "message"),
    [
        (
            {"nextgen_memory-0.1.0.dist-info/METADATA": b""},
            "metadata",
        ),
        (
            {
                "other-0.1.0.dist-info/METADATA": (
                    "Metadata-Version: 2.4\nName: other\nVersion: 0.1.0\n\n"
                )
            },
            "metadata",
        ),
    ],
)
def test_inspector_rejects_ambiguous_metadata(
    tmp_path: Path,
    members: dict[str, bytes | str],
    message: str,
) -> None:
    wheel = write_wheel(
        tmp_path / "nextgen_memory-0.1.0-py3-none-any.whl",
        members=members,
    )

    with pytest.raises(WheelValidationError, match=message):
        inspect_wheel(
            wheel,
            expected_name="nextgen-memory",
            expected_version="0.1.0",
            required_modules=("nextgen_memory",),
        )


def test_inspector_rejects_missing_package_root_or_required_module(
    tmp_path: Path,
) -> None:
    wheel = write_wheel(tmp_path / "nextgen_memory-0.1.0-py3-none-any.whl")

    with zipfile.ZipFile(wheel, "r") as source:
        retained = {
            info.filename: source.read(info)
            for info in source.infolist()
            if info.filename != "nextgen_memory/__init__.py"
        }
    with zipfile.ZipFile(wheel, "w") as target:
        for name, value in retained.items():
            target.writestr(name, value)

    with pytest.raises(WheelValidationError, match="package root"):
        inspect_wheel(
            wheel,
            expected_name="nextgen-memory",
            expected_version="0.1.0",
            required_modules=("nextgen_memory",),
        )

    wheel = write_wheel(tmp_path / "nextgen_memory-second.whl")
    with pytest.raises(WheelValidationError, match="required module"):
        inspect_wheel(
            wheel,
            expected_name="nextgen-memory",
            expected_version="0.1.0",
            required_modules=("nextgen_memory.missing",),
        )


def test_cli_writes_only_canonical_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    wheel = write_wheel(tmp_path / "nextgen_memory-0.1.0-py3-none-any.whl")

    result = main(
        [
            str(wheel),
            "--expected-name",
            "nextgen-memory",
            "--expected-version",
            "0.1.0",
            "--required-module",
            "nextgen_memory.domain",
            "--required-module",
            "nextgen_memory",
        ]
    )

    assert result == 0
    output = capsys.readouterr().out
    parsed = json.loads(output)
    assert parsed["wheel_filename"] == wheel.name
    assert parsed["required_modules"] == [
        "nextgen_memory",
        "nextgen_memory.domain",
    ]
    assert output.endswith("\n")
