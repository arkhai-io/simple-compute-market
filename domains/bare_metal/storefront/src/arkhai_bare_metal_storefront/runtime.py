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
from core_storefront.escrow_verification import verify_escrow_for_settlement
from market_core import MarketDomainContract, validate_domain_contract
from market_settlement_runtime import SettlementRuntime, SettlementSQLiteRepository
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
from .sqlite_client import SQLiteClient


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
    seller_evm_address: str
    plan_builder: Callable[..., dict[str, Any]] = build_bare_metal_settlement_plan
    chain_clients: Mapping[str, Any] = field(default_factory=dict)
    chain_config_paths: Mapping[str, str | None] = field(default_factory=dict)
    escrow_verifier: Callable[..., Awaitable[int]] = verify_escrow_for_settlement
    settlement_repository: SettlementSQLiteRepository = field(init=False, repr=False)
    settlement_runtime: SettlementRuntime = field(init=False, repr=False)

    def __post_init__(self) -> None:
        repository = SettlementSQLiteRepository(
            self.db.db_path,
            apply_migrations=False,
        )
        object.__setattr__(self, "settlement_repository", repository)
        object.__setattr__(
            self,
            "settlement_runtime",
            SettlementRuntime(repository, {}),
        )

    def negotiation_service(self) -> BareMetalNegotiationService:
        """Build the request-scoped bare-metal negotiation orchestrator."""
        return BareMetalNegotiationService(
            db=self.db,
            domain=self.domain,
            seller_principal=self.seller_principal,
            round_hook=default_seller_round_hook(),
            build_plan=self.plan_builder,
        )

    def settlement_service(self) -> BareMetalSettlementService:
        """Build commercial verification from explicitly configured chains."""
        return BareMetalSettlementService(
            db=self.db,
            seller_wallet=self.seller_evm_address,
            chain_clients=self.chain_clients,
            chain_config_paths=self.chain_config_paths,
            build_plan=self.plan_builder,
            verify_escrow=self.escrow_verifier,
            settlement_runtime=self.settlement_runtime,
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
            "commercial_settlement": "ok" if self.chain_clients else "unavailable",
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
        return {
            "status": "degraded" if "unavailable" in checks.values() else "ok",
            "checks": checks,
            "paused": paused,
            "principal": self.seller_principal.model_dump(mode="json"),
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
    return clients, {
        chain.name: chain.address_config_path
        for chain in chains
    }


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
    seller_evm_address = os.environ.get(
        "BARE_METAL_STOREFRONT_EVM_ADDRESS",
        "",
    )
    if not seller_evm_address:
        raise RuntimeError(
            "BARE_METAL_STOREFRONT_EVM_ADDRESS is required for Alkahest settlement",
        )
    chain_clients, chain_config_paths = _build_chain_clients_from_environment()
    return BareMetalStorefrontRuntime(
        db=SQLiteClient(
            os.environ.get(
                "BARE_METAL_STOREFRONT_DB_PATH",
                "bare-metal-storefront.db",
            ),
            domain=selected_domain,
            local_listing_principal=identity_config.principal,
            expected_legacy_sellers=(storefront_url,),
        ),
        domain=selected_domain,
        seller_principal=identity_config.principal,
        storefront_url=storefront_url,
        admin_principals=admin_principals,
        marketplace_signer=signer,
        seller_evm_address=seller_evm_address,
        chain_clients=chain_clients,
        chain_config_paths=chain_config_paths,
    )
