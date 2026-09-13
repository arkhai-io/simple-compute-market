"""Advertised Alkahest options accept into a canonical funded obligation.

The option under test is built by the real Alkahest publication builder, so it
carries what a published listing actually carries — one ``accepted_escrow``
param and no physical facts — and the obligation the seller accepts is compared
whole against the shared materialization the buyer re-derives from the same
advertised entry. A field-by-field comparison would not do: the funded bytes
live inside ``params.obligation_data``.

Every fixture value is obviously synthetic development material with no value on
any network and must never be used on one. Nothing here reaches a chain, a
resource pool or a provisioner: acceptance stops at the seller's own SQLite.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import replace
from typing import Any

import pytest
from core_storefront.models.negotiation_models import NegotiateNewRequest
from market_alkahest import AlkahestSettlementConfig, create_alkahest_registration
from market_alkahest.plans import materialize_settlement_plan_from_proposal
from market_alkahest.proposals import escrow_proposal_from_accepted_entry
from market_identity import Eip191Signer
from market_settlement_runtime import MechanismReadiness

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.negotiation_service import (
    BareMetalNegotiationService,
    NegotiationRequestError,
)
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

BUYER_SIGNER = Eip191Signer(bytes.fromhex("22" * 32))
SELLER_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
# Deterministic development addresses. Never usable on a public network.
SELLER_WALLET = "0x" + "bb" * 20
ESCROW_ADDRESS = "0x" + "11" * 20
TOKEN_ADDRESS = "0x" + "aa" * 20
CHAIN = "base_sepolia"

LISTING_ID = "alkahest-listing"
MACHINE_ID = "bm-machine-1"
SITE_ID = "site-a"
POOL_ID = "pool-a"
PHYSICAL_RESOURCE_ID = "resource-1"
PHYSICAL_HOST_ID = "physical-host-1"
SSH_PUBLIC_KEY = "ssh-ed25519 " + base64.b64encode(b"x" * 32).decode()
DURATION_SECONDS = 3600
RATE_PER_HOUR = 1000
EXPIRATION_UNIX = 1_900_000_000
NOW_UNIX = EXPIRATION_UNIX - 3600


def _escrow_entry(*, rates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """One accepted-escrow wire entry in the shape publication advertises."""

    return {
        "chain_name": CHAIN,
        "escrow_address": ESCROW_ADDRESS,
        "literal_fields": {"token": TOKEN_ADDRESS},
        "rates": [{"field": "amount", "per": "hour", "value": str(RATE_PER_HOUR)}]
        if rates is None
        else rates,
    }


def _published_option(entry: dict[str, Any]) -> dict[str, Any]:
    """Run the real Alkahest option builder over one accepted escrow."""

    registration = create_alkahest_registration()
    artifacts = registration.option_builder(
        AlkahestSettlementConfig(enabled=True),
        MechanismReadiness(
            mechanism="alkahest.v1",
            configured=True,
            enabled=True,
            ready=True,
        ),
        {"accepted_escrows": [entry]},
        "seller",
    )
    option = artifacts["settlement_options"][0]
    # The published shape this whole suite exists for: settlement params only.
    assert set(option["params"]) == {"accepted_escrow"}
    return option


async def _service(
    tmp_path,
    *,
    option: dict[str, Any],
    now_unix: int = NOW_UNIX,
) -> BareMetalNegotiationService:
    domain = get_market_domain_contract()
    db = SQLiteClient(str(tmp_path / "storefront.db"), domain=domain)
    await db.upsert_bare_metal_listing(
        listing_id=LISTING_ID,
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller_principal=SELLER_SIGNER.identity,
        storefront_url="http://seller:8000",
        site_id=SITE_ID,
        pool_id=POOL_ID,
        physical_resource_id=PHYSICAL_RESOURCE_ID,
        listing={
            "kind": "bare_metal.v1",
            "machine_id": MACHINE_ID,
            "physical_host_id": PHYSICAL_HOST_ID,
            "access_methods": ["ssh"],
            "min_duration_seconds": 900,
            "max_duration_seconds": 7200,
        },
        accepted_escrows=[],
        settlement_options=[option],
    )
    composition = BareMetalStorefrontSettlementComposition.from_raw_config(
        {"priority": ["alkahest.v1"], "alkahest": {"enabled": True}},
        resources={"wallet": {"address": SELLER_WALLET}},
    )
    return BareMetalNegotiationService(
        db=db,
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        round_hook=None,  # type: ignore[arg-type]
        build_plan=lambda **kwargs: {},
        accepted_obligation_dispatch=composition.accepted_obligation_dispatch(),
        now_unix=lambda: now_unix,
    )


def _request(
    option: dict[str, Any],
    *,
    duration_seconds: int = DURATION_SECONDS,
    access_method: str = "ssh",
    ssh_public_key: str | None = SSH_PUBLIC_KEY,
    access_ref: dict[str, Any] | None = None,
    expiration_unix: int = EXPIRATION_UNIX,
    option_id: str | None = None,
    mechanism: str | None = None,
) -> NegotiateNewRequest:
    payload: dict[str, Any] = {
        "duration_seconds": duration_seconds,
        "access_method": access_method,
    }
    if ssh_public_key is not None:
        payload["ssh_public_key"] = ssh_public_key
    if access_ref is not None:
        payload["access_ref"] = access_ref
    body = {
        "listing_id": LISTING_ID,
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "buyer_agent_url": "https://buyer.example",
        "provision_terms": {
            "kind": "bare_metal.v1",
            "version": 1,
            "payload": payload,
        },
        "proposal": {
            "settlement_selection": {
                "mechanism": mechanism or option["mechanism"],
                "option_id": option_id or option["option_id"],
                "expiration_unix": expiration_unix,
            },
            "fields": {},
        },
    }
    # Through the wire encoding, so nothing typed here bypasses request parsing.
    return NegotiateNewRequest.model_validate(json.loads(json.dumps(body)))


def _expected_obligation(entry: dict[str, Any]) -> dict[str, Any]:
    """The obligation the shared codec derives from the advertised entry."""

    proposal = escrow_proposal_from_accepted_entry(
        listing={"demands": []},
        entry=entry,
        expiration_unix=EXPIRATION_UNIX,
    )
    plan = materialize_settlement_plan_from_proposal(
        proposal=proposal,
        seller_wallet_address=SELLER_WALLET,
        agreed_amount=RATE_PER_HOUR,
        duration_seconds=DURATION_SECONDS,
        addr_config_path=None,
    )
    return plan.obligations[0].model_dump(mode="json")


def _counts(tmp_path) -> dict[str, int]:
    with sqlite3.connect(tmp_path / "storefront.db") as db:
        return {
            table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in (
                "negotiation_threads",
                "negotiation_messages",
                "settlement_obligations",
                "capacity_holds",
            )
        }


async def test_advertised_option_accepts_into_the_canonical_obligation(
    tmp_path,
) -> None:
    entry = _escrow_entry()
    option = _published_option(entry)
    service = await _service(tmp_path, option=option)

    response = await service.open(
        request=_request(option),
        buyer_principal=BUYER_SIGNER.identity,
    )

    assert response.action == "accept"
    assert response.settlement_selection is not None
    assert response.settlement_selection.option_id == option["option_id"]
    assert response.settlement_selection.mechanism == "alkahest.v1"
    plan = response.settlement_plan
    assert plan is not None and len(plan.obligations) == 1
    expected = _expected_obligation(entry)
    actual = plan.obligations[0].model_dump(mode="json")
    # Whole-obligation equality: the arbiter, the encoded payout demand, the
    # token and the funded amount all live inside params.obligation_data, and
    # a substitution there is invisible to the scalar view above it.
    assert actual == {
        **expected,
        "payer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "claimant_principal": SELLER_SIGNER.identity.model_dump(mode="json"),
    }
    obligation_data = actual["params"]["obligation_data"]
    assert int(obligation_data["amount"]) == RATE_PER_HOUR
    assert obligation_data["token"] == TOKEN_ADDRESS
    # The payout is the seller's own wallet, encoded into the arbiter demand.
    assert SELLER_WALLET[2:].lower() in obligation_data["demand"].lower()
    assert actual["params"]["chain_name"] == CHAIN
    assert actual["params"]["escrow_contract"] == ESCROW_ADDRESS
    assert actual["expiration_unix"] == EXPIRATION_UNIX
    assert actual["asset"] == TOKEN_ADDRESS
    assert plan.obligations[0].amount == RATE_PER_HOUR

    # The physical envelope compared whole against an expectation written out
    # here, so a field the seller invented or dropped fails rather than being
    # read back out of the seller's own answer.
    physical = plan.service_terms["bare_metal.v1"]
    assert physical == {
        "listing_id": LISTING_ID,
        "option_id": option["option_id"],
        "mechanism": "alkahest.v1",
        "physical_binding": {
            "site_id": SITE_ID,
            "pool_id": POOL_ID,
            "physical_resource_id": PHYSICAL_RESOURCE_ID,
            "physical_host_id": PHYSICAL_HOST_ID,
            "access_method": "ssh",
        },
        "provision_terms": {
            "kind": "bare_metal.v1",
            "machine_id": MACHINE_ID,
            "physical_host_id": PHYSICAL_HOST_ID,
            "duration_seconds": DURATION_SECONDS,
            "access_method": "ssh",
            "ssh_public_key": SSH_PUBLIC_KEY,
            "listing_ref": LISTING_ID,
        },
    }
    assert MACHINE_ID != PHYSICAL_HOST_ID
    assert plan.service_terms["alkahest.v1"]["option_id"] == option["option_id"]

    # Accepting is not provisioning: no capacity is held here, and the
    # negotiation service holds no capacity or fulfillment collaborator that
    # could reserve one.
    assert _counts(tmp_path)["capacity_holds"] == 0
    assert not hasattr(service, "capacity_client")
    assert not hasattr(service, "fulfillment_client")

    terms = await service.db.load_bare_metal_terms(
        negotiation_id=response.negotiation_id
    )
    assert terms is not None
    assert terms.machine_id == MACHINE_ID
    assert terms.physical_host_id == PHYSICAL_HOST_ID
    assert terms.ssh_public_key == SSH_PUBLIC_KEY
    thread = await service.db.load_negotiation_thread_row(
        negotiation_id=response.negotiation_id
    )
    assert thread is not None
    persisted = thread["settlement_plan"]
    assert persisted["service_terms"]["bare_metal.v1"] == physical
    assert persisted["obligations"][0]["params"] == actual["params"]


@pytest.mark.parametrize(
    ("kwargs", "detail"),
    [
        ({"option_id": "ee" * 32}, "does not exact-match"),
        ({"mechanism": "fiat.stripe.v1"}, "unsupported mechanism"),
        ({"expiration_unix": NOW_UNIX - 1}, "already expired"),
        ({"duration_seconds": 60}, "outside listing bounds"),
        ({"access_method": "none", "ssh_public_key": None}, "unadvertised access"),
        # Access authority is not a buyer input: the provision envelope forbids
        # unknown payload keys, so it is refused before admission.
        ({"access_ref": {"host": "10.0.0.1"}}, "incompatible bare-metal"),
    ],
)
async def test_rejected_selection_writes_nothing(tmp_path, kwargs, detail) -> None:
    option = _published_option(_escrow_entry())
    service = await _service(tmp_path, option=option)

    with pytest.raises(NegotiationRequestError, match=detail):
        await service.open(
            request=_request(option, **kwargs),
            buyer_principal=BUYER_SIGNER.identity,
        )

    assert set(_counts(tmp_path).values()) == {0}


async def test_ssh_selection_without_an_access_key_is_refused(tmp_path) -> None:
    """The provision-terms codec is where a missing access key enters."""

    option = _published_option(_escrow_entry())
    service = await _service(tmp_path, option=option)

    with pytest.raises(NegotiationRequestError, match="incompatible bare-metal"):
        await service.open(
            request=_request(option, ssh_public_key=None),
            buyer_principal=BUYER_SIGNER.identity,
        )

    assert set(_counts(tmp_path).values()) == {0}


async def test_selection_naming_another_sellers_listing_identity_is_refused(
    tmp_path,
) -> None:
    """A listing whose seller identity moved cannot be accepted against."""

    option = _published_option(_escrow_entry())
    service = replace(
        await _service(tmp_path, option=option),
        seller_principal=Eip191Signer(bytes.fromhex("33" * 32)).identity,
    )

    with pytest.raises(NegotiationRequestError, match="seller identity changed"):
        await service.open(
            request=_request(option),
            buyer_principal=BUYER_SIGNER.identity,
        )

    assert set(_counts(tmp_path).values()) == {0}


async def test_option_pricing_no_lease_time_cannot_accept(tmp_path) -> None:
    """A rate-less Alkahest option fails closed instead of provisioning.

    The publication builder admits an escrow entry with no rate, and such an
    option prices no lease time — so it is not treated as machine-provisioning.
    It must not become a silent non-provisioning acceptance on a listing that
    sells a machine either: the mechanism cannot scale an amount without a
    rate, so the obligation is refused and nothing is written.
    """

    entry = _escrow_entry(rates=[])
    option = _published_option(entry)
    assert option["rates"] == []
    service = await _service(tmp_path, option=option)

    with pytest.raises(NegotiationRequestError, match="cannot produce an exact"):
        await service.open(
            request=_request(option),
            buyer_principal=BUYER_SIGNER.identity,
        )

    assert set(_counts(tmp_path).values()) == {0}
