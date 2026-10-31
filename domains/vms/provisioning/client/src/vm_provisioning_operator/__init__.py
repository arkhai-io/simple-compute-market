"""VM's provisioning routes: their declarations, wire models, and typed client.

The compute family's own routes, relay administration among them, are served
by ``compute_provisioning_client``; VM's typed client wraps that client's
transport.
"""

from vm_provisioning_operator.client import SyncVmOperatorClient, VmOperatorClient
from vm_provisioning_operator.models import (
    CreateVmRequest,
    VmActionRequest,
)
from vm_provisioning_operator.routes import (
    VM_MOCK_ROUTE_MOUNT,
    VM_PROVISIONING_ROUTES,
    vm_route,
)

__all__ = [
    "VM_MOCK_ROUTE_MOUNT",
    "VM_PROVISIONING_ROUTES",
    "vm_route",
    "SyncVmOperatorClient",
    "VmOperatorClient",
    "CreateVmRequest",
    "VmActionRequest",
]
