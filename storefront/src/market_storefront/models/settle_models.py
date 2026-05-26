"""HTTP request/response models for the Settle controller."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SettleRequest(BaseModel):
    negotiation_id: str
    ssh_public_key: str
    buyer_address: str


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
    agreed_price: float = Field(
        description=(
            "Expected absolute payment amount in base units of the payment "
            "token (the field name is retained from before the per-hour → "
            "absolute refactor; semantically it now holds the amount, not "
            "a rate)."
        ),
    )
    agreed_duration_seconds: int = Field(description="Expected lease duration in seconds")
    listing_id: str = Field(description="Listing ID — used to extract token contract from DB")


class VerifyEscrowResponse(BaseModel):
    """Response for POST /api/v1/admin/settle/{escrow_uid}/verify."""
    valid: bool
    escrow_uid: str
    reason: str | None = None


class EvaluateSettleRequest(BaseModel):
    """Body for POST /api/v1/admin/settle/{escrow_uid}/evaluate.

    Caller supplies listing context — the endpoint resolves a host from
    inventory and builds the provisioning job spec. No chain reads, no DB
    writes (read-only inventory lookup). Used by e2e stage 8a to test
    doWork in isolation.
    """
    listing_id: str = Field(description="Listing ID — used to extract compute attributes for host matching")
    ssh_public_key: str = Field(default="", description="SSH public key to inject into the VM")
    duration_seconds: int = Field(default=3600, description="Lease duration in seconds")


class EvaluateSettleResponse(BaseModel):
    """Response for POST /api/v1/admin/settle/{escrow_uid}/evaluate."""
    would_submit: bool
    escrow_uid: str
    vm_host: str | None = None
    vm_target: str | None = None
    required_attributes: dict[str, Any] = Field(default_factory=dict)
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
