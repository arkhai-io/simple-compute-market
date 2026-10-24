"""API-credit storefront composition over the selling library's settlement composition."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arkhai_api_selling.evidence_store import (
    IssuanceEvidenceRepository,
    IssuanceEvidenceService,
    PrivateResultRepository,
)
from arkhai_api_selling.settlement_composition import (
    SellingSettlementComposition,
    build_settlement_registry,
    mechanism_servicing,
    servicing_mechanism_clients,
)
from market_core import MarketDomainContract
from market_identity import Signer, TrustedIdentitySet
from market_settlement_runtime import (
    SettlementConfigurationRegistry,
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
)

from apicredits_storefront.container import SELLER_STAGES, SELLING_CONTRIBUTIONS
from apicredits_storefront.services.credits_service_client import get_credits_service_client
from apicredits_storefront.utils import config as storefront_config


def build_storefront_settlement_registry() -> SettlementConfigurationRegistry:
    """One registration per composed seller stage."""
    return build_settlement_registry(SELLER_STAGES)


def validate_mechanism_configuration(settlement_config: Any = None) -> None:
    """Refuse a configuration a composed mechanism cannot honour.

    With no ``settlement_config``, the storefront's own configuration is resolved.
    """
    if settlement_config is None:
        settlement_config = build_storefront_settlement_registry().resolve(
            storefront_config.settlement_config_mapping(), role="seller"
        )
    for stage in SELLER_STAGES.values():
        stage.validate_configuration(settlement_config)


def build_api_credit_settlement_composition(
    *,
    domain: MarketDomainContract,
    sqlite_client: Any,
    chain_clients: Mapping[str, Any],
    marketplace_signer: Signer,
    failure_policy: Any,
) -> SellingSettlementComposition:
    """Build the servicing clients, each mechanism's servicing, and the shared servicing worker."""
    registry = build_storefront_settlement_registry()
    settlement_config = registry.resolve(
        storefront_config.settlement_config_mapping(),
        role="seller",
    )
    validate_mechanism_configuration(settlement_config)
    repository = SettlementSQLiteRepository(
        sqlite_client.db_path, apply_migrations=False
    )
    resources: dict[str, Any] = {
        "marketplace_signer": marketplace_signer,
        "clients": dict(chain_clients),
        "get_client": lambda chain: chain_clients.get(chain or ""),
        "chains": storefront_config.CHAINS,
        "default_chain": next(iter(storefront_config.CHAINS), None),
    }
    mechanism_clients = servicing_mechanism_clients(
        SELLER_STAGES, registry, settlement_config, resources
    )

    runtime = SettlementRuntime(repository, mechanism_clients)
    # The process-wide client carries the storefront's signed authority
    # configuration; every issuance and rollback goes through it.
    credits_client = get_credits_service_client()
    evidence_service = IssuanceEvidenceService(
        IssuanceEvidenceRepository(sqlite_client.db_path, SELLING_CONTRIBUTIONS),
        contributions=SELLING_CONTRIBUTIONS,
        signer=marketplace_signer,
        trusted_issuers=TrustedIdentitySet(identities=(marketplace_signer.identity,)),
    )
    private_results = PrivateResultRepository(sqlite_client.db_path, SELLING_CONTRIBUTIONS)
    worker = SettlementServicingWorker(
        runtime,
        repository,
        worker_id=f"api-credit-storefront:{storefront_config.AGENT_ID}",
        interval_seconds=storefront_config.settlement_servicing_interval(),
    )
    return SellingSettlementComposition(
        contributions=SELLING_CONTRIBUTIONS,
        stages=SELLER_STAGES,
        domain=domain,
        repository=repository,
        runtime=runtime,
        worker=worker,
        local_principal=marketplace_signer.identity,
        mechanism_clients=mechanism_clients,
        settlement_config=settlement_config,
        configuration_registry=registry,
        mechanism_resources=resources,
        credits_client=credits_client,
        evidence_service=evidence_service,
        private_results=private_results,
        failure_policy=failure_policy,
        servicing=mechanism_servicing(SELLER_STAGES, settlement_config),
    )
