"""API-credit buyer composition for shared settlement registrations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from core_buyer.buyer_config import ResolvedBuyerIdentity
from core_buyer.settlement import BuyerSettlementPolicy
from market_alkahest import create_alkahest_registration
from market_arkhai_payments import create_arkhai_payments_registration
from market_config.config_loader import load_user_config
from market_core import SettlementStageTable
from market_core.schemas import Agreement

from .settlement_stages import AlkahestBuyerStage, PaymentBuyerStage

BUYER_STAGES = SettlementStageTable({
    "alkahest.v1": AlkahestBuyerStage(),
    "arkhai.payments.v1": PaymentBuyerStage(),
})


def buyer_stage(agreement: Any) -> Any:
    accepted = Agreement.model_validate(agreement)
    if accepted.settlement is None:
        raise ValueError("accepted Agreement has no settlement option")
    try:
        return BUYER_STAGES[accepted.settlement.mechanism]
    except KeyError as exc:
        raise ValueError("unsupported accepted API-credit settlement mechanism") from exc


def validate_buyer_acceptance(outcome: Any) -> None:
    buyer_stage(outcome.agreement).validate_acceptance(outcome)
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
    """Return both installed API-credit settlement registrations."""
    return SettlementConfigurationRegistry(
        tuple(stage.registration() for stage in BUYER_STAGES.values())
    )


def select_buyer_proposal(policy: BuyerSettlementPolicy, listing: Mapping[str, Any], **context: Any) -> Any:
    for registration in policy.registry.ordered_registrations(policy.config, role="buyer"):
        section = policy.config.mechanism_config(registration.config_key)
        if section is None or not getattr(section, "enabled", False):
            continue
        stage = BUYER_STAGES.get(registration.mechanism_id)
        if stage is not None:
            selected = stage.select(policy, listing, **context)
            if selected is not None:
                return selected
    return None


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
        stages=BUYER_STAGES,
        public_context={},
    )


async def buyer_settlement_readiness() -> tuple[
    SettlementConfig, tuple[MechanismReadiness, ...]
]:
    """Observe only enabled mechanism prerequisites."""
    identity = resolve_fresh_buyer_identity()
    policy = resolve_buyer_settlement_policy(identity=identity)
    resources: dict[str, Any] = {}
    for registration in policy.registry.ordered_registrations(policy.config, role="buyer"):
        stage = BUYER_STAGES.get(registration.mechanism_id)
        section = policy.config.mechanism_config(registration.config_key)
        if stage is not None and section is not None and getattr(section, "enabled", False):
            resources.update(stage.resources())
    statuses = await policy.registry.ordered_readiness(
        policy.config,
        role="buyer",
        resources=resources,
    )
    return policy.config, statuses
