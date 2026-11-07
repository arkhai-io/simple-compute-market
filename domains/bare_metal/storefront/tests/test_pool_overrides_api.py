"""Bare-metal pool overrides through the kit's typed client against the app.

The app is the real bare-metal storefront over a real database and its held
projection state; each site is the projection double the opening guard tests
use, behind the runtime's per-site client seam (the write's live check) and
under the state (what status reads), which startup loads with its first poll.
The loops start held, so publication runs only when a test steps it.
"""

from __future__ import annotations

import contextlib
import dataclasses

import httpx
import pytest
from market_identity import TrustedIdentitySet
from market_pool_overrides import PoolOverrideClient, pool_override_statuses
from storefront_client import StorefrontClient
from storefront_client.client import StorefrontClientError

from arkhai_bare_metal_storefront.lifecycle_steps import PublicationWake
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from held_loops import held_loop_controller
from source_sites import SourceSite, listing_source_projection, source_projections
from test_http_system import ADMIN_SIGNER, SELLER_SIGNER, _app, _runtime

pytestmark = pytest.mark.asyncio

SITE = "site-a"
POOL = "pool-a"
RATE = {"shape": {"gpu": {"count": 8, "model": "H100"}}, "amount": "12.50",
        "asset": "usd", "period": "hour"}


class _Sites:
    def __init__(self, sites: dict[str, SourceSite]) -> None:
        self._sites = sites

    def site(self, site_id: str) -> SourceSite:
        return self._sites[site_id]


def _record(**fields) -> dict:
    return {"site_id": SITE, "pool_id": POOL, "offering_mode": "bare_metal", **fields}


@contextlib.asynccontextmanager
async def _admin(runtime):
    """An administrator client against a running app over ``runtime``."""
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller",
            signer=ADMIN_SIGNER,
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
            transport=httpx.ASGITransport(app=app),
        ) as admin:
            yield admin


class _CountingWake(PublicationWake):
    """The runtime's publication wake, counting each time it is set."""

    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def __call__(self) -> None:
        self.count += 1
        super().__call__()


def _with_sites(runtime, *site_ids: str, sites: dict[str, SourceSite] | None = None):
    """``runtime`` configured for ``site_ids``, each served by a ``SourceSite``.

    The same double answers the write's live check and the held state's polls.
    """
    served = sites if sites is not None else {site_id: SourceSite() for site_id in site_ids}
    wake = _CountingWake()
    return dataclasses.replace(
        runtime,
        site_bindings=tuple(
            BareMetalSiteBinding(
                site_id=site_id,
                service_peer=f"{site_id}-peer",
                authority_url=f"http://{site_id}",
            )
            for site_id in site_ids
        ),
        capacity_client=_Sites(served),
        site_projections=(
            source_projections(*served.items(), on_resource_pool_change=wake)
            if served
            else None
        ),
        publication_wake=wake,
        loop_controller_factory=held_loop_controller,
    )


@pytest.fixture
async def world(tmp_path):
    runtime = _with_sites(_runtime(str(tmp_path / "storefront.db")), SITE)
    async with _admin(runtime) as admin:
        yield runtime, admin


async def _refused(call) -> StorefrontClientError:
    with pytest.raises(StorefrontClientError) as caught:
        await call
    return caught.value


async def _states(admin) -> dict:
    statuses = pool_override_statuses(await admin.get_system_status()) or []
    return {(o["site_id"], o["pool_id"]): o["state"] for o in statuses}


async def test_replace_read_list_and_delete(world):
    _, admin = world
    overrides = PoolOverrideClient(admin)
    terms = {"min_duration_seconds": 3600, "max_duration_seconds": 86400}

    written = await overrides.put_pool_override(_record(terms=terms, asking_rates=[RATE]))
    read = await overrides.get_pool_override(SITE, POOL, "bare_metal")
    listed = await overrides.list_pool_overrides(site_id=SITE)
    deleted = await overrides.delete_pool_override(SITE, POOL, "bare_metal")

    assert written.override.terms == terms
    assert written.feasibility == []
    assert read.asking_rates == [RATE]
    assert [item.pool_id for item in listed.overrides] == [POOL]
    assert deleted.deleted is True
    assert (await overrides.list_pool_overrides()).overrides == []


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(_record(listing_shapes=[{"gpu": {"count": 1, "model": "H100"}}]),
                     id="shapes"),
        pytest.param(_record(terms={"sla": 99.0}), id="an unknown term"),
        pytest.param(_record(terms={"min_duration_seconds": 10, "max_duration_seconds": 5}),
                     id="bounds out of order"),
        pytest.param(_record(asking_rates=[{**RATE, "period": "month"}]),
                     id="a rate this version cannot read"),
        pytest.param(_record(site_id="site-zz", terms={"max_duration_seconds": 60}),
                     id="an unconfigured site"),
    ],
)
async def test_a_write_outside_the_vocabulary_is_refused_and_stores_nothing(world, record):
    _, admin = world
    overrides = PoolOverrideClient(admin)

    refusal = await _refused(overrides.put_pool_override(record))

    assert refusal.status_code == 422
    assert (await overrides.list_pool_overrides()).overrides == []


