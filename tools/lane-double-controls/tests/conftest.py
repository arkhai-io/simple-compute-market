"""Shared paths and helpers for the controls suite."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

PROJECT = Path(__file__).resolve().parents[1]
TLS = PROJECT / "tls"


@pytest.fixture(scope="session")
def tls_generator() -> ModuleType:
    """``tls/generate.py``, which is a script beside its output, not a module of the package."""

    spec = importlib.util.spec_from_file_location("tls_generate", TLS / "generate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
