"""Bare-metal discovery and schema-opaque hosted settlement commands."""

from __future__ import annotations

import json
import os
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from arkhai_bare_metal import (
    BareMetalBuyerDemand,
    BareMetalListing,
    decode_bare_metal_hosted_option_facts,
    make_bare_metal_provision_terms,
    validate_buyer_selection,
)
from core_buyer import (
    BuyerActionHandler,
    HostedSettlementTransport,
    resolve_buyer_action_policy,
)
from core_buyer.deal_helpers import (
    load_deal_context,
    open_run_log,
    settlement_acceptance_fields,
)
from core_buyer.negotiation_client import negotiate_with_seller
from core_buyer.run_log import RunLog
from market_core.schemas import SettlementOption, SettlementPlan, SettlementSelection
from market_hosted_settlement import FundingMode, FundingSelection
from market_identity import TrustedIdentitySet
from market_settlement_runtime import derive_obligation_ref

from .config import (
    fresh_identity,
    load_bare_metal_buyer_config,
    recovery_identity,
    registry_client,
)
from .fulfillment import BareMetalFulfillmentTransport
from .funding import prepare_funding_authorization

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
) -> tuple[Any, Any, HostedSettlementTransport, BareMetalFulfillmentTransport]:
    deal, identity, trust = _recovered_deal(run_id, config_path)
    hosted = HostedSettlementTransport(
        seller_url=deal.seller_url,
        principal=deal.buyer_principal,
        signer=identity.signer,
        resolve_seller_principals=trust,
    )
    fulfillment = BareMetalFulfillmentTransport(
        seller_url=deal.seller_url,
        principal=deal.buyer_principal,
        signer=identity.signer,
        resolve_seller_principals=trust,
    )
    return deal, identity, hosted, fulfillment


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


