"""VM buyer composition for installed settlement registrations."""

from __future__ import annotations

import os
import webbrowser
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import typer
from core_buyer.action_policy import (
    BuyerActionHandler,
    resolve_buyer_action_policy,
)
from core_buyer.profile_service import BuyerProfileService, ProfileServiceError
from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.settlement import BuyerSettlementPolicy, SelectedSettlementOption
from market_alkahest import create_alkahest_registration
from market_config.config_loader import load_user_config
from market_hosted_settlement import (
    FundingMode,
    FundingProfile,
    FundingSelection,
    HostedPayerError,
    PayerCommandContext,
    create_stripe_command_group,
    create_stripe_registration,
    payer_command_context_from_config,
    payer_compatibility_context,
    stripe_contract_fingerprint,
)
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfig,
    SettlementConfigurationRegistry,
)
from .chain_cli import chain_app
from .common import (
    buyer_chains,
    resolve_buyer_wallet,
    resolve_fresh_buyer_identity,
)
from .escrow_cli import escrow_app


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

    stripe = config.mechanism_config("stripe")
    if stripe is not None and stripe.enabled:
        resources["marketplace_signer"] = resolve_fresh_buyer_identity().signer

    alkahest = config.mechanism_config("alkahest")
    if alkahest is not None and alkahest.enabled:
        chains = buyer_chains()
        address, _private_key = resolve_buyer_wallet()
        resources["chains"] = chains
        resources["wallet"] = {"address": address}
        if len(chains) == 1:
            resources["default_chain"] = next(iter(chains))

    statuses = await policy.registry.ordered_readiness(
        config,
        role="buyer",
        resources=resources,
    )
    return config, statuses


def _dispatch_payer_action(action: Any, requested: str | None) -> Any:
    policy = resolve_buyer_action_policy(
        requested,
        interactive=os.isatty(0) and os.isatty(1),
    )
    handler = BuyerActionHandler(
        policy,
        open_url=webbrowser.open,
        print_url=lambda value: typer.echo(value),
    )
    return handler.handle(action.model_dump(mode="json", exclude_none=True))


def _payer_command_context() -> PayerCommandContext:
    policy = resolve_buyer_settlement_policy()
    section = policy.config.mechanism_config("stripe")
    if section is None:
        raise ValueError("hosted payer commands require Stripe settlement config")
    return payer_command_context_from_config(
        section,
        profiles=BuyerProfileService(),
        dispatch_action=_dispatch_payer_action,
    )


def buyer_settlement_registry() -> SettlementConfigurationRegistry:
    """Return the explicitly installed VM buyer mechanisms."""

    return SettlementConfigurationRegistry(
        (
            replace(
                create_alkahest_registration(),
                command_group=_alkahest_command_group(),
            ),
            create_stripe_registration(
                command_group=create_stripe_command_group(_payer_command_context)
            ),
        )
    )


def _stripe_local_public_context(
    settlement: SettlementConfig,
    identity: ResolvedBuyerIdentity,
    *,
    funding_selection: FundingSelection,
    action_capable: bool,
) -> Mapping[str, Any]:
    """Project local binding and interaction capability without network reads."""

    section = settlement.mechanism_config("stripe")
    if section is None or not getattr(section, "enabled", False):
        return {}
    service = BuyerProfileService()
    try:
        binding = service.authority_payer_binding(
            identity.profile_id,
            authority_id=section.authority_id,
            environment=section.environment,
            principal=identity.principal,
        )
    except (ProfileServiceError, ValueError):
        return {}
    saved_selected = bool(
        action_capable
        and funding_selection.mode is FundingMode.SAVED_INSTRUMENT
        and funding_selection.instrument_ref
    )
    interactive_selected = bool(
        action_capable
        and funding_selection.mode is FundingMode.INTERACTIVE
    )
    return {
        "contract_fingerprint": stripe_contract_fingerprint(section),
        "funding_profiles": tuple(profile.value for profile in FundingProfile),
        "currencies": (section.currency,),
        "countries": (section.country,),
        "interactions": (
            (funding_selection.mode.value,)
            if action_capable
            else ()
        ),
        "selected_payer_binding": binding.model_dump(mode="json"),
        "selected_principal": identity.principal.model_dump(mode="json"),
        "profile_readiness": {
            profile.value: {
                FundingMode.INTERACTIVE.value: interactive_selected,
                FundingMode.SAVED_INSTRUMENT.value: bool(
                    saved_selected
                    and profile is not FundingProfile.US_BANK_TRANSFER
                ),
            }
            for profile in FundingProfile
        },
    }


