"""A storefront's site projection state, held over this service as its authority.

``SiteProjectionState`` is what every storefront reads a site's resource pools
and capacity buckets from. Here it is composed exactly as a storefront composes
it: over an aggregate of the production ``SiteCapacityClient``, signing as a
storefront and verifying this service's signed responses, against the real
in-process application. Only the network between them is controlled, so the
authority can be made unreachable without stopping the application. This is
the proof that the state's polling reads the version and snapshot documents
this service actually serves, which the kit's own tests only simulate.
"""

from __future__ import annotations

import httpx
import pytest
from core_storefront.aggregation import AggregateCapacityClient
from httpx import ASGITransport
from market_capacity_publication import (
    CAPACITY_BUCKET,
    RESOURCE_POOL,
    SiteProjectionState,
)
from market_site_client import SiteCapacityAdminClient, SiteCapacityClient

from compute_provisioning_service.main import app

from .conftest import SERVICE_AUTHORITIES, STOREFRONT_SIGNER

SITE = "site-a"


class _Network(httpx.AsyncBaseTransport):
    """The route from the storefront to the site, which can be cut."""

    def __init__(self) -> None:
        self._app = ASGITransport(app=app)
        self.reachable = True

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if not self.reachable:
            raise httpx.ConnectError("site authority unreachable", request=request)
        return await self._app.handle_async_request(request)


def _bucketed_resources(state: SiteProjectionState) -> int:
    rows = state.values(CAPACITY_BUCKET)[SITE]
    return sum(int(row.get("resource_count") or 0) for row in rows)


@pytest.mark.asyncio
async def test_the_projection_state_follows_its_site_through_the_real_client(
    client_and_queue,
):
    network = _Network()
    remote = SiteCapacityClient(
        "http://test", STOREFRONT_SIGNER, SERVICE_AUTHORITIES, transport=network
    )
    wakes: list[str] = []
    state = SiteProjectionState(
        AggregateCapacityClient({SITE: remote}),
        on_resource_pool_change=lambda: wakes.append("publication"),
    )
    admin = SiteCapacityAdminClient(
        "http://test",
        STOREFRONT_SIGNER,
        SERVICE_AUTHORITIES,
        transport=ASGITransport(app=app),
    )

    async def declare(resource_id: str) -> None:
        await admin.register_resource(
            resource_id,
            pool_id="default",
            total_units=4,
            host_id=f"{resource_id}-host",
            attributes={"gpu_model": "H200"},
        )

    def default_pool_resources() -> set[str]:
        (pool,) = (
            row
            for row in state.values(RESOURCE_POOL)[SITE]
            if row["pool_id"] == "default"
        )
        return {resource["physical_resource_id"] for resource in pool["resources"]}

    # The first poll loads both families from the site's version and snapshot.
    await declare("projection-state-001")
    await state.poll_once()

    first = {family: state.view(SITE, family) for family in (RESOURCE_POOL, CAPACITY_BUCKET)}
    for view in first.values():
        assert view.state.value == "loaded"
        assert view.identity is not None
        assert view.last_error is None
    served = {
        RESOURCE_POOL: await remote.resource_pool_projection_version(),
        CAPACITY_BUCKET: await remote.capacity_bucket_projection_version(),
    }
    for family, view in first.items():
        assert (view.identity.revision, view.identity.digest) == (
            int(served[family]["revision"]),
            str(served[family]["digest"]),
        )
    assert default_pool_resources() == {"projection-state-001"}
    bucketed_before = _bucketed_resources(state)
    assert bucketed_before == 1
    # Loading the pools is a change publication is woken for.
    assert wakes == ["publication"]

    # A capacity declaration at the site is picked up by the next poll.
    await declare("projection-state-002")
    await state.poll_once()

    for family, before in first.items():
        after = state.view(SITE, family)
        assert after.state.value == "loaded"
        assert after.identity != before.identity
        assert after.fetched_at >= before.fetched_at
    assert default_pool_resources() == {"projection-state-001", "projection-state-002"}
    assert _bucketed_resources(state) == bucketed_before + 1
    assert wakes == ["publication", "publication"]

    # An outage keeps the last generation, marked stale with its error.
    held = {family: state.view(SITE, family) for family in (RESOURCE_POOL, CAPACITY_BUCKET)}
    network.reachable = False
    await state.poll_once()

    for family, before in held.items():
        after = state.view(SITE, family)
        assert after.state.value == "stale"
        assert after.identity == before.identity
        assert after.value == before.value
        assert after.fetched_at == before.fetched_at
        assert after.last_error
    status = state.status()[SITE]
    assert status[RESOURCE_POOL].state == "stale"
    assert status[CAPACITY_BUCKET].last_error
