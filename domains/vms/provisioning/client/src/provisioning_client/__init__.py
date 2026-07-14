"""arkhai-vms-provisioning-client — async and sync HTTP clients for the
Arkhai provisioning service REST API.

Usage::

    from provisioning_client import ProvisioningClient, SyncProvisioningClient
    from provisioning_client import CreateVmRequest, HostCreate, JobStatusResponse

The ``ProvisioningClient`` (async) and ``SyncProvisioningClient`` (sync) share
identical method signatures.  Both own their HTTP session internally and accept
a ``transport=`` kwarg for in-process test injection.
"""

from provisioning_client.client import (
    ProvisioningClient,
    ProvisioningError,
    ProvisioningJobError,
    ProvisioningTimeoutError,
    SyncProvisioningClient,
)
from provisioning_client.models import (
    AnsibleReadinessResponse,
    CreateVmRequest,
    CredentialListResponse,
    CredentialResponse,
    FileInfo,
    HealthResponse,
    HostConnectivityResponse,
    HostCreate,
    HostListResponse,
    HostResponse,
    HostUpdate,
    InventoryInfo,
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
    JobSubmitResponse,
    LeaseCreate,
    LeaseForceReleaseRequest,
    LeaseListResponse,
    LeaseReleaseOversightRequest,
    LeaseResponse,
    LeaseRetryReleaseRequest,
    LeaseTerminateRequest,
    LeaseUpdate,
    SshKeyInfo,
    VersionResponse,
    VmActionRequest,
)

__all__ = [
    # Clients
    "ProvisioningClient",
    "SyncProvisioningClient",
    # Exceptions
    "ProvisioningError",
    "ProvisioningJobError",
    "ProvisioningTimeoutError",
    # Host models
    "HostCreate",
    "HostUpdate",
    "HostResponse",
    "HostListResponse",
    "HostConnectivityResponse",
    # Job models
    "JobSubmitResponse",
    "JobStatusResponse",
    "JobLogsResponse",
    "JobListResponse",
    "CredentialResponse",
    "CredentialListResponse",
    # VM request models
    "CreateVmRequest",
    "VmActionRequest",
    # Lease models
    "LeaseCreate",
    "LeaseUpdate",
    "LeaseTerminateRequest",
    "LeaseReleaseOversightRequest",
    "LeaseRetryReleaseRequest",
    "LeaseForceReleaseRequest",
    "LeaseResponse",
    "LeaseListResponse",
    # System models
    "HealthResponse",
    "VersionResponse",
    "FileInfo",
    "InventoryInfo",
    "SshKeyInfo",
    "AnsibleReadinessResponse",
]
