"""Detect concrete Python stubs with lexical, privacy-safe AST analysis."""

from __future__ import annotations

import argparse
import ast
import builtins
import io
import json
import tokenize
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

_STUB_EXPR_VALUES: Final = frozenset({None, Ellipsis})
_BUILTIN_EXCEPTION_NAMES: Final = frozenset(
    name
    for name, value in vars(builtins).items()
    if isinstance(value, type) and issubclass(value, BaseException)
)


@dataclass(frozen=True, slots=True, order=True)
class Finding:
    """One bounded scanner finding with no source payload."""

    path: str
    line: int
    column: int
    kind: str
    symbol: str

    def to_dict(self) -> dict[str, object]:
        return {
            "column": self.column,
            "kind": self.kind,
            "line": self.line,
            "path": self.path,
            "symbol": self.symbol,
        }

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())


@dataclass(frozen=True, slots=True)
class _Binding:
    protocol_marker: bool = False
    protocol_class: bool = False
    exception_class: bool = False
    abstract_decorator: bool = False
    overload_decorator: bool = False
    abc_module: bool = False
    typing_module: bool = False
    builtins_module: bool = False
    not_implemented_error: bool = False


_OTHER: Final = _Binding()
_PROTOCOL_MARKER: Final = _Binding(protocol_marker=True)
_PROTOCOL_CLASS: Final = _Binding(protocol_class=True)
_EXCEPTION_CLASS: Final = _Binding(exception_class=True)
_NOT_IMPLEMENTED_ERROR: Final = _Binding(
    exception_class=True,
    not_implemented_error=True,
)
_ABSTRACT_DECORATOR: Final = _Binding(abstract_decorator=True)
_OVERLOAD_DECORATOR: Final = _Binding(overload_decorator=True)
_ABC_MODULE: Final = _Binding(abc_module=True)
_TYPING_MODULE: Final = _Binding(typing_module=True)
_BUILTINS_MODULE: Final = _Binding(builtins_module=True)


@dataclass(slots=True)
class _Scope:
    kind: str
    parent: _Scope | None = None
    bindings: dict[str, _Binding] = field(default_factory=dict)
    global_names: frozenset[str] = frozenset()
    nonlocal_names: frozenset[str] = frozenset()

    def clone(self) -> _Scope:
        return _Scope(
            kind=self.kind,
            parent=self.parent,
            bindings=dict(self.bindings),
            global_names=self.global_names,
            nonlocal_names=self.nonlocal_names,
        )


@dataclass(frozen=True, slots=True)
class _Classification:
    protocol_classes: frozenset[int]
    exception_classes: frozenset[int]
    allowed_functions: frozenset[int]
    not_implemented_raises: frozenset[int]


