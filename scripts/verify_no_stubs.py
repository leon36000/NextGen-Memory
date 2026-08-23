"""Detect concrete implementation stubs in production Python source."""

from __future__ import annotations

import argparse
import ast
import io
import json
import re
import tokenize
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

_COMMENT_MARKERS = {
    "todo": "todo_comment",
    "fixme": "fixme_comment",
}
_BUILTIN_EXCEPTION_NAMES = frozenset(
    {
        "BaseException",
        "Exception",
        "ArithmeticError",
        "AssertionError",
        "AttributeError",
        "BufferError",
        "EOFError",
        "ImportError",
        "LookupError",
        "MemoryError",
        "NameError",
        "OSError",
        "ReferenceError",
        "RuntimeError",
        "StopAsyncIteration",
        "StopIteration",
        "SyntaxError",
        "SystemError",
        "TypeError",
        "ValueError",
        "Warning",
    }
)


@dataclass(frozen=True, slots=True, order=True)
class Finding:
    path: str
    line: int
    column: int
    kind: str
    symbol: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class _Aliases:
    abstract_names: frozenset[str]
    abstract_modules: frozenset[str]
    overload_names: frozenset[str]
    overload_modules: frozenset[str]


@dataclass(frozen=True, slots=True)
class _Binding:
    protocol: bool = False
    exception: bool = False
    builtins_module: bool = False
    protocol_module: bool = False


@dataclass(slots=True)
class _LexicalScope:
    kind: str
    bindings: dict[str, _Binding]
    fallbacks: tuple[dict[str, _Binding], ...]

    def clone(self) -> _LexicalScope:
        return _LexicalScope(
            kind=self.kind,
            bindings=dict(self.bindings),
            fallbacks=tuple(dict(binding) for binding in self.fallbacks),
        )


_OTHER = _Binding()
_PROTOCOL = _Binding(protocol=True)
_EXCEPTION = _Binding(exception=True)
_BUILTINS_MODULE = _Binding(builtins_module=True)
_PROTOCOL_MODULE = _Binding(protocol_module=True)


def _qualified_name(node: ast.expr | None) -> str | None:
    if node is None:
        return None
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _aliases(tree: ast.Module) -> _Aliases:
    abstract_names = {"abstractmethod"}
    abstract_modules = {"abc"}
    overload_names = {"overload"}
    overload_modules = {"typing", "typing_extensions"}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if alias.name == "abc":
                    abstract_modules.add(bound)
                if alias.name in {"typing", "typing_extensions"}:
                    overload_modules.add(bound)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                bound = alias.asname or alias.name
                if module == "abc" and alias.name == "abstractmethod":
                    abstract_names.add(bound)
                if module in {"typing", "typing_extensions"} and alias.name == "overload":
                    overload_names.add(bound)
    return _Aliases(
        abstract_names=frozenset(abstract_names),
        abstract_modules=frozenset(abstract_modules),
        overload_names=frozenset(overload_names),
        overload_modules=frozenset(overload_modules),
    )


def _matches_reference(
    node: ast.expr,
    *,
    direct_names: frozenset[str],
    module_aliases: frozenset[str],
    attribute: str,
) -> bool:
    name = _qualified_name(node)
    if name is None:
        return False
    if name in direct_names:
        return True
    if "." not in name:
        return False
    module, tail = name.rsplit(".", 1)
    return module in module_aliases and tail == attribute


def _body_without_docstring(body: Sequence[ast.stmt]) -> list[ast.stmt]:
    remaining = list(body)
    if (
        remaining
        and isinstance(remaining[0], ast.Expr)
        and isinstance(remaining[0].value, ast.Constant)
        and isinstance(remaining[0].value.value, str)
    ):
        remaining.pop(0)
    return remaining


def _is_stub_body(body: Sequence[ast.stmt]) -> bool:
    remaining = _body_without_docstring(body)
    if not remaining:
        return True
    if len(remaining) != 1:
        return False
    statement = remaining[0]
    if isinstance(statement, ast.Pass):
        return True
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value is Ellipsis
    )


