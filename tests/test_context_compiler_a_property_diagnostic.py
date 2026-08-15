from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

from nextgen_memory.context_compiler import IntegratedContextCompiler


def _load_property_module():
    path = Path(__file__).with_name("test_context_compiler_properties.py")
    spec = importlib.util.spec_from_file_location(
        "context_compiler_property_source",
        path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_first_generated_property_case_uses_only_input_evidence() -> None:
    source = _load_property_module()
    compile_request, candidates, interactions = source.build_case(
        random.Random(source.SEED),
        0,
    )
    packet = IntegratedContextCompiler().compile(
        compile_request,
        candidates,
        interactions,
    )
    candidate_ids = {item.memory_id for item in candidates}
    selected_ids = set(packet.selected_memory_ids)

    assert selected_ids.issubset(candidate_ids), {
        "candidate_ids": tuple(sorted(map(str, candidate_ids))),
        "selected_ids": tuple(sorted(map(str, selected_ids))),
        "solver_mode": packet.solver_mode.value,
    }
