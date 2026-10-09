"""VM buyer composition for installed settlement registrations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import typer
from core_buyer.buyer_config import ResolvedBuyerIdentity
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

from .chain_cli import chain_app
from .escrow_cli import escrow_app
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
    return buyer_stage(selected.selection.mechanism).plan_validator(match, selected)


def validate_buyer_acceptance(outcome) -> None:
    if outcome.agreement is None or outcome.agreement.settlement is None:
        raise RuntimeError("accepted work has no Agreement settlement option")
    buyer_stage(outcome.agreement.settlement.mechanism).validate_acceptance(outcome)


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
    return BuyerSettlementPolicy(
        config=settlement,
        registry=registry,
        stages=buyer_settlement_stages(),
        public_context={},
    )


def alkahest_entry_from_selection(
    selected: SelectedSettlementOption,
) -> dict[str, Any] | None:
    """Decode the mechanism-owned accepted escrow only after selection."""

    return buyer_stage(selected.selection.mechanism).accepted_entry(selected)


def resolve_alkahest_address_config_path(
    config: Mapping[str, Any] | None = None,
) -> str | None:
    """Resolve Alkahest's public address book without enabling new admission."""

    policy = resolve_buyer_settlement_policy(config)
    section = policy.config.mechanism_config("alkahest")
    value = getattr(section, "address_config_path", None)
    return value if isinstance(value, str) and value else None
