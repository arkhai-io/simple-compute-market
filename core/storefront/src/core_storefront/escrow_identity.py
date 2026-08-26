"""Mechanism-neutral identity backfill for legacy Alkahest escrows.

Every deal has one durable ``settlement_obligations`` record keyed by
``obligation_ref``; a mechanism-issued identifier (the escrow uid) is that
record's ``mechanism_ref``. Deals settled through the current start paths
get their record at the same flow as the ``escrows`` insert — this module
gives the same identity to rows that predate that flow, without touching
their legacy lifecycle state.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from market_identity import Identity

logger = logging.getLogger(__name__)


async def backfill_escrow_obligation_records(
    *,
    sqlite_client: Any,
    settlement_runtime: Any,
    local_principal: Identity,
    mechanism_id: str = "alkahest.v1",
    worker_id: str = "escrow-identity-backfill",
    limit: int = 500,
) -> int:
    """Idempotently record legacy escrows as neutral settlement obligations.

    For each ``escrows`` row with no ``settlement_obligations`` record, the
    accepted plan is re-registered from the negotiation thread and the escrow
    uid adopted as the obligation's ``mechanism_ref``. Rows whose thread has
    no persisted plan (pre-plan flat-proposal deals) are skipped with a log
    line — their identity cannot be derived. Returns the number of rows
    backfilled; a second run returns 0.
    """

    rows = await sqlite_client.list_escrows_missing_obligation_records(limit=limit)
    backfilled = 0
    for row in rows:
        escrow_uid = str(row.get("escrow_uid") or "")
        negotiation_id = str(row.get("negotiation_id") or "")
        if not escrow_uid or not negotiation_id:
            continue
        thread = await sqlite_client.load_negotiation_thread_row(
            negotiation_id=negotiation_id
        )
        plan = (thread or {}).get("settlement_plan")
        obligations = (
            plan.get("obligations") if isinstance(plan, Mapping) else None
        ) or []
        index = next(
            (
                position
                for position, obligation in enumerate(obligations)
                if isinstance(obligation, Mapping)
                and obligation.get("mechanism") == mechanism_id
            ),
            None,
        )
        if index is None:
            logger.info(
                "[SETTLEMENT] escrow %s (negotiation %s) has no derivable"
                " obligation identity; leaving legacy row as is",
                escrow_uid,
                negotiation_id,
            )
            continue
        try:
            records = await settlement_runtime.register_plan(
                agreement_ref=negotiation_id,
                obligations=[dict(obligation) for obligation in obligations],
            )
            outcome = await settlement_runtime.adopt(
                records[index].obligation_ref,
                local_principal=local_principal,
                mechanism_ref=escrow_uid,
                receipt={"backfilled": True},
                worker_id=worker_id,
            )
        except Exception:
            logger.exception(
                "[SETTLEMENT] could not backfill obligation identity for"
                " escrow %s (negotiation %s)",
                escrow_uid,
                negotiation_id,
            )
            continue
        if outcome.status == "succeeded":
            backfilled += 1
        else:
            logger.warning(
                "[SETTLEMENT] obligation identity backfill for escrow %s"
                " finished as %s",
                escrow_uid,
                outcome.status,
            )
    return backfilled


__all__ = ["backfill_escrow_obligation_records"]
