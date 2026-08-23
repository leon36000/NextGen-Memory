from __future__ import annotations

import pytest
from scripts.verify_no_stubs import scan_source


def kinds(source: str) -> list[str]:
    return [finding.kind for finding in scan_source(source, path="src/shadowing.py")]


@pytest.mark.parametrize(
    "source",
    [
        "class ValueError:\n    pass\n",
        "class RuntimeError:\n    ...\n",
        "class Exception:\n    \"\"\"not actually an exception\"\"\"\n    pass\n",
    ],
)
def test_builtin_exception_name_without_inheritance_is_not_exempt(source: str) -> None:
    assert kinds(source) == ["class_stub"]


def test_local_non_exception_class_shadows_builtin_for_later_base() -> None:
    source = '''
class ValueError:
    def marker(self) -> int:
        return 1

class HiddenStub(ValueError):
    pass
'''

    findings = scan_source(source, path="src/shadowing.py")

    assert [(finding.kind, finding.symbol) for finding in findings] == [
        ("class_stub", "HiddenStub")
    ]


@pytest.mark.parametrize(
    "binding",
    [
        "ValueError = object",
        "def ValueError():\n    return object",
        "from custom_errors import Other as ValueError",
        "import custom_errors as ValueError",
    ],
)
def test_prior_non_exception_binding_shadows_builtin_name(binding: str) -> None:
    source = f'''\
{binding}

class HiddenStub(ValueError):
    pass
'''

    assert [(finding.kind, finding.symbol) for finding in scan_source(
        source,
        path="src/shadowing.py",
    )] == [("class_stub", "HiddenStub")]


def test_direct_and_transitive_real_exception_subclasses_remain_exempt() -> None:
    source = '''
class DomainFailure(ValueError):
    pass

class SpecializedFailure(DomainFailure):
    ...
'''

    assert scan_source(source, path="src/exceptions.py") == ()


@pytest.mark.parametrize(
    "source",
    [
        '''
import builtins

class DomainFailure(builtins.ValueError):
    pass
''',
        '''
import builtins as runtime

class DomainFailure(runtime.ValueError):
    pass
''',
    ],
)
def test_qualified_builtin_exception_base_is_recognized(source: str) -> None:
    assert scan_source(source, path="src/exceptions.py") == ()


def test_nested_scope_shadowing_is_local_and_deterministic() -> None:
    source = '''
class Outer:
    class ValueError:
        def marker(self) -> int:
            return 1

    class HiddenStub(ValueError):
        pass

class RealFailure(ValueError):
    pass
'''

    findings = scan_source(source, path="src/nested.py")

    assert [(finding.kind, finding.symbol) for finding in findings] == [
        ("class_stub", "Outer.HiddenStub")
    ]


def test_exception_name_rebound_after_real_subclass_blocks_future_exemption() -> None:
    source = '''
class FirstFailure(ValueError):
    pass

ValueError = object

class HiddenStub(ValueError):
    pass
'''

    findings = scan_source(source, path="src/rebound.py")

    assert [(finding.kind, finding.symbol) for finding in findings] == [
        ("class_stub", "HiddenStub")
    ]
