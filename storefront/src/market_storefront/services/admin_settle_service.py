"""Admin settlement service — dry-run operations for the settle pipeline.

These methods test the constituent parts of the settlement pipeline in
isolation, without DB writes, chain commits, or provisioning calls. They
implement the evaluate→advance→observe pattern:

    evaluate (this module)        advance (POST /settle/{uid})
    ────────────────────────────  ───────────────────────────
    verify_escrow_dry_run         start_settlement_job → verify_escrow_for_settlement
    evaluate_settle_dry_run       start_settlement_job → _build_provisioning_job_spec
                                                        → _do_provision
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Imported at module level so unit tests can patch them directly on this module.
from market_storefront.utils.escrow_verification import (  # noqa: E402
    EscrowVerificationError,
    verify_escrow_for_settlement,
)
from market_storefront.utils.action_executor import _build_provisioning_job_spec  # noqa: E402


class AdminSettleService:
    """Dry-run services for the settlement pipeline.

    Thin service layer: each method calls exactly one pipeline primitive and
    returns a structured result. The controller remains a thin HTTP adapter.

    Args:
        sqlite_client: SQLite client for DB lookups (read-only in this service).
        alkahest_clients: Per-chain ``AlkahestClient`` dict, keyed by chain
            name. ``verify_escrow_dry_run`` picks the entry matching the
            caller-supplied ``chain_name``; an unknown chain surfaces as
            ``valid=False, reason="chain '<name>' not configured"`` rather
            than crashing.
    """

    def __init__(
        self, sqlite_client: Any, alkahest_clients: dict[str, Any] | None = None
    ) -> None:
        self._db = sqlite_client
        self._alkahest_clients = alkahest_clients or {}

    async def verify_escrow_dry_run(
        self,
        *,
        escrow_uid: str,
        listing_id: str,
        seller_wallet: str,
        agreed_price: float,
        agreed_duration_seconds: int,
        chain_name: str,
    ) -> dict:
        """Read the escrow from chain and confirm it matches the supplied terms.

        Tests getRecordFromChain in isolation — no DB writes, no provisioning.

        Returns:
            {"valid": True, "escrow_uid": ...}  on success
            {"valid": False, "escrow_uid": ..., "reason": "<why>"}  on any mismatch

        Raises:
            ValueError  if the listing is not found in SQLite (caller maps to 404)
        """
        listing = await self._db.load_listing(listing_id=listing_id)
        if not listing:
            raise ValueError(f"Listing {listing_id!r} not found")

        alkahest = self._alkahest_clients.get(chain_name)
        if alkahest is None:
            return {
                "valid": False,
                "escrow_uid": escrow_uid,
                "reason": f"chain {chain_name!r} not configured on this storefront",
            }

        from market_storefront.utils.config import CHAINS
        chain_cfg = CHAINS.get(chain_name)
        if chain_cfg is None:
            return {
                "valid": False,
                "escrow_uid": escrow_uid,
                "reason": f"chain {chain_name!r} missing from [chains] config",
            }

        try:
            await verify_escrow_for_settlement(
                escrow_uid=escrow_uid,
                seller_wallet=seller_wallet,
                agreed_price=agreed_price,
                agreed_duration_seconds=agreed_duration_seconds,
                listing=listing,
                alkahest_client=alkahest,
                chain_name=chain_name,
                alkahest_address_config_path=chain_cfg.alkahest_address_config_path,
            )
        except EscrowVerificationError as exc:
            return {"valid": False, "escrow_uid": escrow_uid, "reason": str(exc)}

        return {"valid": True, "escrow_uid": escrow_uid}

    async def evaluate_settle_dry_run(
        self,
        *,
        escrow_uid: str,
        listing_id: str,
        ssh_public_key: str,
        duration_seconds: int,
    ) -> dict:
        """Resolve a host from inventory and build the provisioning job spec.

        Tests doWork in isolation — no chain reads, no DB writes, no provisioning.
        Uses select_available_compute_vm (read-only, reserve=False).

        Returns:
            {"would_submit": True, "escrow_uid": ..., "vm_host": ..., "vm_target": ..., "required_attributes": {...}}
            {"would_submit": False, "escrow_uid": ..., "reason": "<why>"}

        Raises:
            ValueError  if the listing is not found in SQLite (caller maps to 404)
        """
        listing = await self._db.load_listing(listing_id=listing_id)
        if not listing:
            raise ValueError(f"Listing {listing_id!r} not found")

        spec = await _build_provisioning_job_spec(
            order_dict=listing,
            ssh_public_key=ssh_public_key,
            duration_seconds=duration_seconds,
            sqlite_client=self._db,
        )

        if not spec:
            return {
                "would_submit": False,
                "escrow_uid": escrow_uid,
                "reason": (
                    "No available compute VM matched the listing's required attributes. "
                    "Check that at least one host is registered with state='available'."
                ),
            }

        return {
            "would_submit": True,
            "escrow_uid": escrow_uid,
            "vm_host": spec["vm_host"],
            "vm_target": spec["vm_target"],
            "required_attributes": spec["required_attributes"],
        }
