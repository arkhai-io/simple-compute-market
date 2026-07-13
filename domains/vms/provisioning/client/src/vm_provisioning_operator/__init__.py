"""VM provisioning operator client and direct VM administration models.

This package is intentionally separate from the shared, executor-neutral
``compute_provisioning`` contract used by storefront and domain callers.
"""

from vm_provisioning_operator.client import (
    ProvisioningClient,
    ProvisioningError,
    ProvisioningJobError,
    ProvisioningTimeoutError,
    SyncProvisioningClient,
)
from vm_provisioning_operator.models import (
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
