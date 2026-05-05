"""arkhai-registry-client — HTTP clients for the Arkhai ERC-8004 registry REST API.

Two clients with identical method signatures:

``RegistryClient``      — async, backed by ``httpx.AsyncClient``
``SyncRegistryClient``  — sync,  backed by ``httpx.Client``

Both accept a ``transport=`` kwarg for in-process test injection.
"""

from registry_client.client import RegistryClient, SyncRegistryClient
from registry_client.auth import sign_eip191, build_auth_headers, RegistryClientError
from registry_client.models import (
    AgentListResponse,
    AgentSummary,
    AttestationStats,
    HealthResponse,
    HeartbeatRequest,
    ListingListResponse,
    ListingRequest,
    ListingSummary,
    UpdateListingRequest,
    ValidatePublishRequest,
    ValidatePublishResponse,
)

__all__ = [
    "RegistryClient",
    "SyncRegistryClient",
    "RegistryClientError",
    "sign_eip191",
    "build_auth_headers",
    "AgentListResponse",
    "AgentSummary",
    "AttestationStats",
    "HealthResponse",
    "HeartbeatRequest",
    "ListingListResponse",
    "ListingRequest",
    "ListingSummary",
    "UpdateListingRequest",
    "ValidatePublishRequest",
    "ValidatePublishResponse",
]
