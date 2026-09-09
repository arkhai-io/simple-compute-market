"""Settling an exact-selection agreement verifies the accepted obligation.

The negotiation here is produced by the real exact-selection path, so the
thread carries what that producer persists: a settlement-selection envelope in
``buyer_escrow_proposal`` and the immutable accepted plan. Settlement must
verify the funded escrow against that accepted obligation, never against the
listing's mutable advertised terms.

Every fixture value is obviously synthetic development material with no value
on any network and must never be used on one. Nothing here reaches a chain: the
escrow verifier is a mock.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from typing import Any

import pytest
from core_storefront.models.negotiation_models import NegotiateNewRequest
from market_alkahest import AlkahestSettlementConfig, create_alkahest_registration
from market_identity import Eip191Signer, TrustedIdentitySet
from market_settlement_runtime import MechanismReadiness

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.models import BareMetalSettleRequest
from arkhai_bare_metal_storefront.runtime import BareMetalStorefrontRuntime
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.settlement_service import SettlementRequestError
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient

BUYER_SIGNER = Eip191Signer(bytes.fromhex("22" * 32))
SELLER_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))
ADMIN_SIGNER = Eip191Signer(bytes.fromhex("33" * 32))
# Deterministic development addresses. Never usable on a public network.
SELLER_WALLET = "0x" + "bb" * 20
ESCROW_ADDRESS = "0x" + "11" * 20
TOKEN_ADDRESS = "0x" + "aa" * 20
CHAIN = "base_sepolia"

LISTING_ID = "canonical-listing"
MACHINE_ID = "bm-machine-1"
SITE_ID = "site-a"
POOL_ID = "pool-a"
PHYSICAL_RESOURCE_ID = "resource-1"
PHYSICAL_HOST_ID = "physical-host-1"
SSH_PUBLIC_KEY = "ssh-ed25519 " + base64.b64encode(b"x" * 32).decode()
DURATION_SECONDS = 3600
RATE_PER_HOUR = 1000
EXPIRATION_UNIX = 1_900_000_000
NOW_UNIX = EXPIRATION_UNIX - 7200
ESCROW_UID = "0x" + "ab" * 32


def _published_option() -> dict[str, Any]:
    """Run the real Alkahest option builder over one advertised escrow."""
    entry = {
        "chain_name": CHAIN,
        "escrow_address": ESCROW_ADDRESS,
        "literal_fields": {"token": TOKEN_ADDRESS},
        "rates": [{"field": "amount", "per": "hour", "value": str(RATE_PER_HOUR)}],
    }
    artifacts = create_alkahest_registration().option_builder(
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
    return artifacts["settlement_options"][0]


def _composition() -> BareMetalStorefrontSettlementComposition:
    return BareMetalStorefrontSettlementComposition.from_raw_config(
        {"priority": ["alkahest.v1"], "alkahest": {"enabled": True}},
        resources={
            "wallet": {"address": SELLER_WALLET},
            # No chain is reached: the runtime only needs a client object to
            # exist for the mechanism it composes.
            "clients": {CHAIN: object()},
        },
    )


async def _runtime(tmp_path, verifier) -> BareMetalStorefrontRuntime:
    domain = get_market_domain_contract()
    db = SQLiteClient(str(tmp_path / "storefront.db"), domain=domain)
    option = _published_option()
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
    return BareMetalStorefrontRuntime(
        db=db,
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        admin_principals=TrustedIdentitySet(identities=(ADMIN_SIGNER.identity,)),
        storefront_url="http://seller:8000",
        marketplace_signer=SELLER_SIGNER,
        seller_evm_address=SELLER_WALLET,
        plan_builder=_forbidden_plan_builder,
        chain_clients={CHAIN: object()},
        chain_config_paths={CHAIN: None},
        escrow_verifier=verifier,
        settlement_composition=_composition(),
    )


def _forbidden_plan_builder(**_kwargs):
    raise AssertionError(
        "an exact-selection agreement must settle against its accepted plan"
    )


def _selection_request(option: dict[str, Any]) -> NegotiateNewRequest:
    body = {
        "listing_id": LISTING_ID,
        "buyer_principal": BUYER_SIGNER.identity.model_dump(mode="json"),
        "buyer_agent_url": "https://buyer.example",
        "provision_terms": {
            "kind": "bare_metal.v1",
            "version": 1,
            "payload": {
                "duration_seconds": DURATION_SECONDS,
                "access_method": "ssh",
                "ssh_public_key": SSH_PUBLIC_KEY,
            },
        },
        "proposal": {
            "settlement_selection": {
                "mechanism": option["mechanism"],
                "option_id": option["option_id"],
                "expiration_unix": EXPIRATION_UNIX,
            },
        },
    }
    return NegotiateNewRequest.model_validate(body)


async def _accepted_negotiation(runtime: BareMetalStorefrontRuntime) -> str:
    service = runtime.negotiation_service()
    object.__setattr__(service, "now_unix", lambda: NOW_UNIX)
    response = await service.open(
        request=_selection_request(_published_option()),
        buyer_principal=BUYER_SIGNER.identity,
    )
    assert response.action == "accept"
    return response.negotiation_id


def _settle_request(negotiation_id: str) -> BareMetalSettleRequest:
    return BareMetalSettleRequest(
        negotiation_id=negotiation_id,
        buyer_principal=BUYER_SIGNER.identity,
        buyer_evm_address="0x" + "cc" * 20,
    )


def _escrow_rows(db_path: str) -> list:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute("SELECT * FROM escrows").fetchall()
    finally:
        conn.close()


async def test_exact_selection_settles_against_the_accepted_obligation(tmp_path):
    calls: list[dict[str, Any]] = []

    async def verifier(**kwargs):
        calls.append(kwargs)
        return 0

    runtime = await _runtime(tmp_path, verifier)
    negotiation_id = await _accepted_negotiation(runtime)
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    accepted = thread["settlement_plan"]["obligations"][0]

    response = await runtime.settlement_service().verify(
        escrow_uid=ESCROW_UID,
        request=_settle_request(negotiation_id),
        buyer_principal=BUYER_SIGNER.identity,
    )

    assert response.escrow_uid == ESCROW_UID
    assert response.obligation_ref
    # Exactly one on-chain read, against the accepted obligation's own chain,
    # escrow contract, amount and duration.
    assert len(calls) == 1
    assert calls[0]["chain_name"] == accepted["params"]["chain_name"]
    assert calls[0]["agreed_price"] == int(accepted["amount"])
    assert calls[0]["expected_obligation_data"] == (
        accepted["params"]["obligation_data"]
    )
    assert calls[0]["expected_expiration_unix"] == accepted["expiration_unix"]
    assert calls[0]["agreed_duration_seconds"] == DURATION_SECONDS
    proposal = calls[0]["escrow_proposal"]
    assert proposal.escrow_address == accepted["params"]["escrow_contract"]
    assert proposal.expiration_unix == accepted["expiration_unix"]

    # Settling again adopts the same obligation without a second chain read,
    # so a retry cannot fund or verify a duplicate.
    retry = await runtime.settlement_service().verify(
        escrow_uid=ESCROW_UID,
        request=_settle_request(negotiation_id),
        buyer_principal=BUYER_SIGNER.identity,
    )
    assert retry.obligation_ref == response.obligation_ref
    assert len(calls) == 1
    assert len(_escrow_rows(runtime.db.db_path)) == 1


async def test_listing_refresh_cannot_redefine_historical_accepted_terms(tmp_path):
    calls: list[dict[str, Any]] = []

    async def verifier(**kwargs):
        calls.append(kwargs)
        return 0

    runtime = await _runtime(tmp_path, verifier)
    negotiation_id = await _accepted_negotiation(runtime)
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    accepted = thread["settlement_plan"]["obligations"][0]
    conn = sqlite3.connect(runtime.db.db_path)
    try:
        conn.execute(
            "UPDATE listings SET settlement_options = ? WHERE listing_id = ?",
            (json.dumps([]), LISTING_ID),
        )
        conn.commit()
    finally:
        conn.close()

    await runtime.settlement_service().verify(
        escrow_uid=ESCROW_UID,
        request=_settle_request(negotiation_id),
        buyer_principal=BUYER_SIGNER.identity,
    )

    assert len(calls) == 1
    assert calls[0]["expected_obligation_data"] == (
        accepted["params"]["obligation_data"]
    )
    assert calls[0]["expected_expiration_unix"] == accepted["expiration_unix"]


def _corrupt(plan: dict[str, Any], corruption: str) -> None:
    """Break one committed fact while leaving the rest of the plan valid."""
    obligation = plan["obligations"][0]
    physical = plan["service_terms"]["bare_metal.v1"]
    if corruption == "amount":
        obligation["amount"] = str(int(obligation["amount"]) + 1)
    elif corruption == "chain":
        obligation["params"].pop("chain_name")
    elif corruption == "contract":
        obligation["params"]["escrow_contract"] = ""
    elif corruption == "obligations":
        plan["obligations"] = []
    elif corruption == "buyer-principal":
        plan["buyer_principal"] = ADMIN_SIGNER.identity.model_dump(mode="json")
    elif corruption == "claimant-principal":
        obligation["claimant_principal"] = ADMIN_SIGNER.identity.model_dump(
            mode="json"
        )
    elif corruption == "roles":
        obligation["payer"], obligation["claimant"] = ("seller", "buyer")
    elif corruption == "asset":
        obligation["asset"] = "0x" + "de" * 20
    elif corruption == "conditions":
        obligation["conditions"] = [{"kind": "oracle.v1"}]
    elif corruption == "duration":
        physical["provision_terms"]["duration_seconds"] = DURATION_SECONDS + 60
    elif corruption == "machine":
        physical["provision_terms"]["machine_id"] = "bm-machine-other"
    elif corruption == "access-key":
        physical["provision_terms"]["ssh_public_key"] = "ssh-ed25519 other-key"
    elif corruption == "option":
        physical["option_id"] = "option-other"
    elif corruption == "mechanism-terms":
        plan["service_terms"]["alkahest.v1"]["escrow_contract"] = "0x" + "de" * 20
    elif corruption == "mechanism-listing":
        plan["service_terms"]["alkahest.v1"]["listing_id"] = "listing-other"
    elif corruption == "binding-host":
        physical["physical_binding"]["physical_host_id"] = "physical-host-other"
    elif corruption == "binding-access":
        physical["physical_binding"]["access_method"] = "serial"
    elif corruption == "binding-missing":
        physical.pop("physical_binding")
    elif corruption == "unreadable-amount":
        obligation["params"]["obligation_data"]["amount"] = "not-an-integer"
    elif corruption == "nested-amount":
        obligation["params"]["obligation_data"]["amount"] = str(
            int(obligation["amount"]) + 1
        )
    elif corruption == "nested-token":
        obligation["params"]["obligation_data"]["token"] = "0x" + "de" * 20
    elif corruption == "arbiter":
        obligation["params"]["obligation_data"]["arbiter"] = None
    elif corruption == "demand":
        obligation["params"]["obligation_data"]["demand"] = "not-hex"
    elif corruption == "expiry":
        obligation["expiration_unix"] = True
    elif corruption == "unreadable-settlement-expiry":
        plan["service_terms"]["alkahest.v1"]["expiration_unix"] = None
    else:  # pragma: no cover - guards a mistyped parameter
        raise AssertionError(f"unknown corruption {corruption!r}")


@pytest.mark.parametrize(
    "corruption",
    [
        "amount",
        "chain",
        "contract",
        "obligations",
        "buyer-principal",
        "claimant-principal",
        "roles",
        "asset",
        "conditions",
        "duration",
        "machine",
        "access-key",
        "option",
        "mechanism-terms",
        "mechanism-listing",
        "binding-host",
        "binding-access",
        "binding-missing",
        "unreadable-amount",
        "nested-amount",
        "nested-token",
        "arbiter",
        "demand",
        "expiry",
        "unreadable-settlement-expiry",
    ],
)
async def test_a_mismatched_accepted_plan_fails_closed_before_any_write(
    tmp_path, corruption
):
    reads: list[dict[str, Any]] = []

    async def verifier(**kwargs):
        # Recorded rather than raised: a verifier that raises would be reported
        # as a settlement error too, and the refusal must happen before the
        # chain is read at all.
        reads.append(kwargs)
        return 0

    runtime = await _runtime(tmp_path, verifier)
    negotiation_id = await _accepted_negotiation(runtime)
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    plan = thread["settlement_plan"]
    _corrupt(plan, corruption)
    conn = sqlite3.connect(runtime.db.db_path)
    try:
        conn.execute(
            "UPDATE negotiation_threads SET settlement_plan = ?"
            " WHERE negotiation_id = ?",
            (json.dumps(plan), negotiation_id),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(SettlementRequestError):
        await runtime.settlement_service().verify(
            escrow_uid=ESCROW_UID,
            request=_settle_request(negotiation_id),
            buyer_principal=BUYER_SIGNER.identity,
        )

    assert reads == []
    assert _escrow_rows(runtime.db.db_path) == []


async def test_an_unreadable_selection_expiry_is_refused_as_a_settlement_error(
    tmp_path,
):
    """A null in an opaque carrier is a refusal to settle, not a server fault."""

    reads: list[dict[str, Any]] = []

    async def verifier(**kwargs):
        reads.append(kwargs)
        return 0

    runtime = await _runtime(tmp_path, verifier)
    negotiation_id = await _accepted_negotiation(runtime)
    thread = await runtime.db.load_negotiation_thread_row(
        negotiation_id=negotiation_id,
    )
    proposal = thread["buyer_escrow_proposal"]
    proposal["settlement_selection"]["expiration_unix"] = None
    conn = sqlite3.connect(runtime.db.db_path)
    try:
        conn.execute(
            "UPDATE negotiation_threads SET buyer_escrow_proposal = ?"
            " WHERE negotiation_id = ?",
            (json.dumps(proposal), negotiation_id),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(SettlementRequestError):
        await runtime.settlement_service().verify(
            escrow_uid=ESCROW_UID,
            request=_settle_request(negotiation_id),
            buyer_principal=BUYER_SIGNER.identity,
        )

    assert reads == []
    assert _escrow_rows(runtime.db.db_path) == []
