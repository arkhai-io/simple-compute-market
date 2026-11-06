"""Shared paths and helpers for the double's suite."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT / "fixtures"
TLS = PROJECT / "tls"


def committed_accounts() -> dict[str, Any]:
    with (FIXTURES / "accounts.toml").open("rb") as handle:
        return tomllib.load(handle)


def committed_dispute_authority() -> dict[str, Any]:
    with (FIXTURES / "dispute-authority.toml").open("rb") as handle:
        return tomllib.load(handle)


@pytest.fixture(scope="session")
def tls_generator() -> ModuleType:
    """``tls/generate.py``, which is a script beside its output, not a module of the package."""

    spec = importlib.util.spec_from_file_location("tls_generate", TLS / "generate.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Clock:
    """An injected clock a test moves by hand."""

    def __init__(self, now: int) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now
