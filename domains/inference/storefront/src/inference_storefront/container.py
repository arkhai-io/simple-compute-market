"""The storefront's dependency container.

Composed parts are fixed for the process and read the ``resolved_*`` services,
which the lifespan in ``server.py`` sets, when a request or cycle runs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from arkhai_api_selling.auth import StorefrontAuth
from arkhai_api_selling.capacity import QuotaCapacity
from arkhai_api_selling.contributions import ConsumptionRule, SellingContributions
from arkhai_api_selling.evidence_store import IssuanceEvidenceService, PrivateResultRepository
from arkhai_api_selling.lifecycle import ContributedLoop, ListingSeedProgress, StorefrontLoops
from arkhai_api_selling.listings import ListingService
from arkhai_api_selling.persistence import StorefrontSQLiteClient
from arkhai_api_selling.publication import QuotaPublication, RegistryPublication
from arkhai_api_selling.route_services import (
    ListingRoutes,
    NegotiateRoutes,
    NegotiationRoutes,
    SettleRoutes,
    SystemRoutes,
)
from arkhai_api_selling.system import SystemService
from arkhai_api_selling_alkahest.stage import AlkahestSellerStage
from arkhai_inference.label import INFERENCE_LABEL
from arkhai_inference.listings import INFERENCE_KIND, INFERENCE_OFFERING_MODE
from arkhai_inference.schema import InferenceListing
from core_storefront.escrow_identity import backfill_escrow_obligation_records
from core_storefront.multi_registry_client import MultiRegistryClient
from core_storefront.stage_log import stage_event
from market_alkahest import RECIPIENT_RELEASE
from market_core import SettlementStageTable
from market_identity import Identity
from market_storefront_kit import TradingPause

from inference_storefront.issuance import issuance_projection
from inference_storefront.materialization import public_result_extension
from inference_storefront.migrate import TABLE_PREFIX
from inference_storefront.model_card import publication_mapping
from inference_storefront.rate_card_guard import request_priced_guard
from inference_storefront.utils import config

if TYPE_CHECKING:
    from market_alkahest import AlkahestChainProbe
    from market_core import MarketDomainContract
    from core_storefront.services.negotiation_service import NegotiationService
    from market_negotiation_runtime import NegotiationRuntime
    from market_settlement_runtime import (
        FailurePolicy,
        SettlementJobCoordinator,
        SettlementRuntime,
        SettlementServicingWorker,
        SettlementSQLiteRepository,
    )
    from arkhai_api_selling.settlement_composition import SellingSettlementComposition
    from market_identity import Signer
    from market_storefront_kit import StorefrontLoopController


SELLING_CONTRIBUTIONS = SellingContributions(
    label=INFERENCE_LABEL,
    kind=INFERENCE_KIND,
    offering_mode=INFERENCE_OFFERING_MODE,
    contribution_id="inference",
    table_prefix=TABLE_PREFIX,
    listing_schema=InferenceListing,
    publication_mapping=publication_mapping,
    issuance_projection=issuance_projection,
    consumption_rule=ConsumptionRule.FIXED_PER_REQUEST,
    publication_guards=(request_priced_guard,),
    public_result_extension=public_result_extension,
    refusal_noun="inference",
)


def storefront_sqlite_client(db_path: str) -> StorefrontSQLiteClient:
    """The storefront's persistence over ``db_path``, under the inference bundle."""
    return StorefrontSQLiteClient(db_path, SELLING_CONTRIBUTIONS)


_sqlite_client: StorefrontSQLiteClient | None = None


def get_sqlite_client() -> StorefrontSQLiteClient:
    """The process's one client over the configured database, composed on first use."""
    global _sqlite_client
    if _sqlite_client is None:
        _sqlite_client = storefront_sqlite_client(config.settings.db_path)
    return _sqlite_client


def _registry_client() -> MultiRegistryClient:
    signer = resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("storefront marketplace signer is not initialized")
    settings = config.settings
    return MultiRegistryClient(
        list(settings.registry.urls),
        caller_role="seller",
        expected_registries=config.resolve_registry_authorities(),
        timeout=settings.registry.discovery_timeout,
        auth=settings.registry.auth,
        signer=signer,
    )


