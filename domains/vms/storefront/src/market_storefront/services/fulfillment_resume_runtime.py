"""Restart-safe convergence for accepted VM storefront deliveries.

Every unfinished delivery is driven again through the compute family's
delivery path, which reconciles the deal's records and recovers each step
against the same resource: a reservation through its placement key, a
dispatch through its recorded fulfillment, activation and billing start by
repeating them. A deal that waits for its Agreement start is brought back
here until it starts, and an available deal whose continuation is pending is
driven until it converges. See openspec/specs/compute-delivery/spec.md.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

from market_core.schemas import settlement_option_schema

from market_storefront import container as _container
from market_storefront.delivery_ports import drive_vm_delivery, vm_delivery_path
from market_storefront.services.vm_fulfillment_planner import VERIFIED_EVIDENCE_STATUSES
from market_storefront.utils.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)


async def resume_incomplete_fulfillments_once(
    *,
    sqlite_client: SQLiteClient,
    fulfillment_client: Any | None = None,
    capacity: Any | None = None,
    limit: int = 50,
    owner: str | None = None,
    lease_seconds: int = 60,
    composition: Any | None = None,
) -> int:
    """Revalidate each unfinished delivery's settlement and drive it once.

    ``capacity`` is the guarded capacity effects and ``fulfillment_client``
    the per-site fulfillment client; each is built from the storefront's
    runtime when absent. Returns how many deliveries the pass drove to an
    outcome.
    """
    db = sqlite_client
    composition = composition or _container.resolved_settlement_composition
    if composition is None:
        raise RuntimeError("settlement composition was not initialized")
    deliveries = await db.list_incomplete_vm_deliveries(limit=limit)
    if not deliveries:
        # Nothing to resume needs no site or provisioning client.
        return 0
    path = vm_delivery_path(
        db, capacity=capacity, fulfillment=fulfillment_client, composition=composition,
    )
    worker = owner or f"fulfillment-resume:{uuid.uuid4()}"
    progressed = 0
    for delivery in deliveries:
        negotiation_id = delivery["negotiation_id"]
        claimed = await db.claim_vm_delivery(
            negotiation_id=negotiation_id,
            owner=worker,
            lease_until=(
                datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
            ).isoformat(),
        )
        if not claimed:
            continue
        try:
            evidence = await db.load_vm_settlement_evidence(negotiation_id=negotiation_id)
            thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
            # Refund states retain verified facts for recovery; admission still
            # prevents further delivery after their durable final request.
            if (
                evidence is None
                or evidence.status not in VERIFIED_EVIDENCE_STATUSES
                or thread is None
            ):
                continue
            agreement = json.loads(thread["agreement_bytes"])
            stage = composition.seller_stages[settlement_option_schema(agreement["settlement"])]
            # The selected stage revalidates its evidence before any protected
            # effect: an Alkahest escrow is read from the chain again.
            await stage.recover_evidence(
                evidence=evidence, thread=thread, composition=composition, db=db
            )
            outcome = await drive_vm_delivery(
                path, db, negotiation_id,
                failure_policy=partial(stage.delivery_failed, evidence=evidence, db=db),
            )
            if outcome is not None:
                progressed += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "[FULFILLMENT_RESUME] Failed to converge negotiation %s", negotiation_id
            )
        finally:
            await db.release_vm_delivery(negotiation_id=negotiation_id, owner=worker)
    return progressed


async def _reconcile_payment_deals() -> None:
    """Advance accepted payment deals a buyer has not settled (none without payments)."""
    composition = _container.resolved_settlement_composition
    coordinator = getattr(composition, "payments_coordinator", None)
    if coordinator is not None:
        await coordinator.reconcile_once()


async def fulfillment_resume_cycle_once(*, sqlite_client: SQLiteClient) -> None:
    """One cycle of the fulfillment-resume loop: re-drive every unfinished
    accepted VM delivery, then advance accepted payment deals.

    The loop's timer and an operator's step both run exactly this. A failure
    of one delivery is contained inside the sweep; a failure outside it --
    listing the incomplete deliveries, or building a client -- fails the cycle,
    which the loop controller records, and the timer carries on.
    """
    await resume_incomplete_fulfillments_once(sqlite_client=sqlite_client)
    await _reconcile_payment_deals()
