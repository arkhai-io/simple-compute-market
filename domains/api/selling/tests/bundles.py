"""A neutral domain's bundle and storefront tables, so no real domain's values enter the family's tests.

Its listing names its fields differently from any real domain, so a test passing
under it shows the library reads only what the bundle's projection returns.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from datetime import datetime, timezone

from arkhai_api.labels import IssuanceLabel
from arkhai_api.purchase import provision_terms_model
from market_core import (
    MARKET_DOMAIN_CONTRACT_VERSION,
    DomainCapability,
    DomainIdentity,
    ImmutableCodecCapability,
    ImmutableFulfillmentCapability,
    ImmutablePublicationCapability,
    ImmutableSettlementCapability,
    ImmutableStorefrontCapability,
    MarketDomainContract,
    SettlementStageTable,
)
from market_core.schemas import Agreement, SettlementOption, derive_settlement_option_id
from market_identity import Ed25519Signer
from pydantic import BaseModel, ConfigDict

from arkhai_api_selling.persistence import StorefrontSQLiteClient
from arkhai_api_selling.contributions import (
    ConsumptionRule,
    IssuanceSubject,
    QuotaSource,
    SellingContributions,
)

# Deterministic development keys for these tests only; never used on any network.
ISSUER = Ed25519Signer(bytes(range(32)))
BUYER = Ed25519Signer(bytes(range(1, 33))).identity
CLAIMANT = Ed25519Signer(bytes(range(2, 34))).identity
STRANGER = Ed25519Signer(bytes(range(3, 35))).identity


class ExampleResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product: str
    quota: str | None = None
    url: str | None = None
    offering_mode: str | None = None


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


def _unused(value: Any) -> Any:
    return value


DOMAIN = MarketDomainContract(
    identity=DomainIdentity(EXAMPLE.kind),
    contract_version=MARKET_DOMAIN_CONTRACT_VERSION,
    codecs=ImmutableCodecCapability(
        normalize_listing=ExampleListing.model_validate,
        normalize_message=_unused,
        normalize_terms=_unused,
        normalize_materialization=_unused,
        normalize_receipt=_unused,
        normalize_result=_unused,
    ),
    declared_capabilities=frozenset(
        {
            DomainCapability.STOREFRONT,
            DomainCapability.PUBLICATION,
            DomainCapability.SETTLEMENT,
            DomainCapability.FULFILLMENT,
        }
    ),
    storefront=ImmutableStorefrontCapability(run_negotiation_policy=_unused),
    publication=ImmutablePublicationCapability(source_factory=_unused),
    settlement=ImmutableSettlementCapability(
        seller_stages=SettlementStageTable({"opaque.future.v1": object()})
    ),
    fulfillment=ImmutableFulfillmentCapability(fulfill=_unused),
)
"""The neutral domain's contract, whose listing codec is the bundle's listing schema."""


def with_extension(extension) -> SellingContributions:
    return replace(EXAMPLE, public_result_extension=extension)


def accepted_agreement(listing_id: str) -> tuple[Agreement, bytes]:
    """An Agreement for three credits on ``listing_id``, and its exact bytes."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    option = SettlementOption(
        option_id=derive_settlement_option_id(mechanism="opaque.future.v1", asset="USD/2", rates=[], params={}),
        mechanism="opaque.future.v1", asset="USD/2", rates=[], params={},
    )
    agreement = Agreement(
        negotiation_id="neg-accepted", listing_id=listing_id, listing_hash="0" * 64,
        buyer=BUYER.model_dump(mode="json"), seller=CLAIMANT.model_dump(mode="json"),
        settlement=option, amount=300, asset="USD/2", duration_seconds=0,
        start_utc=now, accepted_at=now,
        provision_terms=provision_terms_model(EXAMPLE.kind).purchase(quantity=3).model_dump(mode="json"),
    )
    return agreement, agreement.model_dump_json(exclude_none=True).encode()


def create_tables(db_path: Path, contributions: SellingContributions = EXAMPLE) -> StorefrontSQLiteClient:
    """The storefront's schema, migrated by the selling library's own client under the bundle's prefix."""
    return StorefrontSQLiteClient(str(db_path), contributions)