async def test_a_pool_the_live_site_lacks_is_refused(world):
    _, admin = world
    refusal = await _refused(
        PoolOverrideClient(admin).put_pool_override(
            _record(pool_id="pool-zz", terms={"max_duration_seconds": 60})
        )
    )
    assert refusal.status_code == 404


async def test_status_follows_the_held_projection_of_the_overrides_site(tmp_path):
    """Applied while the held generation projects the pool, orphaned once a
    poll holds one that does not, and unconfigured without the site. Spec
    scenario "Status while a site's projection is held"."""
    site = SourceSite()
    runtime = _with_sites(_runtime(str(tmp_path / "storefront.db")), SITE, sites={SITE: site})
    async with _admin(runtime) as admin:
        await PoolOverrideClient(admin).put_pool_override(
            _record(terms={"max_duration_seconds": 60})
        )
        applied = await _states(admin)

        site.projection = listing_source_projection(pool_id="pool-b")
        await admin.admin_run_lifecycle_cycle("site-projections")
        orphaned = await _states(admin)

    # The same database under a storefront no longer configured for the site.
    async with _admin(_with_sites(runtime)) as without_site:
        unconfigured = await _states(without_site)

    assert applied == {(SITE, POOL): "applied"}
    assert orphaned == {(SITE, POOL): "orphaned"}
    assert unconfigured == {(SITE, POOL): "site_unconfigured"}


async def test_status_is_unknown_until_a_poll_holds_the_site(tmp_path):
    """After a restart while the site cannot be reached, the storefront holds
    no generation of it, so its override is unknown, never judged against pools
    nobody has read; once the site answers a poll, it is applied. Spec scenario
    "Status before the first run"."""
    site = SourceSite()
    runtime = _with_sites(_runtime(str(tmp_path / "storefront.db")), SITE, sites={SITE: site})
    async with _admin(runtime) as admin:
        await PoolOverrideClient(admin).put_pool_override(
            _record(terms={"max_duration_seconds": 60})
        )

    site.error = ConnectionError("site unreachable")
    async with _admin(_with_sites(runtime, SITE, sites={SITE: site})) as restarted:
        unknown = await _states(restarted)
        site.error = None
        await restarted.admin_run_lifecycle_cycle("site-projections")
        applied = await _states(restarted)

    assert unknown == {(SITE, POOL): "unknown"}
    assert applied == {(SITE, POOL): "applied"}


async def test_an_accepted_write_refreshes_the_site_and_wakes_publication(tmp_path):
    """The write's live check sees the site's new generation; once it is
    stored, the storefront's held projection of the site is refreshed to it and
    the publication loop is woken. Spec scenario "A bare-metal override is
    accepted between runs"."""
    site = SourceSite()
    runtime = _with_sites(_runtime(str(tmp_path / "storefront.db")), SITE, sites={SITE: site})
    async with _admin(runtime) as admin:
        before = (await admin.get_system_status()).site_projections[SITE]
        woken = runtime.publication_wake.count
        site.projection = {**listing_source_projection(), "revision": 2}

        await PoolOverrideClient(admin).put_pool_override(
            _record(terms={"max_duration_seconds": 60})
        )
        after = (await admin.get_system_status()).site_projections[SITE]

    assert before["resource_pool"]["revision"] == 1
    assert after["resource_pool"]["revision"] == 2
    assert after["resource_pool"]["state"] == "loaded"
    assert runtime.publication_wake.count == woken + 1


async def test_a_refused_write_refreshes_nothing_and_wakes_nothing(world):
    runtime, admin = world
    calls = runtime.capacity_client.site(SITE).calls
    woken = runtime.publication_wake.count

    await _refused(
        PoolOverrideClient(admin).put_pool_override(
            _record(pool_id="pool-zz", terms={"max_duration_seconds": 60})
        )
    )

    # One live check, and no refresh after it.
    assert runtime.capacity_client.site(SITE).calls == calls + 1
    assert runtime.publication_wake.count == woken


async def test_a_signed_caller_who_is_not_an_administrator_is_refused(tmp_path):
    runtime = _with_sites(_runtime(str(tmp_path / "storefront.db")), SITE)
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller",
            signer=SELLER_SIGNER,
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
            transport=httpx.ASGITransport(app=app),
        ) as stranger:
            refusal = await _refused(PoolOverrideClient(stranger).list_pool_overrides())
    assert refusal.status_code in (401, 403)


async def test_a_minimum_above_the_configured_maximum_is_refused(tmp_path):
    runtime = dataclasses.replace(
        _with_sites(_runtime(str(tmp_path / "storefront.db")), SITE),
        default_max_duration_seconds=3600,
    )
    async with _admin(runtime) as admin:
        overrides = PoolOverrideClient(admin)
        refusal = await _refused(
            overrides.put_pool_override(_record(terms={"min_duration_seconds": 7200}))
        )
        raised = await overrides.put_pool_override(
            _record(terms={"min_duration_seconds": 7200, "max_duration_seconds": 10800})
        )

    assert refusal.status_code == 422
    assert "effective maximum 3600" in str(refusal)
    assert raised.override.terms["max_duration_seconds"] == 10800


