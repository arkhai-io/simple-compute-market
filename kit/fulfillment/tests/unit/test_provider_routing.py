from __future__ import annotations

import pytest

from market_fulfillment import (
    FulfillmentProvider,
    FulfillmentResult,
    ProviderNotFoundError,
    ProviderOperationState,
    ProviderRegistry,
    ProviderStatus,
)


class _Provider(FulfillmentProvider):
    async def create(self, request, resource):
        return FulfillmentResult(provider_metadata={})

    async def teardown(self, capacity_reservation_id, resource, provider_metadata):
        return FulfillmentResult(provider_metadata={})

    async def get_status(self, capacity_reservation_id, resource, provider_metadata):
        return ProviderStatus(state=ProviderOperationState.succeeded)


def test_registry_routes_same_provider_by_resource_kind() -> None:
    vm = _Provider()
    bare_metal = _Provider()
    registry = ProviderRegistry(
        {
            ("ansible", "compute.gpu"): vm,
            ("ansible", "bare_metal"): bare_metal,
        }
    )

    assert registry.require("ansible", "compute.gpu") is vm
    assert registry.require("ansible", "bare_metal") is bare_metal


def test_legacy_provider_registration_is_an_explicit_fallback() -> None:
    legacy = _Provider()
    scoped = _Provider()
    registry = ProviderRegistry(
        {
            "ansible": legacy,
            ("ansible", "compute.gpu"): scoped,
        }
    )

    assert registry.require("ansible") is legacy
    assert registry.require("ansible", "compute.gpu") is scoped
    assert registry.require("ansible", "bare_metal") is legacy


def test_scoped_registration_is_not_inferred_for_another_scope() -> None:
    registry = ProviderRegistry({("ansible", "compute.gpu"): _Provider()})

    with pytest.raises(ProviderNotFoundError, match="resource_kind='bare_metal'"):
        registry.require("ansible", "bare_metal")
    with pytest.raises(ProviderNotFoundError):
        registry.require("ansible")
