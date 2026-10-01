"""Bare-metal discovery, introduction and physical delivery commands."""

from __future__ import annotations

import json
import os
import time
import webbrowser
from collections.abc import Callable
from typing import Any

import typer
from arkhai_bare_metal import (
    BareMetalProvisionTerms,
)
from core_buyer import (
    BuyerActionHandler,
    IntroductionTransport,
    deliver_introduction,
    load_buyer_delivery_sinks,
    report_delivery,
    resolve_buyer_action_policy,
)
from core_buyer.deal_helpers import (
    load_deal_context,
    open_run_log,
    settlement_acceptance_fields,
)
from core_buyer.negotiation_client import negotiate_with_seller
from core_buyer.run_log import RunLog
from market_contact_exchange import MECHANISM as CONTACT_MECHANISM
from market_core.schemas import SettlementOption, SettlementPlan, SettlementSelection
from market_identity import TrustedIdentitySet
from market_settlement_runtime import derive_obligation_ref
from pydantic_core import to_jsonable_python

from .config import (
    fresh_identity,
    load_bare_metal_buyer_config,
    recovery_identity,
    registry_client,
)
from .fulfillment import BareMetalFulfillmentTransport

bare_metal_app = typer.Typer(
    no_args_is_help=True, help="Discover and settle trusted bare-metal listings."
)
settlement_app = typer.Typer(
    no_args_is_help=True,
    help="Mechanism-owned settlement utilities.",
)


def _json(value: Any) -> None:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    typer.echo(
        json.dumps(
            to_jsonable_python(value),
            ensure_ascii=True,
            sort_keys=True,
        )
    )


def _safe_projection(projection: dict[str, Any]) -> dict[str, Any]:
    safe = dict(projection)
    action = safe.pop("action", None)
    if isinstance(action, dict):
        safe["action_required"] = {
            key: action[key] for key in ("kind", "expires_at_unix") if key in action
        }
    return safe


def _recovered_deal(
    run_id: str,
    config_path: str | None,
) -> tuple[Any, Any, Callable[[], TrustedIdentitySet]]:
    identity = recovery_identity(run_id)
    buyer_config = load_bare_metal_buyer_config(config_path)
    expected_seller_url: list[str] = []

    def refresh(
        listing_id: str,
        publisher_id: str,
        source_registry_url: str,
        source_registry_authority: str,
    ) -> TrustedIdentitySet:
        if (
            source_registry_url != buyer_config.registry_url
            or source_registry_authority != buyer_config.registry_authority
        ):
            raise typer.BadParameter(
                "run-log registry authority does not match bare-metal buyer config"
            )
        with registry_client(buyer_config, identity) as client:
            listing = client.get_listing(listing_id)
        if (
            str(listing.publisher_id) != publisher_id
            or listing.publisher_principals is None
        ):
            raise typer.BadParameter(
                "trusted listing publisher no longer matches the accepted deal"
            )
        if expected_seller_url and listing.storefront_url != expected_seller_url[0]:
            raise typer.BadParameter(
                "trusted listing storefront no longer matches the accepted deal"
            )
        return listing.publisher_principals

    deal = load_deal_context(
        run_id,
        signer=identity.signer,
        refresh_publisher_principals=refresh,
    )
    expected_seller_url.append(deal.seller_url)
    return (
        deal,
        identity,
        lambda: refresh(
            deal.listing_id,
            deal.publisher_id,
            deal.source_registry_url,
            deal.source_registry_authority,
        ),
    )


def _recovered_transports(
    run_id: str,
    config_path: str | None,
) -> tuple[Any, Any, BareMetalFulfillmentTransport]:
    deal, identity, trust = _recovered_deal(run_id, config_path)
    fulfillment = BareMetalFulfillmentTransport(
        seller_url=deal.seller_url,
        principal=deal.buyer_principal,
        signer=identity.signer,
        resolve_seller_principals=trust,
    )
    return deal, identity, fulfillment


@bare_metal_app.command("list")
def list_bare_metal(
    config: str | None = typer.Option(None, "--config"),
    limit: int = typer.Option(50, min=1, max=200),
) -> None:
    """List authenticated bare-metal listings from the configured registry."""

    buyer_config = load_bare_metal_buyer_config(config)
    identity = fresh_identity()
    with registry_client(buyer_config, identity) as client:
        response = client.list_listings(limit=limit, virtualization_type="bare_metal")
    _json(response)


