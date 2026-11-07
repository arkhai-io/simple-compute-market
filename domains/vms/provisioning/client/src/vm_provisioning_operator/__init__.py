"""VM's provisioning routes: their declarations, wire models, and typed client.

The compute family's own routes, relay administration among them, are served
by ``compute_provisioning_client``; VM's typed client wraps that client's
transport.
"""

from vm_provisioning_operator.client import SyncVmOperatorClient, VmOperatorClient
from vm_provisioning_operator.models import (
    HOST_DIAGNOSTICS_RESULT_KIND,
    LIBVIRTD_UNIT,
    RELAY_CLIENT_UNIT,
    CreateVmRequest,
    HostDiagnostics,
    HostDiagnosticsError,
    HostDiagnosticsRequest,
    UnitDiagnostics,
    VmActionRequest,
    check_service_unit_name,
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
    "HOST_DIAGNOSTICS_RESULT_KIND",
    "LIBVIRTD_UNIT",
    "RELAY_CLIENT_UNIT",
    "HostDiagnostics",
    "HostDiagnosticsError",
    "HostDiagnosticsRequest",
    "UnitDiagnostics",
    "check_service_unit_name",
]
