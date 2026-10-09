"""Runtime authorities composed by the bare-metal HTTP application."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core_storefront.identity_config import IdentityConfig, resolve_storefront_signer
from core_storefront.models.system_models import ProjectionFamilyStatus
from market_alkahest import create_alkahest_registration
from market_contact_exchange import (
    MECHANISM as CONTACT_MECHANISM,
)
from market_contact_exchange import (
    ContactExchangeComposition,
    ContactSettlementConfig,
    IntroductionRetentionService,
    SQLiteIntroductionStore,
)
from market_core import MarketDomainContract, validate_domain_contract
from market_core.schemas import Agreement, SettlementPlan
from market_identity import Identity, IdentityScheme, Signer, TrustedIdentitySet
from market_negotiation_runtime import NegotiationRuntime
from market_pool_overrides import PoolOverrideService, SQLitePoolOverrideStore
from market_settlement_runtime import (
    SettlementObligationRecord,
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
)
from market_storefront_kit import (
    AlkahestChain,
    AlkahestClientPolicy,
    StorefrontLoopController,
    TradingPause,
    build_alkahest_clients,
)

from .delivery import storefront_introduction_delivery
from .domain_runtime import get_market_domain_contract
from .fulfillment_service import BareMetalFulfillmentService
from .lifecycle_steps import register_bare_metal_lifecycle_steps
from .listing_source_check import build_listing_source_check
from .negotiation import default_seller_round_hook
from .negotiation_runtime import build_bare_metal_negotiation_runtime
from .pool_overrides import (
    BareMetalPoolOverrideContribution,
    accepted_site_projection,
    compile_publication_clauses,
    configured_max_duration_seconds,
)
from .settlement import build_bare_metal_settlement_plan
from .settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from .settlement_service import BareMetalSettlementService
from .site_clients import (
    BareMetalSiteBinding,
    build_trusted_site_clients,
    parse_site_bindings,
)
from .sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)

# The family name VM's health reports a site's resource-pool projection under.
RESOURCE_POOL_PROJECTION_FAMILY = "resource_pool"


@dataclass(frozen=True)
class _RevealRecordingRuntime:
    """The settlement runtime contact exchange drives an introduction through.

    Collecting the introduction's obligation completes the reveal, so the deal's
    settlement evidence is recorded once collection succeeds; every other step
    is the settlement runtime's own.
    """

    runtime: SettlementRuntime
    record_collected: Callable[[str], Awaitable[None]]

    async def register_plan(self, *, agreement_ref: str, obligations: list[Any]) -> Any:
        return await self.runtime.register_plan(
            agreement_ref=agreement_ref, obligations=obligations
        )

    async def materialize(
        self, *, obligation_ref: str, local_principal: Identity, worker_id: str
    ) -> Any:
        return await self.runtime.materialize(
            obligation_ref=obligation_ref,
            local_principal=local_principal,
            worker_id=worker_id,
        )

    async def bind_fulfillment(
        self, obligation_ref: str, fulfillment_ref: str, *, local_principal: Identity
    ) -> Any:
        return await self.runtime.bind_fulfillment(
            obligation_ref, fulfillment_ref, local_principal=local_principal
        )

    async def check(
        self, *, obligation_ref: str, local_principal: Identity, worker_id: str
    ) -> Any:
        return await self.runtime.check(
            obligation_ref=obligation_ref,
            local_principal=local_principal,
            worker_id=worker_id,
        )

    async def collect(
        self, *, obligation_ref: str, local_principal: Identity, worker_id: str
    ) -> Any:
        collected = await self.runtime.collect(
            obligation_ref=obligation_ref,
            local_principal=local_principal,
            worker_id=worker_id,
        )
        await self.record_collected(obligation_ref)
        return collected


@dataclass(frozen=True)
class BareMetalStorefrontRuntime:
    """Process-local handles backed by durable storefront state."""

    db: SQLiteClient
    domain: MarketDomainContract
    seller_principal: Identity
    admin_principals: TrustedIdentitySet
    storefront_url: str
    marketplace_signer: Signer = field(repr=False)
    seller_evm_address: str | None = None
    settlement_composition: BareMetalStorefrontSettlementComposition | None = field(
        default=None,
        repr=False,
    )
    settlement_worker: SettlementServicingWorker | None = field(
        default=None,
        repr=False,
    )
    plan_builder: Callable[..., dict[str, Any]] = build_bare_metal_settlement_plan
    site_bindings: tuple[BareMetalSiteBinding, ...] = ()
    capacity_client: Any | None = field(default=None, repr=False)
    fulfillment_client: Any | None = field(default=None, repr=False)
    chain_clients: Mapping[str, Any] = field(default_factory=dict)
    chain_config_paths: Mapping[str, str | None] = field(default_factory=dict)
    introduction_delivery: Any | None = field(default=None, repr=False)
    escrow_verifier: Callable[..., Awaitable[int]] = field(
        default_factory=lambda: create_alkahest_registration().settlement_verifier
    )
    # The seller chain after the required guards, in any form the policy kit
    # normalizes; None selects the default (``negotiation.DEFAULT_SELLER_POLICIES``).
    negotiation_policies: Any = None
    # Composes one publication cycle for the administrator's publication step;
    # None composes it from the process environment as the command does.
    publication_cycle_factory: Callable[["BareMetalStorefrontRuntime"], Any] | None = (
        field(default=None, repr=False)
    )
    # One publication pass at a time within this process. A pass racing the
    # command in another process is refused by the durable binding's unique
    # derivation key instead.
    publication_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, repr=False, compare=False
    )
    # The process's one loop controller: it holds this storefront's timer loops
    # under one pause and steps each loop's cycle on request.
    loops: StorefrontLoopController = field(
        default_factory=StorefrontLoopController, init=False, repr=False, compare=False
    )
    # Whether this process opens new negotiations; separate from the loops' pause.
    trading_pause: TradingPause = field(
        default_factory=TradingPause, init=False, repr=False, compare=False
    )
    negotiation_runtime: NegotiationRuntime = field(init=False, repr=False)
    settlement_repository: SettlementSQLiteRepository = field(init=False, repr=False)
    settlement_clients: Mapping[str, Any] = field(init=False, repr=False)
    settlement_runtime: SettlementRuntime = field(init=False, repr=False)
    contact_exchange: ContactExchangeComposition = field(init=False, repr=False)

    def __post_init__(self) -> None:
        repository = SettlementSQLiteRepository(
            self.db.db_path,
            apply_migrations=False,
        )
        clients = (
            self.settlement_composition.runtime_clients()
            if self.settlement_composition is not None
            else {}
        )
        object.__setattr__(self, "settlement_repository", repository)
        object.__setattr__(self, "settlement_clients", clients)
        object.__setattr__(
            self,
            "settlement_runtime",
            SettlementRuntime(repository, clients),
        )
        object.__setattr__(
            self,
            "contact_exchange",
            ContactExchangeComposition(
                # Accepted introductions are serviced from the retained
                # section whatever current enablement says; enablement governs
                # only new admission and what the storefront discloses.
                config=self.contact_servicing_config,
                store=SQLiteIntroductionStore(self.db.db_path),
                load_thread=self._accepted_contact_thread,
                load_obligation=repository.load_settlement_obligation,
                load_origin=self._negotiation_origin,
                settlement_runtime=_RevealRecordingRuntime(
                    self.settlement_runtime, self._record_collected_introduction
                ),
                known_origins=[binding.site_id for binding in self.site_bindings],
                deliver=self._deliver_introduction,
            ),
        )
        object.__setattr__(
            self,
            "negotiation_runtime",
            build_bare_metal_negotiation_runtime(
                domain=self.domain,
                seller_principal=self.seller_principal,
                round_hook=default_seller_round_hook(self.negotiation_policies),
                listing_source_check=build_listing_source_check(
                    self.db,
                    self.capacity_client.site if self.capacity_client is not None else None,
                ),
                trading_pause=self.trading_pause,
                plan_builder=self.plan_builder,
                accepted_obligation_dispatch=(
                    self.settlement_composition.accepted_obligation_dispatch()
                    if self.settlement_composition is not None
                    else {}
                ),
                seller_wallet_address=self.seller_evm_address,
                chain_config_paths=self.chain_config_paths,
                settlement_data_dispatch=(
                    self.settlement_composition.settlement_data_dispatch()
                    if self.settlement_composition is not None
                    else {}
                ),
                seller_stages=self.domain.settlement.seller_stages,
            ),
        )
        register_bare_metal_lifecycle_steps(self)

    def _deliver_introduction(self, projection: Any, agreement: Any) -> None:
        """Hand a fresh reveal to the configured seller-side dispatch, if any."""
        if self.introduction_delivery is not None:
            self.introduction_delivery(projection, agreement)

    async def _negotiation_origin(self, negotiation_id: str) -> str | None:
        """The site recorded on the negotiation's binding, or None if unbound."""
        try:
            binding = await self.db.load_thread_binding(negotiation_id=negotiation_id)
        except (KeyError, ValueError):
            return None
        return binding.site_id

    async def _accepted_contact_thread(
        self, *, negotiation_id: str
    ) -> Mapping[str, Any] | None:
        """The negotiation thread contact exchange interprets, behind its seller entry.

        An accepted introduction is serviced from its stored Agreement whatever
        current enablement says: the Agreement must select a mechanism with a
        seller entry, name the thread's parties, and match the plan's one
        obligation, or the reveal is refused.
        """
        thread = await self.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        if thread is None or thread.get("terminal_state") != "success":
            return thread
        try:
            accepted = Agreement.model_validate_json(thread["agreement_bytes"])
            if accepted.settlement is None:
                raise ValueError("accepted Agreement has no settlement selection")
            self.domain.settlement.seller_stages[accepted.settlement.mechanism]
            plan = SettlementPlan.model_validate(thread.get("settlement_plan"))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(
                "accepted Agreement has no supported settlement stage"
            ) from exc
        buyer = Identity.model_validate(accepted.buyer)
        seller = Identity.model_validate(accepted.seller)
        if (
            accepted.negotiation_id != negotiation_id
            or accepted.listing_id != thread.get("our_listing_id")
            or buyer != Identity.model_validate(thread.get("buyer_principal"))
            or seller != Identity.model_validate(thread.get("seller_principal"))
            or len(plan.obligations) != 1
            or plan.obligations[0].mechanism != accepted.settlement.mechanism
            or Identity.model_validate(plan.obligations[0].payer_principal) != buyer
            or Identity.model_validate(plan.obligations[0].claimant_principal) != seller
        ):
            raise ValueError("introduction Agreement differs from the accepted negotiation")
        return thread

    async def _record_collected_introduction(self, obligation_ref: str) -> None:
        """Record a collected introduction as its deal's settlement evidence."""
        row = await self.settlement_repository.load_settlement_obligation(obligation_ref)
        if row is None:
            raise ValueError("introduction obligation is missing")
        negotiation_id = SettlementObligationRecord.model_validate(row).agreement_ref
        thread = await self._accepted_contact_thread(negotiation_id=negotiation_id)
        if thread is None:
            raise ValueError("introduction deal is not accepted")
        accepted = Agreement.model_validate_json(thread["agreement_bytes"])
        assert accepted.settlement is not None
        stage = self.domain.settlement.seller_stages[accepted.settlement.mechanism]
        await stage.record_reveal(
            self.db, negotiation_id=negotiation_id, obligation_ref=obligation_ref
        )

    def payments_reconciliation_enabled(self) -> bool:
        """Whether accepted payment deals need a seller-side reconciliation loop."""
        return (
            self.settlement_composition is not None
            and self.settlement_composition.arkhai_payments_stage() is not None
        )

    def _settlement_service(
        self, begin_fulfillment: Any | None = None
    ) -> BareMetalSettlementService:
        arkhai_payments_stage = (
            self.settlement_composition.arkhai_payments_stage()
            if self.settlement_composition is not None
            else None
        )
        return BareMetalSettlementService(
            db=self.db,
            seller_wallet=self.seller_evm_address or None,
            chain_clients=self.chain_clients,
            chain_config_paths=self.chain_config_paths,
            build_plan=self.plan_builder,
            verify_escrow=self.escrow_verifier,
            settlement_runtime=self.settlement_runtime,
            arkhai_payments_stage=arkhai_payments_stage,
            stages=self.domain.settlement.seller_stages,
            begin_fulfillment=begin_fulfillment,
        )

    def settlement_service(self) -> BareMetalSettlementService:
        """Build settlement for the mechanisms this storefront composes.

        A stage that verifies and delivers in one call (payment settlement)
        starts fulfillment itself once the receipt verifies, so the service
        carries fulfillment's start when the site authorities are composed.
        """
        if self.capacity_client is None or self.fulfillment_client is None:
            return self._settlement_service()
        return self._settlement_service(self.fulfillment_service().begin)

    def fulfillment_service(self) -> BareMetalFulfillmentService:
        """Build durable fulfillment over exact selected-site clients."""
        if self.capacity_client is None or self.fulfillment_client is None:
            raise RuntimeError("bare-metal fulfillment authorities are unavailable")
        return BareMetalFulfillmentService(
            db=self.db,
            capacity_client=self.capacity_client,
            fulfillment_client=self.fulfillment_client,
            read_verified_evidence=self._settlement_service().verified_evidence,
        )

    def contact_settlement_config(self) -> ContactSettlementConfig | None:
        """The contact-exchange section when the mechanism is enabled, else None."""
        composition = self.settlement_composition
        if composition is None or CONTACT_MECHANISM not in composition.enabled_mechanisms:
            return None
        return self.contact_servicing_config()

    def contact_servicing_config(self) -> ContactSettlementConfig | None:
        """The configured contact-exchange section, enabled or not."""
        composition = self.settlement_composition
        if composition is None:
            return None
        section = composition.config.mechanism_config("contact")
        return section if isinstance(section, ContactSettlementConfig) else None

    def introduction_retention(self) -> IntroductionRetentionService | None:
        """Introduction retention while contact exchange is enabled, or None.

        The sweep and operator deletion follow enablement; a disabled section
        still services the reveal of introductions already accepted.
        """
        if self.contact_settlement_config() is None:
            return None
        return self.contact_exchange.retention()

    def pool_override_service(self) -> PoolOverrideService | None:
        """The storefront's pool-override service, or ``None`` without sites.

        Neither after-write effect applies: this storefront caches no site
        projection and publishes only when a run is invoked, so a write takes
        effect at the next run. Status is judged against the generations
        publication runs durably recorded.
        """
        if self.capacity_client is None:
            return None
        db_path = self.db.db_path
        return PoolOverrideService(
            store=SQLitePoolOverrideStore(db_path),
            site_ids=lambda: [binding.site_id for binding in self.site_bindings],
            site_client=self.capacity_client.site,
            contributions={
                BareMetalPoolOverrideContribution.offering_mode: (
                    BareMetalPoolOverrideContribution(
                        configured_max_duration_seconds=lambda: (
                            configured_max_duration_seconds(os.environ)
                        )
                    )
                )
            },
            compile_clauses=compile_publication_clauses,
            projection_source=lambda: accepted_site_projection(db_path),
            refresh_site=None,
            wake_publication=None,
        )

    async def health(self) -> dict[str, object]:
        """Report composed authorities without implying fulfillment readiness.

        Each trusted site's resource-pool projection is reported per site in
        ``site_projections`` and enters no gated check: one site being down
        must not present as the whole storefront being degraded. See
        openspec/specs/site-capacity/spec.md, "Per-site projection load-state
        visibility".
        """

        def _check_database() -> None:
            conn = sqlite3.connect(self.db.db_path)
            try:
                conn.execute("SELECT 1").fetchone()
            finally:
                conn.close()

        checks = {
            "api": "ok",
            "database": "ok",
            "commercial_settlement": (
                "ok"
                if self.settlement_composition is not None or self.chain_clients
                else "unavailable"
            ),
            "fulfillment": (
                "ok" if self.fulfillment_client is not None else "unavailable"
            ),
        }
        try:
            await asyncio.to_thread(_check_database)
            resource_count = await self.db.count_open_bare_metal_resources()
        except Exception:
            checks["database"] = "error"
            resource_count = None
        return {
            "status": (
                "ok" if all(value == "ok" for value in checks.values()) else "degraded"
            ),
            "checks": checks,
            "paused": self.trading_pause.paused,
            "principal": self.seller_principal.model_dump(mode="json"),
            "sites": [binding.diagnostic() for binding in self.site_bindings],
            "resource_count": resource_count,
            "site_projections": await self._site_projections(),
            "disclosures": self._disclosures(),
        }

    def _disclosures(self) -> dict[str, dict[str, object]]:
        """Storefront policies a counterparty may read before committing data.

        Disclosed only while contact exchange admits new deals; a disabled
        section still services accepted introductions.
        """
        if self.contact_settlement_config() is None:
            return {}
        return self.contact_exchange.disclosures()

    async def _site_projections(self) -> dict[str, dict[str, dict[str, object]]]:
        """Each trusted site's resource-pool projection as fetched just now.

        Only the version is fetched: the health route is also the image's
        health probe, and the version carries exactly the revision and digest
        reported. Nothing is cached between calls, so a site is either
        ``loaded`` or ``unavailable``.
        """
        if self.capacity_client is None:
            return {}

        async def _one(site_id: str) -> tuple[str, dict[str, object]]:
            try:
                version = await self.capacity_client.site(
                    site_id
                ).resource_pool_projection_version()
            except Exception as exc:
                status = ProjectionFamilyStatus(
                    state="unavailable", last_error=str(exc)
                )
            else:
                status = ProjectionFamilyStatus(
                    state="loaded",
                    revision=version.get("revision"),
                    digest=version.get("digest"),
                    fetched_at=datetime.now(timezone.utc).isoformat(),
                )
            return site_id, {
                RESOURCE_POOL_PROJECTION_FAMILY: status.model_dump(mode="json")
            }

        results = await asyncio.gather(
            *(_one(binding.site_id) for binding in self.site_bindings)
        )
        return dict(results)


