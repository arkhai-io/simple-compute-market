"""`market credits negotiate` reaches acceptance against the served storefront.

The buyer's standalone command and the storefront's negotiation routes must
agree on the wire: the signed opening, the selection's bargained amount, the
response signatures and the accepted state the command records. Here the real
command runs against the real routes, authentication middleware and API-credit
negotiation runtime, served on loopback. The registry lookup, the buyer's
identity and configuration, the capacity snapshot and the quota hold are
controlled at the seams they resolve through. A payment-only deal needs no
wallet or chain on either side.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import uuid
from types import SimpleNamespace

import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.negotiation_runtime import (
    build_api_credit_negotiation_runtime,
)
from apicredits_storefront.settlement_composition import SELLER_STAGES
from arkhai_apicredits_buyer import negotiate_cli, payments, settlement_composition
from arkhai_apicredits_buyer.cli import app as buyer_app
from core_buyer import orchestration
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.registry_config import RegistryAuthority
from core_buyer.run_log import read_run
from fastapi import FastAPI
from market_arkhai_payments import (
    ARKHAI_PAYMENTS_MECHANISM,
    ArkhaiPaymentsConfig,
    servicing_stage,
)
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_identity import Ed25519Signer, TrustedIdentitySet
from typer.testing import CliRunner

import apicredits_storefront.container as container
from apicredits_storefront import settlement_stages
from apicredits_storefront.controllers.negotiate_controller import (
    router as negotiate_router,
)
from apicredits_storefront.middleware.response_auth import authenticate_response
from tests._settings_overrides import settings_overrides
from tests.integration.credit_negotiation import (
    BUYER_SIGNER,
    LISTING_ID,
    PAYER_ACCOUNT,
    SELLER_SIGNER,
    payment_option,
)
from tests.loopback import serving

# A deterministic development key for this test only; never used on any network.
_SERVICE = Ed25519Signer(bytes.fromhex("55" * 32))
_DISPUTE = "33333333-3333-4333-8333-333333333333"
_DOMAIN = get_market_domain_contract()
_IDENTITY = ResolvedBuyerIdentity(
    profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
    principal=BUYER_SIGNER.identity,
    signer=BUYER_SIGNER,
    source="primary",
)


class _QuotaHolds:
    """The capacity runtime a payment acceptance reserves its quota through."""

    def __init__(self) -> None:
        self.claims: list[dict] = []

    async def reserve(self, _binding, *, claim, deal_ref, ttl_seconds):
        self.claims.append(claim)
        return {
            "capacity_reservation_id": f"alloc-{len(self.claims)}",
            "resource_id": "svc-quota",
            "allocated_units": claim["units"],
            "hold_expires_at": "2099-01-01 00:00",
        }


@pytest.fixture
async def storefront(db, fake_capacity, key_records, monkeypatch):
    """The served negotiation routes of a payments-composed storefront."""
    stage = servicing_stage(
        ArkhaiPaymentsConfig(
            enabled=True,
            service_url="http://127.0.0.1:9",
            service_identity=_SERVICE.identity,
            fee_bps=250,
            dispute_authority=_DISPUTE,
            development_auth=True,
        ),
        client_for_owner=FakePaymentsClient(),
    )
    composition = SimpleNamespace(arkhai_payments_stage=stage)
    runtime = build_api_credit_negotiation_runtime(
        _DOMAIN,
        accepted_obligation_dispatch={ARKHAI_PAYMENTS_MECHANISM: None},
        settlement_artifacts_builder=lambda agreement: SELLER_STAGES[
            agreement["settlement"]["mechanism"]
        ].agreement_artifacts(agreement, composition),
    )
    holds = _QuotaHolds()
    monkeypatch.setattr(settlement_stages, "build_capacity_runtime", lambda _factory: holds)
    monkeypatch.setattr(container, "resolved_sqlite_client", db)
    monkeypatch.setattr(container, "resolved_negotiation_runtime", runtime)
    monkeypatch.setattr(container, "resolved_marketplace_signer", SELLER_SIGNER)
    await db.update_listing(
        listing_id=LISTING_ID,
        settlement_options=[payment_option().model_dump(mode="json")],
    )
    app = FastAPI()
    app.middleware("http")(authenticate_response)
    app.include_router(negotiate_router)
    with settings_overrides(
        **{
            "identity.scheme": "ed25519",
            "identity.identifier": SELLER_SIGNER.identity.identifier,
            "capacity.hold_ttl_seconds": 300,
        }
    ):
        with serving(app) as base_url:
            yield SimpleNamespace(base_url=base_url, db=db, holds=holds)


@pytest.fixture
def buyer(storefront, monkeypatch, tmp_path):
    """The buyer's registry, identity and settlement configuration."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    publishers = TrustedIdentitySet(identities=(SELLER_SIGNER.identity,))
    listing = {
        "listing_id": LISTING_ID,
        "storefront_url": storefront.base_url,
        "publisher_id": "publisher",
        "publisher_principals": publishers.model_dump(mode="json"),
        "settlement_options": [payment_option().model_dump(mode="json")],
        "accepted_escrows": [],
    }
    seams = {
        "resolve_fresh_buyer_identity": lambda: _IDENTITY,
        "resolve_indexer_urls": lambda **_kw: ["http://registry"],
        "resolve_indexer_urls_for_schema": lambda *_a, **_kw: ["http://registry"],
        "resolve_registry_authorities": lambda urls: {
            url: RegistryAuthority(authority="registry", principals=publishers)
            for url in urls
        },
        "resolve_registry_api_keys": lambda: {},
        "resolve_negotiation_config": lambda: (None, None),
        "fetch_listing_dict": lambda *_a, **_kw: dict(listing),
    }
    for name, seam in seams.items():
        monkeypatch.setattr(negotiate_cli, name, seam)
    # The publisher-trust refresh re-reads the listing from its registry.
    monkeypatch.setattr(orchestration, "fetch_listing_dict", seams["fetch_listing_dict"])
    config = {
        "Settlement": {
            "schema_version": 1,
            "priority": [ARKHAI_PAYMENTS_MECHANISM],
            "arkhai_payments": {"enabled": True},
        },
        "apicredits": {"payer_account": PAYER_ACCOUNT},
    }
    monkeypatch.setattr(settlement_composition, "load_user_config", lambda: config)
    monkeypatch.setattr(payments, "load_user_config", lambda: config)