def _registry_publisher() -> Identity:
    signer = resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("storefront marketplace signer is not initialized")
    return signer.identity


def _registry_publication() -> RegistryPublication:
    return RegistryPublication(
        enabled=config.settings.enable_registry_discovery,
        registry_urls=tuple(config.settings.registry.urls),
        storefront_url=config.BASE_URL_OVERRIDE,
        client_factory=_registry_client,
        publisher=_registry_publisher,
    )


QUOTA_CAPACITY = QuotaCapacity(
    sites=config.capacity_sites,
    signer=lambda: resolved_marketplace_signer,
    reconciler=lambda factory: QUOTA_PUBLICATION.reconciler(factory),
)
QUOTA_PUBLICATION = QuotaPublication(
    SELLING_CONTRIBUTIONS, capacity=QUOTA_CAPACITY, registry=_registry_publication
)


def alkahest_stage(**collaborators: Any) -> AlkahestSellerStage:
    """This storefront's Alkahest entry, with any of ``collaborators`` in place of its own."""
    defaults: dict[str, Any] = {
        # A credit grant releases to the seller once issued; no oracle verdict
        # or refund split applies, so only the recipient model is delivered.
        "fulfils_through_capacity": True,
        "release_models": frozenset({RECIPIENT_RELEASE}),
        # The inference schema prices escrow per credit.
        "rate_unit": "credit",
        "chains": lambda: config.CHAINS,
        "address_books": config.chain_address_books,
        "seller_wallet": config.seller_wallet_address,
        "seller_wallet_key": lambda: str(config.settings.get("wallet.private_key", "") or ""),
        "chain_probe": lambda: resolved_alkahest_chain_probe,
        "composition": lambda: resolved_settlement_composition,
        "sqlite_client": lambda: resolved_sqlite_client,
        "backfill_escrows": backfill_escrow_obligation_records,
        "stage_event": stage_event,
    }
    return AlkahestSellerStage(SELLING_CONTRIBUTIONS, **{**defaults, **collaborators})


ALKAHEST_STAGE = alkahest_stage()
#: Alkahest is the only mechanism inference settles through; startup refuses a
#: configured priority naming any other (``startup_refusal``).
SELLER_STAGES = SettlementStageTable({ALKAHEST_STAGE.mechanism: ALKAHEST_STAGE})


def mechanism_loops(stages: SettlementStageTable) -> tuple[ContributedLoop, ...]:
    return tuple(loop for stage in stages.values() for loop in stage.contributed_loops())


def mechanism_startup_steps(
    stages: SettlementStageTable,
) -> tuple[Callable[[], Awaitable[None]], ...]:
    return tuple(step for stage in stages.values() for step in stage.startup_steps())


def mechanism_health(stages: SettlementStageTable) -> dict[str, str]:
    checks: dict[str, str] = {}
    for stage in stages.values():
        checks.update(stage.health_checks())
    return checks


STOREFRONT_LOOPS = StorefrontLoops(
    sqlite_client=lambda: resolved_sqlite_client,
    settlement_worker=lambda: resolved_settlement_worker,
    capacity=QUOTA_CAPACITY,
    settings=config.LOOP_SETTINGS,
    stage_event=stage_event,
    contributed_loops=lambda: mechanism_loops(SELLER_STAGES),
    listing_seed=lambda: resolved_listing_seed,
)

AUTH = StorefrontAuth(
    replay_store=lambda: resolved_sqlite_client,
    signer=lambda: resolved_marketplace_signer,
    admin_principals=lambda: config.resolve_admin_identities(),
    seller_principal=lambda: config.resolve_identity_config().principal,
)

