"""Storefront embedding of the deal-servicing claims engine.

Wires ``core_storefront.settlement_lifecycle.ClaimsEngine`` to this
process's parts: the SQLite claim store, the shared alkahest mechanism
hooks (``market_alkahest.claim_hooks``), stage-event logging, and the
background sweep loop. Token deals have no lease, so claim abandonment
carries no truncation reaction — the quota was sold, not leased.
"""

from __future__ import annotations

import logging
from typing import Any

from core_storefront.settlement_lifecycle import ClaimRecord, ClaimsEngine
from core_storefront.stage_log import stage_event
from market_alkahest.claim_hooks import AlkahestClaimHooks

logger = logging.getLogger(__name__)

ALKAHEST_MECHANISM = "alkahest.v1"


def build_claims_engine(sqlite_client: Any) -> ClaimsEngine:
    from apitokens_storefront import container
    from apitokens_storefront.utils.config import CHAINS

    hooks = AlkahestClaimHooks(
        get_client=lambda chain: container.get_alkahest_client(chain or ""),
        chain_config_paths={
            name: chain.alkahest_address_config_path
            for name, chain in CHAINS.items()
        },
    )

    def _on_event(event: str, **fields: Any) -> None:
        stage_event("claims", event, **fields)

    return ClaimsEngine(
        sqlite_client,
        {ALKAHEST_MECHANISM: hooks},
        on_event=_on_event,
    )


async def claims_engine_loop() -> None:
    """Background task: build the engine on its own DB handle and sweep."""
    from apitokens_storefront.utils.config import settings
    from apitokens_storefront.utils.sqlite_client import SQLiteClient

    sqlite_client = SQLiteClient(db_path=settings.db_path)
    engine = build_claims_engine(sqlite_client)
    interval = float(settings.get("claims_sweep_interval", 30))
    await engine.run(interval_seconds=interval)


async def submit_claim(
    *,
    sqlite_client: Any,
    escrow_uid: str,
    fulfillment_uid: str | None,
    negotiation_id: str | None = None,
    listing_id: str | None = None,
    obligation: dict[str, Any] | None = None,
    chain_name: str | None = None,
    escrow_address: str | None = None,
) -> None:
    """Register the seller-side claim for a fulfilled escrow."""
    if not obligation:
        params: dict[str, Any] = {}
        if chain_name:
            params["chain_name"] = chain_name
        if escrow_address:
            params["escrow_contract"] = escrow_address
        obligation = {"mechanism": ALKAHEST_MECHANISM, "params": params}

    claim = ClaimRecord(
        claim_ref=escrow_uid,
        deal_ref={
            k: v
            for k, v in (
                ("negotiation_id", negotiation_id),
                ("listing_id", listing_id),
            )
            if v
        },
        obligation=obligation,
        fulfillment_ref=fulfillment_uid,
    )
    await sqlite_client.upsert_claim(claim.model_dump())
    stage_event(
        "claims", "claim_submitted",
        claim_ref=escrow_uid,
        mechanism=obligation.get("mechanism"),
        negotiation_id=negotiation_id,
        listing_id=listing_id,
    )


def derive_claim_obligation(
    *,
    proposal: Any | None,
    agreed_amount: int,
) -> dict[str, Any] | None:
    """Re-materialize the plan's payment obligation for the claim row."""
    if proposal is None:
        return None
    try:
        from market_alkahest.plans import materialize_settlement_plan_from_proposal

        from apitokens_storefront.utils.config import CHAINS

        chain = getattr(proposal, "chain_name", None)
        chain_cfg = CHAINS.get(chain) if chain else None
        plan = materialize_settlement_plan_from_proposal(
            proposal=proposal,
            seller_wallet_address=None,
            agreed_amount=int(agreed_amount),
            duration_seconds=0,  # inert: token amounts are always concrete
            addr_config_path=(
                chain_cfg.alkahest_address_config_path if chain_cfg else None
            ),
        )
        if plan.obligations:
            return plan.obligations[0].model_dump()
    except Exception as exc:
        logger.warning("[CLAIMS] could not derive claim obligation: %s", exc)
    return None
