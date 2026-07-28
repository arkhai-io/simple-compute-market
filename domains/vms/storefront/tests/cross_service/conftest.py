"""Expose compute-service integration fixtures to cross-service tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_COMPUTE_CONFTEST = (
    Path(__file__).resolve().parents[5]
    / "provisioning"
    / "compute"
    / "service"
    / "tests"
    / "integration"
    / "conftest.py"
)
_spec = importlib.util.spec_from_file_location(
    "_compute_service_integration_conftest", _COMPUTE_CONFTEST
)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Unable to load compute-service fixtures from {_COMPUTE_CONFTEST}")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

for _name, _value in vars(_module).items():
    if hasattr(_value, "_fixture_function_marker"):
        globals()[_name] = _value
