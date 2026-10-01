"""API-credit buyer composition for shared settlement registrations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.settlement import BuyerSettlementPolicy
from market_alkahest import create_alkahest_registration
from market_config.config_loader import load_user_config
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfig,
    SettlementConfigurationRegistry,
)

from .common import (
    buyer_chains,
    resolve_buyer_wallet,
    resolve_fresh_buyer_identity,
)


def buyer_settlement_registry() -> SettlementConfigurationRegistry:
    """Return the installed API-credit buyer settlement registration."""
    return SettlementConfigurationRegistry((create_alkahest_registration(),))


def resolve_buyer_settlement_policy(
    config: Mapping[str, Any] | None = None,
    *,
    identity: ResolvedBuyerIdentity | None = None,
    action_capable: bool = True,
) -> BuyerSettlementPolicy:
    """Resolve the shared hierarchy without constructing unused mechanisms."""
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
        public_context={},
    )


async def buyer_settlement_readiness() -> tuple[
    SettlementConfig, tuple[MechanismReadiness, ...]
]:
    """Observe only enabled mechanism prerequisites."""
    identity = resolve_fresh_buyer_identity()
    policy = resolve_buyer_settlement_policy(identity=identity)
    resources: dict[str, Any] = {}
    alkahest = policy.config.mechanism_config("alkahest")
    if alkahest is not None and getattr(alkahest, "enabled", False):
        chains = buyer_chains()
        address, _private_key = resolve_buyer_wallet()
        resources["chains"] = chains
        resources["wallet"] = {"address": address}
        if len(chains) == 1:
            resources["default_chain"] = next(iter(chains))
    statuses = await policy.registry.ordered_readiness(
        policy.config,
        role="buyer",
        resources=resources,
    )
    return policy.config, statuses
