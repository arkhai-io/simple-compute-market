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
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM
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
from market_identity import Identity, IdentityScheme, Signer, TrustedIdentitySet
from market_negotiation_runtime import NegotiationRuntime
from market_pool_overrides import PoolOverrideService, SQLitePoolOverrideStore
from market_settlement_runtime import (
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

from .alkahest_lifecycle import BareMetalAlkahestLifecycle
from .delivery import storefront_introduction_delivery
from .domain_runtime import get_market_domain_contract
from .fulfillment_service import BareMetalFulfillmentService
from .lifecycle_steps import register_bare_metal_lifecycle_steps
from .listing_source_check import build_listing_source_check
from .negotiation import default_seller_round_hook, seller_chain_check
from .negotiation_runtime import build_bare_metal_negotiation_runtime
from .pool_overrides import (
    BareMetalPoolOverrideContribution,
    accepted_site_projection,
    compile_publication_clauses,
    configured_max_duration_seconds,
)
from .publication_service import BareMetalRegistryConfiguration
from .settlement import build_bare_metal_settlement_plan
from .settlement_composition import (
    ALKAHEST_MECHANISM,
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


# The family name VM's health reports a site's resource-pool projection under.
RESOURCE_POOL_PROJECTION_FAMILY = "resource_pool"


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
    settlement_servicing_interval_seconds: float = 30.0
    alkahest_lifecycle: BareMetalAlkahestLifecycle | None = field(
        default=None, init=False, repr=False
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
    #: The registry publication writes to; its reachability is a status check.
    registry_configuration: BareMetalRegistryConfiguration | None = None
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
                config=self.contact_settlement_config,
                store=SQLiteIntroductionStore(self.db.db_path),
                load_thread=self.db.load_negotiation_thread_row,
                load_obligation=repository.load_settlement_obligation,
                load_origin=self._negotiation_origin,
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
            ),
        )
        self._compose_settlement_servicing()
        register_bare_metal_lifecycle_steps(self)

    def _compose_settlement_servicing(self) -> None:
        """Compose the Alkahest step and the obligation-servicing worker.

        They are built here, before the lifecycle steps are registered, so the
        settlement-servicing step exists whenever settlement does. With no
        settlement composition there is none of them.
        """

        composition = self.settlement_composition
        if composition is None:
            return
        if composition.configures(ALKAHEST_MECHANISM):
            object.__setattr__(
                self,
                "alkahest_lifecycle",
                BareMetalAlkahestLifecycle(
                    db=self.db,
                    runtime=self.settlement_runtime,
                    local_principal=self.seller_principal,
                    fulfillment_service=self.fulfillment_service,
                    chain_clients=composition.resources.get("clients") or {},
                ),
            )
        alkahest = self.alkahest_lifecycle

        # Each mechanism's fulfillment is started by whatever owns it. Contact
        # exchange's reveal binds its own obligation, so it is declined without
        # being reserved; an obligation under any other mechanism has nothing
        # here that could deliver it.
        async def on_ready(record: Any, worker_id: str) -> None:
            mechanism = str(record.obligation.get("mechanism") or "")
            if mechanism == ALKAHEST_MECHANISM and alkahest is not None:
                await alkahest.fulfill(record, worker_id)
            elif mechanism != CONTACT_MECHANISM:
                raise RuntimeError(
                    f"no bare-metal fulfillment is composed for {mechanism!r}"
                )

        async def on_terminal(record: Any, state: str, reason: str | None) -> None:
            mechanism = str(record.obligation.get("mechanism") or "")
            if mechanism == ALKAHEST_MECHANISM and alkahest is not None:
                await alkahest.end_service(record, state, reason)
            elif mechanism != CONTACT_MECHANISM:
                raise RuntimeError(
                    f"no bare-metal terminal handling is composed for {mechanism!r}"
                )

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

    def payments_reconciliation_enabled(self) -> bool:
        """Whether accepted payment deals need a seller-side reconciliation loop."""
        return (
            self.settlement_composition is not None
            and self.settlement_composition.arkhai_payments_stage() is not None
        )

    def settlement_service(self) -> BareMetalSettlementService:
        """Build settlement from the configured mechanisms and their resources."""
        composition = self.settlement_composition
        if composition is None:
            raise RuntimeError("no bare-metal settlement mechanism is configured")
        alkahest_configured = composition.configures(ALKAHEST_MECHANISM)
        if alkahest_configured and not self.seller_evm_address:
            raise RuntimeError("Alkahest settlement is not configured")
        payments = composition.arkhai_payments_stage()
        if not alkahest_configured and payments is None:
            raise RuntimeError("no bare-metal settlement mechanism is configured")
        return BareMetalSettlementService(
            db=self.db,
            seller_wallet=self.seller_evm_address or None,
            chain_clients=composition.resources.get("clients") or {},
            chain_config_paths=self.chain_config_paths,
            verify_escrow=self.escrow_verifier,
            settlement_runtime=self.settlement_runtime,
            service_obligation=(
                self.settlement_worker.service_obligation
                if self.settlement_worker is not None
                else None
            ),
            arkhai_payments_stage=payments,
            begin_fulfillment=(
                self.fulfillment_service().begin
                if self.capacity_client is not None and self.fulfillment_client is not None
                else None
            ),
        )

    def fulfillment_service(self) -> BareMetalFulfillmentService:
        """Build durable fulfillment over exact selected-site clients."""
        if self.capacity_client is None or self.fulfillment_client is None:
            raise RuntimeError("bare-metal fulfillment authorities are unavailable")
        return BareMetalFulfillmentService(
            db=self.db,
            capacity_client=self.capacity_client,
            fulfillment_client=self.fulfillment_client,
        )

    def contact_settlement_config(self) -> ContactSettlementConfig | None:
        """The contact-exchange section when the mechanism is enabled, else None."""
        composition = self.settlement_composition
        if composition is None or CONTACT_MECHANISM not in composition.enabled_mechanisms:
            return None
        section = composition.config.mechanism_config("contact")
        return section if isinstance(section, ContactSettlementConfig) else None

    def introduction_retention(self) -> IntroductionRetentionService | None:
        """Introduction retention under the running configuration, or None."""
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
            "commercial_settlement": self._commercial_settlement_check(),
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
            "sites": [binding.diagnostic() for binding in self.site_bindings],
            "resource_count": resource_count,
            "site_projections": await self._site_projections(),
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
        return report

    def _disclosures(self) -> dict[str, dict[str, object]]:
        """Storefront policies a counterparty may read before committing data."""
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
    raw_settlement = os.environ.get("BARE_METAL_STOREFRONT_SETTLEMENT", "").strip()
    if not raw_settlement:
        raise RuntimeError(
            "BARE_METAL_STOREFRONT_SETTLEMENT is required: the storefront enables "
            "no settlement mechanism implicitly"
        )
    try:
        settlement_config = json.loads(raw_settlement)
        if not isinstance(settlement_config, dict):
            raise TypeError("settlement config must be a JSON object")
        section_check = BareMetalStorefrontSettlementComposition.from_raw_config(
            settlement_config,
            resources={"marketplace_signer": signer, "claimant_principal": principal},
        )
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "BARE_METAL_STOREFRONT_SETTLEMENT must be strict shared settlement config"
        ) from exc
    # A configured Alkahest section, enabled or not, owns the obligations
    # accepted under it, so its recovery resources are required whenever the
    # section exists; with no section they would be a second, stale statement
    # of what the settlement root says.
    alkahest_configured = section_check.configures(ALKAHEST_MECHANISM)
    seller_evm_address = os.environ.get(
        "BARE_METAL_STOREFRONT_EVM_ADDRESS",
        "",
    ).strip()
    raw_chains = os.environ.get("BARE_METAL_STOREFRONT_CHAINS", "").strip()
    private_key = os.environ.get("BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY", "").strip()
    supplied = {
        "BARE_METAL_STOREFRONT_EVM_ADDRESS": bool(seller_evm_address),
        "BARE_METAL_STOREFRONT_CHAINS": raw_chains not in ("", "{}"),
        "BARE_METAL_STOREFRONT_EVM_PRIVATE_KEY": bool(private_key),
    }
    if alkahest_configured:
        missing = [name for name, present in supplied.items() if not present]
        if missing:
            raise RuntimeError(
                "a configured Alkahest settlement section, enabled or not, requires "
                + ", ".join(missing)
            )
        chain_clients, chain_config_paths = _build_chain_clients_from_environment()
    else:
        stale = [name for name, present in supplied.items() if present]
        if stale:
            raise RuntimeError(
                "Alkahest inputs are set but the settlement configuration has no "
                "Alkahest section: " + ", ".join(stale)
            )
        chain_clients, chain_config_paths = {}, {}
    settlement_composition = BareMetalStorefrontSettlementComposition.from_raw_config(
        settlement_config,
        resources={
            "marketplace_signer": signer,
            "claimant_principal": principal,
            "wallet": seller_evm_address or None,
            "wallet_ready": bool(seller_evm_address),
            "clients": chain_clients,
            "chains": json.loads(raw_chains) if raw_chains else {},
        },
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
    registry_configuration = (
        BareMetalRegistryConfiguration.from_environment(os.environ)
        if os.environ.get("BARE_METAL_STOREFRONT_REGISTRY_URL")
        else None
    )
    runtime = BareMetalStorefrontRuntime(
        negotiation_policies=negotiation_policies,
        registry_configuration=registry_configuration,
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
        settlement_servicing_interval_seconds=float(
            os.environ.get("BARE_METAL_SETTLEMENT_SERVICING_INTERVAL_SECONDS", "30")
        ),
    )
    return runtime
