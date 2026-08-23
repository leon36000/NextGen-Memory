from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from scripts.verify_release_wheel import (
    WheelReproducibilityError,
    compare_wheels,
    validate_source_date_epoch,
)

BASE_TIME = (2020, 1, 2, 3, 4, 6)
LATER_TIME = (2021, 2, 3, 4, 5, 6)


def write_wheel(
    path: Path,
    *,
    timestamp: tuple[int, int, int, int, int, int] = BASE_TIME,
    domain_source: str = "VALUE = 1\n",
    extra_members: dict[str, bytes | str] | None = None,
    remove: tuple[str, ...] = (),
) -> Path:
    members: dict[str, bytes | str] = {
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
    if extra_members:
        members.update(extra_members)
    for name in remove:
        members.pop(name, None)

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            info = zipfile.ZipInfo(name, timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return path


def compare(
    left: Path,
    right: Path,
    *,
    require_byte_reproducible: bool = True,
):
    return compare_wheels(
        left,
        right,
        expected_name="nextgen-memory",
        expected_version="0.1.0",
        required_modules=("nextgen_memory", "nextgen_memory.domain"),
        require_byte_reproducible=require_byte_reproducible,
    )


def test_validate_source_date_epoch_accepts_canonical_zip_epoch() -> None:
    assert validate_source_date_epoch("315532800") == 315532800
    assert validate_source_date_epoch("1798761600") == 1798761600


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("", "source date epoch"),
        (" 315532800", "source date epoch"),
        ("315532800 ", "source date epoch"),
        ("+315532800", "source date epoch"),
        ("-1", "source date epoch"),
        ("3.155328e8", "source date epoch"),
        ("315532799", "ZIP-compatible"),
        ("999999999999999999999", "source date epoch"),
    ],
)
def test_validate_source_date_epoch_rejects_ambiguous_or_unsupported_values(
    value: str,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_source_date_epoch(value)


def test_identical_wheels_are_byte_and_semantically_reproducible(
    tmp_path: Path,
) -> None:
    left = write_wheel(tmp_path / "left.whl")
    right = write_wheel(tmp_path / "right.whl")

    report = compare(left, right)

    assert report.byte_reproducible is True
    assert report.semantic_reproducible is True
    assert report.differences == ()
    assert report.left_sha256 == report.right_sha256
    assert report.to_json() == report.to_json()
    assert json.loads(report.to_json())["differences"] == []
    assert not hasattr(report, "__dict__")


def test_timestamp_only_drift_is_semantically_equal_but_not_byte_equal(
    tmp_path: Path,
) -> None:
    left = write_wheel(tmp_path / "left.whl", timestamp=BASE_TIME)
    right = write_wheel(tmp_path / "right.whl", timestamp=LATER_TIME)

    report = compare(left, right, require_byte_reproducible=False)

    assert report.byte_reproducible is False
    assert report.semantic_reproducible is True
    assert report.differences
    assert all(difference.left is not None for difference in report.differences)
    assert all(difference.right is not None for difference in report.differences)
    assert any(
        difference.left.timestamp != difference.right.timestamp
        for difference in report.differences
        if difference.left is not None and difference.right is not None
    )


def test_changed_member_content_is_semantic_and_byte_drift(tmp_path: Path) -> None:
    sentinel = "raw-private-content-never-report"
    left = write_wheel(tmp_path / "left.whl")
    right = write_wheel(
        tmp_path / "right.whl",
        domain_source=f"VALUE = 2\n# {sentinel}\n",
    )

    report = compare(left, right, require_byte_reproducible=False)

    assert report.byte_reproducible is False
    assert report.semantic_reproducible is False
    assert tuple(difference.name for difference in report.differences) == (
        "nextgen_memory/domain.py",
    )
    payload = report.to_json()
    assert sentinel not in payload
    assert str(tmp_path) not in payload
    assert "VALUE = 2" not in payload


def test_added_and_removed_members_are_reported_without_contents(tmp_path: Path) -> None:
    left = write_wheel(
        tmp_path / "left.whl",
        extra_members={"nextgen_memory/left_only.py": "LEFT_PRIVATE = True\n"},
    )
    right = write_wheel(
        tmp_path / "right.whl",
        extra_members={"nextgen_memory/right_only.py": "RIGHT_PRIVATE = True\n"},
    )

    report = compare(left, right, require_byte_reproducible=False)

    assert report.semantic_reproducible is False
    assert tuple(difference.name for difference in report.differences) == (
        "nextgen_memory/left_only.py",
        "nextgen_memory/right_only.py",
    )
    assert report.differences[0].left is not None
    assert report.differences[0].right is None
    assert report.differences[1].left is None
    assert report.differences[1].right is not None
    payload = report.to_json()
    assert "LEFT_PRIVATE" not in payload
    assert "RIGHT_PRIVATE" not in payload


def test_required_byte_reproducibility_fails_with_bounded_error(tmp_path: Path) -> None:
    sentinel_parent = tmp_path / "private-repository-path"
    sentinel_parent.mkdir()
    left = write_wheel(sentinel_parent / "left.whl", timestamp=BASE_TIME)
    right = write_wheel(sentinel_parent / "right.whl", timestamp=LATER_TIME)

    with pytest.raises(WheelReproducibilityError) as exc_info:
        compare(left, right)

    error = exc_info.value
    assert str(error) == "wheel reproducibility requirement failed"
    payload = error.to_json()
    decoded = json.loads(payload)
    assert decoded["error_class"] == "wheel_reproducibility_error"
    assert decoded["byte_reproducible"] is False
    assert decoded["semantic_reproducible"] is True
    assert decoded["differences"]
    assert "private-repository-path" not in payload
    assert str(tmp_path) not in payload


def test_difference_order_is_independent_of_zip_member_order(tmp_path: Path) -> None:
    first_left = write_wheel(
        tmp_path / "first-left.whl",
        extra_members={
            "nextgen_memory/zeta.py": "Z = 1\n",
            "nextgen_memory/alpha.py": "A = 1\n",
        },
    )
    first_right = write_wheel(
        tmp_path / "first-right.whl",
        extra_members={
            "nextgen_memory/zeta.py": "Z = 2\n",
            "nextgen_memory/alpha.py": "A = 2\n",
        },
    )

    report = compare(first_left, first_right, require_byte_reproducible=False)

    assert tuple(difference.name for difference in report.differences) == (
        "nextgen_memory/alpha.py",
        "nextgen_memory/zeta.py",
    )


def test_report_filenames_never_include_parent_directories(tmp_path: Path) -> None:
    parent = tmp_path / "private-parent-name"
    parent.mkdir()
    left = write_wheel(parent / "left.whl")
    right = write_wheel(parent / "right.whl")

    report = compare(left, right)
    payload = report.to_json()

    assert report.left_filename == "left.whl"
    assert report.right_filename == "right.whl"
    assert "private-parent-name" not in payload
    assert str(parent) not in payload
