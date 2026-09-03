"""arkhai-registry-client — HTTP clients for the Arkhai registry REST API.

Two clients with identical method signatures:

``RegistryClient``      — async, backed by ``httpx.AsyncClient``
``SyncRegistryClient``  — sync,  backed by ``httpx.Client``

Both accept a ``transport=`` kwarg for in-process test injection.
"""

from registry_client.client import RegistryClient, SyncRegistryClient
from market_core import RegistryDescriptor
from registry_client.auth import (
    RegistryClientError,
    authenticate_request,
    authentication_headers,
)
from registry_client.models import (
    FilterSpecResponse,
    HealthResponse,
    ListingListResponse,
    ListingRequest,
    ListingSummary,
    Publisher,
    PublisherIdentity,
    PublisherListResponse,
    SystemStatsResponse,
    UpdateListingRequest,
    ValidatePublishRequest,
    ValidatePublishResponse,
)
from registry_client.query import (
    CompiledResourceQuery,
    FilterVocabularyError,
    ResourceQueryCompilationError,
    compile_resource_query,
    resource_query_descriptors,
)

__all__ = [
    "RegistryClient",
    "SyncRegistryClient",
    "RegistryClientError",
    "RegistryDescriptor",
    "authenticate_request",
    "authentication_headers",
    "FilterSpecResponse",
    "HealthResponse",
    "ListingListResponse",
    "ListingRequest",
    "ListingSummary",
    "Publisher",
    "PublisherIdentity",
    "PublisherListResponse",
    "SystemStatsResponse",
    "UpdateListingRequest",
    "ValidatePublishRequest",
    "ValidatePublishResponse",
    "CompiledResourceQuery",
    "FilterVocabularyError",
    "ResourceQueryCompilationError",
    "compile_resource_query",
    "resource_query_descriptors",
]
