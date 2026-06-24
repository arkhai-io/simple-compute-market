"""RemoteCapacityClient: wire contract, mode dispatch, and delta delivery.

The FakeSite transport mirrors the provisioning service's
/api/v1/capacity surface (whose shapes are pinned by that service's own
integration tests); these tests pin the storefront half of the contract.
"""

from __future__ import annotations

import asyncio
import itertools
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from core_storefront.capacity import CapacityClient, CapacityDelta
from market_storefront.services import capacity_client as cc
from tests.fake_site import FakeSite


@pytest.fixture
def site() -> FakeSite:
    fake = FakeSite()
    fake.add_resource(
        "compute-kvm1-001", 8,
        attributes={"vm_host": "kvm1", "gpu_model": "H200"},
    )
    return fake


@pytest.fixture
def client(site: FakeSite) -> cc.RemoteCapacityClient:
    return cc.RemoteCapacityClient(
        "http://site-authority:8081", "test-key", transport=site.transport(),
    )


def _settings(
    url: str = "http://site-authority:8081",
    sites: dict | None = None,
    placement: str = "fill_first",
):
    return SimpleNamespace(
        capacity=SimpleNamespace(
            authority_url=url, poll_interval=0.01,
            sites=sites, placement=placement,
        ),
        provisioning=SimpleNamespace(service_url="http://prov:8081"),
        admin_api_key="test-key",
    )


@pytest.fixture(autouse=True)
def _reset_aggregate_cache():
    cc._aggregate_state.update(key=None, client=None)
    yield
    cc._aggregate_state.update(key=None, client=None)


