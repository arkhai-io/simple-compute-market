"""arkhai-registry-client — HTTP clients for the Arkhai registry REST API.

Two clients with identical method signatures:

``RegistryClient``      — async, backed by ``httpx.AsyncClient``
``SyncRegistryClient``  — sync,  backed by ``httpx.Client``

Both accept a ``transport=`` kwarg for in-process test injection.
"""

from registry_client.client import FILTER_SPEC_ETAG_PARAM, RegistryClient, SyncRegistryClient
from market_core import RegistryDescriptor
from registry_client.auth import (
    RegistryClientError,
    SignedRegistryRequest,
    request_route,
    sign_registry_request,
    verify_registry_response,
)
from registry_client.models import (
    AdminStatusResponse,
    FilterSpecResponse,
    HealthResponse,
    ListingListResponse,
    ListingRequest,
    ListingSummary,
    Publisher,
    PublisherIdentity,
    PublisherListResponse,
    SystemStatsResponse,
    TimeSettingResponse,
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
    "FILTER_SPEC_ETAG_PARAM",
    "SignedRegistryRequest",
    "request_route",
    "sign_registry_request",
    "verify_registry_response",
    "AdminStatusResponse",
    "FilterSpecResponse",
    "HealthResponse",
    "ListingListResponse",
    "ListingRequest",
    "ListingSummary",
    "Publisher",
    "PublisherIdentity",
    "PublisherListResponse",
    "SystemStatsResponse",
    "TimeSettingResponse",
    "UpdateListingRequest",
    "ValidatePublishRequest",
    "ValidatePublishResponse",
    "CompiledResourceQuery",
    "FilterVocabularyError",
    "ResourceQueryCompilationError",
    "compile_resource_query",
    "resource_query_descriptors",
]
