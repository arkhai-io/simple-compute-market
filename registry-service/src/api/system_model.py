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


class ConfigResponse(BaseModel):
    """Active chain and contract configuration.

    These values are read from the running Settings instance — useful for
    confirming that a deployment is pointed at the correct chain and
    contract addresses without needing to inspect pod environment variables.
    """

    chain_id: int
    rpc_url: str = Field(description="Full RPC URL (safe to expose within the cluster network)")
    identity_registry_address: str
    reputation_registry_address: str
    validation_registry_address: str
    enable_health_checks: bool = Field(
        description="Whether the registry-initiated agent health check service is running"
    )
    heartbeat_ttl_secs: int = Field(
        description="Seconds after which an agent without a heartbeat is considered stale"
    )


class EventSyncStatus(BaseModel):
    running: bool
    last_synced_block: int = Field(
        description="Most recent EVM block number successfully processed (0 if never synced)"
    )


class HealthCheckServiceStatus(BaseModel):
    running: bool
    enabled: bool = Field(
        description="Whether registry-initiated health checks are configured (ENABLE_HEALTH_CHECKS)"
    )


class SyncResponse(BaseModel):
    """Liveness of the two background services started at application startup."""

    event_sync: EventSyncStatus
    health_check: HealthCheckServiceStatus


class OrderStatusCounts(BaseModel):
    open: int = 0
    accepted: int = 0
    closed: int = 0
    expired: int = 0


class StatsResponse(BaseModel):
    """Lightweight population counts — diagnostic visibility without pagination."""

    agent_count: int
    order_count: int
    orders_by_status: OrderStatusCounts
