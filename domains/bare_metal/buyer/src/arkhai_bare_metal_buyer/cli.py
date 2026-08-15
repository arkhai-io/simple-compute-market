"""Bare-metal discovery and schema-opaque hosted settlement commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from arkhai_bare_metal import (
    BareMetalBuyerDemand,
    decode_bare_metal_hosted_option_facts,
    BareMetalListing,
    make_bare_metal_provision_terms,
    validate_buyer_selection,
)
from core_buyer import HostedSettlementTransport
from core_buyer.negotiation_client import negotiate_with_seller
from core_buyer.run_log import RunLog
from market_core.schemas import SettlementOption, SettlementSelection
from market_identity import Identity, IdentityScheme, TrustedIdentitySet
from market_settlement_runtime import derive_obligation_ref

from .config import (
    fresh_identity,
    load_bare_metal_buyer_config,
    recovery_identity,
    registry_client,
)

bare_metal_app = typer.Typer(
    no_args_is_help=True, help="Discover and settle trusted bare-metal listings."
)


def _json(value: Any) -> None:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    elif hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    typer.echo(json.dumps(value, ensure_ascii=True, sort_keys=True))


def _safe_projection(projection: dict[str, Any]) -> dict[str, Any]:
    safe = dict(projection)
    action = safe.pop("action", None)
    if isinstance(action, dict):
        safe["action_required"] = {
            key: action[key] for key in ("kind", "expires_at_unix") if key in action
        }
    return safe


def _principal(value: str) -> Identity:
    try:
        scheme, identifier = value.split(":", 1)
        return Identity(scheme=IdentityScheme(scheme), identifier=identifier)
    except (ValueError, TypeError) as exc:
        raise typer.BadParameter("principal must be scheme:identifier") from exc


def _transport(
    *, seller_url: str, seller_principals: list[str], run_id: str
) -> HostedSettlementTransport:
    identity = recovery_identity(run_id)
    trust = TrustedIdentitySet(
        identities=tuple(_principal(value) for value in seller_principals)
    )
    return HostedSettlementTransport(
        seller_url=seller_url,
        principal=identity.principal,
        signer=identity.signer,
        resolve_seller_principals=lambda: trust,
    )


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


@bare_metal_app.command("buy")
def buy_bare_metal(
    listing_id: str,
    option_id: str = typer.Option(...),
    ssh_public_key_file: str = typer.Option(...),
    duration_seconds: int = typer.Option(..., min=1),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Negotiate one exact authenticated listing and persist recovery identity."""

    buyer_config = load_bare_metal_buyer_config(config)
    identity = fresh_identity()
    with registry_client(buyer_config, identity) as client:
        listing = client.get_listing(listing_id)
    if not listing.storefront_url or listing.publisher_principals is None:
        raise typer.BadParameter("listing has no trusted storefront identity")
    options = [
        SettlementOption.model_validate(item) for item in listing.settlement_options
    ]
    matches = [option for option in options if option.option_id == option_id]
    if len(matches) != 1:
        raise typer.BadParameter("option_id must identify one advertised option")
    selected = matches[0]
    if not selected.rates or selected.rates[0].per != "hour":
        raise typer.BadParameter("bare-metal listing must advertise an hourly rate")
    facts = decode_bare_metal_hosted_option_facts(selected.params.get("bare_metal"))
    selection = SettlementSelection(
        mechanism=selected.mechanism,
        option_id=selected.option_id,
        expiration_unix=int(facts.funding_deadline.timestamp()),
    )
    try:
        ssh_public_key = Path(ssh_public_key_file).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise typer.BadParameter("cannot read SSH public key file") from exc
    demand = BareMetalBuyerDemand(
        duration_seconds=duration_seconds,
        ssh_public_key=ssh_public_key,
        settlement=selection,
        allow_off_session=selected.params.get("interaction") == "off_session",
    )
    validate_buyer_selection(demand=demand, advertised_options=options)
    trusted_listing = BareMetalListing.model_validate(listing.offer)
    if (
        trusted_listing.site_id != facts.site_id
        or trusted_listing.physical_host_id != facts.physical_resource_id
    ):
        raise typer.BadParameter("hosted option conflicts with trusted listing")
    run_log = RunLog.start(
        profile_id=identity.profile_id,
        principal=identity.principal,
        domain="bare_metal",
        listing_id=listing_id,
        option_id=option_id,
        funding_profile=selected.params.get("funding_profile"),
    )
    outcome = negotiate_with_seller(
        seller_url=listing.storefront_url,
        principal=identity.principal,
        signer=identity.signer,
        listing_id=listing_id,
        resolve_seller_principals=lambda: listing.publisher_principals,
        initial_price=float(selected.rates[0].value),
        max_price=float(selected.rates[0].value),
        unit_count=duration_seconds / 3600,
        provision_terms=make_bare_metal_provision_terms(
            duration_seconds=duration_seconds,
            ssh_public_key=ssh_public_key,
        ),
        settlement_selection=selection,
        max_rounds=buyer_config.default_max_rounds,
    )
    if outcome.status != "agreed" or outcome.negotiation_id is None:
        run_log.end("exited", reason=outcome.reason)
        _json({"run_id": run_log.run_id, **outcome.to_dict()})
        return
    if outcome.settlement_plan is None or len(outcome.settlement_plan.obligations) != 1:
        raise RuntimeError("accepted bare-metal agreement has no exact settlement plan")
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
    _json(
        {
            "run_id": run_log.run_id,
            "obligation_ref": obligation_ref,
            **outcome.to_dict(),
        }
    )


@bare_metal_app.command("start")
def start_hosted(
    run_id: str = typer.Option(...),
    seller_url: str = typer.Option(...),
    seller_principal: list[str] = typer.Option(...),
    negotiation_id: str = typer.Option(...),
    obligation_ref: str = typer.Option(...),
    funding_authorization_ref: str = typer.Option(...),
) -> None:
    """Start the exact accepted hosted obligation using its retained run signer."""

    projection = _transport(
        seller_url=seller_url,
        seller_principals=seller_principal,
        run_id=run_id,
    ).start(
        negotiation_id=negotiation_id,
        obligation_ref=obligation_ref,
        funding_authorization_ref=funding_authorization_ref,
    )
    _json(_safe_projection(projection))


@bare_metal_app.command("status")
def hosted_status(
    run_id: str = typer.Option(...),
    seller_url: str = typer.Option(...),
    seller_principal: list[str] = typer.Option(...),
    settlement_ref: str = typer.Option(...),
) -> None:
    """Retrieve current provider-neutral settlement and physical projection."""

    projection = _transport(
        seller_url=seller_url,
        seller_principals=seller_principal,
        run_id=run_id,
    ).status(settlement_ref)
    _json(_safe_projection(projection))


@bare_metal_app.command("reclaim")
def reclaim_hosted(
    run_id: str = typer.Option(...),
    seller_url: str = typer.Option(...),
    seller_principal: list[str] = typer.Option(...),
    settlement_ref: str = typer.Option(...),
) -> None:
    """Request financial reclaim without inferring lease teardown."""

    projection = _transport(
        seller_url=seller_url,
        seller_principals=seller_principal,
        run_id=run_id,
    ).reclaim(settlement_ref)
    _json(_safe_projection(projection))


def register_commands(app: object) -> None:
    """Register the bare-metal group on the core market application."""

    add_typer = getattr(app, "add_typer")
    add_typer(bare_metal_app, name="bare-metal")
