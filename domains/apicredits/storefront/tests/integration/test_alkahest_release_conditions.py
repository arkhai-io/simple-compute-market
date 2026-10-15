"""The release conditions an API-credit listing advertises for Alkahest.

The storefront's settlement composition is built as startup builds it, over a
temporary SQLite database and the anvil development chain's address book, with
no chain client: deriving a listing's conditions asks no chain. Every address
and key here is a deterministic development value, never used on a public
network.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

import httpx
import pytest
from market_alkahest import ReleaseModelError
from market_alkahest.alkahest import get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_config.config_loader import ChainConfig
from market_identity import Ed25519Signer, TrustedIdentitySet
from fastapi import FastAPI
from storefront_client import StorefrontClient

import apicredits_storefront.container as container
from apicredits_storefront.controllers.listings_controller import router as listings_router
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.middleware.response_auth import authenticate_response
from apicredits_storefront.services import capacity_client as capacity_module
from apicredits_storefront.services.fulfillment_service import (
    build_api_credit_failure_policy,
)
from apicredits_storefront.services.listing_service import ListingService
from apicredits_storefront.settlement_composition import (
    build_api_credit_settlement_composition,
)
from apicredits_storefront.utils import config as storefront_config
from apicredits_storefront.utils import sqlite_client as sqlite_module
from apicredits_storefront.utils.sqlite_client import SQLiteClient
from tests.integration.test_publish_reconcile import _QuotaRuntime

SELLER_SIGNER = Ed25519Signer(bytes.fromhex("22" * 32))
BUYER_SIGNER = Ed25519Signer(bytes.fromhex("55" * 32))
SELLER_WALLET = "0x" + "33" * 20
ESCROW = {
    "chain_name": "anvil",
    "escrow_address": "0x" + "11" * 20,
    "literal_fields": {"token": "0x" + "01" * 20},
    "rates": [{"field": "amount", "per": "token", "value": "100"}],
}


@contextmanager
def _configured(**alkahest):
    """The seller's wallet, one anvil chain, and an Alkahest section."""
    settings = storefront_config.settings
    saved = {
        name: deepcopy(settings.get(name)) for name in ("settlement", "wallet")
    }
    chain = ChainConfig(
        name="anvil",
        rpc_url="http://anvil.test",
        chain_id=31337,
        alkahest_address_config_path=str(anvil_address_book_path()),
    )
    try:
        # Replaced at their roots: an override would merge into the test
        # configuration's own tables.
        for name in saved:
            settings.unset(name, force=True)
        settings.set(
            "settlement",
            {
                "schema_version": 1,
                "priority": ["alkahest.v1"],
                "alkahest": {"enabled": True, **alkahest},
            },
        )
        settings.set("wallet", {"address": SELLER_WALLET, "private_key": ""})
        with patch.dict(storefront_config.CHAINS, {"anvil": chain}, clear=True):
            yield
    finally:
        for name, value in saved.items():
            settings.unset(name, force=True)
            if value is not None:
                settings.set(name, value)


def _composition(db: SQLiteClient):
    return build_api_credit_settlement_composition(
        domain=get_market_domain_contract(),
        sqlite_client=db,
        alkahest_clients={},
        marketplace_signer=SELLER_SIGNER,
        failure_policy=build_api_credit_failure_policy(),
    )


@pytest.fixture
def db(tmp_path) -> SQLiteClient:
    return SQLiteClient(db_path=str(tmp_path / "credits-storefront.db"))


def test_startup_refuses_a_release_model_api_credits_cannot_deliver(db):
    with _configured(interruptible=True):
        with pytest.raises(ReleaseModelError, match="'interruptible' release model"):
            _composition(db)


async def test_a_listing_advertises_the_recipient_arbiter_paying_the_seller(
    db, monkeypatch
):
    monkeypatch.setattr(
        capacity_module,
        "build_capacity_runtime",
        lambda factory: _QuotaRuntime({"svc-quota": 42}),
    )
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(sqlite_module, "_sqlite_client", db)
    with _configured():
        listings = ListingService(
            sqlite_client=db,
            seller_principal=SELLER_SIGNER.identity,
            settlement_composition=_composition(db),
        )
        created = await listings.publish_from_quota(
            resource_id="svc-quota",
            service_name="Acme Inference",
            accepted_escrows=[dict(ESCROW)],
        )

    app = FastAPI()
    app.middleware("http")(authenticate_response)
    app.include_router(listings_router)
    monkeypatch.setattr(container, "resolved_marketplace_signer", SELLER_SIGNER)
    async with StorefrontClient(
        "http://seller",
        signer=BUYER_SIGNER,
        caller_role="buyer",
        expected_publishers=TrustedIdentitySet(identities=(SELLER_SIGNER.identity,)),
        transport=httpx.ASGITransport(app=app),
    ) as buyer:
        listing = await buyer.get_listing(created["listing_id"])

    assert listing.extra["demands"] == [
        {
            "chain_name": "anvil",
            "arbiter": get_recipient_arbiter(
                "anvil", config_path=str(anvil_address_book_path())
            ).lower(),
            "demand_data": {"recipient": SELLER_WALLET.lower()},
        }
    ]
