"""The release conditions an API-credit listing advertises for Alkahest.

The real app and lifespan compose the storefront from configuration: its signer
from a development credential supplied as the Secret boundary supplies it, its
settlement composition, wallet, and chains, and the listing service the route
reaches. Two seams stand in for what lies beyond the storefront: the quota
site's capacity runtime, which the listing service resolves through the
container's ``QUOTA_CAPACITY``, and the startup tasks, which preflight the credits
service and start the timer loops. The anvil chain's address book is the
development chain's. Every address and key here is a deterministic development
value, never used on a public network.
"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

import httpx
import pytest
from market_alkahest import ALKAHEST_MECHANISM_ID, ReleaseModelError
from market_alkahest.alkahest import get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_config.config_loader import ChainConfig
from market_identity import Ed25519Signer, TrustedIdentitySet
from storefront_client import StorefrontClient

import apicredits_storefront.server as server
from apicredits_storefront import container
from apicredits_storefront.domain_runtime import get_market_domain_contract
from arkhai_api_selling.publish_route import ListingClient
from apicredits_storefront.utils import config as storefront_config
from tests.integration.test_publish_reconcile import _QuotaRuntime

SEED = b"\x22" * 32
SELLER_SIGNER = Ed25519Signer(SEED)
ADMIN_SIGNER = Ed25519Signer(b"\x44" * 32)
SELLER_WALLET = "0x" + "33" * 20
ESCROW = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": "0x" + "01" * 20},
    "rates": [{"field": "amount", "per": "token", "value": "100"}],
}
ANVIL = ChainConfig(
    name="anvil",
    rpc_url="http://anvil.test",
    chain_id=31337,
    alkahest_address_config_path=str(anvil_address_book_path()),
)


@contextmanager
def _replaced(**roots):
    """Replace whole settings roots: an override would merge into the test
    configuration's own tables."""
    settings = storefront_config.settings
    saved = {name: deepcopy(settings.get(name)) for name in roots}
    try:
        for name, value in roots.items():
            settings.unset(name, force=True)
            settings.set(name, value)
        yield
    finally:
        for name, value in saved.items():
            settings.unset(name, force=True)
            if value is not None:
                settings.set(name, value)


def _settlement(*, enabled: bool = True, **alkahest) -> dict:
    return {
        "schema_version": 1,
        "priority": ["alkahest.v1"] if enabled else [],
        "alkahest": {"enabled": enabled, **alkahest},
    }


@pytest.fixture
def storefront(tmp_path, monkeypatch):
    """The configuration a seller's storefront starts from, and its database path."""
    db_path = tmp_path / "credits-storefront.db"
    monkeypatch.setenv(
        "ARKHAI_IDENTITY_CREDENTIAL", base64.urlsafe_b64encode(SEED).rstrip(b"=").decode()
    )
    # The process's database client is created by the first startup; each test
    # starts from none and leaves none behind.
    monkeypatch.setattr(container, "_sqlite_client", None)
    identity = SELLER_SIGNER.identity
    with _replaced(
        identity={
            "scheme": identity.scheme.value,
            "identifier": identity.identifier,
            "admin_principals": {
                "identities": [ADMIN_SIGNER.identity.model_dump(mode="json")]
            },
        },
        wallet={"address": SELLER_WALLET, "private_key": ""},
        db_path=str(db_path),
        # A quota site the startup refusal can read; its runtime is the test's.
        capacity={
            "placement": "fill_first",
            "sites": {
                "quota-site": {
                    "url": "http://quota-site.invalid:8082",
                    "expected_authorities": {
                        "identities": [ADMIN_SIGNER.identity.model_dump(mode="json")]
                    },
                }
            },
        },
    ), patch.dict(storefront_config.CHAINS, {"anvil": ANVIL}, clear=True):
        yield db_path


def _app():
    return server.build_api_credits_storefront_app(
        registry=server.build_api_credits_storefront_registry(
            domain=get_market_domain_contract()
        )
    )


@pytest.mark.parametrize("enabled", [True, False])
async def test_startup_refuses_a_release_model_api_credits_cannot_deliver(
    storefront, enabled
):
    app = _app()
    with _replaced(settlement=_settlement(enabled=enabled, interruptible=True)):
        with pytest.raises(ReleaseModelError, match="'interruptible' release model"):
            async with app.router.lifespan_context(app):
                pass

    # Refused before the storefront opened its database.
    assert container._sqlite_client is None
    assert not storefront.exists()


async def test_a_published_listing_advertises_the_recipient_arbiter_paying_the_seller(
    storefront, monkeypatch
):
    async def no_startup_tasks(*, domain):
        return None

    monkeypatch.setattr(server, "_startup_tasks", no_startup_tasks)
    monkeypatch.setattr(
        container.QUOTA_CAPACITY, "runtime", lambda factory: _QuotaRuntime({"svc-quota": 42})
    )
    app = _app()
    with _replaced(settlement=_settlement()):
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            publishers = TrustedIdentitySet(identities=(SELLER_SIGNER.identity,))
            async with StorefrontClient(
                "http://seller",
                signer=SELLER_SIGNER,
                caller_role="seller",
                expected_publishers=publishers,
                transport=transport,
            ) as seller, StorefrontClient(
                "http://seller", transport=transport
            ) as public:
                created = await ListingClient(
                    seller,
                    seller=SELLER_SIGNER.identity,
                    request_model=container.PublishFromQuotaRequest,
                ).publish_from_quota(
                    {
                        "resource_id": "svc-quota",
                        "service_name": "Acme Inference",
                        "accepted_escrows": [dict(ESCROW)],
                    }
                )
                listing = await public.get_listing(created.listing_id)

    assert created.status == "created"
    assert listing.extra["demands"] == [
        {
            "chain_name": "anvil",
            "arbiter": get_recipient_arbiter(
                "anvil", config_path=str(anvil_address_book_path())
            ).lower(),
            "demand_data": {"recipient": SELLER_WALLET.lower()},
        }
    ]


async def test_a_disabled_section_still_composes_the_servicing_client_its_deals_need(
    storefront, monkeypatch
):
    """Deals accepted under Alkahest are serviced after it stops publishing."""

    async def no_startup_tasks(*, domain):
        return None

    chain_client = object()
    monkeypatch.setattr(server, "_startup_tasks", no_startup_tasks)
    monkeypatch.setattr(server, "_build_alkahest_clients", lambda: {"anvil": chain_client})
    app = _app()
    with _replaced(settlement=_settlement(enabled=False)):
        async with app.router.lifespan_context(app):
            composition = container.resolved_settlement_composition
            assert ALKAHEST_MECHANISM_ID in composition.mechanism_clients
            assert composition.mechanism_resources["get_client"]("anvil") is chain_client
