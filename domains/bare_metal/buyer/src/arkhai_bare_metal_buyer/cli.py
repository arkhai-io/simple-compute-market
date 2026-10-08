"""Bare-metal discovery, introduction and physical delivery commands."""

from __future__ import annotations

import json
import base64
import os
import time
import webbrowser
from collections.abc import Callable
from typing import Any

import typer
from arkhai_bare_metal import (
    BARE_METAL_OFFERING_MODE,
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
from core_buyer.introductions import IntroductionPayloadsDeleted
from core_buyer.negotiation_client import negotiate_with_seller
from market_contact_exchange import MECHANISM as CONTACT_MECHANISM
from market_contact_exchange import (
    RecoveredIntroductionRun,
    create_contact_command_group,
)
from core_buyer.deal_helpers import (
    load_deal_context,
    open_run_log,
    settlement_acceptance_fields,
)
from core_buyer.run_log import RunLog
from market_core.schemas import (
    SettlementOption,
    SettlementSelection,
    compute_rate_total,
)
from market_identity import TrustedIdentitySet
from pydantic_core import to_jsonable_python
from registry_client.query import compile_resource_query
from market_settlement_runtime import derive_obligation_ref

from .config import (
    fresh_identity,
    load_bare_metal_buyer_config,
    recovery_identity,
    registry_client,
)
from .fulfillment import BareMetalFulfillmentTransport
from market_arkhai_payments import PaymentApproval

from .arkhai_payments import BareMetalSettlementTransport

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
    resource: str | None = typer.Option(
        None,
        "--resource",
        help=(
            "Filter by hardware and region in the registry's own query vocabulary, "
            "e.g. 'gpu_model=H200 gpu_count>=8'."
        ),
    ),
) -> None:
    """List authenticated bare-metal listings from the configured registry.

    A resource query is compiled against the registry's published filter
    specification and sent with its ETag, so a field the registry does not
    declare is refused before any listing is read, and a specification that
    changed since is refused by the registry rather than silently reinterpreted.
    """

    buyer_config = load_bare_metal_buyer_config(config)
    identity = fresh_identity()
    with registry_client(buyer_config, identity) as client:
        params = bare_metal_listing_params(client, resource, registry_url=buyer_config.registry_url)
        response = client.list_listings(limit=limit, **params)
    _json(response)


def bare_metal_listing_params(
    client: Any, resource: str | None, *, registry_url: str
) -> dict[str, Any]:
    """The query parameters one bare-metal listing read sends.

    Always restricted to bare metal; with ``resource``, also the compiled query
    and the ETag of the filter specification it was compiled against.
    """
    params: dict[str, Any] = {"offering_mode": BARE_METAL_OFFERING_MODE}
    if resource is None:
        return params
    try:
        compiled = compile_resource_query(
            resource, filter_spec=client.get_filter_spec(), registry_url=registry_url
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc), param_hint="--resource") from exc
    return {**params, **compiled.as_params(), "etag": compiled.etag}


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




