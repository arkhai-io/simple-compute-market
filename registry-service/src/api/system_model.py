"""Response models for the system diagnostics controller."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class HealthChecks(BaseModel):
    api: str = Field(description="Always 'ok' if this response is returned")
    database: str = Field(description="'ok' or error string from SELECT 1")


class HealthResponse(BaseModel):
    status: str = Field(description="'ok' when all checks pass, 'degraded' otherwise")
    checks: HealthChecks


class OrderStatusCounts(BaseModel):
    open: int = 0
    closed: int = 0
    expired: int = 0


class StatsResponse(BaseModel):
    """Lightweight population counts — diagnostic visibility without pagination."""

    publisher_count: int
    order_count: int
    orders_by_status: OrderStatusCounts

