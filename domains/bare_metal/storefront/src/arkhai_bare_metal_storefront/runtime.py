"""Runtime authorities composed by the bare-metal HTTP application."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from core_storefront.identity_config import IdentityConfig, resolve_storefront_signer
from market_identity import Identity, IdentityScheme, Signer, TrustedIdentitySet
from market_alkahest import create_alkahest_registration
from market_core import MarketDomainContract, validate_domain_contract
from market_hosted_settlement import PortableRemoteFulfillmentRef, canonical_json
from market_settlement_runtime import (
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
)
from market_storefront_kit import (
    AlkahestChain,
    AlkahestClientPolicy,
    build_alkahest_clients,
)

from .domain_runtime import get_market_domain_contract
from .negotiation import default_seller_round_hook
from .negotiation_service import BareMetalNegotiationService
from .settlement import build_bare_metal_settlement_plan
from .settlement_service import BareMetalSettlementService
from .fulfillment_service import BareMetalFulfillmentService
from .hosted_lifecycle import BareMetalHostedLifecycleCallbacks
from .hosted_routes import (
    BareMetalHostedDomainCallbacks,
    lifecycle_domain_callbacks,
)
from .sqlite_client import SQLiteClient
from .site_clients import (
    BareMetalSiteBinding,
    build_trusted_site_clients,
    parse_site_bindings,
)
from .settlement_composition import (
    ALKAHEST_MECHANISM,
    BareMetalStorefrontSettlementComposition,
    default_hosted_selection_dispatch,
)


def _portable_evidence_reference(
    lifecycle: Any,
    attestation_uid: str,
) -> str:
    condition = lifecycle.accepted_binding.option.option.params.get("condition")
    evaluator = condition.get("evaluator") if isinstance(condition, Mapping) else None
    resolver_id = (
        evaluator.get("resolver_id") if isinstance(evaluator, Mapping) else None
    )
    if not isinstance(resolver_id, str) or not resolver_id:
        raise RuntimeError("hosted evidence resolver is unavailable")
    fulfillment = PortableRemoteFulfillmentRef(
        resolver_id=resolver_id,
        uid=attestation_uid,
    )
    return canonical_json(fulfillment.model_dump(mode="json")).decode()


async def _publish_portable_evidence_reference(
    lifecycle: Any,
    evidence: Any,
    publisher: Any,
) -> str:
    attestation_uid = await publisher.publish_fulfillment(
        condition_anchor=evidence.condition_anchor,
        evidence=evidence.canonical_json(),
    )
    return _portable_evidence_reference(lifecycle, attestation_uid)


logger = logging.getLogger(__name__)


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
    hosted_domain_callbacks: BareMetalHostedDomainCallbacks | None = field(
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
    escrow_verifier: Callable[..., Awaitable[int]] = field(
        default_factory=lambda: create_alkahest_registration().settlement_verifier
    )
    settlement_repository: SettlementSQLiteRepository = field(init=False, repr=False)
    settlement_clients: Mapping[str, Any] = field(init=False, repr=False)
    settlement_runtime: SettlementRuntime = field(init=False, repr=False)

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

    def negotiation_service(self) -> BareMetalNegotiationService:
        """Build the request-scoped bare-metal negotiation orchestrator."""
        return BareMetalNegotiationService(
            db=self.db,
            domain=self.domain,
            seller_principal=self.seller_principal,
            round_hook=default_seller_round_hook(),
            build_plan=self.plan_builder,
            accepted_obligation_dispatch=(
                self.settlement_composition.accepted_obligation_dispatch()
                if self.settlement_composition is not None
                else default_hosted_selection_dispatch()
            ),
        )

    def settlement_service(self) -> BareMetalSettlementService:
        """Build commercial verification from explicitly configured chains."""
        if not self.seller_evm_address:
            raise RuntimeError("Alkahest settlement is not configured")
        return BareMetalSettlementService(
            db=self.db,
            seller_wallet=self.seller_evm_address,
            chain_clients=self.chain_clients,
            chain_config_paths=self.chain_config_paths,
            build_plan=self.plan_builder,
            verify_escrow=self.escrow_verifier,
            settlement_runtime=self.settlement_runtime,
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

    async def health(self) -> dict[str, object]:
        """Report composed authorities without implying fulfillment readiness."""

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
            "site_projection": "unavailable",
            "fulfillment": "unavailable",
        }
        try:
            await asyncio.to_thread(_check_database)
            paused = await self.db.is_global_paused()
            resource_count = await self.db.count_open_bare_metal_resources()
        except Exception:
            checks["database"] = "error"
            paused = None
            resource_count = None
        if self.capacity_client is not None:
            try:
                await self.capacity_client.snapshot()
            except Exception:
                checks["site_projection"] = "error"
                checks["fulfillment"] = "error"
            else:
                checks["site_projection"] = "ok"
                checks["fulfillment"] = (
                    "ok" if self.fulfillment_client is not None else "unavailable"
                )
        return {
            "status": (
                "ok" if all(value == "ok" for value in checks.values()) else "degraded"
            ),
            "checks": checks,
            "paused": paused,
            "principal": self.seller_principal.model_dump(mode="json"),
            "sites": [binding.diagnostic() for binding in self.site_bindings],
            "resource_count": resource_count,
        }


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


def build_runtime_from_environment(
    *,
    domain: MarketDomainContract | None = None,
) -> BareMetalStorefrontRuntime:
    """Build the minimal runtime; trusted site bindings are composed later."""
    selected_domain = validate_domain_contract(
        domain or get_market_domain_contract(),
    )
    try:
        identity_config = IdentityConfig(
            scheme=IdentityScheme(
                os.environ.get("BARE_METAL_STOREFRONT_IDENTITY_SCHEME", ""),
            ),
            identifier=os.environ.get(
                "BARE_METAL_STOREFRONT_IDENTITY_IDENTIFIER",
                "",
            ),
        )
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
        signer = resolve_storefront_signer(
            identity_config,
            os.environ["ARKHAI_IDENTITY_CREDENTIAL"],
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
                        "claimant_principal": identity_config.principal,
                    },
                )
            )
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "BARE_METAL_STOREFRONT_SETTLEMENT must be strict shared settlement config"
            ) from exc
    alkahest_enabled = (
        settlement_composition is None
        or ALKAHEST_MECHANISM in settlement_composition.enabled_mechanisms
    )
    seller_evm_address = os.environ.get(
        "BARE_METAL_STOREFRONT_EVM_ADDRESS",
        "",
    ).strip()
    if alkahest_enabled and not seller_evm_address:
        raise RuntimeError(
            "BARE_METAL_STOREFRONT_EVM_ADDRESS is required when Alkahest is enabled",
        )
    if alkahest_enabled:
        chain_clients, chain_config_paths = _build_chain_clients_from_environment()
    else:
        chain_clients, chain_config_paths = {}, {}
    if settlement_config is not None:
        raw_chains = json.loads(os.environ.get("BARE_METAL_STOREFRONT_CHAINS", "{}"))
        settlement_composition = (
            BareMetalStorefrontSettlementComposition.from_raw_config(
                settlement_config,
                resources={
                    "marketplace_signer": signer,
                    "claimant_principal": identity_config.principal,
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
        local_listing_principal=identity_config.principal,
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
    runtime = BareMetalStorefrontRuntime(
        db=db,
        domain=selected_domain,
        seller_principal=identity_config.principal,
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
    if settlement_composition is not None and "fiat.stripe.v1" in (
        settlement_composition.enabled_mechanisms
    ):

        async def publish_evidence(evidence: Any) -> str:
            lifecycle = await db.load_bare_metal_hosted_lifecycle(
                obligation_ref=evidence.obligation_ref
            )
            if lifecycle is None:
                raise RuntimeError("hosted evidence lifecycle is unavailable")
            publisher = runtime.settlement_clients["fiat.stripe.v1"]
            return await _publish_portable_evidence_reference(
                lifecycle,
                evidence,
                publisher,
            )

        lifecycle = BareMetalHostedLifecycleCallbacks(
            db=db,
            runtime=runtime.settlement_runtime,
            local_principal=identity_config.principal,
            capacity_client=capacity_client,
            fulfillment_client=fulfillment_client,
            publish_evidence=publish_evidence,
        )
        callbacks = lifecycle_domain_callbacks(db=db, lifecycle=lifecycle)
        object.__setattr__(runtime, "hosted_domain_callbacks", callbacks)

        async def on_ready(record: Any, worker_id: str) -> None:
            await callbacks.fulfill(record, worker_id)

        async def on_terminal(
            record: Any,
            state: str,
            reason: str | None,
        ) -> None:
            if state != "collected":
                await callbacks.cleanup(
                    record.agreement_ref,
                    reason or state,
                )

        object.__setattr__(
            runtime,
            "settlement_worker",
            SettlementServicingWorker(
                runtime.settlement_runtime,
                runtime.settlement_repository,
                worker_id=f"bare-metal-storefront:{identity_config.principal.identifier}",
                interval_seconds=float(
                    os.environ.get(
                        "BARE_METAL_SETTLEMENT_SERVICING_INTERVAL_SECONDS",
                        "30",
                    )
                ),
                on_ready=on_ready,
                on_terminal=on_terminal,
            ),
        )
    return runtime
