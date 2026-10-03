"""Settlement by introduction for VM buyers.

``request-introduction`` negotiates one advertised rateless introduction option
in the VM market's own terms and records the accepted run. Starting and
re-reading the introduction are the contact-exchange mechanism's commands
(``market settlement contact …``); this module supplies the VM buyer's run
recovery, transport, run log, and sinks to them.
"""

from __future__ import annotations

import json
import time
from typing import Any

import typer
from arkhai_vms import make_vm_provision_terms
from core_buyer import (
    IntroductionTransport,
    deliver_introduction,
    load_buyer_delivery_sinks,
    report_delivery,
)
from core_buyer.buyer_config import resolve_fresh_buyer_identity
from core_buyer.deal_helpers import settlement_acceptance_fields
from core_buyer.introductions import IntroductionPayloadsDeleted
from core_buyer.negotiation_client import negotiate_with_seller
from market_contact_exchange import MECHANISM as CONTACT_MECHANISM
from market_contact_exchange import RecoveredIntroductionRun
from market_core.schemas import SettlementOption, SettlementSelection
from market_identity import TrustedIdentitySet
from market_settlement_runtime import derive_obligation_ref
from pydantic_core import to_jsonable_python

from .buy_orchestrator import fetch_listing_dict
from .deal_helpers import (
    load_deal_context,
    make_deal_publisher_trust_resolver,
    open_run_log,
)
from .run_log import RunLog


def _echo(value: Any) -> None:
    typer.echo(json.dumps(to_jsonable_python(value), ensure_ascii=True, sort_keys=True))


def _seller_principal(deal: Any) -> Any:
    principals = getattr(deal, "seller_principals", None)
    identities = getattr(principals, "identities", ()) if principals else ()
    return identities[0] if identities else None


class IntroductionContext:
    """The VM buyer's run recovery and delivery for the introduction commands."""

    deleted_error = IntroductionPayloadsDeleted

    def recover(
        self, run_id: str, config: str | None, *, deliver: bool
    ) -> RecoveredIntroductionRun:
        from .common import resolve_recovery_buyer_identity

        sinks = load_buyer_delivery_sinks(config) if deliver else None
        identity = resolve_recovery_buyer_identity(run_id)
        deal = load_deal_context(run_id, signer=identity.signer)
        transport = IntroductionTransport(
            seller_url=deal.seller_url,
            principal=deal.buyer_principal,
            signer=identity.signer,
            resolve_seller_principals=make_deal_publisher_trust_resolver(
                run_id, deal, identity.signer
            ),
        )

        def record(name: str, **fields: Any) -> None:
            open_run_log(
                run_id, signer=identity.signer, profile_id=identity.profile_id
            ).event(name, **fields)

        def deliver_copy(projection: Any) -> None:
            """The buyer's own copy, never fatal: the reveal is re-readable."""

            outcomes = deliver_introduction(
                projection,
                sinks=sinks,
                agreement_ref=deal.negotiation_id,
                counterparty=_seller_principal(deal),
            )
            report_delivery(outcomes, sinks.warnings)
            if outcomes:
                record(
                    "introduction_delivered",
                    obligation_ref=projection.get("obligation_ref"),
                    outcomes=[
                        {"sink": outcome.sink, "delivered": outcome.delivered}
                        for outcome in outcomes
                    ],
                )

        return RecoveredIntroductionRun(
            negotiation_id=deal.negotiation_id,
            settlement_plan=deal.settlement_plan,
            start=transport.start,
            read=transport.read,
            record=record,
            deliver=deliver_copy if sinks is not None else None,
        )


def _trusted_listing(listing_id: str, signer: Any) -> tuple[dict[str, Any], str, str]:
    """The listing from the first configured registry that holds it."""
    from .common import (
        resolve_discovery_timeout,
        resolve_indexer_urls,
        resolve_registry_api_keys,
        resolve_registry_authorities,
    )

    urls = resolve_indexer_urls()
    authorities = resolve_registry_authorities(urls)
    api_keys = resolve_registry_api_keys()
    timeout = resolve_discovery_timeout()
    for url in urls:
        listing = fetch_listing_dict(
            url,
            listing_id,
            timeout=timeout,
            signer=signer,
            registry_authority=authorities[url],
            api_key=api_keys.get(url),
        )
        if listing is not None:
            return listing, url, authorities[url].authority
    raise typer.BadParameter(f"no configured registry holds listing {listing_id!r}")


