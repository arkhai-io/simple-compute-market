"""HTTP request/response models for the System controller."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)


class SystemStatusResponse(BaseModel):
    status: str
    paused: bool
    checks: dict[str, str] = Field(default_factory=dict)


class PolicyEvaluateRequest(BaseModel):
    event_type: str = "order_create"
    offer: dict[str, Any] | None = None
    demand: dict[str, Any] | None = None


class PolicyEvaluateResponse(BaseModel):
    action: str
    policy_used: str | None = None
    resolvable: bool = True
    reason: str | None = None


class AdminStatusResponse(BaseModel):
    paused: bool
    active_negotiations: int = 0
    open_listings: int = 0
    paused_listings: int = 0
