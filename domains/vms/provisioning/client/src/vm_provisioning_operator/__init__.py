"""VM provisioning operator client and direct VM administration models.

This package is intentionally separate from the shared, offering-mode-neutral
``compute_provisioning`` contract used by storefront and domain callers.
"""

from compute_provisioning import (
    PoolCreate,
    PoolImportDiff,
    PoolImportRequest,
    PoolImportResponse,
    PoolListResponse,
    PoolReplace,
    PoolResponse,
    PoolUpdate,
    PoolValidateResponse,
    PoolValidationProblem,
)
from vm_provisioning_operator.client import (
    ProvisioningClient,
    ProvisioningError,
    ProvisioningJobError,
    ProvisioningTimeoutError,
    SyncProvisioningClient,
)
from vm_provisioning_operator.routes import VM_PROVISIONING_ROUTES
from vm_provisioning_operator.models import (
    AnsibleReadinessResponse,
    CreateVmRequest,
    FileInfo,
    HostConnectivityResponse,
    InventoryInfo,
    LeaseCreate,
    LeaseForceReleaseRequest,
    LeaseListResponse,
    LeaseReleaseOversightRequest,
    LeaseResponse,
    LeaseRetryReleaseRequest,
    LeaseTerminateRequest,
    LeaseUpdate,
    SshKeyInfo,
    VmActionRequest,
)

__all__ = [
    # Clients
    "ProvisioningClient",
    "VM_PROVISIONING_ROUTES",
    "SyncProvisioningClient",
    # Exceptions
    "ProvisioningError",
    "ProvisioningJobError",
    "ProvisioningTimeoutError",
    # Host models
    "HostConnectivityResponse",
    # Job models
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
    # Resource pool models
    "PoolCreate",
    "PoolReplace",
    "PoolUpdate",
    "PoolResponse",
    "PoolListResponse",
    "PoolImportRequest",
    "PoolImportResponse",
    "PoolImportDiff",
    "PoolValidateResponse",
    "PoolValidationProblem",
    # System models
    "FileInfo",
    "InventoryInfo",
    "SshKeyInfo",
    "AnsibleReadinessResponse",
]
