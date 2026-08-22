from pathlib import Path

WORKFLOW = Path(".github/workflows/release-integrity.yml")


def test_release_integrity_workflow_is_path_filtered_and_cross_version() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in source
    assert "paths:" in source
    for path in (
        "src/**",
        "pyproject.toml",
        "scripts/verify_release_artifact.py",
        "tests/test_release_artifact.py",
        "tests/test_release_integrity_workflow.py",
        ".github/workflows/release-integrity.yml",
    ):
        assert path in source
    assert 'python-version: ["3.12", "3.13"]' in source


def test_release_integrity_workflow_builds_and_inspects_exactly_one_wheel() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "pip wheel --no-deps --no-build-isolation" in source
    assert "test \"${#wheels[@]}\" -eq 1" in source
    assert "scripts/verify_release_artifact.py" in source
    assert "--expected-name nextgen-memory" in source
    assert "--expected-version" in source
    assert "--required-module" in source


def test_release_integrity_workflow_installs_outside_checkout_and_imports_public_api() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "python -m venv" in source
    assert "pip install --no-deps" in source
    assert "mktemp -d" in source
    assert "python -I" in source
    assert "nextgen_memory.__file__" in source
    assert "nextgen_memory.__all__" in source
    assert "pip check" in source
    assert "REPO_ROOT" in source


def test_release_integrity_workflow_has_no_publish_or_credentials_surface() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "contents: read" in source
    assert "pypi" not in source.lower()
    assert "twine upload" not in source
    assert "id-token: write" not in source
    assert "secrets." not in source
