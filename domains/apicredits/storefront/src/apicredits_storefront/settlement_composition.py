"""API-credit storefront composition over the shared settlement runtime."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from market_alkahest import (
    AlkahestConditionalEscrowClient,
    create_alkahest_registration,
)
from market_core import MarketDomainContract
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
from domains.apicredits.settlement import (
    CONFIG_KEY,
    MECHANISM_ID,
    create_api_credits_payments_registration,
    mandate_policy_from_agreement,
)
from market_arkhai_payments import derive_mandate, transaction_id

from apicredits_storefront.services.issuance_evidence import (
    ApiCreditPrivateResultRepository,
    ApiCreditsIssuanceEvidenceService,
    IssuanceEvidenceRepository,
)
from apicredits_storefront.utils import config as storefront_config
from domains.apicredits.settlement import (
    CreditsServiceClient,
)

logger = logging.getLogger(__name__)


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return dict(value.model_dump(mode="json"))
    return dict(value) if isinstance(value, Mapping) else {}


def build_storefront_settlement_registry() -> SettlementConfigurationRegistry:
    """Install the Alkahest and Arkhai payments registrations."""
    return SettlementConfigurationRegistry(
        (create_alkahest_registration(), create_api_credits_payments_registration())
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
    payments_client: Any | None = None

    def payment_settlement_artifacts(
        self, agreement: Mapping[str, Any]
    ) -> dict[str, Any]:
        config = self.settlement_config.mechanism_config(CONFIG_KEY)
        if config is None or not getattr(config, "enabled", False):
            raise ValueError("Arkhai payments is not enabled for API credits")
        policy = mandate_policy_from_agreement(
            agreement,
            fee_bps=config.fee_bps,
            dispute_authority=config.dispute_authority,
        )
        mandate = derive_mandate(dict(agreement), policy)
        return {
            "mandate": mandate.model_dump(
                mode="json", by_alias=True, exclude_none=True
            ),
            "transaction_id": transaction_id(mandate),
        }

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
            alkahest_chains = tuple(
                dict.fromkeys(
                    str(clause.mechanism_input["chain"])
                    for clause in compiled
                    if clause.mechanism == "alkahest.v1"
                    and isinstance(clause.mechanism_input.get("chain"), str)
                )
            )
            readiness_resources = {
                **merged_resources,
                **(
                    {
                        "accepted_escrows": [
                            {"chain_name": name} for name in alkahest_chains
                        ]
                    }
                    if alkahest_chains
                    else {}
                ),
            }
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


def build_api_credit_settlement_composition(
    *,
    domain: MarketDomainContract,
    sqlite_client: Any,
    alkahest_clients: Mapping[str, Any],
    marketplace_signer: Signer,
    failure_policy: Any,
) -> ApiCreditsSettlementComposition:
    """Build lazy mechanism clients and the shared servicing worker."""
    repository = SettlementSQLiteRepository(
        sqlite_client.db_path, apply_migrations=False
    )
    registry = build_storefront_settlement_registry()
    settlement_config = registry.resolve(
        storefront_config.settlement_config_mapping(),
        role="seller",
    )
    resources: dict[str, Any] = {
        "marketplace_signer": marketplace_signer,
        "clients": dict(alkahest_clients),
        "get_client": lambda chain: alkahest_clients.get(chain or ""),
        "chains": storefront_config.CHAINS,
        "default_chain": next(iter(storefront_config.CHAINS), None),
    }
    mechanism_clients: dict[str, Any] = {}
    payments_client: Any | None = None
    for registration in registry.ordered_registrations(
        settlement_config, role="seller"
    ):
        section = settlement_config.mechanism_config(registration.config_key)
        if section is None or not getattr(section, "enabled", False):
            continue
        if registration.mechanism_id == "alkahest.v1":
            mechanism_clients[registration.mechanism_id] = (
                AlkahestConditionalEscrowClient(
                    get_client=resources["get_client"],
                    chain_config_paths={
                        name: chain.alkahest_address_config_path
                        for name, chain in storefront_config.CHAINS.items()
                    },
                    default_chain=resources["default_chain"],
                )
            )
        elif registration.mechanism_id == MECHANISM_ID:
            payments_client = registry.create_client(
                registration.mechanism_id,
                settlement_config,
                role="seller",
                resources=resources,
            )
    runtime = SettlementRuntime(repository, mechanism_clients)
    credits_client = CreditsServiceClient(
        storefront_config.credits_service_url(),
        storefront_config.credits_admin_key(),
    )
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
        interval_seconds=float(
            storefront_config.settings.get("claims_sweep_interval", 30)
        ),
    )
    composition = ApiCreditsSettlementComposition(
        domain=domain,
        repository=repository,
        runtime=runtime,
        worker=worker,
        local_principal=marketplace_signer.identity,
        mechanism_clients=mechanism_clients,
        payments_client=payments_client,
        settlement_config=settlement_config,
        configuration_registry=registry,
        mechanism_resources=resources,
        credits_client=credits_client,
        evidence_service=evidence_service,
        private_results=private_results,
        failure_policy=failure_policy,
    )
    return composition
