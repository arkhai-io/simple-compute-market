"""Asking rates through the bare-metal storefront app and its typed clients.

The real app, database, held projection state, and composition run, the loops
held from the start; publication is the administrator's step route, after a
``site-projections`` step wherever the site changed. Each site and the registry
are the in-process doubles the cycle tests use, standing where this codebase
wraps those services. A declared rate
and a storefront override are each read back as the published listing a buyer
fetches, and each refreshes the same listing in place.
"""

from __future__ import annotations

import contextlib
import dataclasses
from pathlib import Path

import httpx
import pytest
import yaml
from core_storefront.publication_runner import PublicationPayload
from jsonschema import Draft202012Validator
from market_core.schemas import derive_settlement_option_id
from market_identity import TrustedIdentitySet
from market_pool_overrides import PoolOverrideClient
from storefront_client import StorefrontClient

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.publication import BareMetalPublicationCycle
from arkhai_bare_metal_storefront.server import build_bare_metal_storefront_registry
from arkhai_bare_metal_storefront.site_clients import BareMetalSiteBinding
from held_loops import held_loop_controller
from test_http_system import ADMIN_SIGNER, SELLER_SIGNER, _app, _runtime
from test_publication_cycle import (
    REGISTRY_URL,
    RecordingRegistries,
    Site,
    projections_over,
    Terms,
    _priced,
    _rate,
)

pytestmark = pytest.mark.asyncio

SITE = "site-a"


class _Sites:
    def __init__(self, site: Site) -> None:
        self._site = site

    def site(self, site_id: str) -> Site:
        assert site_id == SITE
        return self._site


@contextlib.asynccontextmanager
async def _storefront(
    tmp_path,
    site: Site,
    *,
    default_max_duration_seconds: int | None = 3600,
    registries: RecordingRegistries | None = None,
    build_payload: Terms | None = None,
):
    """The running app over ``site``, its database under ``tmp_path``.

    ``default_max_duration_seconds`` is the configured
    ``[pricing].default_max_duration_seconds``; the runtime reads it when it is
    composed, so a configuration change is a second storefront over the same
    database, as a restart is. ``registries`` records what the registry is
    sent, for a test that reads it; ``build_payload`` stands for the configured
    settlement terms.
    """
    registries = registries if registries is not None else RecordingRegistries()
    terms = build_payload if build_payload is not None else Terms()

    def cycle(runtime):
        return BareMetalPublicationCycle(
            sqlite_client=runtime.db,
            registry=build_bare_metal_storefront_registry(domain=get_market_domain_contract()),
            site_projections=runtime.site_projections,
            site_ids=[SITE],
            registry_client_factory=registries,
            registry_urls=(REGISTRY_URL,),
            storefront_url=runtime.storefront_url,
            seller_principal=runtime.seller_principal,
            build_payload=terms,
            default_max_duration_seconds=runtime.default_max_duration_seconds,
        )

    runtime = dataclasses.replace(
        _runtime(str(tmp_path / "storefront.db")),
        site_bindings=(
            BareMetalSiteBinding(
                site_id=SITE,
                service_peer=f"{SITE}-peer",
                authority_url="http://site-a",
            ),
        ),
        capacity_client=_Sites(site),
        # The storefront's held projection of the site, which startup loads.
        site_projections=projections_over({SITE: site}),
        loop_controller_factory=held_loop_controller,
        publication_cycle_factory=cycle,
        default_max_duration_seconds=default_max_duration_seconds,
    )
    app = _app(runtime)
    async with app.router.lifespan_context(app):
        async with StorefrontClient(
            "http://seller",
            signer=ADMIN_SIGNER,
            caller_role="admin",
            expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
            transport=httpx.ASGITransport(app=app),
        ) as admin, StorefrontClient(
            "http://seller", transport=httpx.ASGITransport(app=app)
        ) as public:
            yield admin, public


def _listing_id(report: dict) -> str:
    (published,) = [item for item in report["actions"] if item["action"] == "publish"]
    return str(published["listing_id"])


async def test_a_declared_rate_and_an_override_reach_the_listing_a_buyer_reads(tmp_path):
    site = Site(_priced(_rate("12.50")))
    async with _storefront(tmp_path, site) as (admin, public):
        listing_id = _listing_id(await admin.admin_run_lifecycle_cycle("publication"))
        declared = await public.get_listing(listing_id)

        await PoolOverrideClient(admin).put_pool_override(
            {"site_id": SITE, "pool_id": "pool-1", "offering_mode": "bare_metal",
             "asking_rates": [_rate("9.00")]}
        )
        await admin.admin_run_lifecycle_cycle("publication")
        overridden = await public.get_listing(listing_id)

        await PoolOverrideClient(admin).put_pool_override(
            {"site_id": SITE, "pool_id": "pool-1", "offering_mode": "bare_metal",
             "asking_rates": []}
        )
        await admin.admin_run_lifecycle_cycle("publication")
        withheld = await public.get_listing(listing_id)

    assert declared.listing_resource["asking_rate"] == {
        "amount": "12.50", "asset": "usd", "period": "hour",
    }
    assert overridden.listing_resource["asking_rate"]["amount"] == "9.00"
    assert "asking_rate" not in withheld.listing_resource
    assert withheld.status == "open"


#: The compute registry's own listing schema, which a bare-metal registry
#: serves and validates a publication against.
_COMPUTE_SPEC = (
    Path(__file__).resolve().parents[4] / "core/registry/src/core_registry/filter-spec.yaml"
)


