from __future__ import annotations

import importlib.util
from pathlib import Path


def test_context_exact_solver_resolves_to_single_canonical_module() -> None:
    spec = importlib.util.find_spec("nextgen_memory.context_exact_solver")

    assert spec is not None
    assert spec.origin is not None
    assert Path(spec.origin).name == "context_exact_solver.py"
    assert spec.submodule_search_locations is None


def test_context_compiler_facade_imports_without_alternate_stack() -> None:
    from nextgen_memory.context_compiler import IntegratedContextCompiler

    assert IntegratedContextCompiler.__module__ == "nextgen_memory.context_compiler"