def _start_or_resume(
    *,
    run_id: str,
    config: str | None,
    funding_mode: str,
    instrument_ref: str | None,
    automatic_funding: bool,
    action: str | None,
) -> tuple[Any, Any, HostedSettlementTransport, BareMetalFulfillmentTransport, str]:
    deal, identity, hosted, fulfillment = _recovered_transports(run_id, config)
    if deal.settlement_plan is None:
        raise typer.BadParameter("accepted run has no settlement plan")
    plan = SettlementPlan.model_validate(deal.settlement_plan)
    if len(plan.obligations) != 1 or plan.obligations[0].mechanism != "fiat.stripe.v1":
        raise typer.BadParameter("accepted run has no exact hosted obligation")
    obligation = plan.obligations[0].model_dump(mode="json")
    obligation_ref = derive_obligation_ref(deal.negotiation_id, 0, obligation)
    try:
        selection = FundingSelection(
            mode=FundingMode(funding_mode),
            instrument_ref=instrument_ref,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    log = open_run_log(
        run_id,
        signer=identity.signer,
        profile_id=identity.profile_id,
    )
    authorization_ref = deal.funding_authorization_ref(obligation_ref)
    if authorization_ref is None:
        authorization = prepare_funding_authorization(
            buyer_profile_id=str(identity.profile_id),
            principal=deal.buyer_principal,
            signer=identity.signer,
            obligation_ref=obligation_ref,
            obligation=obligation,
            selection=selection,
            automatic=automatic_funding,
            action=action,
        )
        authorization_ref = authorization.funding_authorization_ref
        log.event(
            "funding_authorized",
            obligation_ref=obligation_ref,
            funding_profile=authorization.funding_profile.value,
            funding_authorization_ref=authorization_ref,
            expires_at_unix=authorization.expires_at_unix,
        )
    settlement_ref = deal.settlement_ref
    if settlement_ref is None:
        started = hosted.start(
            negotiation_id=deal.negotiation_id,
            obligation_ref=obligation_ref,
            funding_authorization_ref=authorization_ref,
        )
        settlement_ref = started.get("settlement_ref")
        if not isinstance(settlement_ref, str) or not settlement_ref:
            raise RuntimeError("storefront returned no hosted settlement reference")
        action_body = started.get("action")
        action_metadata = action_body if isinstance(action_body, dict) else {}
        log.event(
            "settlement_started",
            settlement_ref=settlement_ref,
            obligation_ref=obligation_ref,
            funding_authorization_ref=authorization_ref,
            action_kind=action_metadata.get("kind"),
            action_expires_at_unix=action_metadata.get("expires_at_unix"),
        )
        if isinstance(action_body, dict):
            _handle_action(action_body, action)
    return deal, identity, hosted, fulfillment, settlement_ref


@bare_metal_app.command("start")
def start_hosted(
    run_id: str = typer.Option(...),
    config: str | None = typer.Option(None, "--config"),
    funding_mode: str = typer.Option("interactive", "--funding-mode"),
    instrument_ref: str | None = typer.Option(None, "--instrument-ref"),
    automatic_funding: bool = typer.Option(False, "--automatic-funding"),
    action: str | None = typer.Option(None, "--action"),
) -> None:
    """Authorize and start the exact accepted hosted obligation."""

    _, _, hosted, _, settlement_ref = _start_or_resume(
        run_id=run_id,
        config=config,
        funding_mode=funding_mode,
        instrument_ref=instrument_ref,
        automatic_funding=automatic_funding,
        action=action,
    )
    _json(_safe_projection(hosted.status(settlement_ref)))


@bare_metal_app.command("complete")
def complete_hosted(
    run_id: str = typer.Option(...),
    config: str | None = typer.Option(None, "--config"),
    funding_mode: str = typer.Option("interactive", "--funding-mode"),
    instrument_ref: str | None = typer.Option(None, "--instrument-ref"),
    automatic_funding: bool = typer.Option(False, "--automatic-funding"),
    action: str | None = typer.Option(None, "--action"),
    poll_interval: float = typer.Option(2.0, min=0.1),
    timeout: float = typer.Option(1800.0, min=1.0),
) -> None:
    """Fund, provision, and return buyer-authorized whole-host access."""

    deal, _, hosted, fulfillment, settlement_ref = _start_or_resume(
        run_id=run_id,
        config=config,
        funding_mode=funding_mode,
        instrument_ref=instrument_ref,
        automatic_funding=automatic_funding,
        action=action,
    )
    settlement = hosted.wait(
        settlement_ref,
        poll_interval=poll_interval,
        total_timeout=timeout,
        on_action=lambda value: _handle_action(dict(value), action),
    )
    if settlement.get("status") not in {"ready", "collected"}:
        raise RuntimeError(
            "hosted settlement did not reach buyer-ready state: "
            f"{settlement.get('status')!r}"
        )
    deadline = time.monotonic() + timeout
    while True:
        physical = fulfillment.status(deal.negotiation_id)
        state = physical.get("state")
        if state == "active":
            break
        if state in {"failed", "teardown_failed", "torn_down", "released"}:
            raise RuntimeError(f"bare-metal fulfillment ended in state {state!r}")
        if time.monotonic() >= deadline:
            raise TimeoutError("bare-metal fulfillment did not become active")
        time.sleep(poll_interval)
    _json(
        {
            "run_id": run_id,
            "settlement": _safe_projection(settlement),
            "fulfillment": physical,
            "result": fulfillment.result(deal.negotiation_id),
            "access": fulfillment.access(deal.negotiation_id),
        }
    )


@bare_metal_app.command("status")
def hosted_status(
    run_id: str = typer.Option(...),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Retrieve current provider-neutral settlement and physical projection."""

    deal, _, hosted, fulfillment = _recovered_transports(run_id, config)
    if deal.settlement_ref is None:
        raise typer.BadParameter("run has no started hosted settlement")
    _json(
        {
            "settlement": _safe_projection(hosted.status(deal.settlement_ref)),
            "fulfillment": fulfillment.status(deal.negotiation_id),
        }
    )


@bare_metal_app.command("result")
def fulfillment_result(
    run_id: str = typer.Option(...),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Retrieve the durable buyer-safe physical result."""

    deal, _, _, fulfillment = _recovered_transports(run_id, config)
    _json(fulfillment.result(deal.negotiation_id))


@bare_metal_app.command("access")
def fulfillment_access(
    run_id: str = typer.Option(...),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Retrieve transient buyer-authorized SSH coordinates."""

    deal, _, _, fulfillment = _recovered_transports(run_id, config)
    _json(fulfillment.access(deal.negotiation_id))


@bare_metal_app.command("teardown")
def teardown_fulfillment(
    run_id: str = typer.Option(...),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Revoke buyer access and converge physical capacity release."""

    deal, _, _, fulfillment = _recovered_transports(run_id, config)
    _json(fulfillment.teardown(deal.negotiation_id))


@bare_metal_app.command("reclaim")
def reclaim_hosted(
    run_id: str = typer.Option(...),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Request financial reclaim without inferring lease teardown."""

    deal, _, hosted, _ = _recovered_transports(run_id, config)
    if deal.settlement_ref is None:
        raise typer.BadParameter("run has no started hosted settlement")
    _json(_safe_projection(hosted.reclaim(deal.settlement_ref)))


def register_commands(app: object) -> None:
    """Register the bare-metal group on the core market application."""

    add_typer = getattr(app, "add_typer")
    add_typer(bare_metal_app, name="bare-metal")
