# Release Wheel Integrity and Reproducibility v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a dependency-free wheel integrity gate that proves safe archive structure, isolated installation, same-interpreter byte reproducibility, and separately reports cross-interpreter byte identity without changing runtime code or publishing a package.

**Architecture:** A pure `zipfile` inspector validates one wheel and emits an allowlisted frozen report. A comparator consumes two validated wheels, distinguishes semantic equality from byte equality, and emits only bounded member evidence on drift. A read-only GitHub Actions workflow builds the exact Git tree twice per Python version under one commit-derived `SOURCE_DATE_EPOCH`, verifies installation outside the checkout, and reports cross-Python equality separately.

**Tech Stack:** Python 3.12/3.13 standard library (`argparse`, `dataclasses`, `email`, `hashlib`, `json`, `pathlib`, `zipfile`), pytest, Ruff, setuptools/wheel/build in GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-23-release-wheel-integrity-v1-design.md`

## Global Constraints

- Base SHA is `937385e4d9235841a38fb28d079fcc0c7c3abe79` on `integration/rehearse-green-candidates-v3-20260823`.
- Write branch is `release/wheel-integrity-reproducibility-v1-20260823`.
- Do not modify `src/nextgen_memory/`, migrations, package-root exports, runtime dependencies, or active corrective-retrieval files.
- The inspector must use only the Python standard library and must never extract or import the inspected wheel.
- Same-interpreter double-build byte equality is required; cross-Python equality is a distinct reported field.
- `SOURCE_DATE_EPOCH` must be derived from the exact candidate commit and must never fall back to wall clock.
- Workflow permissions are `contents: read`; no secrets, publishing credentials, signing, registry upload, or production operation.
- Failure reports contain only allowlisted archive names, sizes, timestamps, CRC-32 values, and SHA-256 values; no member contents, filesystem parent paths, environment, SQL, command output, or credentials.
- TDD order is mandatory: focused RED, minimal complete implementation, focused GREEN, repository regression, exact-SHA CI, blind Sol review.
- No `pass`, ellipsis implementation body, `NotImplementedError`, TODO/FIXME placeholder, skipped/xfail test, `noqa` escape, or fake success path.

---

## File Map

- Create `scripts/verify_release_wheel.py`: wheel validation, safe immutable reports, reproducibility comparison, source-date validation, and CLI.
- Create `tests/test_release_wheel_integrity.py`: adversarial unit contracts for inspection, comparison, bounded diagnostics, source-date handling, and CLI.
- Create `tests/test_release_wheel_workflow.py`: static workflow contract covering permissions, path filters, source archiving, fixed toolchain, double builds, isolated install, artifact boundary, and cross-Python summary semantics.
- Create `.github/workflows/release-wheel-integrity.yml`: executable Python 3.12/3.13 release gate.
- Preserve `pyproject.toml`, runtime sources, migrations, and `src/nextgen_memory/__init__.py` unchanged.

---

### Task 1: Record the inspector and report contracts in RED

**Files:**
- Create: `tests/test_release_wheel_integrity.py`
- Read: `pyproject.toml`
- Read: `src/nextgen_memory/__init__.py`

**Interfaces:**
- Consumes: project distribution `nextgen-memory`, version `0.1.0`, package root `nextgen_memory`.
- Produces test requirements for:
  - `WheelValidationError`;
  - `WheelMemberEvidence`;
  - `WheelInspectionReport`;
  - `inspect_wheel(path: Path, *, expected_name: str, expected_version: str, required_modules: tuple[str, ...]) -> WheelInspectionReport`.

- [ ] **Step 1: Add deterministic synthetic-wheel helpers**

Create a helper that writes exact ZIP members without extraction:

```python
FIXED_ZIP_TIME = (2020, 1, 2, 3, 4, 6)


