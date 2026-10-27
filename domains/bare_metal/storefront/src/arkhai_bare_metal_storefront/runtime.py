"""Runtime authorities composed by the bare-metal HTTP application."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core_storefront.auth import AuthError
from core_storefront.identity_authority import IdentityAuthorityError
from core_storefront.service_peers import ServicePeerTrust, seed_service_peers
from market_alkahest import (
    ALKAHEST_CONFIG_KEY,
    AlkahestChainProbe,
    JsonRpcCall,
    ProbedChain,
    ReleaseModelError,
    create_alkahest_registration,
    json_rpc_call,
)
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
from market_capacity_publication import (
    RESOURCE_POOL,
    SiteDerivationLog,
    SiteProjectionState,
)
from market_contact_exchange import (
    MECHANISM as CONTACT_MECHANISM,
)
from market_contact_exchange import (
    ContactExchangeComposition,
    ContactSettlementConfig,
    IntroductionRetentionService,
    SQLiteIntroductionStore,
)
from compute_provisioning_contracts import COMPUTE_PROVISIONING_CONTRACT_VERSION
from market_core import MarketDomainContract, validate_domain_contract
from market_core.schemas import Agreement, SettlementPlan
from market_identity import Identity, Signer, TrustedIdentitySet
from market_negotiation_runtime import NegotiationRuntime
from market_pool_overrides import PoolOverrideService, SQLitePoolOverrideStore
from market_settlement_runtime import (
    SettlementPublicationClause,
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
)
from market_storefront_kit import (
    AlkahestChain,
    AlkahestClientPolicy,
    NegotiationWatchdogPolicy,
    StorefrontLoopController,
    TradingPause,
    alkahest_client_constructor,
)

from .config import (
    IDENTITY_CREDENTIAL_ENV,
    BareMetalStorefrontSettings,
    ChainSettings,
    identity_credential,
    load_storefront_settings,
    packaged_settings,
)
from .delivery import storefront_introduction_delivery
from .domain_runtime import get_market_domain_contract
from .fulfillment_service import BareMetalFulfillmentService
from .lifecycle_steps import (
    PublicationWake,
    bare_metal_loop_controller,
    register_bare_metal_lifecycle_steps,
    site_projection_status,
)
from .listing_source_check import build_listing_source_check
from .negotiation import default_seller_round_hook, seller_chain_check
from .negotiation_runtime import build_bare_metal_negotiation_runtime
from .pool_overrides import (
    BareMetalPoolOverrideContribution,
    compile_publication_clauses,
    positive_lease_bound,
)
from .publication_service import BareMetalRegistryConfiguration
from .settlement import build_bare_metal_settlement_plan
from .settlement_composition import (
    ALKAHEST_MECHANISM,
    BareMetalStorefrontSettlementComposition,
)
from .settlement_service import BareMetalSettlementService
from .settlement_stages import ObligationServicing
from .site_clients import (
    BareMetalSiteBinding,
    SiteClientFactories,
    build_trusted_site_clients,
    parse_site_bindings,
)
from .sqlite_client import SQLiteClient
from .startup_refusal import require_publishable_storefront

logger = logging.getLogger(__name__)

def _status_check_healthy(name: str, value: str) -> bool:
    """Whether one status check's value is healthy.

    ``negotiation_strategy`` reports the chain it probed and ``alkahest`` the
    chain names it serves, so neither is ``ok`` when healthy; the probe
    failing, or an unknown or failing chain, is a degradation.
    """
    if value in ("ok", "unconfigured"):
        return True
    if name == "negotiation_strategy":
        return "exit_on_probe" not in value and not value.startswith(("unknown:", "error:"))
    if name == "alkahest":
        return bool(value) and not value.startswith(("unknown:", "error:"))
    return False


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _watchdog_policy(settings: BareMetalStorefrontSettings) -> NegotiationWatchdogPolicy:
    """The negotiation watchdog's timeout and sweep interval, as configured."""
    return NegotiationWatchdogPolicy(
        timeout_seconds=settings.negotiation_timeout_seconds,
        interval_seconds=settings.negotiation_watchdog_interval,
    )


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
        default=None, init=False, repr=False
    )
    # A runtime composed without configuration files, as a test composes one,
    # takes each interval from the packaged defaults, so they are stated once.
    settlement_servicing_interval_seconds: float = field(
        default_factory=lambda: packaged_settings().settlement_servicing_interval_seconds
    )
    #: How often accepted payment deals are reconciled, while payments are composed.
    payment_reconciliation_interval_seconds: float = field(
        default_factory=lambda: packaged_settings().payment_reconciliation_interval
    )
    #: When an idle negotiation is abandoned, and how often that is swept for.
    negotiation_watchdog: NegotiationWatchdogPolicy = field(
        default_factory=lambda: _watchdog_policy(packaged_settings())
    )
    obligation_servicing: Mapping[str, ObligationServicing] = field(
        default_factory=dict, init=False, repr=False
    )
    plan_builder: Callable[..., dict[str, Any]] = build_bare_metal_settlement_plan
    site_bindings: tuple[BareMetalSiteBinding, ...] = ()
    #: Each site's service-peer principals, held in memory: what the site's
    #: responses and callbacks are verified against, and what an identity
    #: rotation commits through. None authenticates no site.
    service_peer_trust: ServicePeerTrust | None = field(default=None, repr=False)
    capacity_client: Any | None = field(default=None, repr=False)
    fulfillment_client: Any | None = field(default=None, repr=False)
    #: Every configured site's resource-pool and capacity-bucket projections,
    #: held once for the process over ``capacity_client``'s sites: what
    #: publication, the opening recheck, override status, and health read, so
    #: none of them calls a site. None holds no site, so no listing can be
    #: confirmed or published.
    site_projections: SiteProjectionState | None = field(
        default=None, repr=False, compare=False
    )
    #: Runs the publication loop without waiting out its interval: the
    #: projection state sets it on a resource-pool change, and an accepted
    #: pool-override write sets it too.
    publication_wake: PublicationWake = field(
        default_factory=PublicationWake, repr=False, compare=False
    )
    #: Each configured site's holds, refusals, and reports from the latest
    #: publication cycle that derived it, which system status reports.
    publication_derivation: SiteDerivationLog = field(
        default_factory=SiteDerivationLog, repr=False, compare=False
    )
    #: Seconds between the site-projection poller's cycles.
    site_projection_poll_interval_seconds: float = field(
        default_factory=lambda: packaged_settings().capacity.poll_interval
    )
    #: Seconds between publication cycles, unless a wake runs one sooner.
    publication_interval_seconds: float = field(
        default_factory=lambda: packaged_settings().capacity.publication_interval_seconds
    )
    #: How old a site's last successful poll may be for the opening recheck to
    #: confirm a listing against it.
    source_confirmation_seconds: float = field(
        default_factory=lambda: packaged_settings().capacity.confirmation_window_seconds
    )
    #: The time a confirmation's age is measured at.
    source_confirmation_clock: Callable[[], datetime] = field(
        default=_utc_now, repr=False, compare=False
    )
    #: The live Alkahest client map, which ``alkahest_chain_probe`` updates in
    #: place as it rebuilds a client; every consumer holds this one map.
    chain_clients: Mapping[str, Any] = field(default_factory=dict)
    #: Each configured chain's last probe result, which Alkahest readiness
    #: reads; None while no Alkahest section is configured.
    alkahest_chain_probe: AlkahestChainProbe | None = field(
        default=None, repr=False, compare=False
    )
    chain_config_paths: Mapping[str, str | None] = field(default_factory=dict)
    introduction_delivery: Any | None = field(default=None, repr=False)
    escrow_verifier: Callable[..., Awaitable[int]] = field(
        default_factory=lambda: create_alkahest_registration().settlement_verifier
    )
    # The seller chain after the required guards, in any form the policy kit
    # normalizes; None selects the default (``negotiation.DEFAULT_SELLER_POLICIES``).
    negotiation_policies: Any = None
    #: Every registry publication writes to; their reachability is a status check.
    registry_configuration: BareMetalRegistryConfiguration | None = None
    #: The storefront's publication clauses, which a pool's override replaces.
    publication_clauses: tuple[SettlementPublicationClause, ...] = ()
    #: The maximum lease duration a listing publishes unless its pool's override
    #: states one; a pool for which neither is positive is held at publication.
    default_max_duration_seconds: int | None = None
    # Composes one publication cycle for the publication loop's timer and step;
    # None composes it from this runtime through ``compose_publication_cycle``.
    publication_cycle_factory: Callable[["BareMetalStorefrontRuntime"], Any] | None = (
        field(default=None, repr=False)
    )
    # Builds the process's one loop controller. A factory rather than the
    # controller itself, so a runtime copied with `dataclasses.replace` builds
    # its own controller and registers its steps there once, instead of
    # sharing the original's.
    loop_controller_factory: Callable[[], StorefrontLoopController] = field(
        default=bare_metal_loop_controller, repr=False, compare=False
    )
    # The process's one loop controller: it holds this storefront's timer loops
    # under one pause, runs each loop's cycles one at a time whether its timer
    # or an operator's step started one -- the publication command's included,
    # which steps the loop through the administrator API -- and records each
    # cycle's outcome.
    loops: StorefrontLoopController = field(init=False, repr=False, compare=False)
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
        object.__setattr__(self, "loops", self.loop_controller_factory())
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
                # A revealed introduction is the contact-exchange kit's record,
                # never settlement evidence: the deal has no settlement or
                # fulfillment to verify.
                settlement_runtime=self.settlement_runtime,
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
                    self.site_projections,
                    confirmation_window_seconds=self.source_confirmation_seconds,
                    clock=self.source_confirmation_clock,
                ),
                trading_pause=self.trading_pause,
                plan_builder=self.plan_builder,
                accepted_obligation_dispatch=(
                    self.settlement_composition.accepted_obligation_dispatch()
                    if self.settlement_composition is not None
                    else {}
                ),
                chain_config_paths=self.chain_config_paths,
                settlement_data_dispatch=(
                    self.settlement_composition.settlement_data_dispatch()
                    if self.settlement_composition is not None
                    else {}
                ),
                seller_stages=self.domain.settlement.seller_stages,
            ),
        )
        self._compose_settlement_servicing()
        register_bare_metal_lifecycle_steps(self)

    def _compose_settlement_servicing(self) -> None:
        """Compose each seller entry's obligation servicing and the worker.

        They are built here, before the lifecycle steps are registered, so the
        settlement-servicing step exists whenever settlement does. With no
        settlement composition there is none of them.
        """

        if self.settlement_composition is None:
            return
        object.__setattr__(
            self,
            "obligation_servicing",
            {
                mechanism: servicing
                for mechanism, stage in self.domain.settlement.seller_stages.items()
                if stage.servicing is not None
                and (servicing := stage.servicing(self)) is not None
            },
        )

        async def on_ready(record: Any, worker_id: str) -> None:
            servicing = await self._accepted_servicing(record)
            await servicing.ready(record, worker_id)

        async def on_terminal(record: Any, state: str, reason: str | None) -> None:
            servicing = await self._accepted_servicing(record)
            await servicing.terminal(record, state, reason)

        object.__setattr__(
            self,
            "settlement_worker",
            SettlementServicingWorker(
                self.settlement_runtime,
                self.settlement_repository,
                worker_id=f"bare-metal-storefront:{self.seller_principal.identifier}",
                interval_seconds=self.settlement_servicing_interval_seconds,
                on_ready=on_ready,
                on_terminal=on_terminal,
            ),
        )

    async def _accepted_servicing(self, record: Any) -> ObligationServicing:
        """The servicing of the seller entry the obligation's Agreement selected.

        The entry is resolved from the accepted Agreement, as every recovery is,
        never from current configuration; an obligation naming another
        mechanism than its Agreement, or an entry composed without servicing,
        is refused before the worker acts on it.
        """

        thread = await self.db.load_negotiation_thread_row(
            negotiation_id=record.agreement_ref
        )
        if thread is None or not thread.get("agreement_bytes"):
            raise RuntimeError("serviced obligation has no accepted Agreement")
        agreement = Agreement.model_validate_json(thread["agreement_bytes"])
        if agreement.settlement is None:
            raise RuntimeError("accepted Agreement has no settlement selection")
        mechanism = agreement.settlement.mechanism
        if record.obligation.get("mechanism") != mechanism:
            raise RuntimeError(
                "serviced obligation names another mechanism than its Agreement"
            )
        try:
            return self.obligation_servicing[mechanism]
        except KeyError:
            raise RuntimeError(
                f"no bare-metal obligation servicing is composed for {mechanism!r}"
            ) from None

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

    def payments_reconciliation_enabled(self) -> bool:
        """Whether accepted payment deals need a seller-side reconciliation loop."""
        return (
            self.settlement_composition is not None
            and self.settlement_composition.arkhai_payments_stage() is not None
        )

    def _settlement_service(
        self, begin_fulfillment: Any | None = None
    ) -> BareMetalSettlementService:
        composition = self.settlement_composition
        return BareMetalSettlementService(
            db=self.db,
            seller_wallet=self.seller_evm_address or None,
            chain_clients=(
                composition.chain_clients
                if composition is not None
                else {}
            ),
            chain_config_paths=self.chain_config_paths,
            verify_escrow=self.escrow_verifier,
            settlement_runtime=self.settlement_runtime,
            service_obligation=(
                self.settlement_worker.service_obligation
                if self.settlement_worker is not None
                else None
            ),
            arkhai_payments_stage=(
                composition.arkhai_payments_stage() if composition is not None else None
            ),
            stages=self.domain.settlement.seller_stages,
            begin_fulfillment=begin_fulfillment,
        )

    def settlement_service(self) -> BareMetalSettlementService:
        """Build settlement from the configured mechanisms and their resources.

        A stage that verifies and delivers in one call (payment settlement)
        starts fulfillment itself once the receipt verifies, so the service
        carries fulfillment's start when the site authorities are composed.
        """
        composition = self.settlement_composition
        if composition is None:
            raise RuntimeError("no bare-metal settlement mechanism is configured")
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

        A write is checked against its site's live projection, then refreshes
        the projection the storefront holds of that site and wakes the
        publication loop, which publishes under it. Status is judged against the
        held projection, so a site it holds no generation of is ``unknown``.
        """
        if self.capacity_client is None:
            return None
        state = self.site_projections
        return PoolOverrideService(
            store=SQLitePoolOverrideStore(self.db.db_path),
            site_ids=lambda: [binding.site_id for binding in self.site_bindings],
            site_client=self.capacity_client.site,
            contributions={
                BareMetalPoolOverrideContribution.offering_mode: (
                    BareMetalPoolOverrideContribution(
                        configured_max_duration_seconds=lambda: positive_lease_bound(
                            self.default_max_duration_seconds
                        )
                    )
                )
            },
            compile_clauses=compile_publication_clauses,
            projection_source=lambda: (
                dict(state.values(RESOURCE_POOL)) if state is not None else {}
            ),
            refresh_site=state.refresh_site if state is not None else None,
            wake_publication=self.publication_wake,
        )

    def _commercial_settlement_check(self) -> str:
        """``ok`` while a mechanism that takes payment is enabled for new deals.

        A settlement root that enables none (nothing at all, or only contact
        exchange, which takes no payment) is ``unconfigured``: a deliberate
        choice, while its configured sections still service the deals accepted
        under them. ``unavailable`` means there is no settlement composition.
        """
        composition = self.settlement_composition
        if composition is None:
            return "unavailable"
        paying = {ALKAHEST_MECHANISM, ARKHAI_PAYMENTS_MECHANISM}
        if paying & set(composition.enabled_mechanisms):
            return "ok"
        return "unconfigured"

    async def health(self) -> dict[str, object]:
        """Report composed authorities without implying fulfillment readiness.

        Each site's projection families are reported per site in
        ``site_projections``, as the storefront holds them, and enter no gated
        check: one site being down must not present as the whole storefront
        being degraded. Reading them calls no site, so health stays a liveness
        probe. See openspec/specs/site-capacity/spec.md, "Per-site projection
        load-state visibility".
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
            "commercial_settlement": self._commercial_settlement_check(),
            "fulfillment": (
                "ok" if self.fulfillment_client is not None else "unavailable"
            ),
        }
        try:
            await asyncio.to_thread(_check_database)
        except Exception:
            checks["database"] = "error"
        return {
            # A mechanism deliberately left unconfigured is reported, not a
            # degradation, as the other storefronts report theirs.
            "status": (
                "ok"
                if all(value in ("ok", "unconfigured") for value in checks.values())
                else "degraded"
            ),
            "checks": checks,
            "paused": self.trading_pause.paused,
            "principal": self.seller_principal.model_dump(mode="json"),
            "sites": [
                binding.diagnostic(self.service_peer_trust)
                for binding in self.site_bindings
            ],
            "site_projections": (
                site_projection_status(self.site_projections)
                if self.site_projections is not None
                else {}
            ),
            "disclosures": self._disclosures(),
        }

    async def status(self) -> dict[str, object]:
        """The administrator's status: health, plus what reading it costs.

        Adds the checks a deal's readiness depends on and the health probe
        cannot afford — the registry's reachability is a network call — and
        the provisioning contract version this storefront speaks, from its own
        installed contract wheel. Each check is judged by its own rule, as
        every storefront's status judges it: a strategy or chain list is a
        value, not ``ok``.

        It also reports every lifecycle loop by its controller state with the
        outcome of its last cycle, timer-run or stepped, and each configured
        site's holds and their reasons from the latest publication cycle. See
        openspec/specs/storefront-publication/spec.md, "Operator-visible
        acceptance and projection state".
        """
        report = await self.health()
        checks = dict(report["checks"])  # type: ignore[arg-type]
        checks["registry"] = (
            await self.registry_configuration.reachability(self.marketplace_signer)
            if self.registry_configuration is not None
            else "unconfigured"
        )
        checks["negotiation_strategy"] = seller_chain_check(self.negotiation_policies)
        checks["alkahest"] = (
            ",".join(sorted(self.chain_clients)) if self.chain_clients else "unconfigured"
        )
        report["checks"] = checks
        report["status"] = (
            "ok"
            if all(_status_check_healthy(name, value) for name, value in checks.items())
            else "degraded"
        )
        report["provisioning_contract_version"] = COMPUTE_PROVISIONING_CONTRACT_VERSION
        report["lifecycle"] = {
            name: loop.to_dict() for name, loop in self.loops.snapshot().items()
        }
        report["publication_derivation"] = self.publication_derivation.latest()
        # Readiness reads the chain probe's last results and calls no chain.
        # Status names nothing being published, so readiness answers for every
        # configured chain, which servicing accepted deals needs, as every
        # storefront's status does.
        report["settlement"] = (
            [
                status.safe_projection()
                for status in await self.settlement_composition.readiness(clauses=())
            ]
            if self.settlement_composition is not None
            else None
        )
        return report

    def _disclosures(self) -> dict[str, dict[str, object]]:
        """Storefront policies a counterparty may read before committing data.

        Disclosed only while contact exchange admits new deals; a disabled
        section still services accepted introductions.
        """
        if self.contact_settlement_config() is None:
            return {}
        return self.contact_exchange.disclosures()


