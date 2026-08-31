"""market_storefront.services.capacity_client: mode dispatch, placement,
aggregate composition, and delta delivery.

The client's own wire-contract tests live in
kit/site-client/tests/unit/test_client.py -- these tests cover this
package's own orchestration on top of the client: aggregate/placement
composition, the listing-reconcile subscriber, the projection cache
wiring, and the event-feed poller. The FakeSite transport mirrors the
provisioning service's /api/v1/capacity surface (whose shapes are pinned
by that service's own integration tests).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from core_storefront.capacity import CapacityDelta
from core_storefront.aggregation import fill_first
from market_capacity_publication import (
    CapacityProjection,
    CapacityReconcileContext,
    capacity_availability,
    remote_site_clients,
)
from dynaconf import Dynaconf

from market_storefront.services import capacity_client as cc
from tests._settings_overrides import settings_overrides
from tests.fake_site import (
    TEST_MARKETPLACE_SIGNER,
    TEST_SITE_AUTHORITIES,
    FakeSite,
)


@pytest.fixture
def site() -> FakeSite:
    fake = FakeSite(deliverable_modes={"vm"})
    fake.add_resource(
        "compute-kvm1-001",
        8,
        attributes={"vm_host": "kvm1", "gpu_model": "H200"},
    )
    return fake


@pytest.fixture
def client(site: FakeSite) -> cc.SiteCapacityClient:
    return cc.SiteCapacityClient(
        "http://site-authority:8081",
        signer=TEST_MARKETPLACE_SIGNER,
        expected_authorities=TEST_SITE_AUTHORITIES,
        transport=site.transport(),
    )


def test_site_capacity_client_satisfies_the_site_capacity_authority_protocol(
    client: cc.SiteCapacityClient,
):
    """The per-site client satisfies the narrower per-site protocol
    (no subscribe -- a per-site client has no local bus of its own),
    while the broader `CapacityClient` protocol (including subscribe)
    is what `AggregateCapacityClient` itself implements, not what it
    requires of its member sites."""
    from core_storefront.capacity import CapacityClient, SiteCapacityAuthority

    assert isinstance(client, SiteCapacityAuthority)
    assert not isinstance(client, CapacityClient)


def test_aggregate_capacity_client_satisfies_the_full_capacity_client_protocol(
    client: cc.SiteCapacityClient,
):
    from core_storefront.capacity import CapacityClient

    aggregate = cc.AggregateCapacityClient({"dc-a": client})
    assert isinstance(aggregate, CapacityClient)


def _settings(
    url: str = "http://site-authority:8081",
    sites: dict | None = None,
    placement: str = "fill_first",
    use_site_projection_for_listings: bool = False,
) -> Dynaconf:
    source = Dynaconf(environments=False)
    source.set(
        "identity.principal",
        TEST_MARKETPLACE_SIGNER.identity.model_dump(mode="json"),
    )
    source.set(
        "provisioning.identity.principals",
        [
            principal.model_dump(mode="json")
            for principal in TEST_SITE_AUTHORITIES.identities
        ],
    )
    source.set("capacity.authority_url", url)
    source.set("capacity.poll_interval", 0.01)
    source.set("capacity.sites", sites if sites is not None else {"default": url})
    source.set("capacity.placement", placement)
    source.set(
        "capacity.use_site_projection_for_listings",
        use_site_projection_for_listings,
    )
    source.set("provisioning.service_url", "http://prov:8081")
    return source


@pytest.fixture(autouse=True)
def _reset_aggregate_cache():
    cc._capacity_runtime_state.update(key=None, runtime=None)
    with patch(
        "market_storefront.container.resolved_marketplace_signer",
        TEST_MARKETPLACE_SIGNER,
    ):
        yield
    cc._capacity_runtime_state.update(key=None, runtime=None)


@pytest.mark.asyncio
async def test_exact_site_availability_reflects_consumption(
    client: cc.SiteCapacityClient,
):
    await client.reserve(
        claim={"executor_kind": "vm", "gpu_count": 3},
        deal_ref={},
    )
    aggregate = cc.AggregateCapacityClient({"default": client})
    view = await capacity_availability(aggregate)
    assert view[("default", "compute-kvm1-001")] == 5


def test_build_always_aggregates_site_authorities():
    with patch("market_storefront.utils.config.settings", _settings()):
        built = cc.build_capacity_client(lambda: None)
    assert isinstance(built, cc.AggregateCapacityClient)
    assert built.site_names == ["default"]
    assert built.site("default").base_url == "http://site-authority:8081"
    assert remote_site_clients(built).keys() == {"default"}


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
    assert remote_site_clients(rebuilt).keys() == {"dc-a", "dc-b"}


def test_missing_explicit_sites_is_rejected():
    configured = _settings()
    configured.set("capacity.sites", {})
    with patch("market_storefront.utils.config.settings", configured):
        with pytest.raises(RuntimeError, match="capacity.sites"):
            cc.build_capacity_client(lambda: None)


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
        "pool_id": "p",
        "resource_id": "r",
        "available_units": 3,
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
    assert built._placement is fill_first


@pytest.mark.asyncio
async def test_most_available_ranks_by_legacy_gpu_count_claim_through_the_real_aggregate_client():
    """Behavioral, not structural: proves the composed AggregateCapacityClient
    actually ranks a top-level {"gpu_count": N} claim -- VM's legacy,
    non-dimensional claim shape -- correctly through the full snapshot ->
    placement -> probe path, using real FakeSite-backed HTTP transports,
    not by inspecting functools.partial keywords in isolation."""
    small_site = FakeSite(deliverable_modes={"vm"})
    small_site.add_resource("small-res", 2, attributes={"gpu_model": "H200"})
    big_site = FakeSite(deliverable_modes={"vm"})
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
    built._sites["small"] = cc.SiteCapacityClient(
        "http://small:8081",
        signer=TEST_MARKETPLACE_SIGNER,
        expected_authorities=TEST_SITE_AUTHORITIES,
        transport=small_site.transport(),
    )
    built._sites["big"] = cc.SiteCapacityClient(
        "http://big:8081",
        signer=TEST_MARKETPLACE_SIGNER,
        expected_authorities=TEST_SITE_AUTHORITIES,
        transport=big_site.transport(),
    )

    match = await built.probe(claim={"executor_kind": "vm", "gpu_count": 2})

    assert match is not None
    assert match["resource_id"] == "big-res"


@pytest.mark.asyncio
async def test_most_available_excludes_a_resource_type_mismatch_through_the_real_aggregate_client():
    """Behavioral counterpart to kit/site's own low-level resource_type
    match/mismatch coverage: a claim naming a resource_type no available
    resource actually has must not select any site, even one reporting
    abundant available_units."""
    wrong_type_site = FakeSite(deliverable_modes={"vm"})
    wrong_type_site.add_resource("cpu-only-res", 20, attributes={"gpu_model": "H200"})
    right_type_site = FakeSite(deliverable_modes={"vm"})
    right_type_site.add_resource("gpu-res", 1, attributes={"gpu_model": "H200"})

    with patch(
        "market_storefront.utils.config.settings",
        _settings(
            placement="most_available",
            sites={"wrong": "http://wrong:8081", "right": "http://right:8081"},
        ),
    ):
        built = cc.build_capacity_client(lambda: None)
    built._sites["wrong"] = cc.SiteCapacityClient(
        "http://wrong:8081",
        signer=TEST_MARKETPLACE_SIGNER,
        expected_authorities=TEST_SITE_AUTHORITIES,
        transport=wrong_type_site.transport(),
    )
    built._sites["right"] = cc.SiteCapacityClient(
        "http://right:8081",
        signer=TEST_MARKETPLACE_SIGNER,
        expected_authorities=TEST_SITE_AUTHORITIES,
        transport=right_type_site.transport(),
    )

    match = await built.probe(
        claim={
            "executor_kind": "vm",
            "resource_type": "compute.cpu",
            "gpu_count": 1,
        }
    )

    # FakeSite always reports "compute.gpu" (see its snapshot handler) --
    # neither site actually satisfies a compute.cpu claim, so this proves
    # the exact matcher's resource_type check excludes both from ranking.
    assert match is None


@pytest.mark.asyncio
async def test_domain_hook_closes_and_reopens_with_exact_site_availability():
    calls: list[tuple[str, dict]] = []
    repository = SimpleNamespace(db_path="/tmp/x.db")

    async def fake_close(_db_path, *, member_availability, **_kwargs):
        calls.append(("close", member_availability))
        return []

    async def fake_reopen(_db_path, *, member_availability, **_kwargs):
        calls.append(("reopen", member_availability))
        return []

    reconcile = cc._capacity_reconciler(lambda: repository)
    projection = (CapacityProjection("default", ()),)
    with (
        patch(
            "market_storefront.services.publication_service."
            "close_stale_compute_listings_after_capacity_change",
            fake_close,
        ),
        patch(
            "market_storefront.services.publication_service."
            "reopen_available_compute_listings_after_capacity_change",
            fake_reopen,
        ),
        patch("market_storefront.services.capacity_client.settings", _settings()),
    ):
        await reconcile(
            CapacityReconcileContext(
                projections=projection,
                availability={("default", "compute-kvm1-001"): 6},
                delta=CapacityDelta(kind="reserved", version=1),
            )
        )
        await reconcile(
            CapacityReconcileContext(
                projections=projection,
                availability={("default", "compute-kvm1-001"): 8},
                delta=CapacityDelta(kind="released", version=2),
            )
        )

    assert [name for name, _ in calls] == ["close", "reopen"]
    assert calls[0][1] == {("default", "compute-kvm1-001"): 6}


@pytest.mark.asyncio
async def test_domain_hook_runs_both_passes_for_mixed_capacity_change():
    calls: list[str] = []
    repository = SimpleNamespace(db_path="/tmp/x.db")

    async def fake_close(*_args, **_kwargs):
        calls.append("close")
        return []

    async def fake_reopen(*_args, **_kwargs):
        calls.append("reopen")
        return []

    reconcile = cc._capacity_reconciler(lambda: repository)
    with (
        patch(
            "market_storefront.services.publication_service."
            "close_stale_compute_listings_after_capacity_change",
            fake_close,
        ),
        patch(
            "market_storefront.services.publication_service."
            "reopen_available_compute_listings_after_capacity_change",
            fake_reopen,
        ),
        patch("market_storefront.services.capacity_client.settings", _settings()),
    ):
        await reconcile(
            CapacityReconcileContext(
                projections=(CapacityProjection("default", ()),),
                availability={},
                delta=CapacityDelta(kind="capacity_changed", version=1),
            )
        )

    assert calls == ["close", "reopen"]


@pytest.mark.asyncio
async def test_poller_loop_delegates_to_composed_kit_runtime():
    repository = SimpleNamespace(db_path="/tmp/x.db")
    runtime = SimpleNamespace(poll_events=AsyncMock())
    with (
        patch.object(cc, "build_capacity_runtime", return_value=runtime),
        patch("market_storefront.utils.config.settings", _settings()),
    ):
        await cc.capacity_events_poller_loop(repository)

    runtime.poll_events.assert_awaited_once_with(interval_seconds=0.01)


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


class TestSiteCapacityBuckets:
    """Same None-vs-[] inclusion contract as TestSitePoolProjection,
    verified independently for the sibling function -- both feed the
    same reconciler consumer, and the two are easy to accidentally drift
    apart since they're separate functions over separate cache fields."""

    def test_empty_when_nothing_cached(self):
        with patch(
            "market_storefront.services.site_projection_cache.projection_caches",
            return_value={},
        ):
            assert cc.site_capacity_buckets() == {}

    def test_excludes_a_site_with_no_cached_value(self):
        fake_cache = MagicMock()
        fake_cache.capacity_buckets.view.return_value.value = None
        with patch(
            "market_storefront.services.site_projection_cache.projection_caches",
            return_value={"site-a": fake_cache},
        ):
            result = cc.site_capacity_buckets()
        assert result == {}

    def test_includes_a_site_with_a_loaded_empty_projection(self):
        """A site whose capacity-bucket family loaded successfully with
        zero rows must be included as an empty list, not excluded the
        way an unloaded site is -- reconciler's fungible-mode row builder
        relies on this to trust an authoritative zero instead of falling
        back."""
        fake_cache = MagicMock()
        fake_cache.capacity_buckets.view.return_value.value = []
        with patch(
            "market_storefront.services.site_projection_cache.projection_caches",
            return_value={"site-a": fake_cache},
        ):
            result = cc.site_capacity_buckets()
        assert result == {"site-a": []}
        assert "site-a" in result

    def test_includes_a_site_with_loaded_bucket_rows(self):
        fake_cache = MagicMock()
        fake_cache.capacity_buckets.view.return_value.value = [
            {
                "resource_pool_id": "gpu-pool",
                "available": {"gpu_count": 4},
                "resource_count": 1,
            },
        ]
        with patch(
            "market_storefront.services.site_projection_cache.projection_caches",
            return_value={"site-a": fake_cache},
        ):
            result = cc.site_capacity_buckets()
        assert result == {
            "site-a": [
                {
                    "resource_pool_id": "gpu-pool",
                    "available": {"gpu_count": 4},
                    "resource_count": 1,
                },
            ],
        }