def write_wheel(
    path: Path,
    *,
    distribution: str = "nextgen-memory",
    version: str = "0.1.0",
    members: dict[str, bytes | str] | None = None,
    duplicate: tuple[str, bytes | str] | None = None,
) -> Path:
    payload = {
        "nextgen_memory/__init__.py": "__all__ = ('marker',)\nmarker = 'ok'\n",
        "nextgen_memory/domain.py": "VALUE = 1\n",
        f"nextgen_memory-{version}.dist-info/METADATA": (
            "Metadata-Version: 2.4\n"
            f"Name: {distribution}\n"
            f"Version: {version}\n\n"
        ),
        f"nextgen_memory-{version}.dist-info/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ),
        f"nextgen_memory-{version}.dist-info/RECORD": "",
    }
    if members:
        payload.update(members)
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
```

- [ ] **Step 2: Add the valid-wheel and privacy-safe report tests**

Require frozen/slotted deterministic evidence:

```python
def test_inspect_wheel_accepts_valid_archive_and_emits_safe_canonical_report(
    tmp_path: Path,
) -> None:
    private_parent = tmp_path / "private-parent-secret"
    private_parent.mkdir()
    wheel = write_wheel(private_parent / "nextgen_memory-0.1.0-py3-none-any.whl")

    report = inspect_wheel(
        wheel,
        expected_name="nextgen-memory",
        expected_version="0.1.0",
        required_modules=("nextgen_memory.domain", "nextgen_memory"),
    )

    assert report.distribution == "nextgen-memory"
    assert report.version == "0.1.0"
    assert report.member_count == 5
    assert report.package_member_count == 2
    assert report.required_modules == (
        "nextgen_memory",
        "nextgen_memory.domain",
    )
    assert not hasattr(report, "__dict__")
    payload = report.to_json()
    assert payload == report.to_json()
    assert json.loads(payload)["wheel_filename"] == wheel.name
    assert "private-parent-secret" not in payload
    assert "marker = 'ok'" not in payload
    assert "Metadata-Version" not in payload
```

- [ ] **Step 3: Add unsafe-name and duplicate/collision tests**

Parameterize these invalid member names:

```python
@pytest.mark.parametrize(
    "name",
    [
        "/absolute.py",
        "../escape.py",
        "nextgen_memory/../../escape.py",
        "nextgen_memory\\windows.py",
        "nextgen_memory//double.py",
        "nextgen_memory/./dot.py",
        "nextgen_memory/nul\x00.py",
        "",
    ],
)
def test_inspector_rejects_noncanonical_archive_names(tmp_path: Path, name: str) -> None:
    wheel = write_wheel(tmp_path / "unsafe.whl", members={name: b"unsafe"})
    with pytest.raises(WheelValidationError, match="archive member name"):
        inspect_wheel(
            wheel,
            expected_name="nextgen-memory",
            expected_version="0.1.0",
            required_modules=("nextgen_memory",),
        )
```

Also require rejection of:

```python
("nextgen_memory/domain.py", "SECOND = True\n")  # exact duplicate
"NextGen_Memory/domain.py"  # case collision with nextgen_memory/domain.py
```

- [ ] **Step 4: Add forbidden-payload tests**

Require rejection of all of these paths:

```python
FORBIDDEN_MEMBERS = (
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
)
```

Each must raise `WheelValidationError` with a bounded message containing `forbidden release payload` and not echoing filesystem paths or content.

- [ ] **Step 5: Add metadata and required-module adversarial tests**

Cover:

- missing `METADATA`, `WHEEL`, or `RECORD`;
- two `.dist-info/METADATA` records;
- invalid UTF-8 metadata;
- duplicate `Name` or `Version` headers;
- normalized-name mismatch;
- version mismatch;
- missing `nextgen_memory/__init__.py`;
- missing required module;
- a module required as `nextgen_memory.domain` resolving only to `nextgen_memory/domain/__init__.py` or `nextgen_memory/domain.py`, but not an unrelated prefix.

Use exact assertions such as:

```python
with pytest.raises(WheelValidationError, match="exactly one METADATA"):
    inspect_wheel(...)

