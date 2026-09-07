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
    BareMetalProvisionTerms,
    BareMetalTerms,
    CanonicalPrincipal,
    decode_bare_metal_hosted_option_facts,
    make_bare_metal_provision_terms,
    validate_accepted_hosted_plan,
    validate_buyer_selection,
)
from core_buyer import (
    BuyerActionHandler,
    HostedSettlementTransport,
    IntroductionTransport,
    deliver_introduction,
    load_buyer_delivery_sinks,
    report_delivery,
    resolve_buyer_action_policy,
)
from core_buyer.negotiation_client import negotiate_with_seller
from core_buyer.profile_service import BuyerProfileService
from market_contact_exchange import MECHANISM as CONTACT_MECHANISM
from core_buyer.deal_helpers import (
    load_deal_context,
    open_run_log,
    settlement_acceptance_fields,
)
from market_hosted_settlement import (
    FundingMode,
    FundingSelection,
    PayerCommandContext,
    create_stripe_command_group,
    payer_command_context_from_config,
)
from core_buyer.run_log import RunLog
from market_core.schemas import SettlementOption, SettlementPlan, SettlementSelection
from market_identity import TrustedIdentitySet
from pydantic_core import to_jsonable_python
from market_alkahest.schemas import accepted_recipient_address
from market_settlement_runtime import derive_obligation_ref

from .config import (
    fresh_identity,
    load_bare_metal_buyer_config,
    recovery_identity,
    registry_client,
)
from .fulfillment import BareMetalFulfillmentTransport
from .funding import prepare_funding_authorization, stripe_config_from_user_config
from .escrow import (
    BareMetalEscrowError,
    fund_accepted_obligation,
    funding_address,
    resolve_buyer_chain,
)
from .settlement_composition import (
    ALKAHEST_MECHANISM,
    HOSTED_MECHANISM,
    BareMetalBuyerMechanismError,
    bare_metal_escrow_proposal,
    validate_accepted_alkahest_plan,
)

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


