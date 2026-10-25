"""API-credit market-domain contribution for the core ``market`` buyer CLI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import typer
from arkhai_api_buying.commands import command_group
from arkhai_api_buying.contributions import BuyingContributions, ListingRendering
from arkhai_api_buying.listing import shorten
from arkhai_api_buying.settlement_composition import BuyerSettlementComposition
from arkhai_api_buying_alkahest.stage import AlkahestBuyerStage
from arkhai_api_buying_arkhai_payments.stage import PaymentBuyerStage
from arkhai_apicredits.domain_runtime import market_domain
from arkhai_apicredits.listings import coerce_resource_dict
from arkhai_apicredits.negotiation import ApiCreditsProvisionTerms, make_api_credits_provision_terms
from core_buyer.cli import build_app
from core_buyer.policy_surface import configured_buyer_policy
from market_core import (
    BUYER_IDENTITY_INJECTION_CONTRACT,
    DomainCapability,
    ImmutableBuyerCapability,
    MarketDomainContract,
    SettlementStageTable,
)


def _summary(resource: Mapping[str, Any]) -> str:
    if not resource:
        return "-"
    parts = [str(resource.get("service_name") or "-")]
    if resource.get("description"):
        parts.append(shorten(str(resource["description"]), 48))
    return " — ".join(parts)


def _details(resource: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    rows = [("Service", str(resource.get("service_name") or "-"))]
    if resource.get("description"):
        rows.append(("Description", str(resource["description"])))
    rows.append(("OpenAPI URL", str(resource.get("openapi_url") or "-")))
    rows.append(("Base URL", str(resource.get("base_url") or "-")))
    return tuple(rows)


#: The registry's filter-spec.yaml declares the same schema id.
CONTRIBUTIONS = BuyingContributions(
    schema_id="api_credits",
    provision_terms=ApiCreditsProvisionTerms,
    command="credits",
    command_help="API-credit market: discover, buy, top up keys.",
    noun="API-credit",
    resource_query_example="service_name=weather token in [0xabc,0xdef]",
    rendering=ListingRendering(
        resource=coerce_resource_dict,
        summary_header="Service",
        summary=_summary,
        columns=(("OpenAPI", lambda resource: str(resource.get("openapi_url") or "-")),),
        details=_details,
    ),
)

SETTLEMENT = BuyerSettlementComposition(
    CONTRIBUTIONS,
    SettlementStageTable(
        (stage.mechanism_id, stage)
        for stage in (AlkahestBuyerStage(), PaymentBuyerStage(payer_section="apicredits"))
    ),
)

credits_app = command_group(SETTLEMENT)


def register(app: typer.Typer) -> None:
    """Register the API-credits schema's buyer commands on the core app."""
    app.add_typer(credits_app, name=CONTRIBUTIONS.command, help=CONTRIBUTIONS.command_help)


def _buyer_market_domain() -> MarketDomainContract:
    base = market_domain()
    return replace(
        base,
        declared_capabilities=(base.declared_capabilities | {DomainCapability.BUYER}),
        buyer=ImmutableBuyerCapability(
            identity_injection_contract=BUYER_IDENTITY_INJECTION_CONTRACT,
            register_commands=register,
            build_provision_terms=make_api_credits_provision_terms,
            select_policy=configured_buyer_policy,
            decode_result=base.codecs.result,
        ),
    )


#: Loaded by ``market.buyer_domains`` discovery.
domain = _buyer_market_domain()

#: Pre-assembled app for direct module execution.
app = build_app(domains=[domain])


if __name__ == "__main__":
    app()
