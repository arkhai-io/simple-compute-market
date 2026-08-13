"""VM buyer composition for installed settlement registrations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core_buyer.settlement import BuyerSettlementPolicy, SelectedSettlementOption
from market_alkahest import create_alkahest_registration
from market_config.config_loader import load_user_config
from market_hosted_settlement import create_stripe_registration
from market_settlement_runtime import SettlementConfigurationRegistry


def buyer_settlement_registry() -> SettlementConfigurationRegistry:
    """Return the explicitly installed VM buyer mechanisms."""

    return SettlementConfigurationRegistry(
        (
            create_alkahest_registration(),
            create_stripe_registration(),
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
