from pathlib import Path

WORKFLOW = Path(".github/workflows/no-stubs.yml")


def test_no_stubs_workflow_is_path_filtered_and_cross_version() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "pull_request:" in source
    assert "paths:" in source
    for path in (
        "src/**",
        "scripts/verify_no_stubs.py",
        "tests/test_no_stubs.py",
        "tests/test_no_stubs_workflow.py",
        ".github/workflows/no-stubs.yml",
    ):
        assert path in source
    assert 'python-version: ["3.12", "3.13"]' in source


def test_no_stubs_workflow_runs_scanner_without_write_or_secret_surface() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "python scripts/verify_no_stubs.py src" in source
    assert "python -m pytest -q tests/test_no_stubs.py tests/test_no_stubs_workflow.py" in source
    assert "contents: read" in source
    assert "contents: write" not in source
    assert "secrets." not in source
    assert "git push" not in source
