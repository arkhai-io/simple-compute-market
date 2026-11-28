"""Inference storefront composition over the selling library's settlement composition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arkhai_api_selling.settlement_composition import (
    SellingSettlementComposition,
    build_selling_settlement_composition,
    build_settlement_registry,
    validate_stage_configuration,
)
from core_storefront.stage_log import stage_event
from market_alkahest import AlkahestChainProbe
from market_core import MarketDomainContract
from market_identity import Signer
from market_settlement_runtime import SettlementConfigurationRegistry

from inference_storefront.container import ALKAHEST_STAGE, SELLER_STAGES, SELLING_CONTRIBUTIONS
from inference_storefront.services.credits_service_client import get_credits_service_client
from inference_storefront.utils import config as storefront_config


def build_storefront_settlement_registry() -> SettlementConfigurationRegistry:
    """One registration per composed seller stage."""
    return build_settlement_registry(SELLER_STAGES)


def validate_mechanism_configuration(settlement_config: Any = None) -> None:
    """Refuse a configuration a composed mechanism cannot honour."""
    if settlement_config is None:
        settlement_config = build_storefront_settlement_registry().resolve(
            storefront_config.settlement_config_mapping(), role="seller"
        )
    validate_stage_configuration(SELLER_STAGES, settlement_config)


def record_servicing_event(event: str, fields: dict[str, Any]) -> None:
    """Record a servicing worker's event as a ``claims`` stage event, so a
    failing step is on the deal's record."""
    stage_event("claims", event, **fields)


def settlement_resources(
    *,
    chain_clients: Mapping[str, Any],
    chain_probe: AlkahestChainProbe | None = None,
) -> dict[str, Any]:
    """The chain clients, chains, and Alkahest resources this storefront's mechanisms build from.

    ``chain_clients`` is the live map ``chain_probe`` updates in place, so it is
    held here rather than copied; readiness reads the probe's results.
    """
    resources: dict[str, Any] = {
        "clients": chain_clients,
        "get_client": lambda chain: chain_clients.get(chain or ""),
        "chains": storefront_config.CHAINS,
        "default_chain": next(iter(storefront_config.CHAINS), None),
        **ALKAHEST_STAGE.composition_resources(),
    }
    if chain_probe is not None:
        resources["chain_probe"] = chain_probe
    return resources


def build_inference_settlement_composition(
    *,
    domain: MarketDomainContract,
    sqlite_client: Any,
    chain_clients: Mapping[str, Any],
    marketplace_signer: Signer,
    failure_policy: Any,
    chain_probe: AlkahestChainProbe | None = None,
) -> SellingSettlementComposition:
    """The selling library's settlement composition over this storefront's resources."""
    return build_selling_settlement_composition(
        contributions=SELLING_CONTRIBUTIONS,
        stages=SELLER_STAGES,
        domain=domain,
        database_path=sqlite_client.db_path,
        settlement_configuration=storefront_config.settlement_config_mapping(),
        resources=settlement_resources(
            chain_clients=chain_clients,
            chain_probe=chain_probe,
        ),
        signer=marketplace_signer,
        # Every issuance and rollback goes through the signed process-wide client.
        credits_client=get_credits_service_client(),
        failure_policy=failure_policy,
        worker_id=f"inference-storefront:{storefront_config.AGENT_ID}",
        servicing_interval_seconds=storefront_config.settlement_servicing_interval(),
        on_event=record_servicing_event,
    )
