"""The signed contracts of the routes VM mounts on the provisioning service.

Each is plain data: the operation and resource a request signs, and the caller
roles the route admits. The provisioning service assembles these declarations
with the family's own routes into the table its request authentication reads,
and VM's typed client signs each request from the declaration naming it.

Order is significant within this tuple: the first declaration whose path fully
matches decides. The mock routes are the compute family's mock mechanism, which
VM mounts under ``VM_MOCK_ROUTE_MOUNT``; they are mounted only under the mock
profile.
"""

from __future__ import annotations

from compute_provisioning_contracts import MockRouteMount

#: Where VM mounts the family's mock rule and evaluate-job routes.
VM_MOCK_ROUTE_MOUNT = MockRouteMount("/test", "provisioning_test")

VM_PROVISIONING_ROUTES = (
    {
        "method": "GET",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/capacity",
        "operation": "provisioning_host_capacity",
        "roles": ("admin",),
        "path_resource": "host",
    },
    {
        "method": "GET",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/diagnostics",
        "operation": "provisioning_host_diagnostics",
        "roles": ("admin",),
        "path_resource": "host",
    },
    {
        "method": "POST",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/vms/?",
        "operation": "provisioning_vm_create",
        "roles": ("admin",),
        "path_resource": "host",
    },
    {
        "method": "GET",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/vms/?",
        "operation": "provisioning_vm_list",
        "roles": ("admin",),
        "path_resource": "host",
    },
    {
        "method": "POST",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/start",
        "operation": "provisioning_vm_start",
        "roles": ("admin",),
        "path_resource": ("host", "vm_name"),
    },
    {
        "method": "POST",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/shutdown",
        "operation": "provisioning_vm_shutdown",
        "roles": ("admin",),
        "path_resource": ("host", "vm_name"),
    },
    {
        "method": "POST",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/reboot",
        "operation": "provisioning_vm_reboot",
        "roles": ("admin",),
        "path_resource": ("host", "vm_name"),
    },
    {
        "method": "POST",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/destroy",
        "operation": "provisioning_vm_destroy",
        "roles": ("admin",),
        "path_resource": ("host", "vm_name"),
    },
    {
        "method": "POST",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/undefine",
        "operation": "provisioning_vm_undefine",
        "roles": ("admin",),
        "path_resource": ("host", "vm_name"),
    },
    {
        "method": "GET",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/monitor",
        "operation": "provisioning_vm_monitor",
        "roles": ("admin",),
        "path_resource": ("host", "vm_name"),
    },
    {
        "method": "POST",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/vms/(?P<vm_name>[^/]+)/reset-password",
        "operation": "provisioning_vm_reset_password",
        "roles": ("admin",),
        "path_resource": ("host", "vm_name"),
    },
    *VM_MOCK_ROUTE_MOUNT.route_declarations(),
)


def vm_route(operation: str) -> dict:
    """The declaration of one of VM's routes, by its signed operation."""

    for declaration in VM_PROVISIONING_ROUTES:
        if declaration["operation"] == operation:
            return declaration
    raise KeyError(operation)


__all__ = ["VM_MOCK_ROUTE_MOUNT", "VM_PROVISIONING_ROUTES", "vm_route"]
