"""Schema-invariant storefront system/admin response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)
    paused: bool | None = None
    agent_id: str | None = None
    chain_id: int | None = None
    resource_count: int | None = None


class AdminPauseResponse(BaseModel):
    paused: bool
    message: str = ""


class StageEventResponse(BaseModel):
    events: list[dict[str, Any]]
    count: int
