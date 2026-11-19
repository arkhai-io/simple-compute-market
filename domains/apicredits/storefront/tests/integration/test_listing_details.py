"""A quota-backed publish carries its seller's details to every registry.

The real app and lifespan compose the storefront from configuration, with the
seams ``test_alkahest_release_conditions`` supplies for what lies beyond it: the
quota site's capacity runtime, the startup tasks, and the chain's JSON-RPC
transport. The registries are replaced where ``MultiRegistryClient`` wraps them,
at ``_make_registry_client``: the publication service builds its client there,
and the composition root, which imports it by name, reads the registries'
dispute-authority recommendations through it at startup, so both bindings are
replaced. The double recommends no authority and records each publication as
the JSON the client would send. Every key, address, and principal here is a
deterministic development value, never used on a public network.
"""

from __future__ import annotations

import pytest
from market_identity import Ed25519Signer
from storefront_client.client import StorefrontClientError

import apicredits_storefront.container as container
import apicredits_storefront.server as server
from apicredits_storefront.listing_publication import PublishFromQuotaRequest
from apicredits_storefront.services import publication_service as publication_module
from tests._settings_overrides import settings_overrides
from tests.integration.test_alkahest_release_conditions import (  # noqa: F401  (fixture)
    SEED_LISTING,
    _replaced,
    _settlement,
    _started,
    _supplied_escrows,
    storefront,
)

REGISTRIES = ("https://registry-a.example", "https://registry-b.example")
# The registries' pinned signer; startup refuses discovery without a pin, and
# the recorded registries sign nothing.
REGISTRY_SIGNER = Ed25519Signer(b"\x55" * 32)
DETAILS = ("title", "description", "metadata")
TITLE = "Acme inference credits"
DESCRIPTION = "Tokens for Acme's hosted models, metered per request."
METADATA = {"acme.tier": "gold", "acme.region-count": 3, "acme.batch": True}


class _RecordingRegistries:
    """Stands where ``MultiRegistryClient`` wraps the configured registries.
    Each registry's descriptor reads as unavailable, as the client reports a
    registry it could not read, so none recommends a dispute authority; each
    accepts every publication, which is recorded per registry."""

    urls = REGISTRIES

    def __init__(self) -> None:
        self.published: dict[str, list[dict]] = {url: [] for url in REGISTRIES}
        self.descriptor_reads = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get_descriptors(self):
        self.descriptor_reads += 1
        return {url: None for url in REGISTRIES}

    async def publish_listing_per_registry(self, *, payloads):
        for url, request in payloads.items():
            self.published[url].append(request.to_dict())
        return [
            {"registry_url": url, "success": True, "response": {"ok": True}}
            for url in payloads
        ]

    async def update_listing_per_registry(self, *, listing_id, payloads):
        return [
            {"registry_url": url, "success": True, "response": {"ok": True}}
            for url in payloads
        ]


@pytest.fixture
def registries(storefront, monkeypatch):
    recorded = _RecordingRegistries()
    monkeypatch.setattr(publication_module, "_make_registry_client", lambda: recorded)
    monkeypatch.setattr(server, "_make_registry_client", lambda: recorded)
    with settings_overrides(
        enable_registry_discovery=True,
        registry__urls=list(REGISTRIES),
        registry__authorities={
            url: {
                "authority": f"registry-{index}",
                "identities": [REGISTRY_SIGNER.identity.model_dump(mode="json")],
            }
            for index, url in enumerate(REGISTRIES)
        },
    ):
        yield recorded


async def test_a_publish_stating_details_sends_them_beside_the_envelope_and_the_prose_inside_the_resource(
    registries,
):
    async with _started(_settlement()) as (listings, public, _admin):
        created = await listings.publish_from_quota(
            {
                **_supplied_escrows(),
                "title": TITLE,
                "description": DESCRIPTION,
                "metadata": METADATA,
            }
        )
        listing = await public.get_listing(created.listing_id)

    assert (created.status, created.registry_status) == ("created", "published")
    # Startup read the registries' recommendations from the double too.
    assert registries.descriptor_reads == 1
    assert (listing.title, listing.description, listing.metadata) == (
        TITLE,
        DESCRIPTION,
        METADATA,
    )
    for url in REGISTRIES:
        (body,) = registries.published[url]
        assert body["listing_id"] == created.listing_id
        assert (body["title"], body["description"], body["metadata"]) == (
            TITLE,
            DESCRIPTION,
            METADATA,
        )
        assert body["listing_resource"]["description"] == DESCRIPTION


async def test_a_publish_stating_none_sends_no_envelope_detail_key(registries):
    async with _started(_settlement()) as (listings, _public, _admin):
        created = await listings.publish_from_quota(_supplied_escrows())

    assert created.registry_status == "published"
    for url in REGISTRIES:
        (body,) = registries.published[url]
        assert set(DETAILS).isdisjoint(body)
        assert body["listing_resource"]["description"] is None


async def test_a_description_past_the_envelope_limit_is_refused_before_a_listing_exists(
    registries,
):
    # Rejection-path test: the typed client's request model refuses to build
    # this body, so it is constructed unvalidated and sent through the same
    # client, and only the status code is asserted. The description is far
    # past the limit, whose edges `market_core`'s own tests hold.
    overlong = PublishFromQuotaRequest.model_construct(
        **{
            **PublishFromQuotaRequest.model_validate(_supplied_escrows()).model_dump(),
            "description": "d" * 20_000,
        }
    )
    async with _started(_settlement()) as (listings, public, _admin):
        with pytest.raises(StorefrontClientError) as refused:
            await listings.publish_from_quota(overlong)
        remaining = await public.list_listings()

    assert refused.value.status_code == 422
    assert remaining.listings == []
    assert registries.published == {url: [] for url in REGISTRIES}


async def test_a_seed_description_past_the_envelope_limit_gives_the_seed_up_with_no_listing(
    registries,
):
    """The seed reaches the listing service without the route's request model,
    so the service holds the details to the envelope's limits itself: the seed
    gives up, and no listing is written or sent. Its quota registration, the
    boundary to the credits service, is replaced on the started storefront's
    seed."""
    registered = []

    async def register(**request):
        registered.append(request)

    with _replaced(seed={**SEED_LISTING, "description": "d" * 20_000}):
        async with _started(_settlement()) as (_listings, public, admin):
            container.resolved_listing_seed.register_quota = register
            with pytest.raises(StorefrontClientError):
                await admin.admin_run_lifecycle_cycle("listing-seed")
            given_up = await admin.admin_run_lifecycle_cycle("listing-seed")
            remaining = await public.list_listings()

    assert (given_up["state"], given_up["reason"]) == ("given_up", "ValidationError")
    assert remaining.listings == []
    assert registries.published == {url: [] for url in REGISTRIES}
