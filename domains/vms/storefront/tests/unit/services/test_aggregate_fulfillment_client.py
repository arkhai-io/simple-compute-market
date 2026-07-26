"""AggregateFulfillmentClient: routing by the shared reservation-site cache.

A sibling to ``AggregateCapacityClient`` for the
compute-provisioning fulfillment surface (schedule/begin/status/result),
sharing the exact ``reservation_sites`` dict instance the capacity
aggregator learns at ``reserve()`` time rather than tracking a second,
independent copy.
"""

from __future__ import annotations

from typing import Any

import pytest

from compute_provisioning import (
    ComputeProvisioningError,
    FulfillmentAcceptanceResponse,
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    FulfillmentScheduleResponse,
    FulfillmentStatusResponse,
)
from core_storefront.aggregation import AggregateCapacityClient
from market_fulfillment import VersionedEnvelope
from market_storefront.services.capacity_client import AggregateFulfillmentClient


class FakeFulfillmentSite:
    """In-memory single-site fulfillment surface (schedule/begin/status/result)."""

    def __init__(self, name: str, *, broken: bool = False) -> None:
        self.name = name
        self.broken = broken
        self.known_reservations: set[str] = set()
        self.calls: list[str] = []

    def _check(self, capacity_reservation_id: str) -> None:
        self.calls.append(capacity_reservation_id)
        if self.broken:
            raise ComputeProvisioningError("site unreachable", status_code=503)
        if capacity_reservation_id not in self.known_reservations:
            raise ComputeProvisioningError(
                "fulfillment_not_found", status_code=404,
            )

    async def schedule_resource(
        self, request: FulfillmentScheduleRequest,
    ) -> FulfillmentScheduleResponse:
        self._check(request.capacity_reservation_id)
        return FulfillmentScheduleResponse(
            settlement_resource_id=f"{self.name}-r1",
            pool_id=f"{self.name}-pool",
            resource_kind="compute.gpu",
            provider="ansible",
        )

    async def begin_fulfillment(
        self, body: FulfillmentRequestBody,
    ) -> FulfillmentAcceptanceResponse:
        self._check(body.capacity_reservation_id)
        return FulfillmentAcceptanceResponse(
            fulfillment_id=f"{self.name}-fulfillment-1",
            capacity_reservation_id=body.capacity_reservation_id,
            state="dispatching",
        )

    async def get_fulfillment_status(self, fulfillment_id: str) -> FulfillmentStatusResponse:
        self.calls.append(fulfillment_id)
        if self.broken:
            raise ComputeProvisioningError("site unreachable", status_code=503)
        return FulfillmentStatusResponse(
            fulfillment_id=fulfillment_id,
            capacity_reservation_id="whatever",
            state="dispatching",
        )

    async def get_fulfillment_result(
        self, fulfillment_id: str,
    ) -> VersionedEnvelope[dict[str, Any]]:
        self.calls.append(fulfillment_id)
        if self.broken:
            raise ComputeProvisioningError("site unreachable", status_code=503)
        return VersionedEnvelope[dict[str, Any]](
            kind="fulfillment.result.v1", schema_version=1, payload={},
        )


@pytest.fixture
def reservation_sites() -> dict[str, str]:
    return {}


@pytest.fixture
def sites(reservation_sites: dict[str, str]) -> dict[str, FakeFulfillmentSite]:
    return {"east": FakeFulfillmentSite("east"), "west": FakeFulfillmentSite("west")}


@pytest.fixture
def aggregate(sites: dict[str, FakeFulfillmentSite], reservation_sites: dict[str, str]) -> AggregateFulfillmentClient:
    return AggregateFulfillmentClient(sites, reservation_sites=reservation_sites)


async def test_schedule_routes_to_the_cached_owning_site(
    aggregate: AggregateFulfillmentClient,
    sites: dict[str, FakeFulfillmentSite],
    reservation_sites: dict[str, str],
):
    reservation_sites["res-1"] = "west"
    sites["west"].known_reservations.add("res-1")

    result = await aggregate.schedule_resource(
        FulfillmentScheduleRequest(capacity_reservation_id="res-1", market="vms")
    )
    assert result.settlement_resource_id == "west-r1"
    assert sites["east"].calls == []  # never tried — cache hit on first try
    assert sites["west"].calls == ["res-1"]


async def test_cold_cache_falls_back_to_every_site(
    aggregate: AggregateFulfillmentClient,
    sites: dict[str, FakeFulfillmentSite],
    reservation_sites: dict[str, str],
):
    # No cache entry (e.g. after a storefront restart) — the reservation
    # actually lives on "west", east refuses with 404.
    sites["west"].known_reservations.add("res-2")

    result = await aggregate.schedule_resource(
        FulfillmentScheduleRequest(capacity_reservation_id="res-2", market="vms")
    )
    assert result.settlement_resource_id == "west-r1"
    assert sites["east"].calls == ["res-2"]  # tried and refused
    assert sites["west"].calls == ["res-2"]  # then succeeded
    # A successful fan-out attempt learns the site for next time.
    assert reservation_sites["res-2"] == "west"


async def test_every_site_refusing_raises_the_last_error(
    aggregate: AggregateFulfillmentClient,
):
    with pytest.raises(ComputeProvisioningError):
        await aggregate.schedule_resource(
            FulfillmentScheduleRequest(capacity_reservation_id="no-such-res", market="vms")
        )


async def test_begin_fulfillment_shares_the_cache_schedule_populated(
    aggregate: AggregateFulfillmentClient,
    sites: dict[str, FakeFulfillmentSite],
    reservation_sites: dict[str, str],
):
    sites["east"].known_reservations.add("res-3")
    await aggregate.schedule_resource(
        FulfillmentScheduleRequest(capacity_reservation_id="res-3", market="vms")
    )
    assert reservation_sites["res-3"] == "east"

    sites["east"].calls.clear()
    sites["west"].calls.clear()
    result = await aggregate.begin_fulfillment(
        FulfillmentRequestBody(
            capacity_reservation_id="res-3",
            market="vms",
            fulfillment_request=VersionedEnvelope(
                kind="vm.fulfillment.request", schema_version=1, payload={},
            ),
        )
    )
    assert result.fulfillment_id == "east-fulfillment-1"
    assert sites["west"].calls == []  # cache hit — never tried


async def test_status_and_result_route_by_explicit_capacity_reservation_id(
    aggregate: AggregateFulfillmentClient,
    sites: dict[str, FakeFulfillmentSite],
    reservation_sites: dict[str, str],
):
    # fulfillment_id alone isn't in the reservation_sites cache (it's keyed
    # by capacity_reservation_id) — callers that have it (task 9.3's
    # persisted workflow row) should pass it explicitly for routing.
    reservation_sites["res-4"] = "west"

    status = await aggregate.get_fulfillment_status(
        "west-fulfillment-1", capacity_reservation_id="res-4",
    )
    assert status.fulfillment_id == "west-fulfillment-1"
    assert sites["east"].calls == []
    assert sites["west"].calls == ["west-fulfillment-1"]


async def test_status_without_a_routing_hint_fans_out(
    aggregate: AggregateFulfillmentClient,
    sites: dict[str, FakeFulfillmentSite],
):
    result = await aggregate.get_fulfillment_status("some-fulfillment-id")
    assert result.fulfillment_id == "some-fulfillment-id"
    # No hint at all — tries sites in configured order; "east" (first) answers.
    assert sites["east"].calls == ["some-fulfillment-id"]
