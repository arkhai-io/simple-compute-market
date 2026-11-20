"""An API-credit storefront reads again a registry it could not read.

This storefront composes a listing's settlement options when the listing is
created, so that is where it reads again a registry whose recommended dispute
authorities it could not read. The real app and lifespan compose the storefront
from configuration, as ``test_alkahest_release_conditions`` does, with Arkhai
payments beside Alkahest and no local dispute entry: the payments option relies
on the registry's recommendation alone. The registry is a double standing
where ``MultiRegistryClient`` wraps it, whose descriptor read fails until the
test gives it the registry's descriptor.

Every account, key and address here is a deterministic development value; none
may be used on a public network.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from market_core import RegistryDescriptor
from market_identity import Ed25519Signer
from storefront_client.client import StorefrontClientError

from apicredits_storefront import container

from tests.integration.credit_negotiation import PAYEE_ACCOUNT, payment_authority
from tests.integration.test_alkahest_release_conditions import (  # noqa: F401
    _replaced,
    _settlement,
    _started,
    # The started storefront's configuration and database, as a fixture.
    storefront,
)

pytestmark = pytest.mark.asyncio

_PAYMENTS = "arkhai.payments.v1"
_PAYMENTS_SERVICE = Ed25519Signer(bytes(range(1, 33)))
_REGISTRY_SIGNER = Ed25519Signer(b"\x5c" * 32)
# A reserved name that resolves nowhere; the double stands where its client would.
_REGISTRY_URL = "http://registry.invalid"
_CLAUSE = {
    "mechanism": _PAYMENTS,
    "asset": "USD/6",
    "rate": "1000",
    "per": "token",
    "mechanism_input": {
        "payee_account": PAYEE_ACCOUNT,
        "asset": "USD/6",
        "window": "P7D",
        "dispute_window_seconds": 1296000,
    },
}


def _payments_settlement() -> dict:
    return {
        **_settlement(),
        "priority": ["alkahest.v1", _PAYMENTS],
        "arkhai_payments": {
            "enabled": True,
            "service_url": "http://127.0.0.1:9",
            "service_identity": _PAYMENTS_SERVICE.identity.model_dump(mode="json"),
            "fee_bps": 250,
            "development_auth": True,
        },
    }


def _descriptor(url: str) -> RegistryDescriptor:
    """The registry's descriptor, as its client returns it once verified,
    recommending the payments authority."""
    return RegistryDescriptor.model_validate({
        "access": {"posture": "public"},
        "authority": {
            "name": "registry",
            "principals": [_REGISTRY_SIGNER.identity.model_dump(mode="json")],
        },
        "baseUrl": url,
        "displayName": "Test Registry",
        "operatorIdentity": "Test Operator",
        "schema": {"id": "api_credits.market", "version": "1"},
        "recommendedDisputeAuthorities": [payment_authority()],
    })


class _Registry:
    """The configured registries' client: each descriptor read returns what
    ``descriptors`` holds, ``None`` for a read that fails; ``descriptor_reads``
    records the registries each read selected. Every publication it is sent
    succeeds; the create's result is read from the storefront itself."""

    def __init__(self, urls: list[str]) -> None:
        self.urls = urls
        self.descriptors: dict[str, RegistryDescriptor | None] = {url: None for url in urls}
        self.descriptor_reads: list[list[str]] = []

    def __call__(self, *_args, **_kwargs) -> "_Registry":
        return self

    async def __aenter__(self) -> "_Registry":
        return self

    async def __aexit__(self, *_exc) -> bool:
        return False

    async def get_descriptors(self, registries=None):
        selected = [url for url in self.urls if registries is None or url in registries]
        self.descriptor_reads.append(selected)
        return {url: self.descriptors[url] for url in selected}

    async def publish_listing_per_registry(self, *, payloads):
        return [{"registry_url": url, "success": True, "response": {"ok": True}}
                for url in payloads]


def _request() -> dict:
    return {
        "resource_id": "svc-quota",
        "service_name": "Acme Inference",
        "settlement_clauses": [dict(_CLAUSE)],
    }


async def test_a_storefront_that_started_before_its_registry_offers_payments_once_it_answers(
    storefront,
):
    """Spec scenario "A storefront starts before its registry": the first
    create after the registry answers reads it and publishes the payments
    option its authority allows, with no restart."""
    urls = [_REGISTRY_URL]
    registry = _Registry(urls)
    # The storefront reads its registries only while it publishes to them.
    with patch.object(container, "MultiRegistryClient", registry), _replaced(
        enable_registry_discovery=True,
        registry={
            "urls": urls,
            "authorities": {_REGISTRY_URL: {
                "authority": "registry",
                "identities": [_REGISTRY_SIGNER.identity.model_dump(mode="json")],
            }},
            "discovery_timeout": 1.0,
            "auth": {},
        },
    ):
        async with _started(_payments_settlement()) as (listings, public, admin):
            with pytest.raises(StorefrontClientError) as refused:
                await listings.publish_from_quota(_request())
            status = await admin.get_system_status()

            for url in urls:
                registry.descriptors[url] = _descriptor(url)
            created = await listings.publish_from_quota(_request())
            listing = await public.get_listing(created.listing_id)

    # Unread, the payments clause composes no option, so the create is refused.
    assert refused.value.status_code == 400
    (payments,) = [item for item in status.settlement if item["mechanism"] == _PAYMENTS]
    assert payments["ready"] is True and payments["blockers"] == []
    assert [entry["registry"] for entry in
            payments["public_details"]["dispute_authorities_unread"]] == urls
    assert created.status == "created"
    (option,) = listing.extra["settlement_options"]
    assert option["settlement"]["schema"] == _PAYMENTS
    assert option["lifecycle"]["adjudication"]["dispute"]["account"] == (
        payment_authority()["account"]
    )
    # Startup's read, the refused create's, and the create after the answer.
    assert registry.descriptor_reads == [urls] * 3