with pytest.raises(WheelValidationError, match="required module"):
    inspect_wheel(..., required_modules=("nextgen_memory.missing",))
```

- [ ] **Step 6: Add input-file boundary tests**

Require rejection when the input:

- is missing;
- is a directory;
- is a symlink;
- does not end in `.whl`;
- is not a ZIP archive.

- [ ] **Step 7: Run the focused tests to prove RED**

Run:

```bash
python -m pytest -q tests/test_release_wheel_integrity.py
```

Expected: collection error because `scripts.verify_release_wheel` does not exist. Ruff must still pass for the test file:

```bash
ruff check tests/test_release_wheel_integrity.py
```

Expected: PASS.

- [ ] **Step 8: Commit RED evidence**

```bash
git add tests/test_release_wheel_integrity.py
git commit -m "test: define release wheel integrity contract"
```

---

### Task 2: Implement the dependency-free wheel inspector

**Files:**
- Create: `scripts/verify_release_wheel.py`
- Test: `tests/test_release_wheel_integrity.py`

**Interfaces:**
- Consumes the Task 1 test contract.
- Produces:

```python
class WheelValidationError(ValueError): ...

@dataclass(frozen=True, slots=True)
class WheelMemberEvidence:
    name: str
    size: int
    compressed_size: int
    crc32: str
    timestamp: tuple[int, int, int, int, int, int]
    sha256: str

@dataclass(frozen=True, slots=True)
class WheelInspectionReport:
    wheel_filename: str
    wheel_sha256: str
    wheel_size_bytes: int
    distribution: str
    version: str
    member_count: int
    package_member_count: int
    required_modules: tuple[str, ...]
    metadata_sha256: str
    wheel_metadata_sha256: str
    record_sha256: str
    members: tuple[WheelMemberEvidence, ...]

    def to_safe_dict(self) -> dict[str, object]: ...
    def to_json(self) -> str: ...


def inspect_wheel(
    path: Path,
    *,
    expected_name: str,
    expected_version: str,
    required_modules: tuple[str, ...],
) -> WheelInspectionReport: ...
```

- [ ] **Step 1: Add canonical JSON and distribution normalization**

Implement:

```python
_NORMALIZE_DISTRIBUTION = re.compile(r"[-_.]+")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"


def _normalize_distribution(value: str) -> str:
    normalized = _NORMALIZE_DISTRIBUTION.sub("-", value).lower()
    if not normalized or normalized.startswith("-") or normalized.endswith("-"):
        raise WheelValidationError("distribution name is invalid")
    return normalized
