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
from unittest.mock import MagicMock, patch

import httpx
import pytest

from core_storefront.capacity import CapacityClient, CapacityDelta
from market_storefront.services import capacity_client as cc
from tests._settings_overrides import settings_overrides
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
    use_site_projection_for_listings: bool = False,
):
    return SimpleNamespace(
        capacity=SimpleNamespace(
            authority_url=url, poll_interval=0.01,
            sites=sites, placement=placement,
            use_site_projection_for_listings=use_site_projection_for_listings,
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
    assert reserved["capacity_reservation_id"]
    assert reserved["available_gpu_count"] == 8

    await client.commit(
        resource_id=reserved["resource_id"],
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc="2099-01-01T00:00:00Z",
        lease_end_utc="2099-01-01 01:00",
        idempotency_ref="0xesc",
    )
    truncated = await client.truncate_lease(
        capacity_reservation_id=reserved["capacity_reservation_id"], lease_end_utc="2026-06-01 00:00",
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
async def test_commit_without_capacity_reservation_id_is_an_error(
    client: cc.RemoteCapacityClient,
):
    with pytest.raises(ValueError, match="capacity_reservation_id"):
        await client.commit(
            resource_id="r", capacity_reservation_id=None, lease_end_utc="2099-01-01 00:00",
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
async def test_list_reservations_filters(client: cc.RemoteCapacityClient):
    reserved = await client.reserve(
        claim={"gpu_count": 1}, deal_ref={"escrow_uid": "0xq"},
    )
    rows = await client.list_reservations(escrow_uid="0xq")
    assert [a["capacity_reservation_id"] for a in rows] == [reserved["capacity_reservation_id"]]
    assert await client.list_reservations(state="released") == []


def test_build_always_aggregates_site_authorities():
    with patch("market_storefront.utils.config.settings", _settings()):
        built = cc.build_capacity_client(lambda: None)
    assert isinstance(built, cc.AggregateCapacityClient)
    assert built.site_names == ["default"]
    assert built.site("default").base_url == "http://site-authority:8081"
    assert cc.remote_site_clients(built).keys() == {"default"}


def test_build_is_a_config_keyed_singleton():
    """The aggregator (and its reservation→site routing cache) survives
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


def test_most_available_placement_gets_the_kit_site_exact_claim_matcher():
    """Selecting "most_available" must not rank against the aggregator's
    own coarse default -- this domain's backing site is kit/site, which
    owns the only full claim-parsing and feasibility semantics, so
    composition must inject its exact matcher instead, bound with this
    domain's legacy unit-claim-key vocabulary."""
    import functools

    from market_site import dict_resource_satisfies_claim

    with patch(
        "market_storefront.utils.config.settings",
        _settings(placement="most_available"),
    ):
        built = cc.build_capacity_client(lambda: None)
    assert isinstance(built._placement, functools.partial)
    assert built._placement.func is cc.most_available
    injected_matcher = built._placement.keywords["claim_matcher"]
    assert isinstance(injected_matcher, functools.partial)
    assert injected_matcher.func is dict_resource_satisfies_claim
    assert injected_matcher.keywords["unit_claim_keys"] == cc.VM_UNIT_CLAIM_KEYS
    assert cc.VM_UNIT_CLAIM_KEYS == ("units", "gpu_count")
    # Behavioral, not just structural: the bound matcher must actually
    # apply VM's legacy gpu_count alias, not the module default.
    row = {
        "pool_id": "p", "resource_id": "r", "available_units": 3,
        "available": {"gpu_count": 3},
    }
    assert injected_matcher(row, {"gpu_count": 2}) is True
    assert injected_matcher(row, {"gpu_count": 5}) is False


def test_fill_first_placement_is_not_wrapped_with_a_claim_matcher():
    """fill_first ignores claim entirely -- wrapping it would be
    pointless ceremony, and it must stay the plain function so
    fill_first-selecting domains aren't forced to depend on kit/site."""
    with patch(
        "market_storefront.utils.config.settings",
        _settings(placement="fill_first"),
    ):
        built = cc.build_capacity_client(lambda: None)
    assert built._placement is cc.fill_first


@pytest.mark.asyncio
async def test_most_available_ranks_by_legacy_gpu_count_claim_through_the_real_aggregate_client():
    """Behavioral, not structural: proves the composed AggregateCapacityClient
    actually ranks a top-level {"gpu_count": N} claim -- VM's legacy,
    non-dimensional claim shape -- correctly through the full snapshot ->
    placement -> probe path, using real FakeSite-backed HTTP transports,
    not by inspecting functools.partial keywords in isolation."""
    small_site = FakeSite()
    small_site.add_resource("small-res", 2, attributes={"gpu_model": "H200"})
    big_site = FakeSite()
    big_site.add_resource("big-res", 10, attributes={"gpu_model": "H200"})

    with patch(
        "market_storefront.utils.config.settings",
        _settings(
            placement="most_available",
            sites={"small": "http://small:8081", "big": "http://big:8081"},
        ),
    ):
        built = cc.build_capacity_client(lambda: None)
    # Swap in the fake transports for each named site without going
    # through real HTTP.
    built._sites["small"] = cc.RemoteCapacityClient(
        "http://small:8081", "test-key", transport=small_site.transport(),
    )
    built._sites["big"] = cc.RemoteCapacityClient(
        "http://big:8081", "test-key", transport=big_site.transport(),
    )

    match = await built.probe(claim={"gpu_count": 2})

    assert match is not None
    assert match["resource_id"] == "big-res"


@pytest.mark.asyncio
async def test_most_available_excludes_a_resource_type_mismatch_through_the_real_aggregate_client():
    """Behavioral counterpart to kit/site's own low-level resource_type
    match/mismatch coverage: a claim naming a resource_type no available
    resource actually has must not select any site, even one reporting
    abundant available_units."""
    wrong_type_site = FakeSite()
    wrong_type_site.add_resource("cpu-only-res", 20, attributes={"gpu_model": "H200"})
    right_type_site = FakeSite()
    right_type_site.add_resource("gpu-res", 1, attributes={"gpu_model": "H200"})

    with patch(
        "market_storefront.utils.config.settings",
        _settings(
            placement="most_available",
            sites={"wrong": "http://wrong:8081", "right": "http://right:8081"},
        ),
    ):
        built = cc.build_capacity_client(lambda: None)
    built._sites["wrong"] = cc.RemoteCapacityClient(
        "http://wrong:8081", "test-key", transport=wrong_type_site.transport(),
    )
    built._sites["right"] = cc.RemoteCapacityClient(
        "http://right:8081", "test-key", transport=right_type_site.transport(),
    )

    match = await built.probe(claim={"resource_type": "compute.cpu", "gpu_count": 1})

    # FakeSite always reports "compute.gpu" (see its snapshot handler) --
    # neither site actually satisfies a compute.cpu claim, so this proves
    # the exact matcher's resource_type check excludes both from ranking.
    assert match is None


@pytest.mark.asyncio
async def test_subscriber_closes_and_reopens_with_site_availability(
    client: cc.RemoteCapacityClient,
):
    calls: list[tuple[str, dict | None]] = []

    async def fake_close(
        db_path, *, home_site=None, configured_site_count=0,
        member_availability=None, site_pool_projection=None,
    ):
        calls.append(("close", None, member_availability))
        return ["lst-1"]

    async def fake_reopen(
        db_path, *, home_site=None, member_availability=None, site_pool_projection=None,
    ):
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
async def test_subscriber_runs_both_passes_for_mixed_direction_capacity_change(
    client: cc.RemoteCapacityClient,
):
    """A mixed-direction registration e.g. GPU count grew while RAM shrank.
    "capacity_changed" must run both reconciliation passes and not be silently
    ignored like an unrecognized kind would be."""
    calls: list[str] = []

    async def fake_close(
        db_path, *, home_site=None, configured_site_count=0,
        member_availability=None, site_pool_projection=None,
    ):
        calls.append("close")
        return []

    async def fake_reopen(
        db_path, *, home_site=None, member_availability=None, site_pool_projection=None,
    ):
        calls.append("reopen")
        return []

    subscriber = cc._make_listing_reconcile_subscriber(
        lambda: SimpleNamespace(db_path="/tmp/x.db"), client,
    )
    with patch(
        "market_storefront.services.publication_service."
        "close_stale_compute_listings_after_capacity_change",
        fake_close,
    ), patch(
        "market_storefront.services.publication_service."
        "reopen_available_compute_listings_after_capacity_change",
        fake_reopen,
    ):
        await subscriber(CapacityDelta(kind="capacity_changed", version=1))

    assert calls == ["close", "reopen"]


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


# ---------------------------------------------------------------------------
# site_pool_projection -- projection_caches() -> {site: rows} conversion
# ---------------------------------------------------------------------------

class TestSitePoolProjection:
    def test_empty_when_nothing_cached(self):
        with patch(
            "market_storefront.services.site_projection_cache.projection_caches",
            return_value={},
        ):
            assert cc.site_pool_projection() == {}

    def test_includes_a_site_with_a_loaded_value(self):
        fake_cache = MagicMock()
        fake_cache.resource_pools.view.return_value.value = [
            {"resource_pool_id": "gpu-pool", "resources": []},
        ]
        with patch(
            "market_storefront.services.site_projection_cache.projection_caches",
            return_value={"site-a": fake_cache},
        ):
            result = cc.site_pool_projection()
        assert result == {
            "site-a": [{"resource_pool_id": "gpu-pool", "resources": []}],
        }

    def test_excludes_a_site_with_no_cached_value(self):
        """A site whose projection has never loaded (or is currently
        unavailable/invalid) has value=None -- it must not appear at all,
        not as an empty list -- reconciler's projection-sourced path
        falls back to local tables only when the whole mapping is empty,
        and a present-but-empty-list site would incorrectly look like
        "this site genuinely has zero pools"."""
        fake_cache = MagicMock()
        fake_cache.resource_pools.view.return_value.value = None
        with patch(
            "market_storefront.services.site_projection_cache.projection_caches",
            return_value={"site-a": fake_cache},
        ):
            result = cc.site_pool_projection()
        assert result == {}

    def test_includes_a_site_with_a_loaded_empty_projection(self):
        """The other half of the None-vs-[] distinction: a site whose
        projection HAS successfully loaded, and genuinely has zero
        pools right now, must be included as an empty list -- not
        excluded the way an unloaded site is. Regression case for a
        real bug: `if value:` (truthy) treated a loaded-empty site
        identically to a never-loaded site, so an authoritative "zero
        pools" answer silently fell back to stale local-table data
        instead of correctly registering zero capacity."""
        fake_cache = MagicMock()
        fake_cache.resource_pools.view.return_value.value = []
        with patch(
            "market_storefront.services.site_projection_cache.projection_caches",
            return_value={"site-a": fake_cache},
        ):
            result = cc.site_pool_projection()
        assert result == {"site-a": []}
        assert "site-a" in result  # not just == {} by coincidence

    def test_multiple_sites_only_loaded_ones_included(self):
        loaded = MagicMock()
        loaded.resource_pools.view.return_value.value = [{"resource_pool_id": "p"}]
        unloaded = MagicMock()
        unloaded.resource_pools.view.return_value.value = None
        with patch(
            "market_storefront.services.site_projection_cache.projection_caches",
            return_value={"site-a": loaded, "site-b": unloaded},
        ):
            result = cc.site_pool_projection()
        assert set(result) == {"site-a"}


# ---------------------------------------------------------------------------
# Orchestration: a real cached projection actually reaches reconciliation,
# not just the two pieces (cache -> dict, dict -> dispatch) in isolation.
# ---------------------------------------------------------------------------

class TestReconcileListingsUsesCachedProjectionWhenEnabled:
    async def test_a_real_loaded_cache_entry_reaches_the_close_call(
        self, client: cc.RemoteCapacityClient,
    ):
        """End to end: populate site_projection_cache's real module-level
        cache with a real (not mocked) ProjectionCache in the `loaded`
        state, enable the feature flag, trigger the real subscriber with
        a real CapacityDelta, and confirm the exact cached rows arrive as
        the site_pool_projection argument to the close call -- proving
        the wiring from cache to reconciliation is actually connected,
        not just each half correct in isolation.
        """
        from core_storefront.site_projections import (
            ProjectionCache, ProjectionIdentity, ProjectionState,
        )
        from market_storefront.services import site_projection_cache as spc

        pool_rows = [{"resource_pool_id": "gpu-pool", "resources": []}]

        resource_pools_cache: ProjectionCache = ProjectionCache(client=None)
        resource_pools_cache._value = pool_rows
        resource_pools_cache._state = ProjectionState.loaded
        resource_pools_cache._identity = ProjectionIdentity(revision=1, digest="abc")

        caches = spc.SiteProjectionCaches(
            resource_pools=resource_pools_cache,
            capacity_buckets=ProjectionCache(client=None),
        )

        received: dict = {}

        async def fake_close(
            db_path, *, home_site=None, configured_site_count=0,
            member_availability=None, site_pool_projection=None,
        ):
            received["site_pool_projection"] = site_pool_projection
            return []

        async def fake_reopen(
            db_path, *, home_site=None, member_availability=None, site_pool_projection=None,
        ):
            return []

        subscriber = cc._make_listing_reconcile_subscriber(
            lambda: SimpleNamespace(db_path="/tmp/x.db"), client,
        )
        with patch.dict(spc._caches, {"default": caches}, clear=True), \
             settings_overrides(**{"capacity.use_site_projection_for_listings": True}), \
             patch(
                 "market_storefront.services.publication_service."
                 "close_stale_compute_listings_after_capacity_change",
                 fake_close,
             ), \
             patch(
                 "market_storefront.services.publication_service."
                 "reopen_available_compute_listings_after_capacity_change",
                 fake_reopen,
             ):
            await subscriber(CapacityDelta(kind="reserved", version=1))

        assert received["site_pool_projection"] == {"default": pool_rows}

    async def test_flag_disabled_reaches_the_close_call_as_none(
        self, client: cc.RemoteCapacityClient,
    ):
        """Same cache state, flag off: the cached projection must not be
        used at all -- close still runs (reconciliation itself isn't
        gated), but with site_pool_projection=None."""
        from core_storefront.site_projections import (
            ProjectionCache, ProjectionIdentity, ProjectionState,
        )
        from market_storefront.services import site_projection_cache as spc

        resource_pools_cache: ProjectionCache = ProjectionCache(client=None)
        resource_pools_cache._value = [{"resource_pool_id": "gpu-pool", "resources": []}]
        resource_pools_cache._state = ProjectionState.loaded
        resource_pools_cache._identity = ProjectionIdentity(revision=1, digest="abc")
        caches = spc.SiteProjectionCaches(
            resource_pools=resource_pools_cache,
            capacity_buckets=ProjectionCache(client=None),
        )

        received: dict = {}

        async def fake_close(
            db_path, *, home_site=None, configured_site_count=0,
            member_availability=None, site_pool_projection=None,
        ):
            received["site_pool_projection"] = site_pool_projection
            return []

        async def fake_reopen(
            db_path, *, home_site=None, member_availability=None, site_pool_projection=None,
        ):
            return []

        subscriber = cc._make_listing_reconcile_subscriber(
            lambda: SimpleNamespace(db_path="/tmp/x.db"), client,
        )
        with patch.dict(spc._caches, {"default": caches}, clear=True), \
             settings_overrides(**{"capacity.use_site_projection_for_listings": False}), \
             patch(
                 "market_storefront.services.publication_service."
                 "close_stale_compute_listings_after_capacity_change",
                 fake_close,
             ), \
             patch(
                 "market_storefront.services.publication_service."
                 "reopen_available_compute_listings_after_capacity_change",
                 fake_reopen,
             ):
            await subscriber(CapacityDelta(kind="reserved", version=1))

        assert received["site_pool_projection"] is None