def _target_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        names: set[str] = set()
        for element in node.elts:
            names.update(_target_names(element))
        return names
    if isinstance(node, ast.Starred):
        return _target_names(node.value)
    return set()


class _FunctionLocalCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.names.add(alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None


def _function_local_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    collector = _FunctionLocalCollector()
    for statement in node.body:
        collector.visit(statement)
    for argument in (
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
    ):
        collector.names.add(argument.arg)
    if node.args.vararg is not None:
        collector.names.add(node.args.vararg.arg)
    if node.args.kwarg is not None:
        collector.names.add(node.args.kwarg.arg)
    return collector.names


class _ClassClassifier:
    def __init__(self) -> None:
        self.protocol_nodes: set[int] = set()
        self.exception_nodes: set[int] = set()

    @staticmethod
    def _lookup(scope: _LexicalScope, name: str) -> _Binding | None:
        if name in scope.bindings:
            return scope.bindings[name]
        for fallback in scope.fallbacks:
            if name in fallback:
                return fallback[name]
        return None

    @classmethod
    def _base_binding(cls, base: ast.expr, *, scope: _LexicalScope) -> _Binding:
        name = _qualified_name(base)
        if name is None:
            return _OTHER
        if "." not in name:
            binding = cls._lookup(scope, name)
            if binding is not None:
                return binding
            if name in _BUILTIN_EXCEPTION_NAMES:
                return _EXCEPTION
            return _OTHER
        module, tail = name.rsplit(".", 1)
        module_binding = cls._lookup(scope, module)
        if (
            module_binding is not None
            and module_binding.builtins_module
            and tail in _BUILTIN_EXCEPTION_NAMES
        ):
            return _EXCEPTION
        if module_binding is not None and module_binding.protocol_module and tail == "Protocol":
            return _PROTOCOL
        return _OTHER

    @staticmethod
    def _bind(scope: _LexicalScope, name: str, binding: _Binding) -> None:
        scope.bindings[name] = binding

    @staticmethod
    def _child_fallbacks(scope: _LexicalScope) -> tuple[dict[str, _Binding], ...]:
        if scope.kind == "class":
            return tuple(dict(binding) for binding in scope.fallbacks)
        return (
            dict(scope.bindings),
            *(dict(binding) for binding in scope.fallbacks),
        )

    def _process_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        *,
        parent_scope: _LexicalScope,
    ) -> None:
        function_scope = _LexicalScope(
            kind="function",
            bindings={name: _OTHER for name in _function_local_names(node)},
            fallbacks=self._child_fallbacks(parent_scope),
        )
        self._process_body(node.body, scope=function_scope)

    def _process_nested_statement(
        self,
        node: ast.stmt,
        *,
        scope: _LexicalScope,
    ) -> None:
        groups: list[Sequence[ast.stmt]] = []
        if isinstance(node, (ast.If, ast.For, ast.AsyncFor, ast.While)):
            groups.extend((node.body, node.orelse))
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            groups.append(node.body)
        elif isinstance(node, (ast.Try, ast.TryStar)):
            groups.extend((node.body, node.orelse, node.finalbody))
            groups.extend(handler.body for handler in node.handlers)
        elif isinstance(node, ast.Match):
            groups.extend(case.body for case in node.cases)
        for group in groups:
            self._process_body(group, scope=scope.clone())
        if groups:
            collector = _FunctionLocalCollector()
            collector.visit(node)
            for name in collector.names:
                self._bind(scope, name, _OTHER)

    def _process_body(
        self,
        body: Sequence[ast.stmt],
        *,
        scope: _LexicalScope,
    ) -> None:
        for statement in body:
            if isinstance(statement, ast.Import):
                for alias in statement.names:
                    bound = alias.asname or alias.name.split(".")[0]
                    binding = _OTHER
                    if alias.name == "builtins":
                        binding = _BUILTINS_MODULE
                    elif alias.name in {"typing", "typing_extensions"}:
                        binding = _PROTOCOL_MODULE
                    self._bind(scope, bound, binding)
            elif isinstance(statement, ast.ImportFrom):
                module = statement.module or ""
                for alias in statement.names:
                    if alias.name == "*":
                        continue
                    bound = alias.asname or alias.name
                    binding = _OTHER
                    if module == "builtins" and alias.name in _BUILTIN_EXCEPTION_NAMES:
                        binding = _EXCEPTION
                    elif module in {"typing", "typing_extensions"} and alias.name == "Protocol":
                        binding = _PROTOCOL
                    self._bind(scope, bound, binding)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._process_function(statement, parent_scope=scope)
                self._bind(scope, statement.name, _OTHER)
            elif isinstance(statement, ast.ClassDef):
                base_bindings = [self._base_binding(base, scope=scope) for base in statement.bases]
                is_protocol = any(binding.protocol for binding in base_bindings)
                is_exception = any(binding.exception for binding in base_bindings)
                if is_protocol:
                    self.protocol_nodes.add(id(statement))
                if is_exception:
                    self.exception_nodes.add(id(statement))
                class_scope = _LexicalScope(
                    kind="class",
                    bindings={},
                    fallbacks=self._child_fallbacks(scope),
                )
                self._process_body(statement.body, scope=class_scope)
                self._bind(
                    scope,
                    statement.name,
                    _Binding(protocol=is_protocol, exception=is_exception),
                )
            elif isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets: list[ast.AST] = []
                if isinstance(statement, ast.Assign):
                    targets.extend(statement.targets)
                else:
                    targets.append(statement.target)
                for target in targets:
                    for name in _target_names(target):
                        self._bind(scope, name, _OTHER)
            elif isinstance(statement, ast.Delete):
                for target in statement.targets:
                    for name in _target_names(target):
                        self._bind(scope, name, _OTHER)
            else:
                self._process_nested_statement(statement, scope=scope)

    def classify(self, tree: ast.Module) -> tuple[frozenset[int], frozenset[int]]:
        self._process_body(
            tree.body,
            scope=_LexicalScope(kind="module", bindings={}, fallbacks=()),
        )
        return frozenset(self.protocol_nodes), frozenset(self.exception_nodes)


