"""The compute family's one re-drive of unfinished deliveries, over domain ports.

Each compute storefront's ``delivery-recovery`` loop runs ``recover_deliveries``
over what its domain already has: the query that lists its unfinished deliveries, the
serialization that keeps two drives of one deal apart (VM's durable claim
lease, bare metal's per-deal lock), and its settlement stage's re-check of the
deal's evidence against its authority. The routine owns the
order — list, claim, re-check, drive — so the two domains cannot drift apart
in it; the path's own reconciliation decides what each drive does.

See openspec/specs/compute-delivery/spec.md, "Unfinished deliveries are
re-driven by one routine".
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import Protocol

logger = logging.getLogger(__name__)


class DeliveryDrive(Protocol):
    """What drives one deal: the delivery path, or a domain's entry around it."""

    async def drive(self, negotiation_id: str) -> object: ...


class DeliveryRecovery(Protocol):
    """What a domain supplies for its unfinished deliveries to be re-driven."""

    async def unfinished_deliveries(self, *, limit: int) -> Sequence[str]:
        """The negotiations whose delivery started and has not finished, at most ``limit``."""
        ...

    def claim(self, negotiation_id: str) -> AbstractAsyncContextManager[bool]:
        """The deal under the domain's own serialization while it is re-checked and driven.

        The context answers whether this pass may drive it: ``False`` when
        another worker holds it, so this pass leaves the deal to that worker.
        A domain holds its claim for the context's extent, or, where its drive
        takes the serialization itself, answers whether it is free.
        """
        ...

    async def revalidate(self, negotiation_id: str) -> bool:
        """Whether the deal's settlement evidence re-checks against its authority now.

        ``False`` when it does not, an authority that cannot be reached
        included, so the deal waits for a later pass; a re-check that raises is
        logged by the routine.
        """
        ...


async def recover_deliveries(path: DeliveryDrive, domain: DeliveryRecovery, *, limit: int) -> int:
    """Drive each unfinished delivery the domain can claim and re-check; how many were driven.

    A deal is driven only when the domain's claim admits it and its evidence
    re-checks, since every drive may take a protected step. A failure on one deal is
    logged and the next is still recovered: one deal's unreadable record or
    unreachable authority must not hold back the others.
    """
    driven = 0
    for negotiation_id in await domain.unfinished_deliveries(limit=limit):
        try:
            async with domain.claim(negotiation_id) as claimed:
                if not claimed or not await domain.revalidate(negotiation_id):
                    continue
                await path.drive(negotiation_id)
                driven += 1
        except Exception:
            logger.exception("[DELIVERY_RECOVERY] %s was not re-driven", negotiation_id)
    return driven