LISTING_ROUTES = ListingRoutes(
    repository=lambda: resolved_sqlite_client,
    listing_service=lambda: resolved_listing_service,
    publication=QUOTA_PUBLICATION,
)
NEGOTIATE_ROUTES = NegotiateRoutes(
    repository=lambda: resolved_sqlite_client,
    runtime=lambda: resolved_negotiation_runtime,
    signer=lambda: resolved_marketplace_signer,
    storefront_url=lambda: config.BASE_URL_OVERRIDE,
)
NEGOTIATION_ROUTES = NegotiationRoutes(
    repository=lambda: resolved_sqlite_client,
    negotiation_service=lambda: resolved_negotiation_service,
    runtime=lambda: resolved_negotiation_runtime,
    signer=lambda: resolved_marketplace_signer,
)
SETTLE_ROUTES = SettleRoutes(
    repository=lambda: resolved_sqlite_client,
    composition=lambda: resolved_settlement_composition,
    coordinator=lambda: resolved_settlement_coordinator,
    signer=lambda: resolved_marketplace_signer,
)

resolved_market_domain: "MarketDomainContract | None" = None
resolved_sqlite_client: "StorefrontSQLiteClient | None" = None
resolved_settlement_repository: "SettlementSQLiteRepository | None" = None
resolved_settlement_runtime: "SettlementRuntime | None" = None
resolved_settlement_worker: "SettlementServicingWorker | None" = None
resolved_settlement_coordinator: "SettlementJobCoordinator | None" = None
resolved_failure_policy: "FailurePolicy | None" = None
resolved_settlement_composition: "SellingSettlementComposition | None" = None
resolved_issuance_evidence_service: "IssuanceEvidenceService | None" = None
resolved_private_result_repository: "PrivateResultRepository | None" = None
#: The probe over each configured chain, owning the live chain-client map;
#: None while no Alkahest section is configured.
resolved_alkahest_chain_probe: "AlkahestChainProbe | None" = None
resolved_listing_service: "ListingService | None" = None
#: The configured seed listing's progress; None without a ``[seed]`` table.
resolved_listing_seed: ListingSeedProgress | None = None
resolved_negotiation_service: "NegotiationService | None" = None
resolved_negotiation_runtime: "NegotiationRuntime | None" = None
resolved_system_service: "SystemService | None" = None
resolved_marketplace_signer: "Signer | None" = None
resolved_loop_controller: "StorefrontLoopController | None" = None

#: Whether this process opens new negotiations. Process-local and kept across
#: lifespans: a restarted process trades again, and a lifespan does not reset it.
trading_pause = TradingPause()

SYSTEM_ROUTES = SystemRoutes(
    repository=lambda: resolved_sqlite_client,
    system_service=lambda: resolved_system_service,
    trading_pause=trading_pause,
    loops=lambda: resolved_loop_controller,
)


def clear_lifespan_state(*, domain: "MarketDomainContract") -> None:
    """Clear inference service state owned by one shared lifespan."""

    global resolved_market_domain
    global resolved_sqlite_client
    global resolved_settlement_repository
    global resolved_settlement_runtime
    global resolved_settlement_worker
    global resolved_settlement_coordinator
    global resolved_failure_policy
    global resolved_settlement_composition
    global resolved_issuance_evidence_service
    global resolved_private_result_repository
    global resolved_alkahest_chain_probe
    global resolved_listing_service
    global resolved_listing_seed
    global resolved_negotiation_service
    global resolved_system_service
    global resolved_marketplace_signer
    global resolved_loop_controller

    if resolved_market_domain is not None and resolved_market_domain is not domain:
        raise RuntimeError(
            "cannot clear a dependency container owned by a different "
            "market-domain contract"
        )
    resolved_market_domain = None
    resolved_sqlite_client = None
    resolved_settlement_repository = None
    resolved_settlement_runtime = None
    resolved_settlement_worker = None
    resolved_settlement_coordinator = None
    resolved_failure_policy = None
    resolved_settlement_composition = None
    resolved_issuance_evidence_service = None
    resolved_private_result_repository = None
    resolved_alkahest_chain_probe = None
    resolved_listing_service = None
    resolved_listing_seed = None
    resolved_negotiation_service = None
    resolved_system_service = None
    resolved_marketplace_signer = None
    if resolved_loop_controller is not None:
        resolved_loop_controller.clear_loops()
    resolved_loop_controller = None
