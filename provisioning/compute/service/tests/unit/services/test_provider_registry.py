"""Unit tests for ProviderRegistry."""

from __future__ import annotations

import pytest

from market_fulfillment import ProviderNotFoundError
from market_fulfillment import ProviderRegistry


class _StubProvider:
    needs_host = True


class _UndeclaredProvider:
    pass


def test_require_returns_registered_provider():
    provider = _StubProvider()
    registry = ProviderRegistry({"ansible": provider})
    assert registry.require("ansible") is provider


def test_require_raises_for_unregistered_provider():
    registry = ProviderRegistry({"ansible": _StubProvider()})
    with pytest.raises(ProviderNotFoundError):
        registry.require("kubernetes")


def test_a_provider_that_does_not_declare_its_host_need_cannot_be_registered():
    with pytest.raises(TypeError):
        ProviderRegistry({"ansible": _UndeclaredProvider()})
