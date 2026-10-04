"""VM's provisioning routes: their declarations, wire models, and typed client.

The compute family's own routes are served by ``compute_provisioning_client``;
VM's typed client wraps that client's transport.
"""

from vm_provisioning_operator.client import SyncVmOperatorClient, VmOperatorClient
from vm_provisioning_operator.models import (
    CreateVmRequest,
    LeaseCreate,
    LeaseForceReleaseRequest,
    LeaseListResponse,
    LeaseReleaseOversightRequest,
    LeaseResponse,
    LeaseRetryReleaseRequest,
    LeaseTerminateRequest,
    LeaseUpdate,
    VmActionRequest,
)
from vm_provisioning_operator.relays import (
    RelayCreate,
    RelayListResponse,
    RelayResponse,
    RelayTokenRotate,
    RelayUpdate,
)
from vm_provisioning_operator.routes import VM_PROVISIONING_ROUTES, vm_route

__all__ = [
    "VM_PROVISIONING_ROUTES",
    "vm_route",
    "SyncVmOperatorClient",
    "VmOperatorClient",
    "CreateVmRequest",
    "VmActionRequest",
    "LeaseCreate",
    "LeaseUpdate",
    "LeaseTerminateRequest",
    "LeaseReleaseOversightRequest",
    "LeaseRetryReleaseRequest",
    "LeaseForceReleaseRequest",
    "LeaseResponse",
    "LeaseListResponse",
    "RelayCreate",
    "RelayListResponse",
    "RelayResponse",
    "RelayTokenRotate",
    "RelayUpdate",
]
