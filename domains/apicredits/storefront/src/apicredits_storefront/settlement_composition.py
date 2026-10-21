"""API-credit storefront composition over the shared settlement runtime."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from arkhai_apicredits.settlement import CreditsServiceClient
from market_alkahest import (
    ALKAHEST_CONFIG_KEY,
    ALKAHEST_MECHANISM_ID,
    RECIPIENT_RELEASE,
    AlkahestChainProbe,
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
from market_identity import Identity, Signer, TrustedIdentitySet
from market_settlement_runtime import (
    MechanismReadiness,
    SettlementConfigurationRegistry,
    SettlementPublicationClause,
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
    compile_settlement_publication_clause,
)

from apicredits_storefront.services.issuance_evidence import (
    ApiCreditPrivateResultRepository,
    ApiCreditsIssuanceEvidenceService,
    IssuanceEvidenceRepository,
)
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


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="json"))
    return dict(value) if isinstance(value, Mapping) else {}


def build_storefront_settlement_registry() -> SettlementConfigurationRegistry:
    """Install the Alkahest and Arkhai payments registrations."""
    return SettlementConfigurationRegistry(
        tuple(stage.registration() for stage in SELLER_STAGES.values())
    )


@dataclass(frozen=True, slots=True)
class ApiCreditsSettlementComposition:
    domain: MarketDomainContract
    repository: SettlementSQLiteRepository
    runtime: SettlementRuntime
    worker: SettlementServicingWorker
    local_principal: Identity
    mechanism_clients: Mapping[str, Any]
    settlement_config: Any
    configuration_registry: SettlementConfigurationRegistry
    mechanism_resources: Mapping[str, Any]
    credits_client: CreditsServiceClient
    evidence_service: ApiCreditsIssuanceEvidenceService
    private_results: ApiCreditPrivateResultRepository
    failure_policy: Any
    arkhai_payments_stage: PaymentSellerStage | None = None
    seller_wallet_address: str = ""

    def accepted_settlement_artifacts(self, agreement: Mapping[str, Any]) -> dict[str, Any]:
        mechanism = agreement["settlement"]["mechanism"]
        return SELLER_STAGES[mechanism].agreement_artifacts(agreement, self)

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

    async def readiness(self) -> tuple[MechanismReadiness, ...]:
        return await self.configuration_registry.ordered_readiness(
            self.settlement_config,
            role="seller",
            resources=self.mechanism_resources,
        )

    def accepted_obligation_dispatch(
        self,
    ) -> dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None]:
        """Curried registry dispatch for every enabled obligation-building mechanism."""

        dispatch: dict[
            str, Callable[[Mapping[str, Any], Mapping[str, Any]], Any] | None
        ] = {}
        for mechanism_id in self.settlement_config.priority:
            if mechanism_id not in SELLER_STAGES:
                continue
            registration = self.configuration_registry.registration(mechanism_id)
            if registration.accepted_obligation_builder is None:
                dispatch[mechanism_id] = None
                continue

            def build(
                option: Mapping[str, Any],
                context: Mapping[str, Any],
                *,
                _mechanism_id: str = mechanism_id,
            ) -> Any:
                return self.configuration_registry.build_accepted_obligation(
                    _mechanism_id,
                    option,
                    self.settlement_config,
                    role="seller",
                    context=context,
                )

            dispatch[mechanism_id] = build
        return dispatch

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

    async def publication_artifacts(
        self,
        resources: Mapping[str, Any],
        clauses: list[SettlementPublicationClause | Mapping[str, Any]] | None = None,
    ) -> tuple[
        list[dict[str, Any]], list[dict[str, Any]], tuple[MechanismReadiness, ...]
    ]:
        """Compile each complete ready clause without suppressing ready peers."""
        merged_resources = {**self.mechanism_resources, **resources}
        compiled = (
            [
                compile_settlement_publication_clause(
                    clause,
                    registry=self.configuration_registry,
                    config=self.settlement_config,
                    role="seller",
                )
                for clause in clauses
            ]
            if clauses is not None
            else None
        )
        readiness_resources = merged_resources
        if compiled is not None:
            projected: dict[str, Any] = {}
            for mechanism, stage in SELLER_STAGES.items():
                projected.update(stage.readiness_resources(
                    [clause for clause in compiled if clause.mechanism == mechanism],
                    merged_resources,
                ))
            readiness_resources = {**merged_resources, **projected}
        readiness = await self.configuration_registry.ordered_readiness(
            self.settlement_config,
            role="seller",
            resources=readiness_resources,
        )
        statuses = {status.mechanism: status for status in readiness}
        work = (
            [
                (
                    statuses.get(clause.mechanism),
                    {**merged_resources, "publication_clause": clause},
                )
                for clause in compiled
            ]
            if compiled is not None
            else [(status, merged_resources) for status in readiness]
        )
        accepted_escrows: list[dict[str, Any]] = []
        settlement_options: list[dict[str, Any]] = []
        for status, option_resources in work:
            if status is None:
                raise RuntimeError("settlement clause has no registered mechanism")
            if not status.enabled:
                if compiled is not None:
                    raise ValueError(
                        f"settlement publication mechanism {status.mechanism!r} is disabled"
                    )
                continue
            if not status.ready:
                logger.warning(
                    "[SETTLEMENT] option suppressed mechanism=%s blockers=%s",
                    status.mechanism,
                    ",".join(blocker.code for blocker in status.blockers),
                )
                continue
            if status.mechanism not in SELLER_STAGES:
                continue
            SELLER_STAGES[status.mechanism].validate_publication(option_resources)
            envelope = self.configuration_registry.build_option(
                status,
                self.settlement_config,
                role="seller",
                resources=option_resources,
            )
            if not isinstance(envelope, Mapping):
                raise RuntimeError("settlement option builder returned no envelope")
            accepted_escrows.extend(
                dict(item) for item in envelope.get("accepted_escrows", ())
            )
            settlement_options.extend(
                dict(item) for item in envelope.get("settlement_options", ())
            )
        if not accepted_escrows and not settlement_options:
            raise RuntimeError("no enabled settlement mechanism is ready")
        return accepted_escrows, settlement_options, readiness


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
    chain_probe: AlkahestChainProbe | None = None,
) -> ApiCreditsSettlementComposition:
    """Build lazy mechanism clients and the shared servicing worker.

    ``alkahest_clients`` is the live map ``chain_probe`` updates in place, so
    it is held here rather than copied; readiness reads the probe's results.
    """
    registry = build_storefront_settlement_registry()
    settlement_config = registry.resolve(
        storefront_config.settlement_config_mapping(),
        role="seller",
    )
    require_api_credit_release_model(settlement_config)
    repository = SettlementSQLiteRepository(
        sqlite_client.db_path, apply_migrations=False
    )
    seller_wallet_address = str(
        storefront_config.settings.get("wallet.address", "") or ""
    )
    resources: dict[str, Any] = {
        "marketplace_signer": marketplace_signer,
        "clients": alkahest_clients,
        "get_client": lambda chain: alkahest_clients.get(chain or ""),
        "chains": storefront_config.CHAINS,
        "default_chain": next(iter(storefront_config.CHAINS), None),
        # Readiness reads the seller wallet's address: with none, no escrow
        # could pay the seller, whatever clients are composed.
        "wallet": {"address": seller_wallet_address},
    }
    if chain_probe is not None:
        resources["chain_probe"] = chain_probe
    mechanism_clients: dict[str, Any] = {}
    for registration in registry.ordered_registrations(
        settlement_config, role="seller"
    ):
        section = settlement_config.mechanism_config(registration.config_key)
        if section is None or not getattr(section, "enabled", False):
            continue
        stage = SELLER_STAGES.get(registration.mechanism_id)
        if stage is not None:
            client = stage.client(resources)
            if client is not None:
                mechanism_clients[registration.mechanism_id] = client

    runtime = SettlementRuntime(repository, mechanism_clients)
    # The process-wide client carries the storefront's signed authority
    # configuration; every issuance and rollback goes through it.
    credits_client = get_credits_service_client()
    evidence_service = ApiCreditsIssuanceEvidenceService(
        IssuanceEvidenceRepository(sqlite_client.db_path),
        signer=marketplace_signer,
        trusted_issuers=TrustedIdentitySet(identities=(marketplace_signer.identity,)),
    )
    private_results = ApiCreditPrivateResultRepository(sqlite_client.db_path)
    worker = SettlementServicingWorker(
        runtime,
        repository,
        worker_id=f"api-credit-storefront:{storefront_config.AGENT_ID}",
        interval_seconds=storefront_config.settlement_servicing_interval(),
    )
    composition = ApiCreditsSettlementComposition(
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
        seller_wallet_address=seller_wallet_address,
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
