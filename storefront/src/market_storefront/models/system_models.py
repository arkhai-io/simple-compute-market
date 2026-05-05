"""HTTP request/response models for System and Admin controllers."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    checks: dict[str, str] = Field(default_factory=dict)
    paused: bool | None = None


class PolicyEvaluateRequest(BaseModel):
    event_type: str = "order_create"
    offer: dict[str, Any] | None = None
    demand: dict[str, Any] | None = None
    max_duration_seconds: int | None = None


class PolicyComponentResponse(BaseModel):
    name: str
    resolvable: bool


class PolicyEvaluateResponse(BaseModel):
    action: str
    policy_used: str | None = None
    components: list[str] = Field(default_factory=list)  # callable names
    resolvable: bool = True
    reason: str | None = None


class ImportErrorResponse(BaseModel):
    module: str
    error: str


class SeedPoliciesResponse(BaseModel):
    callable_registry_count: int
    callables: list[str]
    seeded_policies: list[str]
    import_errors: list[ImportErrorResponse]


class SeededPolicyInfo(BaseModel):
    policy_name: str
    trigger_type: str
    components: list[str] = Field(default_factory=list)
    components_resolvable: bool


class PolicyStatusResponse(BaseModel):
    callable_count: int
    callable_registry: dict[str, Any] = Field(default_factory=dict)
    seeded_policies: list[SeededPolicyInfo]


class AdminStatusResponse(BaseModel):
    paused: bool
    active_negotiations: int = 0
    open_listings: int = 0
    paused_listings: int = 0


class AdminPauseResponse(BaseModel):
    paused: bool
    message: str = ""


class StageEventResponse(BaseModel):
    events: list[dict[str, Any]]
    count: int
