"""HTTP request/response models for the Settle controller."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SettleRequest(BaseModel):
    negotiation_id: str
    # Domain payload: the VM domain delivers against it; token deals
    # send "" (their deliverable is keyed by the negotiation's terms).
    ssh_public_key: str = ""
    buyer_address: str
    chain_name: str = Field(
        description=(
            "Chain name from the accepted escrow proposal — the storefront "
            "uses it to pick the matching AlkahestClient out of its "
            "per-chain dispatch table."
        ),
    )


class SettleResponse(BaseModel):
    """Response for POST /api/v1/settle/{escrow_uid} (202 while provisioning)."""
    escrow_uid: str
    status: str
    provisioning_job_id: str | None = None
    model_config = {"extra": "allow"}


class SettleStatusResponse(BaseModel):
    """Response for GET /api/v1/settle/{escrow_uid}/status."""
    escrow_uid: str
    status: str
    provisioning_job_id: str | None = None
    tenant_credentials: dict[str, Any] | None = None
    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Admin dry-run models
# ---------------------------------------------------------------------------

class VerifyEscrowRequest(BaseModel):
    """Body for POST /api/v1/admin/settle/{escrow_uid}/verify.

    Caller supplies the expected terms — the endpoint reads the escrow from
    chain and confirms it matches. No DB writes. Used by e2e stage 7b to
    test getRecordFromChain in isolation before committing to settle.
    """
    seller_wallet: str = Field(description="Expected seller wallet address (recipient on-chain)")
    agreed_price: int = Field(
        description=(
            "Expected absolute payment amount in base units of the payment "
            "token (the field name is retained from before the per-hour → "
            "absolute refactor; semantically it now holds the amount, not "
            "a rate)."
        ),
    )
    agreed_duration_seconds: int = Field(description="Expected lease duration in seconds")
    listing_id: str = Field(description="Listing ID — used to extract token contract from DB")
    chain_name: str = Field(
        description=(
            "Chain name to dispatch the on-chain read on. The storefront "
            "verifies the escrow against its [chains.<name>] entry."
        ),
    )


class VerifyEscrowResponse(BaseModel):
    """Response for POST /api/v1/admin/settle/{escrow_uid}/verify."""
    valid: bool
    escrow_uid: str
    reason: str | None = None


class EvaluateSettleRequest(BaseModel):
    """Body for POST /api/v1/admin/settle/{escrow_uid}/evaluate.

    Caller supplies listing context — the endpoint builds canonical schedule
    and fulfillment requests without selecting a host or writing state.
    """
    listing_id: str = Field(description="Listing ID — used to extract compute attributes for host matching")
    ssh_public_key: str = Field(default="", description="SSH public key to inject into the VM")
    duration_seconds: int = Field(default=3600, description="Lease duration in seconds")


class EvaluateSettleResponse(BaseModel):
    """Response for POST /api/v1/admin/settle/{escrow_uid}/evaluate."""
    would_submit: bool
    escrow_uid: str
    schedule_request: dict[str, Any] | None = None
    begin_request: dict[str, Any] | None = None
    reason: str | None = None


class SettleWaitResponse(BaseModel):
    """Response for GET /api/v1/admin/settle/{escrow_uid}/wait.

    Mirrors the registry-agent wait pattern: ``ready`` indicates whether a
    terminal state was reached before the timeout; ``status`` is the raw
    settlement job status (``ready`` | ``failed`` | ``provisioning``).
    """
    ready: bool
    status: str
    provisioning_job_id: str | None = None
    elapsed_ms: int
