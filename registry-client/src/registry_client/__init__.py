"""arkhai-registry-client — lightweight synchronous HTTP client for the Arkhai ERC-8004 registry REST API."""

from registry_client.client import RegistryClient, RegistryClientError
from registry_client.auth import sign_eip191, build_auth_headers
from registry_client.models import (
    AgentListResponse,
    AgentSummary,
    HealthResponse,
    HeartbeatRequest,
    OrderListResponse,
    OrderRequest,
    OrderSummary,
)

__all__ = [
    "RegistryClient",
    "RegistryClientError",
    "sign_eip191",
    "build_auth_headers",
    "AgentListResponse",
    "AgentSummary",
    "HealthResponse",
    "HeartbeatRequest",
    "OrderListResponse",
    "OrderRequest",
    "OrderSummary",
]
