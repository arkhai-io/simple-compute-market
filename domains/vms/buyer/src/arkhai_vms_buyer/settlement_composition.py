"""VM buyer composition for installed settlement registrations."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from functools import partial
from typing import Any

import typer
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.registry_config import registry_descriptors, resolve_indexer_urls
from market_deal_lifecycle.configuration import authorities_by_registry, dispute_config
from market_deal_lifecycle.selection import AuthoritySelection
from market_deal_lifecycle.terms import TermContext
from market_settlement_runtime.buyer_terms import (
    BuyerTermsPolicy, allows_missing_delivery_deadline, compute_disclosure, lifecycle_disclosure,
    waiver_flags,
)
from market_settlement_runtime.horizon import check_accepted_horizon
from market_settlement_runtime.rate_publication import DefaultRefusal
from market_arkhai_mediation.contract import INTERFACE as MEDIATION_INTERFACE
from core_buyer.settlement import BuyerSettlementPolicy, SelectedSettlementOption
from market_alkahest import create_alkahest_registration
from market_arkhai_payments import create_arkhai_payments_registration
from market_contact_exchange import (
    create_contact_command_group,
    create_contact_exchange_registration,
)
from market_config.config_loader import load_user_config
from market_core import SettlementStageTable
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfig,
    SettlementConfigurationRegistry,
)

from .cli_helpers import emit_lifecycle_disclosure
from .chain_cli import chain_app
from .common import refuse_retired_address_book_keys
from .escrow_cli import escrow_app
from .registry_listing import domain_listing_record
from .pricing_record import retained_pricing_record
from .settlement_stages import AlkahestBuyerStage, PaymentsBuyerStage


_BUYER_STAGES = SettlementStageTable({
    "alkahest.v1": AlkahestBuyerStage(),
    "arkhai.payments.v1": PaymentsBuyerStage(),
})


def buyer_settlement_stages() -> SettlementStageTable:
    """Support for fresh admission and accepted recovery, independent of priority."""
    return _BUYER_STAGES


def buyer_stage(mechanism: str):
    try:
        return _BUYER_STAGES[mechanism]
    except KeyError as exc:
        raise ValueError(
            f"accepted settlement mechanism {mechanism!r} is not installed; "
            "recovery will not fall back to another mechanism"
        ) from exc


def advertised_plan_validator(match: Mapping[str, Any]):
    """The selected entry's check of a plan it materializes, for one match."""
    selected = match.get("_selected_settlement")
    if not isinstance(selected, SelectedSettlementOption):
        return None
    return buyer_stage(selected.selection.settlement_schema).plan_validator(
        match, selected
    )


def accepted_listing_record(match: Mapping[str, Any], _proposal: Any) -> dict[str, Any]:
    """What the selected entry records about a match's listing at acceptance.

    The entry is the match's selected settlement option, from which the
    buyer's proposal was built. A shape-priced match also records what its
    amount codec reads, its family rates keyed as the domain record keys them,
    so a resumed run converts its bounds against the same rates. The listing's
    capacity bounds are kept so a resumed run checks the signed horizon against
    what was advertised, not a current listing.
    """
    selected = match.get("_selected_settlement")
    if not isinstance(selected, SelectedSettlementOption):
        return {}
    match = domain_listing_record(match)
    record = buyer_stage(selected.selection.settlement_schema).listing_record(match)
    if match.get("rate_structure"):
        record = {**record, **retained_pricing_record(match)}
    return {**record, **{key: match[key] for key in ("max_duration_seconds", "available_until_utc")
                         if match.get(key) is not None}}


def buyer_term_context(
    mechanism: str, *, waivers: frozenset[DefaultRefusal] = frozenset(),
) -> TermContext:
    return TermContext(
        mechanism=mechanism, has_adapter=mechanism == "arkhai.payments.v1", compute=True,
        dispute_interfaces=frozenset({MEDIATION_INTERFACE}),
        allow_missing_delivery_deadline=allows_missing_delivery_deadline(waivers),
    )


def buyer_lifecycle_disclosure(option, *, waivers: frozenset[DefaultRefusal] = frozenset()):
    return lifecycle_disclosure(
        option, context=buyer_term_context(option.settlement_schema), waivers=waivers,
    )


def buyer_compute_disclosure(option, **kwargs):
    return compute_disclosure(option, registry=buyer_settlement_registry(), **kwargs)


def disclose_accepted_agreement(
    agreement, *, waivers: frozenset[DefaultRefusal] = frozenset(),
) -> None:
    """Show the accepted terms before approval, naming the run's waivers."""
    emit_lifecycle_disclosure(
        buyer_compute_disclosure(agreement.settlement, agreement=agreement)
        + buyer_lifecycle_disclosure(agreement.settlement, waivers=waivers),
        title="Accepted Agreement: price, horizon and lifecycle terms before approval",
    )


