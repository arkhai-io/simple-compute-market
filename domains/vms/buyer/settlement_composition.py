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
from core_buyer.profile_service import BuyerProfileService
from core_buyer.settlement import BuyerSettlementPolicy, SelectedSettlementOption
from market_alkahest import create_alkahest_registration
from market_config.config_loader import load_user_config
from market_hosted_settlement import (
    PayerCommandContext,
    create_stripe_command_group,
    create_stripe_registration,
    payer_command_context_from_config,
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


def resolve_buyer_settlement_policy(
    config: Mapping[str, Any] | None = None,
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
    return BuyerSettlementPolicy(config=settlement, registry=registry)


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