@pytest.mark.asyncio
async def test_remote_client_speaks_the_capacity_wire_contract(
    client: cc.RemoteCapacityClient, site: FakeSite,
):
    assert isinstance(client, CapacityClient)

    snapshot = await client.snapshot()
    assert snapshot[0]["available_units"] == 8

    assert await client.probe(claim={"gpu_model": "A100"}) is None
    match = await client.probe(claim={"gpu_model": "H200"})
    assert match["vm_host"] == "kvm1"

    reserved = await client.reserve(
        claim={"gpu_count": 3}, deal_ref={"escrow_uid": "0xesc"},
    )
    assert reserved["allocation_id"]
    assert reserved["available_gpu_count"] == 8

    await client.commit(
        resource_id=reserved["resource_id"],
        allocation_id=reserved["allocation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01 01:00",
        idempotency_ref="0xesc",
    )
    truncated = await client.truncate_lease(
        allocation_id=reserved["allocation_id"], lease_end_utc="2026-06-01 00:00",
    )
    assert truncated["lease_end_utc"] == "2026-06-01 00:00"

    released = await client.release(
        deal_ref={"escrow_uid": "0xesc"}, failure_reason="provisioning_failed",
    )
    assert released["state"] == "released"
    assert released["failure_reason"] == "provisioning_failed"

    events, latest = await client.events_after(0)
    assert [e["kind"] for e in events] == [
        "reserved", "committed", "lease_truncated", "released",
    ]
    assert latest == events[-1]["version"]
    # Every call authenticated.
    assert set(site.seen_admin_keys) == {"test-key"}


@pytest.mark.asyncio
async def test_commit_without_allocation_id_is_an_error(
    client: cc.RemoteCapacityClient,
):
    with pytest.raises(ValueError, match="allocation_id"):
        await client.commit(
            resource_id="r", allocation_id=None, lease_end_utc="2099-01-01 00:00",
        )


@pytest.mark.asyncio
async def test_member_availability_view_reflects_consumption(
    client: cc.RemoteCapacityClient,
):
    await client.reserve(claim={"gpu_count": 3}, deal_ref={})
    view = await cc.member_availability_view(client)
    assert view[(None, "compute-kvm1-001")] == 5
    assert view[("default", "compute-kvm1-001")] == 5


@pytest.mark.asyncio
async def test_list_allocations_filters(client: cc.RemoteCapacityClient):
    reserved = await client.reserve(
        claim={"gpu_count": 1}, deal_ref={"escrow_uid": "0xq"},
    )
    rows = await client.list_allocations(escrow_uid="0xq")
    assert [a["allocation_id"] for a in rows] == [reserved["allocation_id"]]
    assert await client.list_allocations(state="released") == []


def test_build_always_aggregates_site_authorities():
    with patch("market_storefront.utils.config.settings", _settings()):
        built = cc.build_capacity_client(lambda: None)
    assert isinstance(built, cc.AggregateCapacityClient)
    assert built.site_names == ["default"]
    assert built.site("default").base_url == "http://site-authority:8081"
    assert cc.remote_site_clients(built).keys() == {"default"}


def test_build_is_a_config_keyed_singleton():
    """The aggregator (and its allocation→site routing cache) survives
    across build calls until the site configuration changes."""
    with patch("market_storefront.utils.config.settings", _settings()):
        first = cc.build_capacity_client(lambda: None)
        second = cc.build_capacity_client(lambda: None)
    assert first is second

    other = _settings(sites={"dc-a": "http://a:8081", "dc-b": "http://b:8081"})
    with patch("market_storefront.utils.config.settings", other):
        rebuilt = cc.build_capacity_client(lambda: None)
    assert rebuilt is not first
    assert rebuilt.site_names == ["dc-a", "dc-b"]
    assert cc.remote_site_clients(rebuilt).keys() == {"dc-a", "dc-b"}


def test_site_mode_defaults_authority_url_to_provisioning():
    with patch(
        "market_storefront.utils.config.settings", _settings(url=""),
    ):
        built = cc.build_capacity_client(lambda: None)
    assert built.site("default").base_url == "http://prov:8081"


@pytest.mark.asyncio
async def test_subscriber_closes_and_reopens_with_site_availability(
    client: cc.RemoteCapacityClient,
):
    calls: list[tuple[str, dict | None]] = []

    async def fake_close(db_path, *, member_availability=None):
        calls.append(("close", None, member_availability))
        return ["lst-1"]

    async def fake_reopen(db_path, *, member_availability=None):
        calls.append(("reopen", None, member_availability))
        return []

    subscriber = cc._make_listing_reconcile_subscriber(
        lambda: SimpleNamespace(db_path="/tmp/x.db"), client,
    )
    await client.reserve(claim={"gpu_count": 2}, deal_ref={})
    with patch(
        "market_storefront.services.publication_service."
        "close_stale_compute_listings_after_capacity_change",
        fake_close,
    ), patch(
        "market_storefront.services.publication_service."
        "reopen_available_compute_listings_after_capacity_change",
        fake_reopen,
    ):
        await subscriber(CapacityDelta(kind="reserved", version=1))
        await subscriber(CapacityDelta(kind="released", version=2))

    assert [c[0] for c in calls] == ["close", "reopen"]
    # Availability came from the site snapshot, keyed for the home site.
    assert calls[0][2][(None, "compute-kvm1-001")] == 6


@pytest.mark.asyncio
async def test_poller_positions_at_head_then_emits_new_deltas(site: FakeSite):
    """Each site's poller skips history, reconciles once, then streams
    site-tagged deltas onto the aggregate bus."""
    client = cc.RemoteCapacityClient(
        "http://site-authority:8081", "test-key",
        transport=site.transport(),
    )
    aggregate = cc.AggregateCapacityClient({"dc-a": client})
    seen: list[CapacityDelta] = []

    async def record(delta: CapacityDelta) -> None:
        seen.append(delta)

    aggregate.subscribe(record)
    site._emit("reserved", "compute-kvm1-001")  # history — must NOT replay

    reconciles = 0

    async def fake_reconcile(db_path, *, member_availability=None):
        nonlocal reconciles
        reconciles += 1
        return []

    with patch.object(cc, "build_capacity_client", return_value=aggregate), patch(
        "market_storefront.utils.config.settings", _settings(),
    ), patch(
        "market_storefront.utils.sqlite_client.get_sqlite_client",
        return_value=SimpleNamespace(db_path="/tmp/x.db"),
    ), patch(
        "market_storefront.services.publication_service."
        "close_stale_compute_listings_after_capacity_change",
        fake_reconcile,
    ), patch(
        "market_storefront.services.publication_service."
        "reopen_available_compute_listings_after_capacity_change",
        fake_reconcile,
    ):
        task = asyncio.create_task(cc.capacity_events_poller_loop())
        try:
            for _ in range(200):
                if reconciles >= 2:  # startup close+reopen ran
                    break
                await asyncio.sleep(0.01)
            site._emit("committed", "compute-kvm1-001")
            for _ in range(200):
                if seen:
                    break
                await asyncio.sleep(0.01)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert reconciles >= 2
    assert [d.kind for d in seen] == ["committed"]
    assert seen[0].resource_id == "compute-kvm1-001"
    assert seen[0].site == "dc-a"
