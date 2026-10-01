"""Bare-metal pool overrides through the kit's typed client against the app.

The app is the real bare-metal storefront over a real database; each site is the
projection double the opening guard tests use, behind the runtime's per-site
client seam. Override status is judged against the generations publication runs
record, so these tests record one exactly as a run does.
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

from arkhai_bare_metal_storefront.pool_overrides import record_accepted_generation
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from source_sites import SourceSite
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


def _with_sites(runtime, *site_ids: str):
    return dataclasses.replace(
        runtime,
        site_bindings=tuple(
            BareMetalSiteBinding(
                site_id=site_id,
                authority_principal=SELLER_SIGNER.identity,
                authority_url=f"http://{site_id}",
            )
            for site_id in site_ids
        ),
        capacity_client=_Sites({site_id: SourceSite() for site_id in site_ids}),
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


async def test_status_follows_the_generations_publication_accepted(world):
    runtime, admin = world
    overrides = PoolOverrideClient(admin)
    await overrides.put_pool_override(_record(terms={"max_duration_seconds": 60}))

    assert await _states(admin) == {(SITE, POOL): "unknown"}

    record_accepted_generation(
        runtime.db.db_path, site_id=SITE, revision=1, digest="d1", pool_ids=[POOL]
    )
    assert await _states(admin) == {(SITE, POOL): "applied"}

    record_accepted_generation(
        runtime.db.db_path, site_id=SITE, revision=2, digest="d2", pool_ids=["pool-b"]
    )
    assert await _states(admin) == {(SITE, POOL): "orphaned"}

    # The same database under a storefront no longer configured for the site.
    async with _admin(_with_sites(runtime)) as without_site:
        assert await _states(without_site) == {(SITE, POOL): "site_unconfigured"}


async def test_a_signed_caller_who_is_not_an_administrator_is_refused(world):
    runtime, _ = world
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