async def revalidate_hosted_buyer_option(
    *,
    policy: BuyerSettlementPolicy,
    option: Any,
    identity: ResolvedBuyerIdentity,
    funding_selection: FundingSelection,
    action_capable: bool,
) -> None:
    """Re-fetch exact hosted readiness immediately before seller negotiation."""

    if getattr(option, "mechanism", None) != "fiat.stripe.v1":
        return
    local_context = _stripe_local_public_context(
        policy.config,
        identity,
        funding_selection=funding_selection,
        action_capable=action_capable,
    )
    if not policy.registry.buyer_compatible(
        option.mechanism,
        option,
        policy.config,
        public_context=local_context,
    ):
        raise ValueError("selected hosted funding is not locally compatible")
    section = policy.config.mechanism_config("stripe")
    service = BuyerProfileService()
    client = None
    try:
        binding = service.authority_payer_binding(
            identity.profile_id,
            authority_id=section.authority_id,
            environment=section.environment,
            principal=identity.principal,
        )
        context = payer_command_context_from_config(
            section,
            profiles=service,
            dispatch_action=_dispatch_payer_action,
        )
        client = context.client_factory(identity.signer)
        public_context = await payer_compatibility_context(
            config=section,
            binding=binding,
            signer=identity.signer,
            client=client,
            funding_mode=funding_selection.mode,
            instrument_ref=funding_selection.instrument_ref,
            action_capable=action_capable,
        )
        if not policy.registry.buyer_compatible(
            option.mechanism,
            option,
            policy.config,
            public_context=public_context,
        ):
            raise ValueError("selected hosted funding is not remotely ready")
    except (HostedPayerError, ProfileServiceError, ValueError):
        raise ValueError("selected hosted funding is not ready") from None
    finally:
        if client is not None:
            close = getattr(client, "aclose", None)
            if callable(close):
                await close()


def resolve_buyer_settlement_policy(
    config: Mapping[str, Any] | None = None,
    *,
    identity: ResolvedBuyerIdentity | None = None,
    funding_selection: FundingSelection | None = None,
    action_capable: bool = True,
) -> BuyerSettlementPolicy:
    """Strictly resolve the common buyer ``[Settlement]`` hierarchy."""

    document = dict(load_user_config() if config is None else config)
    if "settlement" in document:
        raise ValueError(
            "legacy [settlement] configuration is not supported; run "
            "`market config migrate --scope settlement --write --backup`"
        )
    raw = document.get("Settlement", {})
    if not isinstance(raw, Mapping):
        raise ValueError("[Settlement] must be a table")
    registry = buyer_settlement_registry()
    settlement = registry.resolve(raw, role="buyer")
    selection = funding_selection or FundingSelection(mode=FundingMode.INTERACTIVE)
    public_context = (
        _stripe_local_public_context(
            settlement,
            identity,
            funding_selection=selection,
            action_capable=action_capable,
        )
        if identity is not None
        else {}
    )
    return BuyerSettlementPolicy(
        config=settlement,
        registry=registry,
        public_context=public_context,
    )


def alkahest_entry_from_selection(
    selected: SelectedSettlementOption,
) -> dict[str, Any] | None:
    """Decode the mechanism-owned accepted escrow only after selection."""

    if selected.registration.config_key != "alkahest":
        return None
    value = selected.option.params.get("accepted_escrow")
    if not isinstance(value, Mapping):
        raise ValueError("selected Alkahest option has no accepted escrow payload")
    return dict(value)


def resolve_alkahest_address_config_path(
    config: Mapping[str, Any] | None = None,
) -> str | None:
    """Resolve Alkahest's public address book without enabling new admission."""

    policy = resolve_buyer_settlement_policy(config)
    section = policy.config.mechanism_config("alkahest")
    value = getattr(section, "address_config_path", None)
    return value if isinstance(value, str) and value else None
