"""Accepted introduction deals on the VM full-app harness, through typed clients.

The publication loop publishes a pool an operator offers by introduction, the
buyer's storefront client negotiates the listing's introduction option to
acceptance, and the production buyer's ``IntroductionTransport`` reaches the
introduction routes over loopback.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from core_buyer.introductions import IntroductionTransport
from market_identity import TrustedIdentitySet
from market_pool_overrides import PoolOverrideClient
from market_settlement_runtime import derive_obligation_ref

from tests.fake_site import TEST_MARKETPLACE_SIGNER
from tests.fixtures.publication_cycle import validate_cycle_report
from tests.publication_app import BUYER_SIGNER, contact_clause

CONTACT_MECHANISM = "contact-exchange.v1"
BUYER_CONTACT = {"email": "buyer@example.invalid"}
# Contact exchange settles by revealing contacts, so unbacked supply may offer it.
CONTACT_PUBLISHABLE = {"alkahest.v1": True, "arkhai.payments.v1": True, CONTACT_MECHANISM: False}


def vm_provision(duration_seconds: int = 3600) -> dict:
    # An introduction provisions nothing, so it carries no access key.
    return {
        "kind": "compute.v1",
        "version": 1,
        "payload": {"duration_seconds": duration_seconds, "ssh_public_key": ""},
    }


def listing_row(listing: Any) -> dict:
    row = dict(listing) if isinstance(listing, dict) else {**listing.extra, **asdict(listing)}
    row.pop("extra", None)
    resource = row.get("listing_resource")
    if isinstance(resource, str):
        row["listing_resource"] = json.loads(resource)
    return row


async def offer_introduction(world, site: str, pool_id: str) -> None:
    """Offer the pool by introduction alone, as an operator's override does."""
    await PoolOverrideClient(world.client).put_pool_override(
        {
            "site_id": site,
            "pool_id": pool_id,
            "offering_mode": "vm",
            "settlements": [contact_clause()],
        }
    )


async def publish(world) -> dict[str, dict]:
    """One publication cycle; the open listings keyed by the pool they come from."""
    report = await world.client.admin_run_lifecycle_cycle("publication")
    validate_cycle_report(report)
    page = await world.client.list_listings(status="open", limit=200)
    by_pool = {}
    for row in map(listing_row, page.listings):
        by_pool[row["listing_resource"]["pool_id"]] = row
    return by_pool


def introduction_transport(base_url: str) -> IntroductionTransport:
    """The production buyer's introduction client, pointed at ``base_url``."""
    return IntroductionTransport(
        seller_url=base_url,
        principal=BUYER_SIGNER.identity,
        signer=BUYER_SIGNER,
        resolve_seller_principals=lambda: TrustedIdentitySet(
            identities=(TEST_MARKETPLACE_SIGNER.identity,)
        ),
    )


async def accept_introduction(world, listing: dict) -> tuple[str, str]:
    """Negotiate the listing's one introduction option to acceptance."""
    (option,) = listing["settlement_options"]
    assert option["mechanism"] == CONTACT_MECHANISM
    # Under the storefront's default policy chain; an unpriced option needs no
    # policy override to be accepted.
    payload = await world.buyer.negotiate_new(
        listing_id=listing["listing_id"],
        initial_amount=None,
        provision_terms=vm_provision(),
        proposal_fields={},
        settlement_selection={
            "mechanism": CONTACT_MECHANISM,
            "option_id": option["option_id"],
            "expiration_unix": 1_900_000_000,
        },
        selection_only=True,
        buyer_agent_url="https://buyer.invalid",
    )
    assert payload["action"] == "accept", payload
    negotiation_id = payload["negotiation_id"]
    obligation_ref = derive_obligation_ref(
        negotiation_id, 0, payload["settlement_plan"]["obligations"][0]
    )
    return negotiation_id, obligation_ref
