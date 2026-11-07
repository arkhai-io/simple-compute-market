"""Seller-side reconciliation of accepted payment deals.

A buyer may approve a payment and never call settle again, or a storefront may
restart between approval and delivery. The seller then holds the payment with
nothing delivered. A reconciliation pass advances each such deal through the
domain's own settle path, exactly as a buyer's settle call would, so the deal
converges without the buyer.

The domain supplies every accepted payment candidate it has not settled,
including buyers that never sent a commitment peer message. Its settle function
reads the payment authority and either serves the verified commitment or refunds
through the same voluntary lifecycle reverse path. This module only runs the
pass and keeps one deal's failure from stopping the others.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ReconciliationPass:
    """What one pass did."""

    attempted: int
    failed: int


async def reconcile_accepted_payments(
    negotiation_ids: Iterable[str],
    settle: Callable[[str], Awaitable[Any]],
    *,
    logger: logging.Logger,
) -> ReconciliationPass:
    """Advance each accepted payment deal through ``settle``.

    ``settle`` is idempotent: a deal whose payment is still pending stays
    pending, and a deal already advanced is reported as it stands. A failure is
    logged and the pass continues; the next pass retries the deal.
    """

    attempted = failed = 0
    for negotiation_id in negotiation_ids:
        attempted += 1
        try:
            await settle(negotiation_id)
        except Exception:
            failed += 1
            logger.exception("[PAYMENTS] reconciling %s failed; retrying next pass", negotiation_id)
    return ReconciliationPass(attempted=attempted, failed=failed)


_HELD_POLL_SECONDS = 1.0


async def run_payment_reconciliation(
    reconcile_once: Callable[[], Awaitable[Any]],
    *,
    interval_seconds: float,
    logger: logging.Logger,
    paused: Callable[[], bool] | None = None,
    wait: Callable[[float], Awaitable[None]] | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> None:
    """Run ``reconcile_once`` every interval until the task is cancelled.

    The gate is read on entry and before every pass, and ``wait`` is the
    storefront's loop controller, which returns early on a pause request. The
    first pass is due one interval after start, as for the storefront's other
    timer loops; an operator who wants one sooner steps the loop.

    A held pass polls the gate through ``sleep`` rather than ``wait``: the
    controller's wait returns at once while a pause is requested, so a held
    loop polling through it would spin.
    """

    if paused is not None and wait is None:
        raise TypeError("a gated reconciliation loop requires an interruptible wait")
    idle = wait or asyncio.sleep
    while True:
        await idle(interval_seconds)
        try:
            if paused is not None and paused():
                await sleep(_HELD_POLL_SECONDS)
                continue
            await reconcile_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[PAYMENTS] reconciliation pass failed; continuing")


__all__ = ["ReconciliationPass", "reconcile_accepted_payments", "run_payment_reconciliation"]