```

- [ ] **Step 2: Validate the input path before ZIP access**

Use `Path.lstat()` and reject symlinks, non-regular files, non-`.whl` names, and missing files with fixed messages. Never include the parent path in an error or report.

- [ ] **Step 3: Validate every ZIP member name and collision domain**

For each `ZipInfo.filename`:

- require exact `PurePosixPath(name).as_posix() == name`;
- reject absolute paths, `.`/`..`, empty parts, backslash, NUL, leading slash, trailing slash for non-directory entries, and duplicate separators;
- keep an exact-name set and a `casefold()` set;
- reject exact duplicate or case-fold collision before reading contents.

- [ ] **Step 4: Validate forbidden payload patterns**

Match complete path components and suffixes, not arbitrary substrings. Reject VCS directories, test roots, cache directories, `.pyc`/`.pyo`, `.env`, private-key/certificate suffixes, credential directories, and editor metadata.

- [ ] **Step 5: Parse exact metadata records**

Collect exactly one path ending in each of:

```python
".dist-info/METADATA"
".dist-info/WHEEL"
".dist-info/RECORD"
```

Require all three share the same `.dist-info` directory. Decode metadata as strict UTF-8 and parse with `email.parser.BytesParser(policy=email.policy.default)`. Require exactly one nonempty `Name` and `Version` header and exact normalized identity.

- [ ] **Step 6: Resolve required modules exactly**

For module `a.b.c`, accept either:

```text
a/b/c.py
a/b/c/__init__.py
```

For package root `nextgen_memory`, require `nextgen_memory/__init__.py`. Sort/deduplicate the caller-supplied required modules before validation and report construction.

- [ ] **Step 7: Build allowlisted member and wheel evidence**

For each member, compute SHA-256 from `archive.read(info)` and encode CRC as eight lowercase hex digits. Store only the relative archive name and bounded metadata. Compute the wheel SHA-256 by streaming the file in fixed chunks.

- [ ] **Step 8: Run focused GREEN**

```bash
ruff check scripts/verify_release_wheel.py tests/test_release_wheel_integrity.py
python -m pytest -q tests/test_release_wheel_integrity.py
```

Expected: all Task 1 tests pass.

- [ ] **Step 9: Commit the complete inspector**

```bash
git add scripts/verify_release_wheel.py tests/test_release_wheel_integrity.py
git commit -m "feat: inspect release wheels without extraction"
```

---

### Task 3: Add source-date and reproducibility comparison contracts

**Files:**
- Modify: `tests/test_release_wheel_integrity.py`
- Modify: `scripts/verify_release_wheel.py`

**Interfaces:**
- Consumes `WheelInspectionReport` and `WheelMemberEvidence`.
- Produces:

```python
class WheelReproducibilityError(ValueError):
    def to_json(self) -> str: ...

@dataclass(frozen=True, slots=True)
class WheelMemberDifference:
    name: str
    left: WheelMemberEvidence | None
    right: WheelMemberEvidence | None

@dataclass(frozen=True, slots=True)
class WheelReproducibilityReport:
    left_filename: str
    right_filename: str
    left_sha256: str
    right_sha256: str
    byte_reproducible: bool
    semantic_reproducible: bool
    differences: tuple[WheelMemberDifference, ...]

    def to_safe_dict(self) -> dict[str, object]: ...
    def to_json(self) -> str: ...


def compare_wheels(
    left: Path,
    right: Path,
    *,
    expected_name: str,
    expected_version: str,
    required_modules: tuple[str, ...],
    require_byte_reproducible: bool = True,
) -> WheelReproducibilityReport: ...


