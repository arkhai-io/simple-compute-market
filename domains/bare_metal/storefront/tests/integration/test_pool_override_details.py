"""A pool override's seller details through the bare-metal storefront app.

Application integration: the running app over a runtime whose every cycle is
composed as production composes it, under the configured Alkahest settlement
(``test_http_system._derivation_runtime``); the site and the registry are the
in-process doubles the cycle tests use, standing where this codebase wraps those
services. Each override is written through the typed pool-override client, each
cycle is the administrator's ``publication`` step, and the listing is read back
through the storefront client.
"""

from __future__ import annotations

import pytest
from market_pool_overrides import PoolOverrideClient

from test_http_publication_rates import SITE, _listing_id, _Sites
from test_http_system import _admin_client, _app, _derivation_runtime
from test_publication_cycle import Site, member, pool

pytestmark = pytest.mark.asyncio

DETAILS = {
    "title": "A whole H100 machine",
    "description": "Dedicated host; no oversubscription.",
    "metadata": {"acme.tier": "gold", "nvlink": True, "max_jobs": 4},
}
DETAIL_FIELDS = ("title", "description", "metadata")


def _details_of(listing) -> dict:
    return {field: getattr(listing, field) for field in DETAIL_FIELDS}


def _refreshed_fields(report: dict) -> list[list[str]]:
    return [sorted(item["fields"]) for item in report["actions"] if item["action"] == "refresh"]


async def test_an_overrides_details_publish_refresh_in_place_and_clear_when_withdrawn(
    tmp_path, monkeypatch,
):
    """Spec scenario "A pool override states details": the listing publishes the
    override's details, a change to them refreshes that listing in place, and an
    override that stops stating them republishes it with no detail key, and the
    listing carries none. Every version of the override keeps one lease maximum,
    since an override must state something."""
    site = Site(pool("pool-1", member("r1", "pool-1")))
    runtime = _derivation_runtime(
        tmp_path, monkeypatch, {SITE: site}, capacity_client=_Sites(site)
    )
    sent = runtime.registry_configuration.recording.sent
    changed_details = {**DETAILS, "title": "A whole H100 machine, now with NVMe"}

    async def state(details: dict | None) -> dict:
        terms: dict = {"max_duration_seconds": 3600}
        if details is not None:
            terms["details"] = details
        await PoolOverrideClient(admin).put_pool_override(
            {"site_id": SITE, "pool_id": "pool-1", "offering_mode": "bare_metal",
             "terms": terms}
        )
        sent.clear()
        return await admin.admin_run_lifecycle_cycle("publication")

    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with _admin_client(app) as admin:
            listing_id = _listing_id(await state(DETAILS))
            added = list(sent)
            stated = await admin.get_listing(listing_id)

            changed = await state(changed_details)
            changed_sent = list(sent)
            refreshed = await admin.get_listing(listing_id)

            withdrawn = await state(None)
            withdrawn_sent = list(sent)
            cleared = await admin.get_listing(listing_id)

    assert [(operation, listing) for operation, _, listing, _ in added] == [
        ("publish", listing_id)
    ]
    assert {field: added[0][3][field] for field in DETAIL_FIELDS} == DETAILS
    assert _details_of(stated) == DETAILS

    assert _refreshed_fields(changed) == [["listing.title"]]
    assert [(operation, listing) for operation, _, listing, _ in changed_sent] == [
        ("publish", listing_id)
    ]
    assert {field: changed_sent[0][3][field] for field in DETAIL_FIELDS} == changed_details
    assert _details_of(refreshed) == changed_details

    assert _refreshed_fields(withdrawn) == [sorted(f"listing.{field}" for field in DETAIL_FIELDS)]
    assert [(operation, listing) for operation, _, listing, _ in withdrawn_sent] == [
        ("publish", listing_id)
    ]
    assert not set(DETAIL_FIELDS) & set(withdrawn_sent[0][3])
    assert _details_of(cleared) == dict.fromkeys(DETAIL_FIELDS)
    assert [listing.status for listing in (stated, refreshed, cleared)] == ["open"] * 3
