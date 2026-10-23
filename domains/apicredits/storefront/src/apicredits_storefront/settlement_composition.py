"""API-credit storefront composition over the shared settlement runtime."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from arkhai_api_selling.evidence_store import (
    IssuanceEvidenceRepository,
    IssuanceEvidenceService,
    PrivateResultRepository,
)
from arkhai_api_selling.settlement_composition import (
    SellingSettlementComposition,
    build_settlement_registry,
    enabled_mechanism_clients,
)
from market_alkahest import (
    ALKAHEST_CONFIG_KEY,
    ALKAHEST_MECHANISM_ID,
    RECIPIENT_RELEASE,
    release_conditions,
    require_deliverable_release_model,
)
from market_arkhai_payments import (
    ARKHAI_PAYMENTS_CONFIG_KEY,
    ARKHAI_PAYMENTS_MECHANISM,
    ClientForOwner,
    PaymentSellerStage,
    servicing_stage,
)
from market_core import MarketDomainContract, SettlementStageTable
from market_identity import Signer, TrustedIdentitySet
from market_settlement_runtime import (
    SettlementConfigurationRegistry,
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
)

from apicredits_storefront.container import SELLING_CONTRIBUTIONS
from apicredits_storefront.services.credits_service_client import get_credits_service_client
from apicredits_storefront.services.payment_settlement_service import (
    ApiCreditPaymentSettlementService,
)
from apicredits_storefront.settlement_stages import AlkahestSellerStage, ArkhaiPaymentsSellerStage
from apicredits_storefront.utils import config as storefront_config

SELLER_STAGES = SettlementStageTable({
    # A credit grant releases to the seller once issued; nothing here judges an
    # oracle's verdict or splits a refund, so only the recipient model is
    # delivered.
    ALKAHEST_MECHANISM_ID: AlkahestSellerStage(
        fulfils_through_capacity=True, release_models=frozenset({RECIPIENT_RELEASE})
    ),
    ARKHAI_PAYMENTS_MECHANISM: ArkhaiPaymentsSellerStage(fulfils_through_capacity=True),
})

logger = logging.getLogger(__name__)


def build_storefront_settlement_registry() -> SettlementConfigurationRegistry:
    """Install the Alkahest and Arkhai payments registrations."""
    return build_settlement_registry(SELLER_STAGES)


@dataclass(frozen=True, slots=True)
class ApiCreditsSettlementComposition(SellingSettlementComposition):
    """The selling library's composition plus this storefront's Alkahest and payments parts."""

    arkhai_payments_stage: PaymentSellerStage | None = None
    seller_wallet_address: str = ""

    def payment_service(self, db: Any) -> Any:
        """The deal-scoped payment settlement service, or None when payments is not serviced."""
        if self.arkhai_payments_stage is None:
            return None
        return ApiCreditPaymentSettlementService(
            db=db,
            composition=self,
            stage=self.arkhai_payments_stage,
            mechanism=ARKHAI_PAYMENTS_MECHANISM,
        )

    def release_conditions(
        self, accepted_escrows: Sequence[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        """The release conditions a listing publishing ``accepted_escrows`` advertises.

        Accepted escrows are the Alkahest publication form, so each one's chain
        gets the condition the Alkahest mechanism derives from the configured
        section, the seller wallet, and that chain's address book. An escrow on
        a chain this storefront does not configure is refused, since nothing
        could settle it. An unset wallet still derives a condition, with no
        recipient; materialization refuses every deal under it as unreadable.
        """
        chain_names = {str(escrow["chain_name"]) for escrow in accepted_escrows}
        if not chain_names:
            return []
        chains = self.mechanism_resources["chains"]
        unconfigured = sorted(name for name in chain_names if name not in chains)
        if unconfigured:
            raise ValueError(
                f"accepted escrow names chain {unconfigured[0]!r}, which this "
                "storefront does not configure under [chains]"
            )
        return release_conditions(
            self.settlement_config.mechanism_config(ALKAHEST_CONFIG_KEY),
            chain_names=chain_names,
            chains=chains,
            wallet_address=self.seller_wallet_address,
        )


def require_api_credit_release_model(settlement_config: Any = None) -> None:
    """Refuse a configured Alkahest release model API credits cannot deliver.

    A configured section owns the deals accepted under it, enabled or not, so
    its release model must be one the Alkahest entry declares. With no
    ``settlement_config``, the storefront's own configuration is resolved.
    """
    if settlement_config is None:
        settlement_config = build_storefront_settlement_registry().resolve(
            storefront_config.settlement_config_mapping(), role="seller"
        )
    alkahest_section = settlement_config.mechanism_config(ALKAHEST_CONFIG_KEY)
    if alkahest_section is not None:
        require_deliverable_release_model(
            alkahest_section, SELLER_STAGES[ALKAHEST_MECHANISM_ID].release_models
        )


def build_api_credit_settlement_composition(
    *,
    domain: MarketDomainContract,
    sqlite_client: Any,
    alkahest_clients: Mapping[str, Any],
    marketplace_signer: Signer,
    failure_policy: Any,
    payments_client_for_owner: ClientForOwner | None = None,
) -> ApiCreditsSettlementComposition:
    """Build lazy mechanism clients and the shared servicing worker."""
    registry = build_storefront_settlement_registry()
    settlement_config = registry.resolve(
        storefront_config.settlement_config_mapping(),
        role="seller",
    )
    require_api_credit_release_model(settlement_config)
    repository = SettlementSQLiteRepository(
        sqlite_client.db_path, apply_migrations=False
    )
    resources: dict[str, Any] = {
        "marketplace_signer": marketplace_signer,
        "clients": dict(alkahest_clients),
        "get_client": lambda chain: alkahest_clients.get(chain or ""),
        "chains": storefront_config.CHAINS,
        "default_chain": next(iter(storefront_config.CHAINS), None),
    }
    mechanism_clients = enabled_mechanism_clients(
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
    composition = ApiCreditsSettlementComposition(
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
        arkhai_payments_stage=_payments_stage(settlement_config, payments_client_for_owner),
        seller_wallet_address=str(
            storefront_config.settings.get("wallet.address", "") or ""
        ),
    )
    return composition


def _payments_stage(
    settlement_config: Any, client_for_owner: ClientForOwner | None
) -> PaymentSellerStage | None:
    # Accepted payment deals are serviced whether or not new payment options are
    # published, so the stage follows the servicing fields, not `enabled`.
    return servicing_stage(
        settlement_config.mechanism_config(ARKHAI_PAYMENTS_CONFIG_KEY),
        client_for_owner=client_for_owner,
    )
