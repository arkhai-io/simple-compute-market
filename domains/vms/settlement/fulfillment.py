"""VM settlement fulfillment submission and reconciliation helpers."""

from __future__ import annotations

import inspect
import logging
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class FulfillmentReconciliationUnavailable(RuntimeError):
    """Raised when chain truth cannot be queried before a retry."""


async def find_compute_fulfillments(
    *,
    client: Any,
    escrow_uid: str,
    connection_details: str | None,
) -> list[str]:
    """Find matching string-obligation attestations for an escrow.

    Alkahest client versions expose chain queries through different adapter
    names. This narrow compatibility shim accepts only query methods that
    return attestations and validates their reference and payload when those
    fields are present. Absence of a query surface is not interpreted as
    absence of an attestation.
    """
    obligation = getattr(client, "string_obligation", None)
    candidates = []
    for name in (
        "find_obligations_by_ref",
        "get_obligations_by_ref",
        "find_attestations_by_ref",
    ):
        method = getattr(obligation, name, None)
        if method is None:
            continue
        value = method(escrow_uid)
        rows = await value if inspect.isawaitable(value) else value
        candidates = list(rows or [])
        break
    else:
        raise FulfillmentReconciliationUnavailable(
            "The configured Alkahest client exposes no attestation query by refUID"
        )

    matches: list[str] = []
    for row in candidates:
        if isinstance(row, str):
            matches.append(row)
            continue
        if not isinstance(row, dict):
            row = vars(row)
        ref_uid = row.get("refUID") or row.get("ref_uid") or row.get("reference_uid")
        if ref_uid is not None and str(ref_uid) != str(escrow_uid):
            continue
        data = row.get("data") or row.get("obligation_data") or row.get("value")
        if data is not None and connection_details is not None and str(data) != str(connection_details):
            continue
        if row.get("revoked") is True or row.get("is_revoked") is True:
            continue
        uid = row.get("uid") or row.get("attestation_uid") or row.get("fulfillment_uid")
        if uid:
            matches.append(str(uid))
    return sorted(set(matches))


async def reconcile_or_submit_compute_fulfillment(
    *,
    client: Any | None,
    escrow_uid: str,
    connection_details: str | None,
    allow_submit: bool,
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
            client=client,
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
