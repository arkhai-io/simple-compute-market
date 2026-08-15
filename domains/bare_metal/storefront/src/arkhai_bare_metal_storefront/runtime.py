"""Runtime authorities composed by the bare-metal HTTP application."""

from __future__ import annotations

import asyncio
import json
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

from .domain_runtime import get_market_domain_contract
from .negotiation import default_seller_round_hook
from .negotiation_service import BareMetalNegotiationService
from .settlement import build_bare_metal_settlement_plan
from .settlement_service import BareMetalSettlementService
from .sqlite_client import SQLiteClient
from .site_clients import (
    BareMetalSiteBinding,
    build_trusted_site_clients,
    parse_site_bindings,
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
    seller_evm_address: str
    plan_builder: Callable[..., dict[str, Any]] = build_bare_metal_settlement_plan
    site_bindings: tuple[BareMetalSiteBinding, ...] = ()
    capacity_client: Any | None = field(default=None, repr=False)
    fulfillment_site_clients: Mapping[str, Any] = field(
        default_factory=dict,
        repr=False,
    )
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
        if self.capacity_client is not None:
            try:
                await self.capacity_client.snapshot()
            except Exception:
                checks["site_projection"] = "error"
                checks["fulfillment"] = "error"
            else:
                checks["site_projection"] = "ok"
                checks["fulfillment"] = (
                    "ok" if self.fulfillment_site_clients else "unavailable"
                )
        return {
            "status": (
                "ok"
                if all(value == "ok" for value in checks.values())
                else "degraded"
            ),
            "checks": checks,
            "paused": paused,
            "principal": self.seller_principal.model_dump(mode="json"),
            "sites": [binding.diagnostic() for binding in self.site_bindings],
            "resource_count": resource_count,
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
        capacity_client, fulfillment_site_clients = build_trusted_site_clients(
            bindings=site_bindings,
            signer=signer,
            db_path=db.db_path,
            placement=site_placement,
        )
    except (RuntimeError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "bare-metal storefront trusted site composition is invalid",
        ) from exc
    return BareMetalStorefrontRuntime(
        db=db,
        domain=selected_domain,
        seller_principal=identity_config.principal,
        storefront_url=storefront_url,
        admin_principals=admin_principals,
        marketplace_signer=signer,
        seller_evm_address=seller_evm_address,
        site_bindings=site_bindings,
        capacity_client=capacity_client,
        fulfillment_site_clients=fulfillment_site_clients,
    )