def _build_chain_clients_from_environment() -> tuple[
    dict[str, Any],
    dict[str, str | None],
]:
    raw = os.environ.get("BARE_METAL_STOREFRONT_CHAINS", "{}")
    try:
        values = json.loads(raw)
        if not isinstance(values, dict):
            raise TypeError("chain configuration must be a JSON object")
        chains = tuple(
            AlkahestChain(
                name=str(name),
                rpc_url=str(value["rpc_url"]),
                address_config_path=(
                    str(value["alkahest_address_config_path"])
                    if value.get("alkahest_address_config_path")
                    else None
                ),
            )
            for name, value in values.items()
            if isinstance(value, dict)
        )
        if len(chains) != len(values):
            raise TypeError("every chain configuration must be a JSON object")
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "BARE_METAL_STOREFRONT_CHAINS must map chain names to rpc_url "
            "and optional alkahest_address_config_path"
        ) from exc
    private_key = os.environ.get("BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY", "").strip()
    missing = ("wallet.private_key",) if chains and not private_key else ()
    clients = build_alkahest_clients(
        AlkahestClientPolicy(
            private_key=private_key,
            chains=chains,
            missing_requirements=missing,
        ),
        logger=logger,
    )
    return clients, {chain.name: chain.address_config_path for chain in chains}