def validate_buyer_acceptance(
    outcome, *, listing: Mapping[str, Any] | None = None,
    requested_duration_seconds: int | None = None,
    waivers: frozenset[DefaultRefusal] = frozenset(),
) -> None:
    """Check a seller's acceptance before its Agreement is observed or approved.

    With the advertised ``listing``, the signed horizon is held to its capacity
    bounds at the Agreement's start and to the buyer's request, or to the default
    bound when the buyer named none: the seller's own resolver protects only
    against the seller's mistakes, not a counterparty signing other terms.
    ``waivers`` are the run's, named in the accepted disclosure.
    """
    if outcome.agreement is None or outcome.agreement.settlement is None:
        raise RuntimeError("accepted work has no Agreement settlement option")
    if listing is not None:
        try:
            check_accepted_horizon(
                start_utc=outcome.agreement.start_utc,
                duration_seconds=outcome.agreement.duration_seconds,
                requested_duration_seconds=requested_duration_seconds,
                max_duration_seconds=listing.get("max_duration_seconds"),
                available_until_utc=listing.get("available_until_utc"),
            )
        except ValueError as exc:
            raise RuntimeError(f"accepted horizon refused: {exc}") from exc
    buyer_stage(outcome.agreement.settlement.settlement_schema).validate_acceptance(outcome)
    disclose_accepted_agreement(outcome.agreement, waivers=waivers)


def listing_acceptance_validator(
    requested_duration_seconds: int | None, *, waivers: frozenset[DefaultRefusal] = frozenset(),
):
    """Bind :func:`validate_buyer_acceptance` to each candidate listing."""
    def for_match(match: Mapping[str, Any]):
        return partial(
            validate_buyer_acceptance, listing=match,
            requested_duration_seconds=requested_duration_seconds, waivers=waivers,
        )
    return for_match


def _alkahest_command_group():

    group = typer.Typer(
        no_args_is_help=True,
        help="Raw Alkahest setup, inspection, and mutation utilities.",
    )
    group.add_typer(
        escrow_app,
        name="escrow",
        help="Inspect, create, or reclaim Alkahest escrows.",
    )
    group.add_typer(
        chain_app,
        name="chain",
        help="Check the configured EVM contracts used by Alkahest.",
    )
    return group


async def buyer_settlement_readiness() -> tuple[
    SettlementConfig, tuple[MechanismReadiness, ...]
]:
    """Observe installed buyer mechanism prerequisites without mutation."""

    policy = resolve_buyer_settlement_policy()
    config = policy.config
    resources: dict[str, Any] = {}

    for registration in policy.ordered_registrations():
        resources.update(buyer_stage(registration.mechanism_id).readiness_resources())

    statuses = await policy.registry.ordered_readiness(
        config,
        role="buyer",
        resources=resources,
    )
    return config, statuses


def _introduction_context() -> Any:
    # The introduction commands negotiate and recover through the buyer
    # client, which imports this composition for acceptance validation.
    from .introduction_cli import IntroductionContext

    return IntroductionContext()


def buyer_settlement_registry() -> SettlementConfigurationRegistry:
    """Return the explicitly installed VM buyer mechanisms."""

    return SettlementConfigurationRegistry(
        (
            replace(
                create_alkahest_registration(),
                command_group=_alkahest_command_group(),
            ),
            create_arkhai_payments_registration(),
            create_contact_exchange_registration(
                command_group=create_contact_command_group(_introduction_context)
            ),
        )
    )


def resolve_buyer_settlement_policy(
    config: Mapping[str, Any] | None = None,
    *,
    identity: ResolvedBuyerIdentity | None = None,
    action_capable: bool = True,
    registry_urls: str | None = None,
    waivers: frozenset[DefaultRefusal] = frozenset(),
) -> BuyerSettlementPolicy:
    """Strictly resolve the common buyer ``[Settlement]`` hierarchy.

    ``waivers`` are the default refusals this run waives, each by its own flag.
    """

    document = dict(load_user_config() if config is None else config)
    if "settlement" in document:
        raise ValueError(
            "legacy [settlement] configuration is not supported; run "
            "`market config migrate --scope settlement --write --backup`"
        )
    refuse_retired_address_book_keys(document)
    raw = document.get("Settlement", {})
    if not isinstance(raw, Mapping):
        raise ValueError("[Settlement] must be a table")
    registry = buyer_settlement_registry()
    settlement = registry.resolve(raw, role="buyer")
    disputes = dispute_config(document, role="buyer")
    descriptors = (
        registry_descriptors(
            signer=identity.signer, urls=resolve_indexer_urls(override=registry_urls)
        )
        if identity is not None and action_capable and disputes.use_registry_dispute_authorities
        else {}
    )
    authorities = authorities_by_registry(
        disputes,
        {url: descriptor.recommended_dispute_authorities or [] if descriptor else []
         for url, descriptor in descriptors.items()},
        role="buyer",
        report=logging.getLogger(__name__).warning if identity is not None else lambda _: None,
    )
    return BuyerSettlementPolicy(
        config=settlement,
        registry=registry,
        stages=buyer_settlement_stages(),
        option_preference=BuyerTermsPolicy(AuthoritySelection(authorities, contexts={
            "arkhai.payments.v1": buyer_term_context("arkhai.payments.v1", waivers=waivers),
        }, report=logging.getLogger(__name__).info), waivers=waivers),
        public_context={
            "dispute_authorities_by_registry": authorities,
            "compute_term_waivers": list(waiver_flags(waivers)),
        },
    )


def alkahest_entry_from_selection(
    selected: SelectedSettlementOption,
) -> dict[str, Any] | None:
    """Decode the mechanism-owned accepted escrow only after selection."""

    return buyer_stage(selected.selection.settlement_schema).accepted_entry(selected)