# ---------------------------------------------------------------------------
# Orchestration: a real cached projection actually reaches reconciliation,
# not just the two pieces (cache -> dict, dict -> dispatch) in isolation.
# ---------------------------------------------------------------------------


class TestReconcileListingsUsesCachedProjectionWhenEnabled:
    async def test_a_real_loaded_cache_entry_reaches_the_close_call(
        self,
        client: cc.SiteCapacityClient,
    ):
        """End to end: populate site_projection_cache's real module-level
        cache with a real (not mocked) ProjectionCache in the `loaded`
        state, enable the feature flag, trigger the real subscriber with
        a real CapacityDelta, and confirm the exact cached rows arrive as
        the site_pool_projection argument to the close call -- proving
        the wiring from cache to reconciliation is actually connected,
        not just each half correct in isolation. Also proves the sibling
        site_capacity_buckets cache reaches the same call the same way.
        """
        from core_storefront.site_projections import (
            ProjectionCache,
            ProjectionIdentity,
            ProjectionState,
        )

        from market_storefront.services import site_projection_cache as spc

        pool_rows = [{"resource_pool_id": "gpu-pool", "resources": []}]
        bucket_rows = [
            {
                "resource_pool_id": "gpu-pool",
                "available": {"gpu_count": 4},
                "resource_count": 1,
            }
        ]

        resource_pools_cache: ProjectionCache = ProjectionCache(client=None)
        resource_pools_cache._value = pool_rows
        resource_pools_cache._state = ProjectionState.loaded
        resource_pools_cache._identity = ProjectionIdentity(revision=1, digest="abc")

        capacity_buckets_cache: ProjectionCache = ProjectionCache(client=None)
        capacity_buckets_cache._value = bucket_rows
        capacity_buckets_cache._state = ProjectionState.loaded
        capacity_buckets_cache._identity = ProjectionIdentity(revision=1, digest="def")

        caches = spc.SiteProjectionCaches(
            resource_pools=resource_pools_cache,
            capacity_buckets=capacity_buckets_cache,
        )

        received: dict = {}
        repository = SimpleNamespace(db_path="/tmp/x.db")

        async def fake_close(
            db_path,
            *,
            sqlite_client,
            home_site=None,
            configured_site_count=0,
            member_availability=None,
            site_pool_projection=None,
            site_capacity_buckets=None,
        ):
            assert sqlite_client is repository
            received["site_pool_projection"] = site_pool_projection
            received["site_capacity_buckets"] = site_capacity_buckets
            return []

        async def fake_reopen(
            db_path,
            *,
            sqlite_client,
            home_site=None,
            member_availability=None,
            site_pool_projection=None,
            site_capacity_buckets=None,
        ):
            assert sqlite_client is repository
            return []

        reconcile = cc._capacity_reconciler(lambda: repository)
        with (
            patch.dict(spc._caches, {"default": caches}, clear=True),
            settings_overrides(**{"capacity.use_site_projection_for_listings": True}),
            patch(
                "market_storefront.services.publication_service."
                "close_stale_compute_listings_after_capacity_change",
                fake_close,
            ),
            patch(
                "market_storefront.services.publication_service."
                "reopen_available_compute_listings_after_capacity_change",
                fake_reopen,
            ),
        ):
            await reconcile(
                CapacityReconcileContext(
                    projections=(CapacityProjection("default", ()),),
                    availability={},
                    delta=CapacityDelta(kind="reserved", version=1),
                )
            )

        assert received["site_pool_projection"] == {"default": pool_rows}
        assert received["site_capacity_buckets"] == {"default": bucket_rows}

    async def test_flag_disabled_reaches_the_close_call_as_none(
        self,
        client: cc.SiteCapacityClient,
    ):
        """Same cache state, flag off: the cached projection must not be
        used at all -- close still runs (reconciliation itself isn't
        gated), but with site_pool_projection=None (and, following from
        it, site_capacity_buckets=None -- the buckets fetch is itself
        gated on the projection having been fetched)."""
        from core_storefront.site_projections import (
            ProjectionCache,
            ProjectionIdentity,
            ProjectionState,
        )

        from market_storefront.services import site_projection_cache as spc

        resource_pools_cache: ProjectionCache = ProjectionCache(client=None)
        resource_pools_cache._value = [
            {"resource_pool_id": "gpu-pool", "resources": []}
        ]
        resource_pools_cache._state = ProjectionState.loaded
        resource_pools_cache._identity = ProjectionIdentity(revision=1, digest="abc")
        caches = spc.SiteProjectionCaches(
            resource_pools=resource_pools_cache,
            capacity_buckets=ProjectionCache(client=None),
        )

        received: dict = {}
        repository = SimpleNamespace(db_path="/tmp/x.db")

        async def fake_close(
            db_path,
            *,
            sqlite_client,
            home_site=None,
            configured_site_count=0,
            member_availability=None,
            site_pool_projection=None,
            site_capacity_buckets=None,
        ):
            assert sqlite_client is repository
            received["site_pool_projection"] = site_pool_projection
            received["site_capacity_buckets"] = site_capacity_buckets
            return []

        async def fake_reopen(
            db_path,
            *,
            sqlite_client,
            home_site=None,
            member_availability=None,
            site_pool_projection=None,
            site_capacity_buckets=None,
        ):
            assert sqlite_client is repository
            return []

        reconcile = cc._capacity_reconciler(lambda: repository)
        with (
            patch.dict(spc._caches, {"default": caches}, clear=True),
            settings_overrides(**{"capacity.use_site_projection_for_listings": False}),
            patch(
                "market_storefront.services.publication_service."
                "close_stale_compute_listings_after_capacity_change",
                fake_close,
            ),
            patch(
                "market_storefront.services.publication_service."
                "reopen_available_compute_listings_after_capacity_change",
                fake_reopen,
            ),
        ):
            await reconcile(
                CapacityReconcileContext(
                    projections=(CapacityProjection("default", ()),),
                    availability={},
                    delta=CapacityDelta(kind="reserved", version=1),
                )
            )

        assert received["site_pool_projection"] is None
        assert received["site_capacity_buckets"] is None