class _IntroductionContext:
    """The bare-metal buyer's run recovery and delivery for the introduction commands."""

    deleted_error = IntroductionPayloadsDeleted

    def recover(
        self, run_id: str, config: str | None, *, deliver: bool
    ) -> RecoveredIntroductionRun:
        sinks = load_buyer_delivery_sinks(config) if deliver else None
        deal, identity, trust = _recovered_deal(run_id, config)
        transport = IntroductionTransport(
            seller_url=deal.seller_url,
            principal=deal.buyer_principal,
            signer=identity.signer,
            resolve_seller_principals=trust,
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


settlement_app.add_typer(
    create_contact_command_group(_IntroductionContext),
    name="contact",
)


@bare_metal_app.command("buy")
def buy_bare_metal(
    listing_id: str,
    option_id: str = typer.Option(...),
    ssh_public_key: str = typer.Option(..., "--ssh-public-key"),
    duration_seconds: int = typer.Option(3600, min=1),
    payment_timeout_seconds: float = typer.Option(300.0, min=1.0, max=3600.0),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Approve one exact Arkhai option and provision after its receipt verifies."""
    buyer_config = load_bare_metal_buyer_config(config)
    if buyer_config.payer_account is None:
        raise typer.BadParameter("bare-metal buyer config requires payer_account")
    if buyer_config.arkhai_payments is None or not buyer_config.arkhai_payments.enabled:
        raise typer.BadParameter(
            "bare-metal buyer config requires enabled arkhai_payments"
        )
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
    if selected.mechanism != "arkhai.payments.v1" or len(selected.rates) != 1:
        raise typer.BadParameter("buy requires one priced arkhai.payments.v1 option")
    rate = selected.rates[0]
    if rate.per != "hour":
        raise typer.BadParameter(
            "bare-metal purchase currently requires an hourly option"
        )
    amount = compute_rate_total(rate, duration_seconds)
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
            principal.model_dump(mode="json")
            for principal in listing.publisher_principals.identities
        ],
        source_registry_url=buyer_config.registry_url,
        source_registry_authority=buyer_config.registry_authority,
    )
    selection = SettlementSelection(
        mechanism=selected.mechanism,
        option_id=selected.option_id,
        params={"payer_account": buyer_config.payer_account},
    )
    outcome = negotiate_with_seller(
        seller_url=listing.storefront_url,
        principal=identity.principal,
        signer=identity.signer,
        listing_id=listing_id,
        resolve_seller_principals=lambda: listing.publisher_principals,
        initial_price=amount,
        max_price=amount,
        unit_count=duration_seconds / 3600,
        provision_terms=BareMetalProvisionTerms(
            payload={
                "duration_seconds": duration_seconds,
                "access_method": "ssh",
                "ssh_public_key": ssh_public_key,
            },
        ),
        settlement_selection=selection,
        max_rounds=buyer_config.default_max_rounds,
    )
    if outcome.status != "agreed" or outcome.negotiation_id is None:
        run_log.end("exited", reason=outcome.reason)
        _json({"run_id": run_log.run_id, **outcome.to_dict()})
        return
    if (
        outcome.agreement is None
        or outcome.settlement_data is None
        or not outcome.agreement_bytes
    ):
        raise RuntimeError(
            "accepted payment negotiation omitted its Agreement or mandate"
        )
    agreement_bytes = base64.b64decode(outcome.agreement_bytes, validate=True)
    run_log.event(
        "agreement_accepted",
        negotiation_id=outcome.negotiation_id,
        agreement_ref=outcome.negotiation_id,
        settlement_data=outcome.settlement_data,
        agreement_bytes=outcome.agreement_bytes,
        **settlement_acceptance_fields(
            negotiation_id=outcome.negotiation_id,
            selection=outcome.settlement_selection,
            plan=outcome.settlement_plan,
        ),
    )
    transaction = PaymentApproval(
        buyer_config.arkhai_payments, buyer_config.payer_account
    ).approve(
        agreement_bytes,
        outcome.settlement_data,
        timeout=payment_timeout_seconds,
    )
    run_log.event("payment_approved", transaction_id=transaction)
    settlement = BareMetalSettlementTransport(
        seller_url=listing.storefront_url,
        principal=identity.principal,
        signer=identity.signer,
        resolve_seller_principals=lambda: listing.publisher_principals,
        timeout=buyer_config.timeout_seconds,
    )
    # Settlement starts delivery once the seller verifies the receipt; the buyer
    # retries while the seller reports no payment evidence yet.
    deadline = time.monotonic() + payment_timeout_seconds
    while True:
        fulfillment = settlement.settle(outcome.negotiation_id)
        if fulfillment.get("status") != "pending":
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("seller has not observed the verified payment receipt")
        time.sleep(min(1.0, remaining))
    if fulfillment.get("settlement_ref") != transaction:
        raise RuntimeError("seller settled a different payment transaction")
    run_log.end(
        "agreed",
        negotiation_id=outcome.negotiation_id,
        agreed_amount=outcome.agreed_amount,
        transaction_id=transaction,
        fulfillment=fulfillment,
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
            "transaction_id": transaction,
            "fulfillment": fulfillment,
        }
    )


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


def _seller_principal(deal: Any) -> Any:
    principals = getattr(deal, "seller_principals", None)
    identities = getattr(principals, "identities", ()) if principals else ()
    return identities[0] if identities else None


def register_commands(app: object) -> None:
    """Register the bare-metal group on the core market application."""

    add_typer = getattr(app, "add_typer")
    add_typer(bare_metal_app, name="bare-metal")
    add_typer(settlement_app, name="settlement")
