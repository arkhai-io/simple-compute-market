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