def _decorator_matches(
    decorators: Sequence[ast.expr],
    *,
    direct_names: frozenset[str],
    module_aliases: frozenset[str],
    attribute: str,
) -> bool:
    return any(
        _matches_reference(
            decorator.func if isinstance(decorator, ast.Call) else decorator,
            direct_names=direct_names,
            module_aliases=module_aliases,
            attribute=attribute,
        )
        for decorator in decorators
    )


class _ConcreteRaiseVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.raises: list[ast.Raise] = []

    def visit_Raise(self, node: ast.Raise) -> None:
        target = node.exc
        if isinstance(target, ast.Call):
            target = target.func
        if _qualified_name(target) == "NotImplementedError":
            self.raises.append(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None


class _Scanner(ast.NodeVisitor):
    def __init__(
        self,
        *,
        path: str,
        aliases: _Aliases,
        protocol_nodes: frozenset[int],
        exception_nodes: frozenset[int],
    ) -> None:
        self.path = path
        self.aliases = aliases
        self.protocol_nodes = protocol_nodes
        self.exception_nodes = exception_nodes
        self.scope: list[str] = []
        self.protocol_stack: list[bool] = []
        self.findings: list[Finding] = []

    def _symbol(self, name: str) -> str:
        return ".".join((*self.scope, name)) if self.scope else name

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        symbol = self._symbol(node.name)
        is_protocol = id(node) in self.protocol_nodes
        is_exception = id(node) in self.exception_nodes
        if _is_stub_body(node.body) and not is_protocol and not is_exception:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    column=node.col_offset,
                    kind="class_stub",
                    symbol=symbol,
                )
            )
        self.scope.append(node.name)
        self.protocol_stack.append(is_protocol)
        self.generic_visit(node)
        self.protocol_stack.pop()
        self.scope.pop()

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        symbol = self._symbol(node.name)
        parent_protocol = bool(self.protocol_stack and self.protocol_stack[-1])
        abstract = _decorator_matches(
            node.decorator_list,
            direct_names=self.aliases.abstract_names,
            module_aliases=self.aliases.abstract_modules,
            attribute="abstractmethod",
        )
        overload = _decorator_matches(
            node.decorator_list,
            direct_names=self.aliases.overload_names,
            module_aliases=self.aliases.overload_modules,
            attribute="overload",
        )
        allowed_stub = parent_protocol or abstract or overload
        if _is_stub_body(node.body) and not allowed_stub:
            self.findings.append(
                Finding(
                    path=self.path,
                    line=node.lineno,
                    column=node.col_offset,
                    kind="function_stub",
                    symbol=symbol,
                )
            )
        if not allowed_stub:
            visitor = _ConcreteRaiseVisitor()
            for statement in node.body:
                visitor.visit(statement)
            for raised in visitor.raises:
                self.findings.append(
                    Finding(
                        path=self.path,
                        line=raised.lineno,
                        column=raised.col_offset,
                        kind="not_implemented_error",
                        symbol=symbol,
                    )
                )
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)