@bare_metal_app.command("show")
def show_bare_metal(
    listing_id: str,
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Retrieve one authenticated listing without selecting seller-owned facts."""

    buyer_config = load_bare_metal_buyer_config(config)
    identity = fresh_identity()
    with registry_client(buyer_config, identity) as client:
        listing = client.get_listing(listing_id)
    _json(listing)


def _handle_action(action: dict[str, Any], requested: str | None) -> None:
    policy = resolve_buyer_action_policy(
        requested,
        interactive=os.isatty(0) and os.isatty(1),
    )
    BuyerActionHandler(
        policy,
        open_url=webbrowser.open,
        print_url=typer.echo,
    ).handle(action)


@bare_metal_app.command("result")
def fulfillment_result(
    run_id: str = typer.Option(...),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Retrieve the durable buyer-safe physical result."""

    deal, _, fulfillment = _recovered_transports(run_id, config)
    _json(fulfillment.result(deal.negotiation_id))


@bare_metal_app.command("access")
def fulfillment_access(
    run_id: str = typer.Option(...),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Retrieve transient buyer-authorized SSH coordinates."""

    deal, _, fulfillment = _recovered_transports(run_id, config)
    _json(fulfillment.access(deal.negotiation_id))


@bare_metal_app.command("teardown")
def teardown_fulfillment(
    run_id: str = typer.Option(...),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Revoke buyer access and converge physical capacity release."""

    deal, _, fulfillment = _recovered_transports(run_id, config)
    _json(fulfillment.teardown(deal.negotiation_id))


def _parse_contact(entries: list[str]) -> dict[str, str]:
    payload: dict[str, str] = {}
    for entry in entries:
        key, separator, value = entry.partition("=")
        if not separator or not key.strip() or not value.strip():
            raise typer.BadParameter("contact entries must be key=value pairs")
        payload[key.strip()] = value.strip()
    return payload


def _recovered_introduction(
    run_id: str,
    config: str | None,
) -> tuple[Any, Any, IntroductionTransport, str]:
    deal, identity, trust = _recovered_deal(run_id, config)
    if deal.settlement_plan is None:
        raise typer.BadParameter("accepted run has no settlement plan")
    plan = SettlementPlan.model_validate(deal.settlement_plan)
    if len(plan.obligations) != 1 or plan.obligations[0].mechanism != (
        CONTACT_MECHANISM
    ):
        raise typer.BadParameter("accepted run is not an introduction deal")
    obligation_ref = derive_obligation_ref(
        deal.negotiation_id,
        0,
        plan.obligations[0].model_dump(mode="json"),
    )
    transport = IntroductionTransport(
        seller_url=deal.seller_url,
        principal=deal.buyer_principal,
        signer=identity.signer,
        resolve_seller_principals=trust,
    )
    return deal, identity, transport, obligation_ref


@bare_metal_app.command("request-introduction")
def request_introduction(
    listing_id: str,
    option_id: str = typer.Option(...),
    duration_seconds: int = typer.Option(3600, min=1),
    expiration_seconds: int = typer.Option(3600, min=60),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Negotiate one exact introduction option: no payment, no provisioning."""

    buyer_config = load_bare_metal_buyer_config(config)
    identity = fresh_identity()
    with registry_client(buyer_config, identity) as client:
        listing = client.get_listing(listing_id)
    if not listing.storefront_url or listing.publisher_principals is None:
        raise typer.BadParameter("listing has no trusted storefront identity")
    publisher_principals = listing.publisher_principals
    options = [
        SettlementOption.model_validate(item) for item in listing.settlement_options
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
        profile_id=identity.profile_id,
        principal=identity.principal,
        domain="bare_metal",
        listing_id=listing_id,
        option_id=option_id,
        duration_seconds=duration_seconds,
        seller_url=listing.storefront_url,
        storefront_url=listing.storefront_url,
        publisher_id=str(listing.publisher_id),
        publisher_principals=[
            item.model_dump(mode="json")
            for item in listing.publisher_principals.identities
        ],
        source_registry_url=buyer_config.registry_url,
        source_registry_authority=buyer_config.registry_authority,
    )
    outcome = negotiate_with_seller(
        seller_url=listing.storefront_url,
        principal=identity.principal,
        signer=identity.signer,
        listing_id=listing_id,
        resolve_seller_principals=lambda: publisher_principals,
        initial_price=0.0,
        max_price=0.0,
        unit_count=duration_seconds / 3600,
        provision_terms=BareMetalProvisionTerms(
            payload={
                "duration_seconds": duration_seconds,
                "access_method": "none",
            },
        ),
        settlement_selection=selection,
        max_rounds=buyer_config.default_max_rounds,
    )
    if outcome.status != "agreed" or outcome.negotiation_id is None:
        run_log.end("exited", reason=outcome.reason)
        _json({"run_id": run_log.run_id, **outcome.to_dict()})
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
        seller_principals=[
            item.model_dump(mode="json")
            for item in listing.publisher_principals.identities
        ],
        storefront_url=listing.storefront_url,
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
    _json(
        {
            "run_id": run_log.run_id,
            "obligation_ref": obligation_ref,
            **outcome.to_dict(),
        }
    )


def _deliver_locally(projection: Any, deal: Any, sinks: Any, log: Any) -> None:
    """Send the buyer's own copy onward, after the answer has been printed.

    Never fatal: the reveal is durable and re-readable, so a sink that fails
    costs a re-send and nothing else. Outcomes carry a sink name and a deal
    reference, never the contact payload.
    """

    outcomes = deliver_introduction(
        projection,
        sinks=sinks,
        agreement_ref=deal.negotiation_id,
        counterparty=_seller_principal(deal),
    )
    report_delivery(outcomes, sinks.warnings)
    if outcomes:
        log.event(
            "introduction_delivered",
            obligation_ref=projection.get("obligation_ref"),
            outcomes=[
                {"sink": outcome.sink, "delivered": outcome.delivered}
                for outcome in outcomes
            ],
        )


def _seller_principal(deal: Any) -> Any:
    principals = getattr(deal, "seller_principals", None)
    identities = getattr(principals, "identities", ()) if principals else ()
    return identities[0] if identities else None


@bare_metal_app.command("introduce")
def introduce(
    run_id: str = typer.Option(...),
    contact: list[str] = typer.Option(
        ...,
        "--contact",
        help="Your contact payload as key=value entries (repeatable).",
    ),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Start the introduction: supply your contact, receive the seller's."""

    # Built before the reveal: a misconfigured sink is the operator's own
    # mistake and should surface before anything irreversible happens.
    sinks = load_buyer_delivery_sinks(config)
    deal, identity, transport, obligation_ref = _recovered_introduction(run_id, config)
    projection = transport.start(
        negotiation_id=deal.negotiation_id,
        obligation_ref=obligation_ref,
        contact_payload=_parse_contact(contact),
    )
    log = open_run_log(
        run_id,
        signer=identity.signer,
        profile_id=identity.profile_id,
    )
    log.event("introduction_revealed", obligation_ref=obligation_ref)
    _json(projection)
    _deliver_locally(projection, deal, sinks, log)


@bare_metal_app.command("introduction")
def read_introduction(
    run_id: str = typer.Option(...),
    deliver: bool = typer.Option(
        False,
        "--deliver",
        help="Send the introduction to your configured sinks again.",
    ),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Re-read the revealed introduction; the reveal is durable."""

    sinks = load_buyer_delivery_sinks(config) if deliver else None
    deal, identity, transport, obligation_ref = _recovered_introduction(run_id, config)
    projection = transport.read(obligation_ref=obligation_ref)
    _json(projection)
    if sinks is not None:
        log = open_run_log(
            run_id,
            signer=identity.signer,
            profile_id=identity.profile_id,
        )
        _deliver_locally(projection, deal, sinks, log)


def register_commands(app: object) -> None:
    """Register the bare-metal group on the core market application."""

    add_typer = getattr(app, "add_typer")
    add_typer(bare_metal_app, name="bare-metal")
    add_typer(settlement_app, name="settlement")
