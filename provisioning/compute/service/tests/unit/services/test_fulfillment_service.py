"""Unit tests for FulfillmentService.

Uses a fake FulfillmentProvider, not AnsibleFulfillmentProvider — this is a
FulfillmentService-boundary test (idempotency/conflict/dispatch counting),
not an Ansible-integration test.
"""

from __future__ import annotations

import pytest

from market_fulfillment import PhysicalSettlementRequest, SettlementResource
from market_fulfillment import (
    FulfillmentConflictError,
    FulfillmentProvider,
    FulfillmentResult,
    ProviderNotFoundError,
    ProviderOperationState,
    ProviderStatus,
)
from compute_provisioning_service.services.fulfillment_service import FulfillmentService
from market_fulfillment import ProviderRegistry


class _FakeProvider(FulfillmentProvider):
    def __init__(self):
        self.create_calls = 0
        self.teardown_calls = 0
        self.status_calls = 0

    async def create(self, request, resource):
        self.create_calls += 1
        return FulfillmentResult(provider_metadata={"job_id": f"create-{self.create_calls}"})

    async def teardown(self, allocation_id, resource, provider_metadata):
        self.teardown_calls += 1
        return FulfillmentResult(provider_metadata={"job_id": f"teardown-{self.teardown_calls}"})

    async def get_status(self, allocation_id, resource, provider_metadata):
        self.status_calls += 1
        return ProviderStatus(state=ProviderOperationState.succeeded)


def _request(**overrides) -> PhysicalSettlementRequest:
    defaults = dict(
        capacity_reservation_id="alloc-1",
        market="vms",
        requirements={"units": 1},
    )
    defaults.update(overrides)
    return PhysicalSettlementRequest(**defaults)


def _resource(**overrides) -> SettlementResource:
    defaults = dict(
        settlement_resource_id="res-1",
        pool_id="pool-1",
        resource_kind="vm",
        provider="ansible",
        attributes={},
    )
    defaults.update(overrides)
    return SettlementResource(**defaults)


@pytest.fixture
def provider():
    return _FakeProvider()


@pytest.fixture
def service(provider):
    return FulfillmentService(provider_registry=ProviderRegistry({"ansible": provider}))


class TestCreateIdempotency:
    async def test_first_create_dispatches(self, service, provider):
        result = await service.create(_request(), _resource())
        assert provider.create_calls == 1
        assert result.provider_metadata["job_id"] == "create-1"

    async def test_equivalent_retry_returns_existing_result_without_redispatch(
        self, service, provider
    ):
        first = await service.create(_request(), _resource())
        second = await service.create(_request(), _resource())
        assert provider.create_calls == 1
        assert second is first

    async def test_conflicting_requirements_raises_before_dispatch(self, service, provider):
        # agreement_id no longer exists on PhysicalSettlementRequest
        # requirements are the normalized values this equivalence
        # check now has left, besides market and the resource, to prove a
        # same-capacity_reservation_id retry with a genuinely different
        # request is rejected rather than silently treated as a retry.
        await service.create(_request(), _resource())
        with pytest.raises(FulfillmentConflictError):
            await service.create(_request(requirements={"units": 2}), _resource())
        assert provider.create_calls == 1

    async def test_conflicting_resource_raises_before_dispatch(self, service, provider):
        # Differs only in a resource field the request itself doesn't
        # carry — proves comparison uses the stored SettlementResource,
        # not request.resource_id.
        await service.create(_request(), _resource())
        with pytest.raises(FulfillmentConflictError):
            await service.create(_request(), _resource(settlement_resource_id="res-2"))
        assert provider.create_calls == 1

    async def test_unregistered_provider_propagates(self, service):
        with pytest.raises(ProviderNotFoundError):
            await service.create(_request(), _resource(provider="kubernetes"))

    def test_unregistered_provider_is_structured_during_validation(self, service):
        result = service.validate_create(
            _request(), _resource(provider="kubernetes")
        )
        assert not result.valid
        assert result.issues[0].code == "provider_not_found"


class TestTeardownIdempotency:
    async def test_teardown_dispatches_once(self, service, provider):
        await service.create(_request(), _resource())
        first = await service.teardown("alloc-1")
        second = await service.teardown("alloc-1")
        assert provider.teardown_calls == 1
        assert second is first

    async def test_teardown_without_create_raises(self, service):
        with pytest.raises(LookupError):
            await service.teardown("never-created")


class TestGetStatus:
    async def test_defaults_to_create_operation(self, service, provider):
        await service.create(_request(), _resource())
        status = await service.get_status("alloc-1")
        assert status.state is ProviderOperationState.succeeded
        assert provider.status_calls == 1

    async def test_teardown_operation_requires_teardown_to_have_happened(
        self, service, provider
    ):
        await service.create(_request(), _resource())
        with pytest.raises(LookupError):
            await service.get_status("alloc-1", operation="teardown")

        await service.teardown("alloc-1")
        status = await service.get_status("alloc-1", operation="teardown")
        assert status.state is ProviderOperationState.succeeded
