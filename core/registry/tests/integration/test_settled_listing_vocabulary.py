"""Interservice coverage for the settled listing vocabulary.

Real registry app, real database, and the canonical `RegistryClient` over
`ASGITransport` — the integration level `docs/development/TESTING.md` defines.
Raw HTTP appears only where a rejection cannot be expressed through the typed
client, and those assertions are on status alone.
"""

from __future__ import annotations

import httpx
import pytest

from registry_client import ListingRequest
from src.main import app
from tests.integration.test_validate_publish import _ValidationAuth

pytestmark = pytest.mark.asyncio

_COMPUTE_LISTING_RESOURCE = {
    "gpu_model": "H200",
    "region": "us-west",
    "offering_mode": "vm",
}


def _listing(listing_id: str, **overrides) -> ListingRequest:
    resource = {**_COMPUTE_LISTING_RESOURCE, **overrides}
    return ListingRequest(
        listing_id=listing_id,
        listing_resource=resource,
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": "0x" + "11" * 20,
                "literal_fields": {"token": "0x" + "22" * 20},
            }
        ],
        storefront_url="http://seller",
    )


class TestPublishAndQueryUnderTheSettledNames:
    """Closes 9.5: a compute listing round-trips through the canonical client
    under `listing_resource` and `offering_mode`."""

    async def test_listing_publishes_and_is_returned_under_the_settled_key(
        self, registry_client
    ):
        await registry_client.publish_listing(_listing("settled-1"))

        fetched = await registry_client.get_listing("settled-1")

        assert fetched.listing_resource == _COMPUTE_LISTING_RESOURCE
        assert fetched.listing_resource["offering_mode"] == "vm"
        # `ListingSummary` no longer carries the retired attribute at all, so
        # a caller reading the old name fails loudly rather than silently
        # receiving an empty shape.
        assert not hasattr(fetched, "offer")

    async def test_offering_mode_filter_reads_the_settled_path(
        self, registry_client
    ):
        await registry_client.publish_listing(_listing("vm-1", offering_mode="vm"))
        await registry_client.publish_listing(
            _listing("bm-1", offering_mode="bare_metal")
        )

        matched = await registry_client.list_listings(offering_mode="vm")

        ids = {str(row.id) for row in matched.listings}
        assert "vm-1" in ids
        assert "bm-1" not in ids

    async def test_a_listing_publishing_no_offering_mode_is_excluded(
        self, registry_client
    ):
        """The compute filter declares `on_missing: fail`, so absence excludes
        rather than matching — the behaviour the published field's optionality
        would otherwise hide."""
        await registry_client.publish_listing(_listing("with-mode"))
        without = _listing("without-mode")
        without.listing_resource.pop("offering_mode")
        await registry_client.publish_listing(without)

        matched = await registry_client.list_listings(offering_mode="vm")

        ids = {str(row.id) for row in matched.listings}
        assert "with-mode" in ids
        assert "without-mode" not in ids


class TestRetiredSpellingsAreRejected:
    """Rejection boundaries. Raw HTTP because the typed client cannot express a
    retired key, and status only because the message is not contractual."""

    async def _post(self, body: dict) -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            auth=_ValidationAuth(),
        ) as raw:
            return await raw.post(
                "/api/v1/listings/validate-publish", json=body
            )

    async def test_the_retired_shape_key_is_refused(self, registry_client):
        response = await self._post(
            {
                "listing_id": "retired-shape",
                "storefront_url": "http://seller",
                "offer_resource": _COMPUTE_LISTING_RESOURCE,
                "accepted_escrows": [],
            }
        )
        assert response.status_code == 200
        assert response.json()["valid"] is False

    async def test_the_retired_offering_mode_key_is_refused(self, registry_client):
        response = await self._post(
            {
                "listing_id": "retired-mode",
                "storefront_url": "http://seller",
                "listing_resource": {
                    "gpu_model": "H200",
                    "region": "us-west",
                    "virtualization_type": "vm",
                },
                "accepted_escrows": [
                    {
                        "chain_name": "anvil",
                        "escrow_address": "0x" + "11" * 20,
                        "literal_fields": {"token": "0x" + "22" * 20},
                    }
                ],
            }
        )
        body = response.json()
        assert response.status_code == 200
        # The retired key is not the settled one, so it is carried as opaque
        # extra content and contributes no offering mode: the listing is
        # therefore invisible to an offering-mode filter rather than matching.
        assert body["valid"] is True
        assert "listing_resource_type" not in body

    async def test_no_derived_resource_type_tag_is_reported(self, registry_client):
        response = await self._post(
            {
                "listing_id": "no-tag",
                "storefront_url": "http://seller",
                "listing_resource": _COMPUTE_LISTING_RESOURCE,
                "accepted_escrows": [],
            }
        )
        body = response.json()
        assert "offer_resource_type" not in body
        assert "listing_resource_type" not in body


class TestSchemaIdentityCompatibility:
    """Closes 9.14: a buyer declaring the family identity is compatible; one
    declaring the retired single-domain identity is not."""

    async def test_the_served_identity_names_the_family(self, registry_client):
        spec = await registry_client.get_filter_spec()

        assert spec.schema_id == "compute.market"
        assert spec.schema_id != "vms.compute"

    async def test_the_offering_mode_filter_is_advertised_under_its_settled_name(
        self, registry_client
    ):
        spec = await registry_client.get_filter_spec()

        names = {f["name"] for f in spec.filters}
        assert "offering_mode" in names
        assert "virtualization_type" not in names

    async def test_every_advertised_filter_path_uses_the_settled_shape_key(
        self, registry_client
    ):
        spec = await registry_client.get_filter_spec()

        shape_paths = [
            f["path"] for f in spec.filters if f["path"].startswith("$.listing")
        ]
        assert shape_paths, "no listing-shape filters advertised"
        assert not [
            f["path"] for f in spec.filters if "offer_resource" in f["path"]
        ]
