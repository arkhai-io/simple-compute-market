"""Unit tests for ProviderRegistry."""

from __future__ import annotations

import pytest

from services.fulfillment_provider import ProviderNotFoundError
from services.provider_registry import ProviderRegistry


class _StubProvider:
    pass


def test_require_returns_registered_provider():
    provider = _StubProvider()
    registry = ProviderRegistry({"ansible": provider})
    assert registry.require("ansible") is provider


def test_require_raises_for_unregistered_provider():
    registry = ProviderRegistry({"ansible": _StubProvider()})
    with pytest.raises(ProviderNotFoundError):
        registry.require("kubernetes")
