"""HTTP request/response models for the deal-servicing endpoints."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DealHeartbeatRequest(BaseModel):
    """One buyer-signed liveness attestation for an active deal.

    The request signature covers ``deal_heartbeat:<escrow_uid>:<ts>``
    where ``ts`` is the ``X-Timestamp`` header — that timestamp doubles
    as the heartbeat's claimed send time, so replay protection (strict
    per-deal monotonicity in ``core_storefront.heartbeats``) covers
    exactly what was signed.

    ``payload`` is schema-tagged and opaque to core, like every other
    domain envelope: what a VM heartbeat attests is
    ``domains.vms.settlement.heartbeats``' business.
    """

    buyer_address: str = Field(description="Buyer wallet address (EIP-191 signer).")
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Schema-tagged attestation payload. Opaque to core.",
    )


class DealHeartbeatResponse(BaseModel):
    deal_ref: str
    sent_at_unix: float
    heartbeat_count: int = Field(
        description="Total heartbeats recorded for this deal so far.",
    )
    next_expected_by_unix: float | None = Field(
        default=None,
        description=(
            "Hint: when the seller expects the next heartbeat (sent_at + "
            "the advertised cadence). Advisory — gating is lifecycle "
            "policy."
        ),
    )
