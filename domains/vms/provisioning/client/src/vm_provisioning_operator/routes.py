"""The signed contracts of the routes VM mounts on the provisioning service.

Each is plain data: the operation and resource a request signs, and the caller
roles the route admits. The provisioning service assembles these declarations
with the family's own routes into the table its request authentication reads,
and VM's typed client signs each request from the declaration naming it.

Order is significant within this tuple: the first declaration whose path fully
matches decides. The test routes are mounted only under the mock profile.
"""

from __future__ import annotations

VM_PROVISIONING_ROUTES = (
    {
        "method": "GET",
        "path": r"/api/v1/hosts/(?P<host>[^/]+)/capacity",
        "operation": "provisioning_host_capacity",
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
    # Relay administration, the administrator's alone: relays are operator
    # infrastructure, and no storefront administers them. Ordered so the
    # token, enable, and disable sub-resources match before the bare relay id
    # pattern, which would otherwise swallow them and authenticate a rotation
    # as an ordinary read.
    {"method": "GET", "path": r"/api/v1/relays/?$", "operation": "provisioning_relays_list", "roles": ("admin",)},
    {
        "method": "POST",
        "path": r"/api/v1/relays/(?P<relay_id>[^/]+)/token",
        "operation": "provisioning_relay_rotate_token",
        "roles": ("admin",),
        "path_resource": "relay_id",
    },
    {
        "method": "POST",
        "path": r"/api/v1/relays/(?P<relay_id>[^/]+)/enable",
        "operation": "provisioning_relay_enable",
        "roles": ("admin",),
        "path_resource": "relay_id",
    },
    {
        "method": "POST",
        "path": r"/api/v1/relays/(?P<relay_id>[^/]+)/disable",
        "operation": "provisioning_relay_disable",
        "roles": ("admin",),
        "path_resource": "relay_id",
    },
    {
        "method": "GET",
        "path": r"/api/v1/relays/(?P<relay_id>[^/]+)",
        "operation": "provisioning_relay_get",
        "roles": ("admin",),
        "path_resource": "relay_id",
    },
    {"method": "POST", "path": r"/api/v1/relays/?$", "operation": "provisioning_relay_create", "roles": ("admin",)},
    {
        "method": "PATCH",
        "path": r"/api/v1/relays/(?P<relay_id>[^/]+)",
        "operation": "provisioning_relay_update",
        "roles": ("admin",),
        "path_resource": "relay_id",
    },
    {
        "method": "POST",
        "path": r"/test/mock-rules",
        "operation": "provisioning_test_rule_add",
        "roles": ("admin",),
    },
    {
        "method": "GET",
        "path": r"/test/mock-rules",
        "operation": "provisioning_test_rules_list",
        "roles": ("admin",),
    },
    {
        "method": "DELETE",
        "path": r"/test/mock-rules/(?P<rule_id>[^/]+)",
        "operation": "provisioning_test_rule_delete",
        "roles": ("admin",),
        "path_resource": "rule_id",
    },
    {
        "method": "POST",
        "path": r"/test/mock-rules/(?P<rule_id>[^/]+)/resume",
        "operation": "provisioning_test_rule_resume",
        "roles": ("admin",),
        "path_resource": "rule_id",
    },
    {
        "method": "POST",
        "path": r"/test/evaluate-job",
        "operation": "provisioning_test_job_evaluate",
        "roles": ("admin",),
    },
)



def vm_route(operation: str) -> dict:
    """The declaration of one of VM's routes, by its signed operation."""

    for declaration in VM_PROVISIONING_ROUTES:
        if declaration["operation"] == operation:
            return declaration
    raise KeyError(operation)


__all__ = ["VM_PROVISIONING_ROUTES", "vm_route"]