def _comment_findings(source: str, *, path: str) -> Iterable[Finding]:
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            lowered = token.string.lower()
            for marker, kind in _COMMENT_MARKERS.items():
                if re.search(rf"\b{marker}\b", lowered):
                    yield Finding(
                        path=path,
                        line=token.start[0],
                        column=token.start[1],
                        kind=kind,
                        symbol="<comment>",
                    )
    except (IndentationError, tokenize.TokenError):
        return


def scan_source(source: str, *, path: str) -> tuple[Finding, ...]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return (
            Finding(
                path=path,
                line=max(exc.lineno or 1, 1),
                column=max((exc.offset or 1) - 1, 0),
                kind="syntax_error",
                symbol="<module>",
            ),
        )
    aliases = _aliases(tree)
    protocol_nodes, exception_nodes = _ClassClassifier().classify(tree)
    scanner = _Scanner(
        path=path,
        aliases=aliases,
        protocol_nodes=protocol_nodes,
        exception_nodes=exception_nodes,
    )
    scanner.visit(tree)
    findings = [*scanner.findings, *_comment_findings(source, path=path)]
    return tuple(sorted(set(findings)))


def _python_files(roots: Sequence[Path]) -> tuple[tuple[Path, str], ...]:
    selected: dict[Path, str] = {}
    for root in sorted(roots, key=lambda item: item.as_posix()):
        if not root.exists():
            raise ValueError(f"scan root does not exist: {root.name}")
        if root.is_file():
            candidates = (root,) if root.suffix == ".py" else ()
            anchor = root.parent
        else:
            candidates = tuple(sorted(root.rglob("*.py")))
            anchor = root.parent
        for candidate in candidates:
            resolved = candidate.resolve()
            display = candidate.relative_to(anchor).as_posix()
            existing = selected.get(resolved)
            if existing is None or display < existing:
                selected[resolved] = display
    return tuple(
        (path, display)
        for path, display in sorted(
            selected.items(),
            key=lambda item: item[1],
        )
    )


def scan_paths(roots: Sequence[str | Path]) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    paths = tuple(Path(root) for root in roots)
    for file_path, display_path in _python_files(paths):
        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            findings.append(
                Finding(
                    path=display_path,
                    line=1,
                    column=0,
                    kind="source_read_error",
                    symbol="<module>",
                )
            )
            continue
        findings.extend(scan_source(source, path=display_path))
    return tuple(sorted(set(findings)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reject concrete implementation stubs in Python source."
    )
    parser.add_argument("roots", nargs="+")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    findings = scan_paths(args.roots)
    payload = {
        "finding_count": len(findings),
        "findings": [finding.to_dict() for finding in findings],
    }
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
