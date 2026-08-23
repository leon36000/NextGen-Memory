from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest
import scripts.verify_release_wheel as release_wheel
from scripts.verify_release_wheel import (
    WheelInspectionReport,
    WheelValidationError,
    inspect_wheel,
)

FIXED_ZIP_TIME = (2020, 1, 2, 3, 4, 6)


def write_wheel(
    path: Path,
    *,
    distribution: str = "nextgen-memory",
    version: str = "0.1.0",
    members: dict[str, bytes | str] | None = None,
    remove: tuple[str, ...] = (),
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
    for name in remove:
        payload.pop(name, None)

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in payload.items():
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
        if duplicate:
            info = zipfile.ZipInfo(duplicate[0], FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, duplicate[1])
    return path


def inspect(path: Path, *required_modules: str) -> WheelInspectionReport:
    return inspect_wheel(
        path,
        expected_name="nextgen-memory",
        expected_version="0.1.0",
        required_modules=required_modules or ("nextgen_memory",),
    )


def test_inspect_wheel_accepts_valid_archive_and_emits_safe_canonical_report(
    tmp_path: Path,
) -> None:
    private_parent = tmp_path / "private-parent-secret"
    private_parent.mkdir()
    wheel = write_wheel(private_parent / "nextgen_memory-0.1.0-py3-none-any.whl")

    first = inspect(wheel, "nextgen_memory.domain", "nextgen_memory")
    second = inspect(wheel, "nextgen_memory", "nextgen_memory.domain")

    assert first == second
    assert first.distribution == "nextgen-memory"
    assert first.version == "0.1.0"
    assert first.wheel_filename == wheel.name
    assert len(first.wheel_sha256) == 64
    assert first.wheel_size_bytes == wheel.stat().st_size
    assert first.member_count == 5
    assert first.package_member_count == 2
    assert first.required_modules == (
        "nextgen_memory",
        "nextgen_memory.domain",
    )
    assert len(first.metadata_sha256) == 64
    assert len(first.wheel_metadata_sha256) == 64
    assert len(first.record_sha256) == 64
    assert not hasattr(first, "__dict__")
    assert all(not hasattr(member, "__dict__") for member in first.members)

    payload = first.to_json()
    assert payload == second.to_json()
    assert payload.endswith("\n")
    decoded = json.loads(payload)
    assert decoded["wheel_filename"] == wheel.name
    assert decoded["required_modules"] == [
        "nextgen_memory",
        "nextgen_memory.domain",
    ]
    assert "private-parent-secret" not in payload
    assert "synthetic fixture" not in payload
    assert "marker = 'ok'" not in payload
    assert "Metadata-Version" not in payload


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
        "nextgen_memory/./dot.py",
    ],
)
def test_inspector_rejects_representable_noncanonical_archive_names(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    wheel = write_wheel(
        tmp_path / "unsafe.whl",
        members={unsafe_name: "unsafe"},
    )

    with pytest.raises(WheelValidationError, match="archive member name"):
        inspect(wheel)


@pytest.mark.parametrize("unsafe_name", ["", "nextgen_memory/nul\x00.py"])
def test_member_name_validator_rejects_empty_or_nul_name(unsafe_name: str) -> None:
    with pytest.raises(WheelValidationError, match="archive member name"):
        release_wheel._validate_archive_name(unsafe_name)


def test_inspector_rejects_raw_nul_archive_name(tmp_path: Path) -> None:
    wheel = write_wheel(
        tmp_path / "raw-nul.whl",
        members={"nextgen_memory/nulX.py": "unsafe"},
    )
    source_name = b"nextgen_memory/nulX.py"
    target_name = b"nextgen_memory/nul\x00.py"
    raw = wheel.read_bytes()
    assert raw.count(source_name) == 2
    wheel.write_bytes(raw.replace(source_name, target_name))

    with pytest.raises(WheelValidationError, match="archive member name"):
        inspect(wheel)


def test_inspector_rejects_duplicate_archive_members(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        wheel = write_wheel(
            tmp_path / "duplicate.whl",
            duplicate=("nextgen_memory/domain.py", "SECOND = True\n"),
        )

    with pytest.raises(WheelValidationError, match="duplicate"):
        inspect(wheel)


def test_inspector_rejects_case_colliding_archive_members(tmp_path: Path) -> None:
    wheel = write_wheel(
        tmp_path / "case-collision.whl",
        members={"NextGen_Memory/domain.py": "SECOND = True\n"},
    )

    with pytest.raises(WheelValidationError, match="case-colliding"):
        inspect(wheel)


@pytest.mark.parametrize(
    "forbidden_name",
    [
        ".git/config",
        ".hg/store",
        ".svn/entries",
        "tests/test_private.py",
        "nextgen_memory/tests/test_internal.py",
        "nextgen_memory/__pycache__/domain.cpython-312.pyc",
        "nextgen_memory/domain.pyc",
        "nextgen_memory/.pytest_cache/state",
        "config/.env",
        "secrets/id_rsa",
        "certs/private.pem",
        "credentials/service-account.json",
        ".idea/workspace.xml",
        ".vscode/settings.json",
    ],
)
def test_inspector_rejects_forbidden_release_payloads(
    tmp_path: Path,
    forbidden_name: str,
) -> None:
    sentinel = "raw-private-content-never-echo"
    wheel = write_wheel(
        tmp_path / "forbidden.whl",
        members={forbidden_name: sentinel},
    )

    with pytest.raises(WheelValidationError, match="forbidden release payload") as exc_info:
        inspect(wheel)

    assert sentinel not in str(exc_info.value)
    assert str(tmp_path) not in str(exc_info.value)


@pytest.mark.parametrize(
    ("removed_suffix", "message"),
    [
        ("METADATA", "exactly one METADATA"),
        ("WHEEL", "exactly one WHEEL"),
        ("RECORD", "exactly one RECORD"),
    ],
)
def test_inspector_requires_one_dist_info_record_of_each_kind(
    tmp_path: Path,
    removed_suffix: str,
    message: str,
) -> None:
    path = f"nextgen_memory-0.1.0.dist-info/{removed_suffix}"
    wheel = write_wheel(tmp_path / "missing-record.whl", remove=(path,))

    with pytest.raises(WheelValidationError, match=message):
        inspect(wheel)


def test_inspector_rejects_ambiguous_metadata_records(tmp_path: Path) -> None:
    wheel = write_wheel(
        tmp_path / "ambiguous-metadata.whl",
        members={
            "other-0.1.0.dist-info/METADATA": (
                "Metadata-Version: 2.4\n"
                "Name: other\n"
                "Version: 0.1.0\n\n"
            )
        },
    )

    with pytest.raises(WheelValidationError, match="exactly one METADATA"):
        inspect(wheel)


def test_inspector_rejects_records_from_different_dist_info_directories(
    tmp_path: Path,
) -> None:
    wheel = write_wheel(
        tmp_path / "split-dist-info.whl",
        remove=("nextgen_memory-0.1.0.dist-info/WHEEL",),
        members={
            "other-0.1.0.dist-info/WHEEL": (
                "Wheel-Version: 1.0\n"
                "Root-Is-Purelib: true\n"
                "Tag: py3-none-any\n"
            )
        },
    )

    with pytest.raises(WheelValidationError, match="same dist-info"):
        inspect(wheel)


def test_inspector_rejects_invalid_utf8_metadata(tmp_path: Path) -> None:
    wheel = write_wheel(
        tmp_path / "invalid-metadata.whl",
        members={"nextgen_memory-0.1.0.dist-info/METADATA": b"\xff\xfe"},
    )

    with pytest.raises(WheelValidationError, match="UTF-8 metadata"):
        inspect(wheel)


@pytest.mark.parametrize(
    "metadata",
    [
        (
            "Metadata-Version: 2.4\n"
            "Name: nextgen-memory\n"
            "Name: nextgen-memory\n"
            "Version: 0.1.0\n\n"
        ),
        (
            "Metadata-Version: 2.4\n"
            "Name: nextgen-memory\n"
            "Version: 0.1.0\n"
            "Version: 0.1.0\n\n"
        ),
        "Metadata-Version: 2.4\nName: \nVersion: 0.1.0\n\n",
        "Metadata-Version: 2.4\nName: nextgen-memory\nVersion: \n\n",
    ],
)
def test_inspector_rejects_ambiguous_or_empty_identity_headers(
    tmp_path: Path,
    metadata: str,
) -> None:
    wheel = write_wheel(
        tmp_path / "ambiguous-identity.whl",
        members={"nextgen_memory-0.1.0.dist-info/METADATA": metadata},
    )

    with pytest.raises(WheelValidationError, match="metadata identity"):
        inspect(wheel)


def test_inspector_rejects_missing_package_root(tmp_path: Path) -> None:
    wheel = write_wheel(
        tmp_path / "missing-root.whl",
        remove=("nextgen_memory/__init__.py",),
    )

    with pytest.raises(WheelValidationError, match="package root"):
        inspect(wheel)


def test_inspector_rejects_missing_required_module(tmp_path: Path) -> None:
    wheel = write_wheel(tmp_path / "missing-module.whl")

    with pytest.raises(WheelValidationError, match="required module"):
        inspect(wheel, "nextgen_memory", "nextgen_memory.missing")


def test_required_module_accepts_module_file_or_package_directory(tmp_path: Path) -> None:
    module_wheel = write_wheel(tmp_path / "module.whl")
    package_wheel = write_wheel(
        tmp_path / "package.whl",
        remove=("nextgen_memory/domain.py",),
        members={"nextgen_memory/domain/__init__.py": "VALUE = 1\n"},
    )

    assert inspect(module_wheel, "nextgen_memory.domain").required_modules == (
        "nextgen_memory.domain",
    )
    assert inspect(package_wheel, "nextgen_memory.domain").required_modules == (
        "nextgen_memory.domain",
    )


def test_required_module_does_not_accept_unrelated_prefix(tmp_path: Path) -> None:
    wheel = write_wheel(
        tmp_path / "prefix.whl",
        remove=("nextgen_memory/domain.py",),
        members={"nextgen_memory/domain_extra.py": "VALUE = 1\n"},
    )

    with pytest.raises(WheelValidationError, match="required module"):
        inspect(wheel, "nextgen_memory.domain")


@pytest.mark.parametrize(
    ("kind", "message"),
    [
        ("missing", "regular wheel file"),
        ("directory", "regular wheel file"),
        ("non-wheel", r"\.whl"),
        ("invalid-zip", "valid ZIP"),
    ],
)
def test_inspector_rejects_invalid_input_boundaries(
    tmp_path: Path,
    kind: str,
    message: str,
) -> None:
    path = tmp_path / "artifact.whl"
    if kind == "directory":
        path.mkdir()
    elif kind == "non-wheel":
        path = tmp_path / "artifact.zip"
        path.write_bytes(b"not-a-wheel")
    elif kind == "invalid-zip":
        path.write_bytes(b"not-a-zip")

    with pytest.raises(WheelValidationError, match=message):
        inspect(path)


def test_inspector_rejects_symlink_input(tmp_path: Path) -> None:
    target = write_wheel(tmp_path / "target.whl")
    link = tmp_path / "link.whl"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(WheelValidationError, match="non-symlink"):
        inspect(link)


def test_report_member_evidence_is_sorted_and_bounded(tmp_path: Path) -> None:
    wheel = write_wheel(
        tmp_path / "ordered.whl",
        members={
            "nextgen_memory/zeta.py": "Z = 1\n",
            "nextgen_memory/alpha.py": "A = 1\n",
        },
    )

    report = inspect(wheel)

    assert tuple(member.name for member in report.members) == tuple(
        sorted(member.name for member in report.members)
    )
    for member in report.members:
        assert len(member.sha256) == 64
        assert len(member.crc32) == 8
        assert member.size >= 0
        assert member.compressed_size >= 0
        assert len(member.timestamp) == 6


def test_report_is_immutable(tmp_path: Path) -> None:
    report = inspect(write_wheel(tmp_path / "immutable.whl"))

    with pytest.raises((AttributeError, TypeError)):
        report.version = "9.9.9"  # type: ignore[misc]


def test_inspection_does_not_extract_archive(tmp_path: Path) -> None:
    extraction_sentinel = tmp_path / "nextgen_memory"
    wheel = write_wheel(tmp_path / "no-extract.whl")

    inspect(wheel)

    assert not extraction_sentinel.exists()
    assert os.listdir(tmp_path) == [wheel.name]
