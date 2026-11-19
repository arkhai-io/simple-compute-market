"""Restart-safe convergence for accepted VM storefront deliveries.

The ``delivery-recovery`` loop drives every unfinished delivery again through
the compute family's re-drive routine, which claims it, has its settlement stage re-check its
evidence and drives it through the delivery path; the path reconciles the
deal's records and recovers each step against the same resource: a
reservation through its placement key, a dispatch through its recorded
fulfillment, activation and billing start by repeating them. A deal that
waits for its Agreement start is brought back here until it starts, and an
available deal whose continuation is pending is driven until it converges.
See openspec/specs/compute-delivery/spec.md, "Unfinished deliveries are
re-driven by one routine".
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from functools import partial
from typing import Any

import injected_time
from compute_delivery import ComputeDeliveryPath, DeliveryOutcome, recover_deliveries
from market_core.schemas import settlement_option_schema

from market_storefront import container as _container
from market_storefront.delivery_ports import drive_vm_delivery, vm_delivery_path
from market_storefront.services.vm_fulfillment_planner import VERIFIED_EVIDENCE_STATUSES
from market_storefront.utils.sqlite_client import SQLiteClient

logger = logging.getLogger(__name__)


async def _accepted_stage(db: Any, composition: Any, negotiation_id: str) -> tuple[Any, Any, Any] | None:
    """The deal's verified evidence, its thread and its selected seller stage.

    ``None`` when the evidence is not in a verified state: refund states retain
    verified facts for recovery, and admission still prevents further delivery
    after their durable final request.
    """
    evidence = await db.load_vm_settlement_evidence(negotiation_id=negotiation_id)
    thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    if evidence is None or evidence.status not in VERIFIED_EVIDENCE_STATUSES or thread is None:
        return None
    agreement = json.loads(thread["agreement_bytes"])
    return evidence, thread, composition.seller_stages[settlement_option_schema(agreement["settlement"])]


class VmDeliveryRecovery:
    """VM's ports for the family's re-drive: its incomplete deliveries, its
    durable claim lease and its stage's evidence re-check."""

    def __init__(self, db: Any, composition: Any, *, owner: str, lease_seconds: int) -> None:
        self._db = db
        self._composition = composition
        self._owner = owner
        self._lease_seconds = lease_seconds

    async def unfinished_deliveries(self, *, limit: int) -> list[str]:
        rows = await self._db.list_incomplete_vm_deliveries(limit=limit)
        return [row["negotiation_id"] for row in rows]

    @asynccontextmanager
    async def claim(self, negotiation_id: str) -> AsyncIterator[bool]:
        """The deal's convergence lease, held by this pass's owner until it is released.

        A lease another owner holds and has not let expire answers ``False``.
        """
        claimed = await self._db.claim_vm_delivery(
            negotiation_id=negotiation_id,
            owner=self._owner,
            lease_until=(injected_time.now_datetime() + timedelta(seconds=self._lease_seconds)).isoformat(),
        )
        try:
            yield claimed
        finally:
            if claimed:
                await self._db.release_vm_delivery(negotiation_id=negotiation_id, owner=self._owner)

    async def revalidate(self, negotiation_id: str) -> bool:
        """Whether the selected stage re-checks the deal's evidence now, before
        any protected effect: an Alkahest escrow is read from the chain again, a
        payments receipt verified again. A stage refuses evidence it cannot
        re-check with ``ValueError``, an unreachable chain included, which
        answers ``False``."""
        accepted = await _accepted_stage(self._db, self._composition, negotiation_id)
        if accepted is None:
            logger.warning(
                "[DELIVERY] %s does not re-check for recovery: its settlement evidence is not verified",
                negotiation_id,
            )
            return False
        evidence, thread, stage = accepted
        try:
            await stage.recover_evidence(
                evidence=evidence, thread=thread, composition=self._composition, db=self._db,
            )
        except ValueError as exc:
            logger.warning("[DELIVERY] %s does not re-check for recovery: %s", negotiation_id, exc)
            return False
        return True


class VmRecoveryDrive:
    """A recovery drive through VM's delivery entry, which records the outcome
    in its delivery record and runs the stage's failure policy once.

    The path is built at the first drive: it needs the composition's deal
    lifecycle, which a pass with nothing to resume does not.
    """

    def __init__(self, build_path: Callable[[], ComputeDeliveryPath], db: Any, composition: Any) -> None:
        self._build_path = build_path
        self._path: ComputeDeliveryPath | None = None
        self._db = db
        self._composition = composition

    async def drive(self, negotiation_id: str) -> DeliveryOutcome | None:
        if self._path is None:
            self._path = self._build_path()
        accepted = await _accepted_stage(self._db, self._composition, negotiation_id)
        failure_policy = (
            partial(accepted[2].delivery_failed, evidence=accepted[0], db=self._db)
            if accepted is not None
            else None
        )
        return await drive_vm_delivery(self._path, self._db, negotiation_id, failure_policy=failure_policy)


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
    """Re-drive each unfinished delivery this pass can claim and re-check: one
    cycle of the ``delivery-recovery`` loop, which its timer and an operator's
    step both run. A failure of one delivery is contained inside the re-drive;
    listing the incomplete deliveries failing fails the cycle, which the loop
    controller records, and the timer carries on.

    ``capacity`` is the guarded capacity effects and ``fulfillment_client``
    the per-site fulfillment client; each defaults to the deal lifecycle's
    capacity runtime and fulfillment client, and is otherwise built from the
    configured sites when first used, so a pass with nothing to resume needs
    neither.
    Returns how many deliveries the pass drove.
    """
    db = sqlite_client
    composition = composition or _container.resolved_settlement_composition
    if composition is None:
        raise RuntimeError("settlement composition was not initialized")
    drive = VmRecoveryDrive(
        lambda: vm_delivery_path(db, capacity=capacity, fulfillment=fulfillment_client, composition=composition),
        db, composition,
    )
    recovery = VmDeliveryRecovery(
        db, composition, owner=owner or f"delivery-recovery:{uuid.uuid4()}", lease_seconds=lease_seconds,
    )
    return await recover_deliveries(drive, recovery, limit=limit)