def _validate_hosted_option_binding(
    listing: BareMetalListing,
    *,
    physical_host_id: str | None,
) -> None:
    if listing.physical_host_id != physical_host_id:
        raise typer.BadParameter("hosted option conflicts with trusted listing")


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
    escrow_expiration_seconds: int = typer.Option(
        3600,
        min=1,
        help=(
            "Alkahest only: seconds from now until the buyer's escrow may be "
            "reclaimed. An advertised escrow entry carries no expiry."
        ),
    ),
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
    # The rail is decided by the option the buyer selected, not by the domain.
    mechanism = selected.mechanism
    if mechanism not in (ALKAHEST_MECHANISM, HOSTED_MECHANISM):
        raise typer.BadParameter(
            f"settlement mechanism {mechanism!r} is not supported by this buyer"
        )

    trusted_listing = BareMetalListing.model_validate(listing.offer)
    escrow_proposal = None
    if mechanism == ALKAHEST_MECHANISM:
        # An advertised escrow entry carries no expiry, so the buyer sets the
        # instant its own funds become reclaimable.
        expiration_unix = int(time.time()) + escrow_expiration_seconds
        try:
            escrow_proposal = bare_metal_escrow_proposal(
                listing=listing.offer,
                option=selected,
                expiration_unix=expiration_unix,
            )
        except BareMetalBuyerMechanismError as exc:
            raise typer.BadParameter(str(exc)) from exc
        # When the seller advertises the address it will be paid at, the buyer
        # pins it. Without one the payee is the seller's own choice at
        # acceptance time and cannot be checked against anything the listing
        # said; the rest of the obligation is still re-derived from it.
        advertised_payout = accepted_recipient_address(escrow_proposal)
        # The same address set the funding call will use, so the re-derived
        # obligation is compared against the contracts actually deployed here.
        try:
            escrow_address_config_path = resolve_buyer_chain(
                escrow_proposal.chain_name
            ).alkahest_address_config_path
        except BareMetalEscrowError as exc:
            raise typer.BadParameter(str(exc)) from exc
        # On-chain funding is an act the buyer performs; there is no saved
        # instrument to authorize off-session.
        allow_off_session = False
    else:
        facts = decode_bare_metal_hosted_option_facts(selected.params.get("bare_metal"))
        expiration_unix = int(facts.funding_deadline.timestamp())
        allow_off_session = selected.params.get("interaction") == "saved_instrument"

    selection = SettlementSelection(
        mechanism=selected.mechanism,
        option_id=selected.option_id,
        expiration_unix=expiration_unix,
    )
    try:
        ssh_public_key = Path(ssh_public_key_file).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise typer.BadParameter("cannot read SSH public key file") from exc
    demand = BareMetalBuyerDemand(
        duration_seconds=duration_seconds,
        ssh_public_key=ssh_public_key,
        settlement=selection,
        allow_off_session=allow_off_session,
    )
    if mechanism == ALKAHEST_MECHANISM:
        hosted_option = None
    else:
        hosted_option = validate_buyer_selection(
            demand=demand, advertised_options=options
        )
        _validate_hosted_option_binding(
            trusted_listing,
            physical_host_id=facts.physical_host_id,
        )
    accepted_terms = BareMetalTerms(
        machine_id=trusted_listing.machine_id,
        physical_host_id=trusted_listing.physical_host_id,
        duration_seconds=demand.duration_seconds,
        access_method=demand.access_method,
        ssh_public_key=demand.ssh_public_key,
        listing_ref=listing_id,
    )
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
        publisher_principals=listing.publisher_principals.model_dump(mode="json"),
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
        policy_params={"_selected_settlement_option": selected.model_dump(mode="json")},
        validate_advertised_plan=(
            (
                lambda plan: validate_accepted_alkahest_plan(
                    plan=plan,
                    proposal=escrow_proposal,
                    duration_seconds=duration_seconds,
                    address_config_path=escrow_address_config_path,
                    seller_payout_address=advertised_payout,
                )
            )
            if mechanism == ALKAHEST_MECHANISM
            else (
                lambda plan: validate_accepted_hosted_plan(
                    plan=plan,
                    listing_id=listing_id,
                    option=hosted_option,
                    demand=demand,
                    buyer_principal=CanonicalPrincipal.model_validate(
                        identity.principal.model_dump(mode="json")
                    ),
                    seller_principal=CanonicalPrincipal.model_validate(
                        plan.seller_principal
                    ),
                    seller_terms=accepted_terms,
                )
            )
        ),
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
            to_jsonable_python(outcome.accepted_provision_terms)
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


def _dispatch_payer_action(action: Any, requested: str | None) -> None:
    _handle_action(
        action.model_dump(mode="json", exclude_none=True),
        requested,
    )


def _payer_command_context() -> PayerCommandContext:
    return payer_command_context_from_config(
        stripe_config_from_user_config(),
        profiles=BuyerProfileService(),
        dispatch_action=_dispatch_payer_action,
    )


settlement_app.add_typer(
    create_stripe_command_group(_payer_command_context),
    name="stripe",
)


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


def _accepted_alkahest_obligation(deal: Any) -> tuple[dict[str, Any], str]:
    """The one accepted Alkahest obligation and its reference."""
    if deal.settlement_plan is None:
        raise typer.BadParameter("accepted run has no settlement plan")
    plan = SettlementPlan.model_validate(deal.settlement_plan)
    if len(plan.obligations) != 1 or plan.obligations[0].mechanism != ALKAHEST_MECHANISM:
        raise typer.BadParameter("accepted run has no exact Alkahest obligation")
    obligation = plan.obligations[0].model_dump(mode="json")
    return obligation, derive_obligation_ref(deal.negotiation_id, 0, obligation)


