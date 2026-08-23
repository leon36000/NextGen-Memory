from __future__ import annotations

import builtins

import pytest
from scripts.verify_no_stubs import scan_source

BUILTIN_EXCEPTION_NAMES = tuple(
    sorted(
        name
        for name, value in vars(builtins).items()
        if isinstance(value, type) and issubclass(value, BaseException)
    )
)


def findings(source: str) -> list[tuple[str, str]]:
    return [
        (finding.kind, finding.symbol)
        for finding in scan_source(source, path="src/lexical_hardening.py")
    ]


@pytest.mark.parametrize("exception_name", BUILTIN_EXCEPTION_NAMES)
def test_every_builtin_exception_subclass_is_exempt(
    exception_name: str,
) -> None:
    source = f"class DomainFailure({exception_name}):\n    pass\n"

    assert scan_source(source, path="src/builtin_exceptions.py") == ()


def test_protocol_subclass_without_explicit_protocol_base_is_concrete() -> None:
    source = '''
from typing import Protocol

class Contract(Protocol):
    def run(self) -> None: ...

class HiddenStub(Contract):
    pass
'''

    assert findings(source) == [("class_stub", "HiddenStub")]


@pytest.mark.parametrize(
    "source",
    [
        '''
from abc import abstractmethod
abstractmethod = lambda function: function

@abstractmethod
def unfinished() -> None:
    pass
''',
        '''
import abc
abc = object()

@abc.abstractmethod
def unfinished() -> None:
    pass
''',
        '''
from typing import overload
overload = lambda function: function

@overload
def unfinished(value: int) -> int:
    ...
''',
        '''
import typing
typing = object()

@typing.overload
def unfinished(value: int) -> int:
    ...
''',
        '''
@abstractmethod
def unfinished() -> None:
    pass
''',
        '''
@typing.overload
def unfinished(value: int) -> int:
    ...
''',
        '''
from abc import abstractmethod

@abstractmethod()
def unfinished() -> None:
    pass
''',
        '''
from typing import overload

@overload()
def unfinished(value: int) -> int:
    ...
''',
    ],
)
def test_shadowed_unbound_or_called_abstract_decorators_do_not_exempt_stubs(
    source: str,
) -> None:
    assert findings(source) == [("function_stub", "unfinished")]


def test_function_local_abstractmethod_alias_is_recognized() -> None:
    source = '''
def factory():
    from abc import abstractmethod as abstract

    @abstract
    def unfinished() -> None:
        pass

    return unfinished
'''

    assert scan_source(source, path="src/local_abstract.py") == ()


def test_class_local_abstractmethod_alias_is_recognized() -> None:
    source = '''
class AbstractService:
    from abc import abstractmethod as abstract

    @abstract
    def run(self) -> None:
        pass
'''

    assert scan_source(source, path="src/class_abstract.py") == ()


def test_direct_abstractmethod_assignment_alias_is_recognized() -> None:
    source = '''
from abc import abstractmethod
abstract = abstractmethod

@abstract
def unfinished() -> None:
    pass
'''

    assert scan_source(source, path="src/direct_abstract.py") == ()


def test_function_local_decorator_rebinding_blocks_exemption() -> None:
    source = '''
def factory():
    from abc import abstractmethod as abstract
    abstract = lambda function: function

    @abstract
    def unfinished() -> None:
        pass

    return unfinished
'''

    assert findings(source) == [("function_stub", "factory.unfinished")]


def test_late_function_import_is_prebound_and_cannot_use_outer_alias() -> None:
    source = '''
from abc import abstractmethod as abstract

def factory():
    @abstract
    def unfinished() -> None:
        pass

    from abc import abstractmethod as abstract
    return unfinished
'''

    assert findings(source) == [("function_stub", "factory.unfinished")]


def test_except_alias_shadows_builtin_exception_in_handler() -> None:
    source = '''
try:
    raise RuntimeError
except RuntimeError as ValueError:
    class HiddenStub(ValueError):
        pass
'''

    assert findings(source) == [("class_stub", "HiddenStub")]


def test_named_expression_binding_shadows_builtin_before_branch() -> None:
    source = '''
if (ValueError := object):
    class HiddenStub(ValueError):
        pass
'''

    assert findings(source) == [("class_stub", "HiddenStub")]


def test_function_global_assignment_is_visible_to_later_class_base() -> None:
    source = '''
def factory():
    global ValueError
    ValueError = object

    class HiddenStub(ValueError):
        pass

    return HiddenStub
'''

    assert findings(source) == [("class_stub", "factory.HiddenStub")]


@pytest.mark.parametrize(
    "source",
    [
        '''
class NotImplementedError(RuntimeError):
    pass

def complete() -> None:
    raise NotImplementedError("domain failure")
''',
        '''
NotImplementedError = RuntimeError

def complete() -> None:
    raise NotImplementedError("domain failure")
''',
        '''
def complete() -> None:
    class NotImplementedError(RuntimeError):
        pass
    raise NotImplementedError("domain failure")
''',
    ],
)
def test_shadowed_not_implemented_error_is_not_a_stub(source: str) -> None:
    assert scan_source(source, path="src/domain_errors.py") == ()


@pytest.mark.parametrize(
    "source",
    [
        '''
import builtins

def unfinished() -> None:
    raise builtins.NotImplementedError
''',
        '''
import builtins as runtime

def unfinished() -> None:
    raise runtime.NotImplementedError("later")
''',
        '''
from builtins import NotImplementedError as MissingImplementation

def unfinished() -> None:
    raise MissingImplementation
''',
        '''
def unfinished() -> None:
    from builtins import NotImplementedError as MissingImplementation
    raise MissingImplementation
''',
        '''
import builtins
MissingImplementation = builtins.NotImplementedError

def unfinished() -> None:
    raise MissingImplementation
''',
    ],
)
def test_qualified_or_aliased_builtin_not_implemented_error_is_reported(
    source: str,
) -> None:
    assert findings(source) == [("not_implemented_error", "unfinished")]
