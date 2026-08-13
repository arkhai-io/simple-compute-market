"""VM settlement fulfillment submission and reconciliation helpers."""

from __future__ import annotations

import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class FulfillmentReconciliationUnavailable(RuntimeError):
    """Raised when chain truth cannot be queried before a retry."""


async def find_compute_fulfillments(
    *,
    query_fulfillments: Any | None,
    escrow_uid: str,
    connection_details: str | None,
) -> list[str]:
    """Use an explicitly supplied supported attestation query capability.

    The pinned Alkahest dependency does not expose discovery by ``refUID``.
    Production composition therefore passes no query today.  This seam exists
    only so a future supported adapter can be injected without probing guessed
    method names on the external client.
    """
    if query_fulfillments is None:
        raise FulfillmentReconciliationUnavailable(
            "No supported attestation query capability is configured"
        )
    rows = await query_fulfillments(
        escrow_uid=escrow_uid, connection_details=connection_details
    )
    return sorted({str(uid) for uid in (rows or []) if uid})


async def reconcile_or_submit_compute_fulfillment(
    *,
    client: Any | None,
    escrow_uid: str,
    connection_details: str | None,
    allow_submit: bool,
    query_fulfillments: Any | None = None,
) -> str:
    """Adopt an existing fulfillment or submit only at a known-safe boundary.

    ``allow_submit`` is True only for the live first attempt after a durable
    submission-intent checkpoint. Recovery calls use False: they must discover
    chain truth before retrying and never infer "not submitted" from a query
    failure.
    """
    if not client:
        if not allow_submit:
            raise FulfillmentReconciliationUnavailable(
                "Demo fulfillment cannot be reconciled after restart"
            )
        return await submit_compute_fulfillment(
            client=None, escrow_uid=escrow_uid, connection_details=connection_details
        )

    try:
        matches = await find_compute_fulfillments(
            query_fulfillments=query_fulfillments,
            escrow_uid=escrow_uid,
            connection_details=connection_details,
        )
    except FulfillmentReconciliationUnavailable:
        if not allow_submit:
            raise
        matches = []

    if matches:
        if len(matches) > 1:
            logger.error(
                "[ALKAHEST] Multiple identical fulfillment attestations for escrow %s; "
                "adopting canonical UID %s",
                escrow_uid,
                matches[0],
            )
        return matches[0]
    if not allow_submit:
        raise FulfillmentReconciliationUnavailable(
            f"No matching fulfillment could be proven for escrow {escrow_uid}; "
            "blind resubmission is forbidden"
        )
    return await submit_compute_fulfillment(
        client=client,
        escrow_uid=escrow_uid,
        connection_details=connection_details,
    )


async def submit_compute_fulfillment(
    *,
    client: Any | None,
    escrow_uid: str,
    connection_details: str | None,
) -> str:
    """Submit VM fulfillment on-chain, or return a simulated id in demo mode."""
    if not client:
        fulfillment_uid = f"fulfill_{uuid.uuid4()}"
        logger.info(
            "[ALKAHEST] (Simulated) Fulfilled compute obligation without on-chain client."
        )
        return fulfillment_uid

    from market_alkahest.txlock import chain_tx_lock

    async with chain_tx_lock(None):
        fulfillment_uid = await client.string_obligation.do_obligation(
            connection_details,
            escrow_uid,
        )
    logger.info(
        "[ALKAHEST] Fulfilled compute obligation with on-chain client; machine provisioned."
    )
    return fulfillment_uid
