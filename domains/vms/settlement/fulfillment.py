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
    oracle_address: str | None,
    demand_bytes: bytes,
) -> str:
    """Submit VM fulfillment on-chain, or return a simulated id in demo mode."""
    if not client or not oracle_address:
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
    request_arbitration_result = await client.oracle.request_arbitration(
        fulfillment_uid,
        oracle_address,
        demand_bytes,
    )
    logger.info("[ALKAHEST] Arbitration requested: %s", request_arbitration_result)
    return fulfillment_uid
