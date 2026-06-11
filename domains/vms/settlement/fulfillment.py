"""VM settlement fulfillment submission helpers."""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


async def submit_compute_fulfillment(
    *,
    client: Any | None,
    escrow_uid: str,
    connection_details: str | None,
) -> str:
    """Submit VM fulfillment on-chain, or return a simulated id in demo mode.

    Submission only: requesting arbitration, watching ``ArbitrationMade``,
    and collecting are the claims agent's job (work item I.6 of the
    settlement-lifecycle design replaced the fire-and-forget
    ``request_arbitration`` that used to live here) — fulfillment is the
    first step of the claim, not the last step of settlement.
    """
    if not client:
        fulfillment_uid = f"fulfill_{uuid.uuid4()}"
        logger.info(
            "[ALKAHEST] (Simulated) Fulfilled compute obligation without on-chain client."
        )
        return fulfillment_uid

    fulfillment_uid = await client.string_obligation.do_obligation(
        connection_details,
        escrow_uid,
    )
    logger.info(
        "[ALKAHEST] Fulfilled compute obligation with on-chain client; "
        "machine provisioned."
    )
    return fulfillment_uid
