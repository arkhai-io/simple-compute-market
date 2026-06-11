"""Storefront embedding of the deal-servicing claims engine.

Wires ``core_storefront.settlement_lifecycle.ClaimsEngine`` (the
mechanism-generic state machine) to this process's parts: the SQLite
claim store, the alkahest mechanism hooks from the VM settlement
domain, stage-event logging, and the watchdog-style background loop.

Submission is decoupled from the running engine: ``submit_claim``
writes the claim row directly (idempotent by escrow uid) and the
engine's next sweep picks it up — so settlement jobs don't need a
handle on the engine task, and a restart loses nothing.
"""

from __future__ import annotations

import logging
from typing import Any

from core_storefront.settlement_lifecycle import ClaimRecord, ClaimsEngine
from core_storefront.stage_log import stage_event

logger = logging.getLogger(__name__)

ALKAHEST_MECHANISM = "alkahest.v1"


def build_claims_engine(sqlite_client: Any) -> ClaimsEngine:
    """Assemble the engine over this storefront's store, clients, config."""
    from domains.vms.settlement.claims import AlkahestClaimHooks
    from market_storefront import container
    from market_storefront.utils.config import CHAINS, settings

    hooks = AlkahestClaimHooks(
        get_client=lambda chain: container.get_alkahest_client(chain or ""),
        chain_config_paths={
            name: chain.alkahest_address_config_path
            for name, chain in CHAINS.items()
        },
        default_chain=getattr(settings, "chain_name", None),
    )
    return ClaimsEngine(
        sqlite_client,
        {ALKAHEST_MECHANISM: hooks},
        on_event=lambda event, **fields: stage_event("claims", event, **fields),
    )


async def claims_engine_loop() -> None:
    """Background task: build the engine on its own DB handle and sweep.

    Mirrors the negotiation-watchdog embedding (own SQLiteClient, started
    via ``asyncio.create_task`` from startup).
    """
    from market_storefront.utils.config import settings
    from market_storefront.utils.sqlite_client import SQLiteClient

    sqlite_client = SQLiteClient(db_path=settings.db_path)
    engine = build_claims_engine(sqlite_client)
    interval = float(getattr(settings, "claims_sweep_interval", 30))
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
    """Register the seller-side claim for a fulfilled escrow.

    ``obligation`` is the settlement-plan obligation envelope when the
    deal carries one; legacy deals get a minimal alkahest envelope built
    from the escrow row (the hooks treat a missing arbiter as
    ready-to-collect, matching RecipientArbiter-era behavior).
    """
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
    duration_seconds: int,
    chain_config_paths: dict[str, str | None],
) -> dict[str, Any] | None:
    """Re-materialize the plan's payment obligation for the claim row.

    Deterministic — the same derivation that produced the negotiated
    ``settlement_plan`` artifact, so the claim services exactly what the
    buyer escrowed. Returns ``None`` when no proposal is pinned or the
    derivation fails (the claim then falls back to the minimal
    envelope).
    """
    if proposal is None:
        return None
    try:
        from market_alkahest.plans import materialize_settlement_plan_from_proposal

        chain = getattr(proposal, "chain_name", None)
        plan = materialize_settlement_plan_from_proposal(
            proposal=proposal,
            seller_wallet_address=None,
            agreed_amount=int(agreed_amount),
            duration_seconds=int(duration_seconds),
            addr_config_path=chain_config_paths.get(chain),
        )
        if plan.obligations:
            return plan.obligations[0].model_dump()
    except Exception as exc:
        logger.warning("[CLAIMS] could not derive claim obligation: %s", exc)
    return None
