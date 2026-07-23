"""Runtime authorities composed by the bare-metal HTTP application."""

from __future__ import annotations

import asyncio
import os
import sqlite3
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from core_storefront.escrow_verification import verify_escrow_for_settlement
from market_core import MarketDomainContract, validate_domain_contract

from .domain_runtime import get_market_domain_contract
from .negotiation import default_seller_round_hook
from .negotiation_service import BareMetalNegotiationService
from .settlement import build_bare_metal_settlement_plan
from .settlement_service import BareMetalSettlementService
from .sqlite_client import SQLiteClient


@dataclass(frozen=True)
class BareMetalStorefrontRuntime:
    """Process-local handles backed by durable storefront state."""

    db: SQLiteClient
    domain: MarketDomainContract
    seller_id: str
    admin_key: str | None = None
    plan_builder: Callable[..., dict[str, Any]] = build_bare_metal_settlement_plan
    chain_clients: Mapping[str, Any] = field(default_factory=dict)
    chain_config_paths: Mapping[str, str | None] = field(default_factory=dict)
    escrow_verifier: Callable[..., Awaitable[None]] = verify_escrow_for_settlement

    def negotiation_service(self) -> BareMetalNegotiationService:
        """Build the request-scoped bare-metal negotiation orchestrator."""
        return BareMetalNegotiationService(
            db=self.db,
            domain=self.domain,
            seller_id=self.seller_id,
            round_hook=default_seller_round_hook(),
            build_plan=self.plan_builder,
        )

    def settlement_service(self) -> BareMetalSettlementService:
        """Build commercial verification from explicitly configured chains."""
        return BareMetalSettlementService(
            db=self.db,
            seller_wallet=self.seller_id,
            chain_clients=self.chain_clients,
            chain_config_paths=self.chain_config_paths,
            build_plan=self.plan_builder,
            verify_escrow=self.escrow_verifier,
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
            "agent_id": self.seller_id or None,
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
    return BareMetalStorefrontRuntime(
        db=SQLiteClient(
            os.environ.get(
                "BARE_METAL_STOREFRONT_DB_PATH",
                "bare-metal-storefront.db",
            ),
            domain=selected_domain,
        ),
        domain=selected_domain,
        seller_id=os.environ.get("BARE_METAL_STOREFRONT_SELLER_ID", ""),
        admin_key=os.environ.get("BARE_METAL_STOREFRONT_ADMIN_KEY") or None,
    )
