"""A neutral domain's bundle and an accepted escrow deal, so no real domain's values enter these tests.

The selling library's own suite has a bundle of the same shape; the two packages
share no test code.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from arkhai_api.labels import IssuanceLabel
from arkhai_api.purchase import provision_terms_model
from arkhai_api_selling.contributions import (
    ConsumptionRule,
    IssuanceSubject,
    QuotaSource,
    SellingContributions,
)
from arkhai_api_selling.issuance import settlement_evidence
from arkhai_api_selling.persistence import StorefrontSQLiteClient
from market_alkahest import ALKAHEST_MECHANISM_ID
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer
from pydantic import BaseModel, ConfigDict

# Deterministic development keys for these tests only; never used on any network.
SELLER = Ed25519Signer(bytes(range(32)))
BUYER = Ed25519Signer(bytes(range(1, 33))).identity

NEGOTIATION = "neg-escrow"
ESCROW_UID = "0x" + "ee" * 32
LISTING = {"product": "alpha", "quota": "quota-a", "url": "https://alpha.example"}
ACCEPTED_AT = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()


class ExampleResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: str
    quota: str | None = None
    url: str | None = None


class ExampleListing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing_resource: ExampleResource


def _subject(listing_resource: Mapping[str, Any]) -> IssuanceSubject:
    return IssuanceSubject(
        service=str(listing_resource.get("product") or ""),
        resource_id=listing_resource.get("quota"),
        endpoint=listing_resource.get("url"),
    )


def _listing_resource(request: Mapping[str, Any], source: QuotaSource) -> dict[str, Any]:
    return {"product": request["product"], "quota": source.resource_id}


EXAMPLE = SellingContributions(
    label=IssuanceLabel("example"),
    kind="example.v1",
    offering_mode="example",
    contribution_id="example",
    table_prefix="example",
    listing_schema=ExampleListing,
    publication_mapping=_listing_resource,
    issuance_projection=_subject,
    consumption_rule=ConsumptionRule.FIXED_PER_REQUEST,
)


def obligation() -> dict[str, Any]:
    """The escrow obligation an accepted deal's plan holds."""
    return {
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": BUYER.model_dump(mode="json"),
        "claimant_principal": SELLER.identity.model_dump(mode="json"),
        "mechanism": ALKAHEST_MECHANISM_ID,
        "expiration_unix": 4_102_444_800,
    }


def accepted_agreement() -> tuple[Agreement, bytes]:
    """An Agreement for three credits settled through the escrow, and its exact bytes."""
    now = ACCEPTED_AT
    params = {"accepted_escrow": {"chain_name": "anvil"}}
    option = SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism=ALKAHEST_MECHANISM_ID, asset="0x" + "01" * 20, rates=[], params=params
        ),
        mechanism=ALKAHEST_MECHANISM_ID, asset="0x" + "01" * 20, rates=[], params=params,
    )
    agreement = Agreement(
        negotiation_id=NEGOTIATION, listing_id="L-1", listing_hash="0" * 64,
        buyer=BUYER.model_dump(mode="json"), seller=SELLER.identity.model_dump(mode="json"),
        settlement=option, amount=300, asset="0x" + "01" * 20, duration_seconds=0,
        start_utc=now, accepted_at=now,
        provision_terms=provision_terms_model(EXAMPLE.kind).purchase(quantity=3).model_dump(mode="json"),
    )
    return agreement, agreement.model_dump_json(exclude_none=True).encode()


async def accepted_deal(db: StorefrontSQLiteClient, *, obligation_ref: str) -> None:
    """The accepted thread, its verified escrow evidence, and its open issuance progress."""
    agreement, raw = accepted_agreement()
    await db.create_negotiation_thread(
        negotiation_id=NEGOTIATION, our_listing_id="L-1", their_listing_id="",
        our_agent_id="seller", their_agent_id="buyer",
        buyer_principal=BUYER, seller_principal=SELLER.identity, owner_id="seller",
    )
    await db.commit_agreed_terms(
        negotiation_id=NEGOTIATION, agreed_price=300, agreed_duration_seconds=0,
        agreement_bytes=raw, accepted_at=ACCEPTED_AT, agreed_start_utc=ACCEPTED_AT,
    )
    await db.update_negotiation_thread_terminal(negotiation_id=NEGOTIATION, terminal_state="success")
    await db.save_settlement_evidence(settlement_evidence(
        EXAMPLE, agreement, raw, reference=ESCROW_UID, status="verified",
        source={"chain_name": "anvil", "escrow_uid": ESCROW_UID, "obligation_index": 0,
                "obligation_ref": obligation_ref, "funding_expiration_unix": 4_102_444_800},
        order={"listing_resource": LISTING},
    ))
    await db.save_issuance_progress(
        negotiation_id=NEGOTIATION, public_ref=ESCROW_UID, status="provisioning",
    )