def _alkahest_client_policy(
    chains: Mapping[str, ChainSettings], *, private_key: str
) -> AlkahestClientPolicy:
    """What the Alkahest chain clients for ``[Chains]`` are built from."""
    alkahest_chains = tuple(
        AlkahestChain(
            name=name,
            rpc_url=chain.rpc_url,
            address_config_path=chain.alkahest_address_config_path or None,
        )
        for name, chain in chains.items()
    )
    missing = ("wallet.private_key",) if alkahest_chains and not private_key else ()
    return AlkahestClientPolicy(
        private_key=private_key,
        chains=alkahest_chains,
        missing_requirements=missing,
    )


def _alkahest_release_models(domain: MarketDomainContract) -> frozenset[str]:
    """The release models the domain's Alkahest seller entry delivers."""
    stage = domain.settlement.seller_stages.get(ALKAHEST_MECHANISM)
    return frozenset(getattr(stage, "release_models", ()) or ())


def seed_service_peer_trust(runtime: BareMetalStorefrontRuntime) -> None:
    """Seed each configured site's service peer, then load the trust from it.

    The database's durable identity state owns a peer's principals from then
    on: a peer seen for the first time is written from configuration, and one
    already seeded must still be covered by it, or startup refuses. One peer at
    a time, so a refusal names the peer it concerns. Blocking; the server runs
    it before it serves.
    """
    trust = runtime.service_peer_trust
    if trust is None:
        return
    for peer_id, peer in trust.peers.items():
        try:
            seed_service_peers(runtime.db.db_path, {peer_id: peer})
        except (AuthError, IdentityAuthorityError) as exc:
            raise RuntimeError(
                f"bare-metal storefront service peer {peer_id!r} cannot be seeded "
                f"into its identity state: {exc}"
            ) from exc
    trust.reload()


