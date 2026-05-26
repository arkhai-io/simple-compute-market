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


class HealthCheckServiceStatus(BaseModel):
    running: bool
    enabled: bool = Field(
        description="Whether registry-initiated health checks are configured (ENABLE_HEALTH_CHECKS)"
    )


class SyncResponse(BaseModel):
    """Liveness of the background services started at application startup.

    Agent indexing happens just-in-time on the request path (see
    ``api/utils.py::ensure_agent_indexed``); there is no event-sync
    background service to report on here.
    """

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


class AgentIndexedResponse(BaseModel):
    """Response from GET /api/v1/system/sync/wait-for-agent.

    ``indexed=True`` means the agent row is present in the registry DB and
    the caller can safely proceed with heartbeat and listing publish calls.
    ``indexed=False`` means the request timed out before the agent appeared.
    """

    indexed: bool = Field(description="True if the agent was found before the timeout elapsed")
    agent_id: str = Field(description="The canonical agent ID that was polled for")
    elapsed_ms: int = Field(description="Approximate wait time in milliseconds")


