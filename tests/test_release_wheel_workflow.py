from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(".github/workflows/release-wheel-integrity.yml")
EXPECTED_PATH_FILTERS = {
    ".github/workflows/release-wheel-integrity.yml",
    "docs/superpowers/plans/2026-08-23-release-wheel-integrity-v1.md",
    "docs/superpowers/specs/2026-08-23-release-wheel-integrity-v1-design.md",
    "pyproject.toml",
    "scripts/verify_release_wheel.py",
    "src/**",
    "tests/test_release_wheel_cli.py",
    "tests/test_release_wheel_integrity.py",
    "tests/test_release_wheel_reproducibility.py",
    "tests/test_release_wheel_workflow.py",
}


def text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def path_filters() -> set[str]:
    lines = text().splitlines()
    filters: set[str] = set()
    in_paths = False
    paths_indent = 0
    for line in lines:
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if stripped == "paths:":
            in_paths = True
            paths_indent = indent
            continue
        if in_paths and stripped.startswith("- "):
            filters.add(stripped[2:].strip('"\''))
            continue
        if in_paths and stripped and indent <= paths_indent:
            break
    return filters


def test_workflow_is_pull_request_only_read_only_and_path_filtered() -> None:
    workflow = text()

    assert "pull_request:" in workflow
    assert "paths:" in workflow
    assert path_filters() == EXPECTED_PATH_FILTERS
    assert "permissions:" in workflow
    assert "contents: read" in workflow
    assert "contents: write" not in workflow
    assert "id-token: write" not in workflow
    assert "workflow_dispatch:" not in workflow
    assert "push:" not in workflow
    assert "schedule:" not in workflow


def test_workflow_runs_python_312_and_313_with_pinned_build_tools() -> None:
    workflow = text()

    assert 'python-version: ["3.12", "3.13"]' in workflow
    assert "actions/checkout@v4" in workflow
    assert "actions/setup-python@v5" in workflow
    for requirement in (
        "pip==25.2",
        "setuptools==80.9.0",
        "wheel==0.45.1",
        "build==1.3.0",
    ):
        assert requirement in workflow
    assert "python -m pip install -e '.[dev]'" in workflow
    assert "ruff check ." in workflow
    assert "python -m compileall -q src scripts" in workflow
    assert "python -m pytest -q" in workflow


def test_workflow_derives_epoch_and_two_clean_sources_from_exact_git_tree() -> None:
    workflow = text()

    assert "git rev-parse HEAD" in workflow
    assert "git show -s --format=%ct HEAD" in workflow
    assert "validate-source-date-epoch" in workflow
    assert workflow.count("git archive --format=tar HEAD") == 2
    assert "source-a" in workflow
    assert "source-b" in workflow
    assert "date +%s" not in workflow
    assert "SOURCE_DATE_EPOCH: '315532800'" not in workflow
    assert "cp -a ." not in workflow
    assert "rsync" not in workflow


def test_workflow_builds_twice_per_interpreter_under_one_fixed_environment() -> None:
    workflow = text()

    assert workflow.count("python -m build --wheel --no-isolation") == 2
    assert "PYTHONHASHSEED: '0'" in workflow
    assert "TZ: UTC" in workflow
    assert "LC_ALL: C.UTF-8" in workflow
    assert "LANG: C.UTF-8" in workflow
    assert "SOURCE_DATE_EPOCH" in workflow
    assert "build-a" in workflow
    assert "build-b" in workflow
    assert "expected exactly one wheel" in workflow


def test_workflow_inspects_compares_and_keeps_cross_python_status_separate() -> None:
    workflow = text()

    assert "scripts/verify_release_wheel.py inspect" in workflow
    assert "scripts/verify_release_wheel.py compare" in workflow
    assert "--expected-name nextgen-memory" in workflow
    assert "--expected-version 0.1.0" in workflow
    assert "--required-module nextgen_memory" in workflow
    assert "same_interpreter_reproducible" in workflow
    assert "cross_python_byte_identical" in workflow
    assert "python_3_12_sha256" in workflow
    assert "python_3_13_sha256" in workflow
    assert "same_interpreter_reproducible = cross_python_byte_identical" not in workflow


def test_workflow_installs_outside_checkout_and_verifies_all_public_exports() -> None:
    workflow = text()

    assert "python -m venv" in workflow
    assert "pip install --no-deps" in workflow
    assert "python -I" in workflow
    assert "mktemp -d" in workflow
    assert "nextgen_memory.__file__" in workflow
    assert "nextgen_memory.__all__" in workflow
    assert "pip check" in workflow
    assert "Path(sys.prefix).resolve()" in workflow
    assert "is_relative_to" in workflow


def test_workflow_uploads_only_bounded_release_evidence_for_seven_days() -> None:
    workflow = text()

    assert "actions/upload-artifact@v4" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "if-no-files-found: error" in workflow
    assert "retention-days: 7" in workflow
    for artifact in (
        "wheel-a/*.whl",
        "wheel-b/*.whl",
        "inspection-a.json",
        "inspection-b.json",
        "same-interpreter-comparison.json",
        "build-environment.json",
        "cross-python-summary.json",
    ):
        assert artifact in workflow
    assert "stdout.log" not in workflow
    assert "stderr.log" not in workflow
    assert "repository.tar" not in workflow


def test_workflow_has_no_publication_or_repository_secret_surface() -> None:
    workflow = text().lower()

    assert "${{ secrets." not in workflow
    assert "twine" not in workflow
    assert "pypi" not in workflow
    assert "npm publish" not in workflow
    assert "gh release" not in workflow
    assert "docker push" not in workflow
    assert "sigstore" not in workflow
    assert "attest" not in workflow