def storefront_signer_from_environment(environ: Mapping[str, str]) -> Signer:
    """The storefront's own marketplace signer, from its public identity and
    credential inputs. The server and the operator commands both sign with it,
    so a command can act only as an identity the server would also be.

    Raises ``KeyError`` or ``ValueError`` when an input is missing or does not
    match.
    """
    identity_config = IdentityConfig(
        scheme=IdentityScheme(environ.get("BARE_METAL_STOREFRONT_IDENTITY_SCHEME", "")),
        identifier=environ.get("BARE_METAL_STOREFRONT_IDENTITY_IDENTIFIER", ""),
    )
    return resolve_storefront_signer(identity_config, environ["ARKHAI_IDENTITY_CREDENTIAL"])


def build_runtime_from_environment(
    *,
    domain: MarketDomainContract | None = None,
) -> BareMetalStorefrontRuntime:
    """Build the minimal runtime; trusted site bindings are composed later."""
    selected_domain = validate_domain_contract(
        domain or get_market_domain_contract(),
    )
    try:
        signer = storefront_signer_from_environment(os.environ)
        # The signer resolves only when it owns the configured principal, so its
        # identity is the storefront's public principal.
        principal = signer.identity
        raw_admin_identities = json.loads(
            os.environ["BARE_METAL_STOREFRONT_ADMIN_IDENTITIES"],
        )
        if not isinstance(raw_admin_identities, list):
            raise TypeError("admin identities must be a JSON list")
        admin_principals = TrustedIdentitySet(
            identities=tuple(
                Identity.model_validate(value) for value in raw_admin_identities
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "bare-metal storefront requires public storefront identity, "
            "1-2 admin identities, and a matching ARKHAI_IDENTITY_CREDENTIAL",
        ) from exc
    storefront_url = os.environ.get(
        "BARE_METAL_STOREFRONT_PUBLIC_URL",
        "",
    ).rstrip("/")
    if not storefront_url:
        raise RuntimeError(
            "BARE_METAL_STOREFRONT_PUBLIC_URL is required for listing ownership",
        )
    raw_settlement = os.environ.get("BARE_METAL_STOREFRONT_SETTLEMENT")
    settlement_config: dict[str, Any] | None = None
    settlement_composition: BareMetalStorefrontSettlementComposition | None = None
    if raw_settlement:
        try:
            parsed_settlement = json.loads(raw_settlement)
            if not isinstance(parsed_settlement, dict):
                raise TypeError("settlement config must be a JSON object")
            settlement_config = parsed_settlement
            settlement_composition = (
                BareMetalStorefrontSettlementComposition.from_raw_config(
                    settlement_config,
                    resources={
                        "marketplace_signer": signer,
                        "claimant_principal": principal,
                    },
                )
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "BARE_METAL_STOREFRONT_SETTLEMENT must be strict shared settlement config"
            ) from exc
    if settlement_composition is None:
        raise RuntimeError("BARE_METAL_STOREFRONT_SETTLEMENT is required")
    seller_evm_address = os.environ.get("BARE_METAL_STOREFRONT_EVM_ADDRESS", "").strip()
    chain_clients, chain_config_paths = {}, {}
    for mechanism in settlement_composition.enabled_mechanisms:
        entry = settlement_composition.seller_stages[mechanism]
        if entry.runtime_resources is not None:
            chain_clients, chain_config_paths = entry.runtime_resources(
                seller_evm_address, _build_chain_clients_from_environment
            )
    if settlement_config is not None:
        raw_chains = json.loads(os.environ.get("BARE_METAL_STOREFRONT_CHAINS", "{}"))
        settlement_composition = (
            BareMetalStorefrontSettlementComposition.from_raw_config(
                settlement_config,
                resources={
                    "marketplace_signer": signer,
                    "claimant_principal": principal,
                    "wallet": seller_evm_address or None,
                    "wallet_ready": bool(seller_evm_address),
                    "clients": chain_clients,
                    "chains": raw_chains,
                },
            )
        )
    try:
        site_bindings = parse_site_bindings(
            os.environ["BARE_METAL_STOREFRONT_SITES"],
        )
        site_placement = os.environ.get(
            "BARE_METAL_STOREFRONT_SITE_PLACEMENT",
            "fill_first",
        ).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "bare-metal storefront requires valid trusted site bindings",
        ) from exc
    db = SQLiteClient(
        os.environ.get(
            "BARE_METAL_STOREFRONT_DB_PATH",
            "bare-metal-storefront.db",
        ),
        domain=selected_domain,
        local_listing_principal=principal,
        expected_legacy_sellers=(storefront_url,),
    )
    try:
        capacity_client, fulfillment_client = build_trusted_site_clients(
            bindings=site_bindings,
            signer=signer,
            db_path=db.db_path,
            placement=site_placement,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "bare-metal storefront trusted site composition is invalid",
        ) from exc
    try:
        introduction_delivery = storefront_introduction_delivery(
            known_origins=[binding.site_id for binding in site_bindings],
            signer=signer,
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "BARE_METAL_STOREFRONT_DELIVERY must be a strict [Delivery] section"
        ) from exc
    try:
        negotiation_policies = json.loads(
            os.environ.get("BARE_METAL_STOREFRONT_NEGOTIATION_POLICIES", "null")
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "BARE_METAL_STOREFRONT_NEGOTIATION_POLICIES must be a JSON list of policy names"
        ) from exc
    runtime = BareMetalStorefrontRuntime(
        negotiation_policies=negotiation_policies,
        introduction_delivery=introduction_delivery,
        db=db,
        domain=selected_domain,
        seller_principal=principal,
        storefront_url=storefront_url,
        admin_principals=admin_principals,
        marketplace_signer=signer,
        seller_evm_address=seller_evm_address,
        settlement_composition=settlement_composition,
        chain_clients=chain_clients,
        chain_config_paths=chain_config_paths,
        site_bindings=site_bindings,
        capacity_client=capacity_client,
        fulfillment_client=fulfillment_client,
    )
    return runtime