class _FunctionLocalCollector(ast.NodeVisitor):
    """Collect function-local bindings without descending into nested scopes."""

    def __init__(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.names: set[str] = set()
        self.global_names: set[str] = set()
        self.nonlocal_names: set[str] = set()
        arguments = node.args
        for argument in (
            *arguments.posonlyargs,
            *arguments.args,
            *arguments.kwonlyargs,
        ):
            self.names.add(argument.arg)
        if arguments.vararg is not None:
            self.names.add(arguments.vararg.arg)
        if arguments.kwarg is not None:
            self.names.add(arguments.kwarg.arg)
        for statement in node.body:
            self.visit(statement)
        self.names.difference_update(self.global_names)
        self.names.difference_update(self.nonlocal_names)

    def visit_Global(self, node: ast.Global) -> None:
        self.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.nonlocal_names.update(node.names)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names.add(node.id)

    def visit_arg(self, node: ast.arg) -> None:
        self.names.add(node.arg)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.names.add(alias.asname or alias.name.split(".", 1)[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name != "*":
                self.names.add(alias.asname or alias.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self.names.add(node.name)
        for statement in node.body:
            self.visit(statement)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.pattern is not None:
            self.visit(node.pattern)
        if node.name is not None:
            self.names.add(node.name)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self.names.add(node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        for pattern in node.patterns:
            self.visit(pattern)
        if node.rest is not None:
            self.names.add(node.rest)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:
        return

    def visit_SetComp(self, node: ast.SetComp) -> None:
        return

    def visit_DictComp(self, node: ast.DictComp) -> None:
        return

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        return


class _LexicalClassifier:
    """Classify abstractions and stub raises by exact lexical binding identity."""

    def __init__(self, tree: ast.Module) -> None:
        self._tree = tree
        self.protocol_classes: set[int] = set()
        self.exception_classes: set[int] = set()
        self.allowed_functions: set[int] = set()
        self.not_implemented_raises: set[int] = set()

    def classify(self) -> _Classification:
        module = _Scope(kind="module")
        self._process_body(self._tree.body, module)
        return _Classification(
            protocol_classes=frozenset(self.protocol_classes),
            exception_classes=frozenset(self.exception_classes),
            allowed_functions=frozenset(self.allowed_functions),
            not_implemented_raises=frozenset(self.not_implemented_raises),
        )

    def _process_body(self, body: Sequence[ast.stmt], scope: _Scope) -> None:
        for statement in body:
            self._process_statement(statement, scope)

    def _process_statement(self, statement: ast.stmt, scope: _Scope) -> None:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            self._process_function(statement, scope)
            return
        if isinstance(statement, ast.ClassDef):
            self._process_class(statement, scope)
            return
        if isinstance(statement, ast.Import):
            self._process_import(statement, scope)
            return
        if isinstance(statement, ast.ImportFrom):
            self._process_import_from(statement, scope)
            return
        if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            self._bind_assignment(statement, scope)
            return
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            self._process_expression_bindings(statement.iter, scope)
            self._bind_target(scope, statement.target, _OTHER)
            self._process_parallel_groups(scope, statement.body, statement.orelse)
            return
        if isinstance(statement, (ast.With, ast.AsyncWith)):
            for item in statement.items:
                self._process_expression_bindings(item.context_expr, scope)
                if item.optional_vars is not None:
                    self._bind_target(scope, item.optional_vars, _OTHER)
            self._process_body(statement.body, scope)
            return
        if isinstance(statement, ast.If):
            self._process_expression_bindings(statement.test, scope)
            self._process_parallel_groups(scope, statement.body, statement.orelse)
            return
        if isinstance(statement, ast.While):
            self._process_expression_bindings(statement.test, scope)
            self._process_parallel_groups(scope, statement.body, statement.orelse)
            return
        if isinstance(statement, (ast.Try, ast.TryStar)):
            branches: list[_Scope] = []
            success = scope.clone()
            self._process_body(statement.body, success)
            if statement.orelse:
                self._process_body(statement.orelse, success)
            branches.append(success)
            for handler in statement.handlers:
                branch = scope.clone()
                if handler.type is not None:
                    self._process_expression_bindings(handler.type, branch)
                if handler.name is not None:
                    self._bind_name(branch, handler.name, _OTHER)
                self._process_body(handler.body, branch)
                branches.append(branch)
            self._merge_branches(scope, branches)
            if statement.finalbody:
                self._process_body(statement.finalbody, scope)
            return
        if isinstance(statement, ast.Match):
            self._process_expression_bindings(statement.subject, scope)
            self._process_match(statement, scope)
            return
        if isinstance(statement, ast.Raise):
            if self._is_builtin_not_implemented_error(statement.exc, scope):
                self.not_implemented_raises.add(id(statement))
            return
        if isinstance(statement, ast.Delete):
            for target in statement.targets:
                self._bind_target(scope, target, _OTHER)
            return

        # Raises and bindings nested inside statement expressions are not runtime
        # scope declarations. Compound statement bodies are handled explicitly.

    def _process_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        scope: _Scope,
    ) -> None:
        allowed = any(
            self._is_allowed_decorator(decorator, scope) for decorator in node.decorator_list
        )
        if allowed:
            self.allowed_functions.add(id(node))

        # The function name is visible when the body eventually executes.
        self._bind_name(scope, node.name, _OTHER)

        collector = _FunctionLocalCollector(node)
        child = _Scope(
            kind="function",
            parent=scope,
            bindings={name: _OTHER for name in collector.names},
            global_names=frozenset(collector.global_names),
            nonlocal_names=frozenset(collector.nonlocal_names),
        )
        self._process_body(node.body, child)

    def _process_class(self, node: ast.ClassDef, scope: _Scope) -> None:
        base_bindings = [self._resolve_expression(base, scope) for base in node.bases]
        is_protocol = any(binding.protocol_marker for binding in base_bindings)
        is_exception = any(binding.exception_class for binding in base_bindings)

        if is_protocol:
            self.protocol_classes.add(id(node))
        if is_exception:
            self.exception_classes.add(id(node))

        child = _Scope(kind="class", parent=scope)
        self._process_body(node.body, child)
        binding = _PROTOCOL_CLASS if is_protocol else _EXCEPTION_CLASS if is_exception else _OTHER
        self._bind_name(scope, node.name, binding)

    def _process_import(self, node: ast.Import, scope: _Scope) -> None:
        for alias in node.names:
            local_name = alias.asname or alias.name.split(".", 1)[0]
            root = alias.name.split(".", 1)[0]
            if root == "abc":
                binding = _ABC_MODULE
            elif root in {"typing", "typing_extensions"}:
                binding = _TYPING_MODULE
            elif root == "builtins":
                binding = _BUILTINS_MODULE
            else:
                binding = _OTHER
            self._bind_name(scope, local_name, binding)

    def _process_import_from(self, node: ast.ImportFrom, scope: _Scope) -> None:
        module = node.module or ""
        for alias in node.names:
            if alias.name == "*":
                continue
            local_name = alias.asname or alias.name
            if module == "abc" and alias.name == "abstractmethod":
                binding = _ABSTRACT_DECORATOR
            elif module in {"typing", "typing_extensions"} and alias.name == "Protocol":
                binding = _PROTOCOL_MARKER
            elif module in {"typing", "typing_extensions"} and alias.name == "overload":
                binding = _OVERLOAD_DECORATOR
            elif module == "builtins" and alias.name in _BUILTIN_EXCEPTION_NAMES:
                binding = (
                    _NOT_IMPLEMENTED_ERROR
                    if alias.name == "NotImplementedError"
                    else _EXCEPTION_CLASS
                )
            else:
                binding = _OTHER
            self._bind_name(scope, local_name, binding)

    def _bind_assignment(
        self,
        statement: ast.Assign | ast.AnnAssign | ast.AugAssign,
        scope: _Scope,
    ) -> None:
        if isinstance(statement, ast.Assign):
            self._process_expression_bindings(statement.value, scope)
            binding = self._resolve_expression(statement.value, scope)
            for target in statement.targets:
                self._bind_target(
                    scope,
                    target,
                    binding if isinstance(target, ast.Name) else _OTHER,
                )
            return
        if isinstance(statement, ast.AnnAssign):
            if statement.value is not None:
                self._process_expression_bindings(statement.value, scope)
                binding = self._resolve_expression(statement.value, scope)
            else:
                binding = _OTHER
            self._bind_target(
                scope,
                statement.target,
                binding if isinstance(statement.target, ast.Name) else _OTHER,
            )
            return
        self._process_expression_bindings(statement.value, scope)
        self._bind_target(scope, statement.target, _OTHER)

    def _process_expression_bindings(
        self,
        expression: ast.AST,
        scope: _Scope,
    ) -> None:
        class _NamedExpressionVisitor(ast.NodeVisitor):
            def __init__(self, owner: _LexicalClassifier) -> None:
                self._owner = owner

            def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
                self.visit(node.value)
                binding = self._owner._resolve_expression(node.value, scope)
                self._owner._bind_target(scope, node.target, binding)

            def visit_Lambda(self, node: ast.Lambda) -> None:
                return

            def visit_ListComp(self, node: ast.ListComp) -> None:
                return

            def visit_SetComp(self, node: ast.SetComp) -> None:
                return

            def visit_DictComp(self, node: ast.DictComp) -> None:
                return

            def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
                return

        _NamedExpressionVisitor(self).visit(expression)

    def _process_match(self, statement: ast.Match, scope: _Scope) -> None:
        branches: list[_Scope] = []
        for case in statement.cases:
            branch = scope.clone()
            self._bind_pattern(branch, case.pattern)
            self._process_body(case.body, branch)
            branches.append(branch)
        self._merge_branches(scope, branches or [scope.clone()])

    def _bind_pattern(self, scope: _Scope, pattern: ast.pattern) -> None:
        if isinstance(pattern, ast.MatchAs):
            if pattern.pattern is not None:
                self._bind_pattern(scope, pattern.pattern)
            if pattern.name is not None:
                self._bind_name(scope, pattern.name, _OTHER)
        elif isinstance(pattern, ast.MatchStar):
            if pattern.name is not None:
                self._bind_name(scope, pattern.name, _OTHER)
        elif isinstance(pattern, ast.MatchMapping):
            for child in pattern.patterns:
                self._bind_pattern(scope, child)
            if pattern.rest is not None:
                self._bind_name(scope, pattern.rest, _OTHER)
        elif isinstance(pattern, ast.MatchSequence):
            for child in pattern.patterns:
                self._bind_pattern(scope, child)
        elif isinstance(pattern, ast.MatchClass):
            for child in (*pattern.patterns, *pattern.kwd_patterns):
                self._bind_pattern(scope, child)
        elif isinstance(pattern, ast.MatchOr):
            for child in pattern.patterns:
                self._bind_pattern(scope, child)

    def _process_parallel_groups(
        self,
        scope: _Scope,
        *groups: Sequence[ast.stmt],
    ) -> None:
        branches: list[_Scope] = []
        for group in groups:
            branch = scope.clone()
            self._process_body(group, branch)
            branches.append(branch)
        if len(groups) == 1 or any(not group for group in groups):
            branches.append(scope.clone())
        self._merge_branches(scope, branches)

    @staticmethod
    def _merge_branches(scope: _Scope, branches: Sequence[_Scope]) -> None:
        if not branches:
            return
        names = set().union(*(branch.bindings for branch in branches))
        for name in names:
            values = {branch.bindings.get(name, _OTHER) for branch in branches}
            scope.bindings[name] = values.pop() if len(values) == 1 else _OTHER

    def _bind_target(
        self,
        scope: _Scope,
        target: ast.expr,
        binding: _Binding,
    ) -> None:
        if isinstance(target, ast.Name):
            self._bind_name(scope, target.id, binding)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                self._bind_target(scope, element, binding)
        elif isinstance(target, ast.Starred):
            self._bind_target(scope, target.value, binding)

    def _bind_name(self, scope: _Scope, name: str, binding: _Binding) -> None:
        # global/nonlocal declarations change lookup but must not mutate the
        # statically analyzed outer binding merely because a function may run.
        scope.bindings[name] = binding

    def _resolve_name(self, name: str, scope: _Scope) -> _Binding:
        if scope.kind == "function" and name in scope.global_names:
            if name in scope.bindings:
                return scope.bindings[name]
            module = self._module_scope(scope)
            return self._resolve_module_name(name, module)
        if scope.kind == "function" and name in scope.nonlocal_names:
            if name in scope.bindings:
                return scope.bindings[name]
            parent = self._next_lexical_scope(scope.parent)
            if parent is not None:
                return self._resolve_name(name, parent)
            return _OTHER

        if name in scope.bindings:
            return scope.bindings[name]

        parent = self._next_lexical_scope(scope.parent)
        if parent is not None:
            return self._resolve_name(name, parent)
        return self._builtin_binding(name)

    def _resolve_module_name(self, name: str, module: _Scope) -> _Binding:
        if name in module.bindings:
            return module.bindings[name]
        return self._builtin_binding(name)

    @staticmethod
    def _module_scope(scope: _Scope) -> _Scope:
        current = scope
        while current.parent is not None:
            current = current.parent
        return current

    @staticmethod
    def _next_lexical_scope(scope: _Scope | None) -> _Scope | None:
        current = scope
        while current is not None and current.kind == "class":
            current = current.parent
        return current

    @staticmethod
    def _builtin_binding(name: str) -> _Binding:
        if name == "NotImplementedError":
            return _NOT_IMPLEMENTED_ERROR
        if name in _BUILTIN_EXCEPTION_NAMES:
            return _EXCEPTION_CLASS
        return _OTHER

    def _resolve_expression(self, expression: ast.expr, scope: _Scope) -> _Binding:
        if isinstance(expression, ast.Name):
            return self._resolve_name(expression.id, scope)
        if isinstance(expression, ast.Attribute):
            parent = self._resolve_expression(expression.value, scope)
            if parent.abc_module and expression.attr == "abstractmethod":
                return _ABSTRACT_DECORATOR
            if parent.typing_module and expression.attr == "Protocol":
                return _PROTOCOL_MARKER
            if parent.typing_module and expression.attr == "overload":
                return _OVERLOAD_DECORATOR
            if parent.builtins_module and expression.attr in _BUILTIN_EXCEPTION_NAMES:
                return (
                    _NOT_IMPLEMENTED_ERROR
                    if expression.attr == "NotImplementedError"
                    else _EXCEPTION_CLASS
                )
            return _OTHER
        return _OTHER

    def _is_allowed_decorator(self, expression: ast.expr, scope: _Scope) -> bool:
        binding = self._resolve_expression(expression, scope)
        return binding.abstract_decorator or binding.overload_decorator

    def _is_builtin_not_implemented_error(
        self,
        exception: ast.expr | None,
        scope: _Scope,
    ) -> bool:
        if exception is None:
            return False
        expression = exception.func if isinstance(exception, ast.Call) else exception
        return self._resolve_expression(expression, scope).not_implemented_error


class _RaiseCollector(ast.NodeVisitor):
    """Collect classified raises in one function, excluding nested scopes."""

    def __init__(self, classified: frozenset[int]) -> None:
        self._classified = classified
        self.nodes: list[ast.Raise] = []

    def visit_Raise(self, node: ast.Raise) -> None:
        if id(node) in self._classified:
            self.nodes.append(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return


class _Scanner(ast.NodeVisitor):
    def __init__(
        self,
        *,
        path: str,
        classification: _Classification,
    ) -> None:
        self._path = path
        self._classification = classification
        self._findings: list[Finding] = []
        self._symbols: list[str] = []
        self._parents: list[ast.AST] = []

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(sorted(self._findings))

    def visit(self, node: ast.AST) -> object:
        self._parents.append(node)
        try:
            return super().visit(node)
        finally:
            self._parents.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        symbol = self._qualified_symbol(node.name)
        allowed = (
            id(node) in self._classification.protocol_classes
            or id(node) in self._classification.exception_classes
        )
        if _is_stub_body(node.body) and not allowed:
            self._add(node, kind="class_stub", symbol=symbol)

        self._symbols.append(node.name)
        self.generic_visit(node)
        self._symbols.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function(node)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        symbol = self._qualified_symbol(node.name)
        direct_protocol_method = (
            len(self._parents) >= 2
            and isinstance(self._parents[-2], ast.ClassDef)
            and id(self._parents[-2]) in self._classification.protocol_classes
        )
        allowed = id(node) in self._classification.allowed_functions or direct_protocol_method
        if _is_stub_body(node.body) and not allowed:
            self._add(node, kind="function_stub", symbol=symbol)
        if not allowed:
            collector = _RaiseCollector(self._classification.not_implemented_raises)
            for statement in node.body:
                collector.visit(statement)
            for raised in collector.nodes:
                self._add(
                    raised,
                    kind="not_implemented_error",
                    symbol=symbol,
                )

        self._symbols.append(node.name)
        self.generic_visit(node)
        self._symbols.pop()

    def _qualified_symbol(self, leaf: str) -> str:
        return ".".join((*self._symbols, leaf)) if self._symbols else leaf

    def _add(self, node: ast.AST, *, kind: str, symbol: str) -> None:
        self._findings.append(
            Finding(
                path=self._path,
                line=max(1, getattr(node, "lineno", 1)),
                column=max(0, getattr(node, "col_offset", 0)),
                kind=kind,
                symbol=symbol,
            )
        )


def scan_source(source: str, *, path: str) -> tuple[Finding, ...]:
    """Scan one source string without evaluating it."""

    if not isinstance(source, str):
        raise TypeError("source must be a string")
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError, TypeError) as error:
        return (
            Finding(
                path=path,
                line=max(1, error.lineno or 1) if isinstance(error, SyntaxError) else 1,
                column=max(0, (error.offset or 1) - 1) if isinstance(error, SyntaxError) else 0,
                kind="syntax_error",
                symbol="<module>",
            ),
        )

    classification = _LexicalClassifier(tree).classify()
    scanner = _Scanner(path=path, classification=classification)
    scanner.visit(tree)
    findings = list(scanner.findings)
    findings.extend(_comment_findings(source, path=path))
    return tuple(sorted(findings))


def scan_paths(paths: Sequence[Path]) -> tuple[Finding, ...]:
    """Scan Python files below paths in deterministic display-path order."""

    if isinstance(paths, (str, bytes)) or not isinstance(paths, Sequence):
        raise TypeError("paths must be a sequence of Path values")
    findings: list[Finding] = []
    files: dict[Path, str] = {}
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file():
            if path.suffix == ".py":
                files[path.resolve()] = path.name
            continue
        if not path.is_dir():
            findings.append(
                Finding(
                    path=path.name or ".",
                    line=1,
                    column=0,
                    kind="path_error",
                    symbol="<module>",
                )
            )
            continue
        display_root = path.name
        for candidate in sorted(path.rglob("*.py")):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            relative = candidate.relative_to(path).as_posix()
            display = f"{display_root}/{relative}" if relative else display_root
            files[candidate.resolve()] = display

    for file_path, display in sorted(files.items(), key=lambda item: item[1]):
        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            findings.append(
                Finding(
                    path=display,
                    line=1,
                    column=0,
                    kind="read_error",
                    symbol="<module>",
                )
            )
            continue
        findings.extend(scan_source(source, path=display))
    return tuple(sorted(findings))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_no_stubs")
    parser.add_argument("paths", nargs="+", type=Path)
    arguments = parser.parse_args(argv)
    findings = scan_paths(tuple(arguments.paths))
    report = {
        "finding_count": len(findings),
        "findings": [finding.to_dict() for finding in findings],
    }
    print(_canonical_json(report), end="")
    return 1 if findings else 0


def _comment_findings(source: str, *, path: str) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type != tokenize.COMMENT:
                continue
            upper = token.string.upper()
            for marker, kind in (
                ("TODO", "todo_comment"),
                ("FIXME", "fixme_comment"),
            ):
                if marker in upper:
                    findings.append(
                        Finding(
                            path=path,
                            line=max(1, token.start[0]),
                            column=max(0, token.start[1]),
                            kind=kind,
                            symbol="<module>",
                        )
                    )
                    break
    except (IndentationError, SyntaxError, tokenize.TokenError):
        # Syntax failures are already represented by the bounded AST finding.
        return ()
    return tuple(sorted(findings))


def _is_stub_body(body: Sequence[ast.stmt]) -> bool:
    statements = list(body)
    if (
        statements
        and isinstance(statements[0], ast.Expr)
        and isinstance(statements[0].value, ast.Constant)
        and isinstance(statements[0].value.value, str)
    ):
        statements = statements[1:]
    if len(statements) != 1:
        return False
    statement = statements[0]
    if isinstance(statement, ast.Pass):
        return True
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and statement.value.value in _STUB_EXPR_VALUES
    )


def _canonical_json(value: object) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
