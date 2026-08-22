from __future__ import annotations

from scripts.verify_no_stubs import scan_source


def test_nested_concrete_class_reusing_protocol_name_is_not_exempt() -> None:
    source = '''
from typing import Protocol

class Contract(Protocol):
    def run(self) -> None: ...

class Outer:
    class Contract:
        pass
'''

    findings = scan_source(source, path="src/protocol_shadow.py")

    assert [(finding.kind, finding.symbol) for finding in findings] == [
        ("class_stub", "Outer.Contract")
    ]


def test_later_concrete_redefinition_of_protocol_name_is_not_exempt() -> None:
    source = '''
from typing import Protocol

class Contract(Protocol):
    def run(self) -> None: ...

class Contract:
    pass
'''

    findings = scan_source(source, path="src/protocol_rebound.py")

    assert [(finding.kind, finding.symbol) for finding in findings] == [
        ("class_stub", "Contract")
    ]


def test_real_protocol_subclass_chain_remains_exempt() -> None:
    source = '''
from typing import Protocol

class ParentContract(Protocol):
    def run(self) -> None: ...

class ChildContract(ParentContract, Protocol):
    def stop(self) -> None: ...
'''

    assert scan_source(source, path="src/protocols.py") == ()