def validate_source_date_epoch(value: str) -> int: ...
```

- [ ] **Step 1: Add SOURCE_DATE_EPOCH RED cases**

Require acceptance of canonical decimal epoch `315532800` and rejection of:

```python
("", "source date epoch")
(" 315532800", "source date epoch")
("315532800 ", "source date epoch")
("+315532800", "source date epoch")
("-1", "source date epoch")
("3.155328e8", "source date epoch")
("315532799", "ZIP-compatible")
("999999999999999999999", "source date epoch")
```

The lower bound is 1980-01-01 UTC (`315532800`). Validate that `datetime.fromtimestamp(value, timezone.utc).year <= 2107`, matching ZIP timestamp representability.

- [ ] **Step 2: Add identical-wheel comparison tests**

Write two wheels with the same bytes and require:

```python
report = compare_wheels(...)
assert report.byte_reproducible is True
assert report.semantic_reproducible is True
assert report.differences == ()
assert report.to_json() == report.to_json()
```

- [ ] **Step 3: Add bounded drift tests**

Create wheels differing by:

- one member content;
- one added member;
- one removed member;
- one ZIP timestamp only;
- one compression-size/metadata difference while member bytes remain equal.

With `require_byte_reproducible=False`, require a deterministic sorted `differences` tuple containing only member evidence. Assert sentinel contents, parent paths, environment values, and raw metadata are absent from JSON.

With `require_byte_reproducible=True`, require `WheelReproducibilityError`; its JSON contains `byte_reproducible=false`, `semantic_reproducible` and bounded differences only.

- [ ] **Step 4: Add semantic-vs-byte separation tests**

A ZIP timestamp-only difference must yield:

```python
assert report.byte_reproducible is False
assert report.semantic_reproducible is True
```

A changed member SHA-256, member set, normalized metadata identity, or required-module set must yield `semantic_reproducible=False`.

- [ ] **Step 5: Run RED**

```bash
python -m pytest -q tests/test_release_wheel_integrity.py -k "source_date or reproducib or compare"
```

Expected: failures because comparison/source-date interfaces are absent.

- [ ] **Step 6: Implement strict source-date parsing**

Use exact ASCII decimal parsing and `datetime.fromtimestamp(..., timezone.utc)` without fallback. Reject booleans/non-strings at the public function boundary.

- [ ] **Step 7: Implement semantic and byte comparison**

Inspect both wheels independently, compare full file bytes for byte equality, and compare validated member SHA/name/metadata/module evidence for semantic equality. Sort differences by member name. Never inspect unvalidated names.

- [ ] **Step 8: Implement bounded reproducibility errors**

`WheelReproducibilityError` receives a `WheelReproducibilityReport`, exposes only `to_safe_dict()`/`to_json()`, and uses fixed `str(error) == "wheel reproducibility requirement failed"`.

- [ ] **Step 9: Run focused GREEN and complete current suite**

```bash
ruff check scripts/verify_release_wheel.py tests/test_release_wheel_integrity.py
python -m pytest -q tests/test_release_wheel_integrity.py
python -m pytest -q
```

Expected: all pass.

- [ ] **Step 10: Commit comparison support**

```bash
git add scripts/verify_release_wheel.py tests/test_release_wheel_integrity.py
git commit -m "feat: compare release wheels reproducibly"
```

---

### Task 4: Add the safe CLI contract

**Files:**
- Modify: `scripts/verify_release_wheel.py`
- Modify: `tests/test_release_wheel_integrity.py`

**Interfaces:**
- Consumes inspector, comparator, and source-date validator.
- Produces:

```python
def main(argv: Sequence[str] | None = None) -> int: ...
```

CLI modes:

```text
inspect WHEEL --expected-name NAME --expected-version VERSION --required-module MODULE...
compare LEFT RIGHT --expected-name NAME --expected-version VERSION --required-module MODULE... [--allow-byte-difference]
validate-source-date-epoch VALUE
```

- [ ] **Step 1: Add CLI success tests**

Require stdout to be exactly one canonical JSON object plus newline and stderr empty for all three modes.

- [ ] **Step 2: Add CLI failure/privacy tests**

For invalid wheel, failed required comparison, and invalid source date:

- return code is `2`;
- stdout is empty;
- stderr is one canonical JSON object with an allowlisted `error_class` and safe report fields;
- sentinel parent path, content, environment, and credential values are absent.

- [ ] **Step 3: Run CLI RED**

```bash
python -m pytest -q tests/test_release_wheel_integrity.py -k cli
```

- [ ] **Step 4: Implement argparse subcommands and bounded exception handling**

Catch only `WheelValidationError`, `WheelReproducibilityError`, and source-date `ValueError`. Unexpected exceptions must propagate in library use and may be converted by `main()` to the fixed class `unexpected_error` without `repr(exc)` or backend text.

- [ ] **Step 5: Run focused GREEN**

```bash
ruff check scripts/verify_release_wheel.py tests/test_release_wheel_integrity.py
python -m pytest -q tests/test_release_wheel_integrity.py
```

- [ ] **Step 6: Commit CLI**

```bash
git add scripts/verify_release_wheel.py tests/test_release_wheel_integrity.py
git commit -m "feat: add privacy-safe wheel verification CLI"
```

---

### Task 5: Define and implement the read-only release workflow

**Files:**
- Create: `tests/test_release_wheel_workflow.py`
- Create: `.github/workflows/release-wheel-integrity.yml`

**Interfaces:**
- Consumes `scripts/verify_release_wheel.py` CLI.
- Produces one matrix job per Python version and one cross-version summary job.

- [ ] **Step 1: Add workflow RED tests**

Require exact path filters:

```python
EXPECTED_PATHS = {
    ".github/workflows/release-wheel-integrity.yml",
    "docs/superpowers/plans/2026-08-23-release-wheel-integrity-v1.md",
    "docs/superpowers/specs/2026-08-23-release-wheel-integrity-v1-design.md",
    "pyproject.toml",
    "scripts/verify_release_wheel.py",
    "src/**",
    "tests/test_release_wheel_integrity.py",
    "tests/test_release_wheel_workflow.py",
}
```

Require:

```text
pull_request only
permissions: contents: read
python-version: ["3.12", "3.13"]
no push / workflow_dispatch / id-token / secrets / twine / pypi / gh release
```

- [ ] **Step 2: Require exact source archiving and commit-derived epoch**

Static tests must find:

```bash
git rev-parse HEAD
git show -s --format=%ct HEAD
git archive --format=tar HEAD
```

and two distinct clean source directories. They must not find `cp -a .`, wall-clock `date +%s`, or a hard-coded epoch.

- [ ] **Step 3: Require pinned double-build commands**

Static tests require pinned versions:

```text
pip==25.2
setuptools==80.9.0
wheel==0.45.1
build==1.3.0
```

and two `python -m build --wheel --no-isolation` invocations under the same `SOURCE_DATE_EPOCH`, `PYTHONHASHSEED=0`, `TZ=UTC`, and `LC_ALL/LANG=C.UTF-8`.

- [ ] **Step 4: Require inspector/comparator and isolated install**

Static tests require:

```text
scripts/verify_release_wheel.py inspect
scripts/verify_release_wheel.py compare
python -m venv
pip install --no-deps
python -I
nextgen_memory.__file__
nextgen_memory.__all__
pip check
```

The isolated import working directory must be created with `mktemp -d` outside `${{ github.workspace }}`.

- [ ] **Step 5: Require artifact and matrix-summary boundaries**

The matrix job uploads exactly:

- two wheels;
- two inspection reports;
- one same-interpreter comparison report;
- one build-environment report containing exact source SHA, Python version, tool versions, and source-date epoch.

Retention is seven days and `if-no-files-found: error`. The summary job downloads both artifacts and emits:

```json
{
  "same_interpreter_reproducible": true,
  "python_3_12_sha256": "...",
  "python_3_13_sha256": "...",
  "cross_python_byte_identical": false
}
```

The summary must never change `same_interpreter_reproducible` based on cross-Python equality.

- [ ] **Step 6: Run workflow-contract RED**

```bash
ruff check tests/test_release_wheel_workflow.py
python -m pytest -q tests/test_release_wheel_workflow.py
```

Expected: failures because `.github/workflows/release-wheel-integrity.yml` is absent.

- [ ] **Step 7: Implement the workflow**

Use `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`, and `actions/download-artifact@v4`. The matrix job must prove exactly one wheel per output directory and invoke the CLI with:

```text
--expected-name nextgen-memory
--expected-version 0.1.0
--required-module nextgen_memory
```

Generate additional required modules from a fixed workflow allowlist covering every current top-level `src/nextgen_memory/*.py` module that is intended to ship; compare this list against the built wheel through the inspector.

- [ ] **Step 8: Run workflow-contract GREEN and repository checks**

```bash
ruff check .
python -m compileall -q src scripts
python -m pytest -q tests/test_release_wheel_integrity.py tests/test_release_wheel_workflow.py
python -m pytest -q
git diff --check 937385e4d9235841a38fb28d079fcc0c7c3abe79...HEAD
```

- [ ] **Step 9: Commit workflow**

```bash
git add .github/workflows/release-wheel-integrity.yml tests/test_release_wheel_workflow.py
git commit -m "ci: verify release wheel integrity reproducibly"
```

---

### Task 6: Create the exact candidate and verify it independently

**Files:**
- No new product files unless a concrete failure requires a reviewed correction.
- Update PR/issue/checkpoint metadata outside the candidate tree.

**Interfaces:**
- Consumes the complete release-wheel candidate.
- Produces one immutable exact-SHA review boundary and evidence packet.

- [ ] **Step 1: Inspect the exact base-to-head surface**

Expected paths only:

```text
.github/workflows/release-wheel-integrity.yml
docs/superpowers/plans/2026-08-23-release-wheel-integrity-v1.md
docs/superpowers/specs/2026-08-23-release-wheel-integrity-v1-design.md
scripts/verify_release_wheel.py
tests/test_release_wheel_integrity.py
tests/test_release_wheel_workflow.py
```

`pyproject.toml` must remain unchanged unless a test proves an exact packaging requirement that cannot be satisfied in workflow/tooling alone. `src/**`, migrations, and corrective-retrieval paths must be absent.

- [ ] **Step 2: Run ordinary PR CI**

Require both standard CI jobs and both release-wheel matrix jobs to complete successfully on Python 3.12 and 3.13. Record exact run IDs and artifact IDs.

- [ ] **Step 3: Run raw-SHA verification**

Create an ephemeral verifier that checks out the immutable candidate SHA directly and repeats:

- exact SHA/base/path proof;
- Ruff, compileall, focused tests, complete suite;
- same-interpreter double build and comparison for Python 3.12 and 3.13;
- isolated install/import/API/pip check;
- cross-Python summary without conflating statuses;
- privacy scan of all JSON artifacts.

Close the verifier without merge after evidence capture.

- [ ] **Step 4: Review the exact diff and reports**

Verify:

- no unsafe archive or member content appears in reports;
- no source checkout path appears;
- no environment/credential/command output appears;
- exact source SHA and tool versions are present;
- same-interpreter reproducibility is true in both jobs;
- cross-Python field accurately reflects observed bytes.

- [ ] **Step 5: Post the blind Sol packet**

The packet contains the task contract, exact SHA/base, exact six-path diff, focused/full test evidence, both build reports, same-interpreter and cross-interpreter results, known platform boundary, and no prior reviewer verdict or persuasive worker identity.

- [ ] **Step 6: Record durable Neon/Mongo checkpoint**

Record candidate branch/SHA, base SHA, exact scope, ordinary and raw-SHA run IDs, wheel identities, tool versions, source-date epoch, report hashes, Sol verdict, merge prohibition, known limitations, and next action. Store no secret, raw wheel contents, or transient workspace path.

- [ ] **Step 7: Merge only on exact-SHA Sol APPROVE**

If verdict is `CHANGES_REQUIRED`, address exact findings and repeat invalidated evidence. If `BLOCKED_BY_EVIDENCE`, narrow the claim or obtain missing evidence. Never merge or publish a package without `APPROVE` on the unchanged SHA and correct dependency order.

---

## Self-Review

- Spec coverage: Tasks 1–4 cover safe inspection, metadata, source-date, semantic/byte comparison, bounded diagnostics, and CLI. Task 5 covers read-only build/install/reproducibility workflow and separate cross-Python reporting. Task 6 covers exact-SHA evidence, durable state, Sol, merge, and no publication.
- Placeholder scan: no TODO/TBD/“implement later” steps remain; each code-facing step names exact interfaces, inputs, expected assertions, and commands.
- Type consistency: `WheelMemberEvidence`, `WheelInspectionReport`, `WheelMemberDifference`, `WheelReproducibilityReport`, `inspect_wheel`, `compare_wheels`, `validate_source_date_epoch`, and `main` retain identical names across tasks.
- Scope consistency: no task modifies runtime `src/`, migrations, package-root API, or corrective-retrieval files.

## Execution Choice

This session uses **Inline Execution** with `superpowers:executing-plans`: execute the tasks sequentially, preserve TDD RED evidence, and checkpoint after each independently reviewable deliverable.