def _compute_schema_errors(body: dict) -> list[str]:
    shape = yaml.safe_load(_COMPUTE_SPEC.read_text())["listing_shape"]
    return [
        f"{list(error.absolute_path)}: {error.message}"
        for error in Draft202012Validator(shape).iter_errors(body)
    ]


_OPTION_SETTLEMENT = {"schema": "arkhai.payments.v1"}


class _OneOptionTerms(Terms):
    """Configured terms publishing one rateless settlement option, standing for
    a composed mechanism: the compute schema admits no listing that offers
    neither an option nor an escrow, and the option's content is the
    mechanism's, not this domain's."""

    async def __call__(self, candidate: dict) -> PublicationPayload:
        option = {
            "option_id": derive_settlement_option_id(settlement=_OPTION_SETTLEMENT),
            "settlement": dict(_OPTION_SETTLEMENT),
        }
        return PublicationPayload(
            settlement_options=(option,), max_duration_seconds=self.max_duration_seconds
        )


async def test_every_publication_path_sends_a_document_the_compute_registry_admits(tmp_path):
    """A priced machine's first publication, which the registry refuses, and the
    repair the next step makes through the domain's publication candidate each
    send a document the compute registry's schema admits, the asking rate in
    its ``pricing`` and not in the machine's description, while the listing a
    buyer reads from the storefront keeps the rate beside the shape."""
    registries = RecordingRegistries()
    registries.failing = {("publish", REGISTRY_URL)}
    site = Site(_priced(_rate("12.50")))
    async with _storefront(
        tmp_path, site, registries=registries, build_payload=_OneOptionTerms()
    ) as (admin, public):
        listing_id = _listing_id(await admin.admin_run_lifecycle_cycle("publication"))
        # The refused first publication, then the cycle's own convergence retry.
        refused = [body for operation, _, _, body in registries.sent if operation == "publish"]
        registries.failing.clear()
        registries.sent.clear()
        repaired = await admin.admin_run_lifecycle_cycle("publication")
        (repair,) = [body for operation, _, _, body in registries.sent if operation == "publish"]
        local = await public.get_listing(listing_id)

    assert [item["listing_id"] for item in repaired["actions"] if item["action"] == "converge"] == [
        listing_id
    ]
    first = refused[0]
    for body in (*refused, repair):
        assert _compute_schema_errors(body) == []
        assert body["pricing"] == {
            "asking_rate": {"amount": "12.50", "asset": "usd", "period": "hour"},
        }
        assert "asking_rate" not in body["listing_resource"]
        assert body == first
    assert local.listing_resource["asking_rate"]["amount"] == "12.50"


def _holds(report: dict) -> set[str]:
    return {item["reason"] for item in report["actions"] if item["action"] == "hold"}


async def test_an_unreadable_rate_holds_the_listing_a_buyer_reads(tmp_path):
    """Fail closed through the running app: the step reports the hold, and the
    buyer still reads the listing as it was last published."""
    site = Site(_priced(_rate("12.50")))
    async with _storefront(tmp_path, site) as (admin, public):
        listing_id = _listing_id(await admin.admin_run_lifecycle_cycle("publication"))

        site.serve(_priced({**_rate("11.00"), "period": "month"}))
        await admin.admin_run_lifecycle_cycle("site-projections")
        report = await admin.admin_run_lifecycle_cycle("publication")
        held = await public.get_listing(listing_id)

    assert _holds(report) == {"asking_rates_unreadable"}
    assert held.status == "open"
    assert held.listing_resource["asking_rate"]["amount"] == "12.50"


async def test_a_bound_conflict_after_the_write_holds_rather_than_fails(tmp_path):
    """An override minimum accepted under one configured maximum; the storefront
    then restarts with a configured maximum below it. The next step holds the
    pool instead of publishing an unordered pair or failing the run."""
    site = Site(_priced(_rate("12.50")))
    async with _storefront(tmp_path, site, default_max_duration_seconds=10800) as (admin, _):
        listing_id = _listing_id(await admin.admin_run_lifecycle_cycle("publication"))
        await PoolOverrideClient(admin).put_pool_override(
            {"site_id": SITE, "pool_id": "pool-1", "offering_mode": "bare_metal",
             "terms": {"min_duration_seconds": 7200}}
        )

    async with _storefront(tmp_path, site, default_max_duration_seconds=3600) as (
        admin,
        public,
    ):
        report = await admin.admin_run_lifecycle_cycle("publication")
        held = await public.get_listing(listing_id)

    assert _holds(report) == {"pool_override_terms_conflict"}
    assert held.status == "open"
    assert "min_duration_seconds" not in held.listing_resource


async def test_a_pool_resolving_no_lease_bound_is_held_through_the_running_app(tmp_path):
    """With no configured maximum, the step reports the pool held for its lease
    bound and publishes nothing for it; an override stating a maximum then lets
    the next step publish it. Spec scenario: "A bare-metal pool resolves no
    lease bound"."""
    site = Site(_priced(_rate("12.50")))
    async with _storefront(tmp_path, site, default_max_duration_seconds=None) as (
        admin,
        public,
    ):
        held = await admin.admin_run_lifecycle_cycle("publication")
        await PoolOverrideClient(admin).put_pool_override(
            {"site_id": SITE, "pool_id": "pool-1", "offering_mode": "bare_metal",
             "terms": {"max_duration_seconds": 7200}}
        )
        listing = await public.get_listing(
            _listing_id(await admin.admin_run_lifecycle_cycle("publication"))
        )

    assert _holds(held) == {"pool_lease_bound_missing"}
    assert [item for item in held["actions"] if item["action"] == "publish"] == []
    assert listing.status == "open"