def _negotiate(*args: str):
    return CliRunner().invoke(
        buyer_app,
        ["credits", "negotiate", "--listing-id", LISTING_ID, "--quantity", "3", "--yes", *args],
    )


@pytest.mark.parametrize(
    "prices,amount",
    [((), 300), (("--initial-price", "100", "--max-price", "120"), 300)],
)
async def test_payment_negotiation_is_accepted_and_recorded(
    storefront, buyer, prices, amount
) -> None:
    result = await asyncio.to_thread(_negotiate, *prices)
    assert result.exit_code == 0, (result.output, result.exception)

    run_id = re.search(r"\b[0-9a-f]{32}\b", result.output)
    assert run_id is not None, result.output
    accepted = read_run(run_id.group(), signer=BUYER_SIGNER)[-1]
    negotiation_id = accepted["negotiation_id"]
    selection = accepted["settlement_selection"]
    assert selection["option_id"] == payment_option().option_id
    assert selection["params"] == {"payer_account": PAYER_ACCOUNT}
    agreement = json.loads(base64.b64decode(accepted["agreement_bytes"]))
    assert agreement["amount"] == str(amount)
    assert agreement["settlement_params"] == {"payer_account": PAYER_ACCOUNT}
    assert accepted["settlement_data"]["mandate"]

    thread = await storefront.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    assert thread["terminal_state"] == "success"
    assert int(thread["agreed_price"]) == amount
    assert await storefront.db.load_credit_terms(negotiation_id=negotiation_id) == {
        "negotiation_id": negotiation_id,
        "quantity": 3,
        "key_mode": "new",
        "key_id": None,
    }
    assert [claim["units"] for claim in storefront.holds.claims] == [3]