def build_runtime_from_configuration(
    settings: BareMetalStorefrontSettings | None = None,
    *,
    credential: str | None = None,
    domain: MarketDomainContract | None = None,
    build_chain_client: Callable[
        [AlkahestClientPolicy], Callable[[str], Any] | None
    ] = alkahest_client_constructor,
    chain_json_rpc: JsonRpcCall = json_rpc_call,
    site_clients: SiteClientFactories = SiteClientFactories(),
) -> BareMetalStorefrontRuntime:
    """Compose the runtime from the storefront's configuration files.

    ``settings`` defaults to what the configuration files say now, and
    ``credential`` to ``ARKHAI_IDENTITY_CREDENTIAL``. Nothing durable is built
    until the configuration is known to publish: the startup refusal runs
    before the signer, the settlement composition, or the database.
    ``build_chain_client`` gives the constructor the chain probe builds each
    Alkahest chain client with, the boundary to the chains the storefront
    settles on, ``chain_json_rpc`` the probe's JSON-RPC transport to each chain, and
    ``site_clients`` each site's clients, the boundary to the site authorities.

    The service-peer trust is built here and holds nothing until the server
    starts and ``seed_service_peer_trust`` seeds and loads it.
    """
    selected_domain = validate_domain_contract(
        domain or get_market_domain_contract(),
    )
    active = load_storefront_settings() if settings is None else settings
    require_publishable_storefront(active)
    try:
        signer = active.signer(identity_credential() if credential is None else credential)
        # The signer resolves only when it owns the configured principal, so its
        # identity is the storefront's public principal.
        principal = signer.identity
        admin_principals = active.administrator_principals()
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "bare-metal storefront requires [Identity.principal], one or two "
            "administrator principals under [Identity.administrators], and a "
            f"matching {IDENTITY_CREDENTIAL_ENV}: {exc}",
        ) from exc
    settlement_config = active.settlement
    try:
        section_check = BareMetalStorefrontSettlementComposition.from_raw_config(
            settlement_config,
            resources={"marketplace_signer": signer, "claimant_principal": principal},
        )
    except ReleaseModelError as exc:
        # A section selecting contradictory release models is incoherent: the
        # refusal names the models rather than calling the section malformed.
        raise RuntimeError(str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise RuntimeError("[Settlement] must be strict shared settlement config") from exc
    # A configured Alkahest section, enabled or not, owns the obligations
    # accepted under it. One that lacks its address, chains, or key cannot
    # settle, which Alkahest readiness reports by name while the storefront's
    # other mechanisms run; with no section, those inputs would be a second,
    # stale statement of what the settlement root says, which is incoherent.
    alkahest_configured = section_check.configures(ALKAHEST_MECHANISM)
    seller_evm_address = active.wallet.address.strip()
    private_key = active.wallet.private_key.strip()
    supplied = {
        "[Wallet].address": bool(seller_evm_address),
        "[Chains]": bool(active.chains),
        "[Wallet].private_key": bool(private_key),
    }
    if alkahest_configured:
        chain_config_paths = {
            name: chain.alkahest_address_config_path or None
            for name, chain in active.chains.items()
        }
        alkahest_section = section_check.config.mechanism_config(ALKAHEST_CONFIG_KEY)
        # The map starts empty and the probe owns it: its first step constructs
        # each chain's client, bounded, since a websocket client connects while
        # it is built and composition must not wait on a chain. The composition
        # and the runtime below are both handed this one dict, which the probe
        # updates in place.
        chain_clients: dict[str, Any] = {}
        chain_probe: AlkahestChainProbe | None = AlkahestChainProbe(
            [
                ProbedChain.from_config(name, chain)
                for name, chain in active.chains.items()
            ],
            build_client=build_chain_client(
                _alkahest_client_policy(active.chains, private_key=private_key)
            ),
            clients=chain_clients,
            interval_seconds=alkahest_section.probe_interval_seconds,
            rpc_timeout_seconds=alkahest_section.rpc_timeout_seconds,
            json_rpc=chain_json_rpc,
        )
    else:
        stale = [name for name, present in supplied.items() if present]
        if stale:
            raise RuntimeError(
                "Alkahest inputs are set but the settlement configuration has no "
                "Alkahest section: " + ", ".join(stale)
            )
        chain_clients, chain_config_paths = {}, {}
        chain_probe = None
    settlement_composition = BareMetalStorefrontSettlementComposition.from_raw_config(
        settlement_config,
        resources={
            "marketplace_signer": signer,
            "claimant_principal": principal,
            # Bare metal signs its settlement transactions with this key, so
            # readiness reports a missing key or chain; the composition's
            # resources are never part of its repr.
            "wallet": {"address": seller_evm_address, "private_key": private_key},
            "signs_transactions": True,
            "deliverable_release_models": _alkahest_release_models(selected_domain),
            "clients": chain_clients,
            **({"chain_probe": chain_probe} if chain_probe is not None else {}),
            "chains": {
                name: chain.model_dump(exclude_none=True)
                for name, chain in active.chains.items()
            },
        },
    )
    try:
        publication_clauses = compile_publication_clauses(active.pricing.settlements)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"[pricing].settlements do not compile: {exc}") from exc
    storefront_url = active.storefront_url
    try:
        site_bindings = parse_site_bindings(
            active.capacity.sites, active.service_peer_configs()
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"bare-metal storefront site bindings are invalid: {exc}") from exc
    db = SQLiteClient(
        active.db_path,
        domain=selected_domain,
        local_listing_principal=principal,
        expected_legacy_sellers=(storefront_url,),
    )
    # Built here and seeded when the server starts (``seed_service_peer_trust``),
    # so composing a runtime writes nothing to the identity state.
    service_peer_trust = ServicePeerTrust(db.db_path, active.service_peer_configs())
    try:
        capacity_client, fulfillment_client = build_trusted_site_clients(
            bindings=site_bindings,
            signer=signer,
            db_path=db.db_path,
            placement=active.capacity.placement,
            trust=service_peer_trust,
            factories=site_clients,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "bare-metal storefront trusted site composition is invalid",
        ) from exc
    # The process's one held projection of every configured site, over the
    # sites' aggregate client, so publication and the opening recheck read one
    # generation per site and family; startup loads it with a first poll.
    publication_wake = PublicationWake()
    site_projections = SiteProjectionState(
        capacity_client, on_resource_pool_change=publication_wake
    )
    try:
        introduction_delivery = storefront_introduction_delivery(
            active.delivery,
            known_origins=[binding.site_id for binding in site_bindings],
            signer=signer,
        )
    except (TypeError, ValueError) as exc:
        raise RuntimeError("[Delivery] must be a strict delivery section") from exc
    return BareMetalStorefrontRuntime(
        negotiation_policies=active.negotiation.policies,
        registry_configuration=BareMetalRegistryConfiguration(
            authorities=active.registry_authorities()
        ),
        publication_clauses=publication_clauses,
        default_max_duration_seconds=active.pricing.default_max_duration_seconds,
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
        alkahest_chain_probe=chain_probe,
        chain_config_paths=chain_config_paths,
        site_bindings=site_bindings,
        service_peer_trust=service_peer_trust,
        capacity_client=capacity_client,
        fulfillment_client=fulfillment_client,
        site_projections=site_projections,
        publication_wake=publication_wake,
        site_projection_poll_interval_seconds=active.capacity.poll_interval,
        publication_interval_seconds=active.capacity.publication_interval_seconds,
        source_confirmation_seconds=active.capacity.confirmation_window_seconds,
        settlement_servicing_interval_seconds=active.settlement_servicing_interval_seconds,
        payment_reconciliation_interval_seconds=active.payment_reconciliation_interval,
        negotiation_watchdog=_watchdog_policy(active),
    )