@bare_metal_app.command("fund")
def fund_alkahest(
    run_id: str = typer.Option(...),
    buyer_evm_address: str = typer.Option(
        ...,
        help="The address funding the escrow; the seller records it as the payer.",
    ),
    private_key_env: str = typer.Option(
        "BARE_METAL_BUYER_EVM_PRIVATE_KEY",
        help="Environment variable holding the funding key. Never passed as an argument.",
    ),
    escrow_uid: str | None = typer.Option(
        None,
        help="Adopt an escrow already funded for this run instead of creating one.",
    ),
    config: str | None = typer.Option(None, "--config"),
) -> None:
    """Fund the accepted Alkahest obligation, have it verified, and begin.

    One command because the three steps are not independently useful: a funded
    escrow the seller has not verified reserves nothing, and a verified
    settlement that never begins leaves paid-for capacity unclaimed. Re-running
    with `--escrow-uid` resumes after a partial run rather than funding twice.
    """
    deal, identity, _, fulfillment = _recovered_transports(run_id, config)
    obligation, obligation_ref = _accepted_alkahest_obligation(deal)
    log = open_run_log(run_id, signer=identity.signer, profile_id=identity.profile_id)

    # The run log is the record of what this run already spent. Reading it
    # before funding is what stops a rerun after a crash from creating a second
    # escrow and paying twice for one agreement.
    if escrow_uid is None:
        escrow_uid = getattr(deal, "escrow_uid", None)
        if escrow_uid:
            typer.echo(
                f"adopting the escrow this run already created: {escrow_uid}",
                err=True,
            )

    if escrow_uid is None:
        private_key = os.environ.get(private_key_env, "").strip()
        if not private_key:
            raise typer.BadParameter(
                f"{private_key_env} must hold the buyer's funding key"
            )
        try:
            derived = funding_address(private_key)
        except BareMetalEscrowError as exc:
            raise typer.BadParameter(str(exc)) from exc
        if derived.lower() != buyer_evm_address.strip().lower():
            raise typer.BadParameter(
                "--buyer-evm-address is not the address the funding key controls; "
                "the seller would record a payer that did not fund the escrow"
            )
        try:
            escrow_uid = fund_accepted_obligation(obligation, private_key=private_key)
        except BareMetalEscrowError as exc:
            raise typer.BadParameter(str(exc)) from exc
        # Recorded before verification: an escrow that exists on chain but was
        # never verified must still be recoverable, or the buyer's funds are
        # stranded with no reference to reclaim them by.
        log.event(
            "escrow_created",
            escrow_uid=escrow_uid,
            obligation_ref=obligation_ref,
            chain_name=(obligation.get("params") or {}).get("chain_name"),
        )

    verified = fulfillment.settle(
        escrow_uid=escrow_uid,
        negotiation_id=deal.negotiation_id,
        buyer_evm_address=buyer_evm_address,
    )
    log.event(
        "settlement_verified",
        escrow_uid=escrow_uid,
        obligation_ref=verified.get("obligation_ref") or obligation_ref,
    )

    begun = fulfillment.begin(
        negotiation_id=deal.negotiation_id,
        escrow_uid=escrow_uid,
    )
    log.event("fulfillment_begun", escrow_uid=escrow_uid)
    _json({"escrow_uid": escrow_uid, "settlement": verified, "fulfillment": begun})


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
    _json(_safe_projection(hosted.status(settlement_ref=settlement_ref)))


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
        settlement_ref=settlement_ref,
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
    projection: dict[str, Any] = {
        "fulfillment": fulfillment.status(deal.negotiation_id)
    }
    # A settlement reference exists only on the hosted rail; an Alkahest run
    # settles on chain and has none. Refusing here would leave a crypto lease
    # with no way to observe its own physical convergence.
    if deal.settlement_ref is not None:
        projection["settlement"] = _safe_projection(
            hosted.status(settlement_ref=deal.settlement_ref)
        )
    _json(projection)


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
    _json(_safe_projection(hosted.reclaim(settlement_ref=deal.settlement_ref)))


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
        funding_profile=None,
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
    deal, identity, transport, obligation_ref = _recovered_introduction(
        run_id, config
    )
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
    deal, identity, transport, obligation_ref = _recovered_introduction(
        run_id, config
    )
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