def request_introduction(
    listing_id: str,
    option_id: str = typer.Option(...),
    duration_seconds: int = typer.Option(3600, min=1),
    expiration_seconds: int = typer.Option(3600, min=60),
    max_rounds: int = typer.Option(10, min=1),
) -> None:
    """Negotiate one exact introduction option: no payment, no provisioning."""

    identity = resolve_fresh_buyer_identity()
    listing, registry_url, registry_authority = _trusted_listing(
        listing_id, identity.signer
    )
    storefront_url = listing.get("storefront_url")
    principals = listing.get("publisher_principals")
    if not storefront_url or principals is None:
        raise typer.BadParameter("listing has no trusted storefront identity")
    publisher_principals = TrustedIdentitySet.model_validate(principals)
    options = [
        SettlementOption.model_validate(item)
        for item in listing.get("settlement_options") or ()
    ]
    matches = [option for option in options if option.option_id == option_id]
    if len(matches) != 1:
        raise typer.BadParameter("option_id must identify one advertised option")
    selected = matches[0]
    if selected.mechanism != CONTACT_MECHANISM or selected.rates:
        raise typer.BadParameter(
            "option is not a rateless introduction; use `buy` for priced options"
        )
    selection = SettlementSelection(
        mechanism=selected.mechanism,
        option_id=selected.option_id,
        expiration_unix=int(time.time()) + expiration_seconds,
    )
    run_log = RunLog.start(
        command="market vm request-introduction",
        profile_id=identity.profile_id,
        principal=identity.principal,
        domain="vm",
        listing_id=listing_id,
        option_id=option_id,
        duration_seconds=duration_seconds,
        seller_url=storefront_url,
        storefront_url=storefront_url,
        publisher_id=str(listing.get("publisher_id") or ""),
        publisher_principals=publisher_principals.model_dump(mode="json"),
        source_registry_url=registry_url,
        source_registry_authority=registry_authority,
    )
    outcome = negotiate_with_seller(
        seller_url=storefront_url,
        principal=identity.principal,
        signer=identity.signer,
        listing_id=listing_id,
        resolve_seller_principals=lambda: publisher_principals,
        initial_price=0.0,
        max_price=0.0,
        unit_count=duration_seconds / 3600,
        # An introduction provisions nothing, so it carries no access key.
        provision_terms=make_vm_provision_terms(
            duration_seconds=duration_seconds, ssh_public_key=""
        ),
        settlement_selection=selection,
        max_rounds=max_rounds,
    )
    if outcome.status != "agreed" or outcome.negotiation_id is None:
        run_log.end("exited", reason=outcome.reason)
        _echo({"run_id": run_log.run_id, **outcome.to_dict()})
        return
    if outcome.settlement_plan is None or len(outcome.settlement_plan.obligations) != 1:
        raise RuntimeError("accepted introduction has no exact settlement plan")
    obligation = outcome.settlement_plan.obligations[0].model_dump(mode="json")
    obligation_ref = derive_obligation_ref(outcome.negotiation_id, 0, obligation)
    run_log.event(
        "agreement_accepted",
        negotiation_id=outcome.negotiation_id,
        agreement_ref=outcome.negotiation_id,
        obligation_ref=obligation_ref,
        seller_principals=publisher_principals.model_dump(mode="json"),
        storefront_url=storefront_url,
        accepted_plan=outcome.settlement_plan.model_dump(mode="json"),
    )
    run_log.end(
        "agreed",
        negotiation_id=outcome.negotiation_id,
        agreed_amount=outcome.agreed_amount,
        accepted_provision_terms=(
            outcome.accepted_provision_terms.model_dump(mode="json")
            if outcome.accepted_provision_terms is not None
            else None
        ),
        **settlement_acceptance_fields(
            negotiation_id=outcome.negotiation_id,
            selection=outcome.settlement_selection,
            plan=outcome.settlement_plan,
        ),
    )
    _echo({"run_id": run_log.run_id, "obligation_ref": obligation_ref, **outcome.to_dict()})


__all__ = ["IntroductionContext", "request_introduction"]
