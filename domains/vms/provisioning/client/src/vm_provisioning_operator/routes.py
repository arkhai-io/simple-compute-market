"""The signed contracts of the routes VM mounts on the provisioning service.

Each is plain data, so this client package needs no more of the compute family
kit than its client: the operation and resource a request signs, and the caller
roles the route admits. The provisioning service assembles these declarations
with the family kit's own routes into the table its request authentication
reads; this package's operator client resolves against the same assembly.

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
    {
        "method": "GET",
        "path": r"/api/v1/leases/?",
        "operation": "provisioning_leases_list",
        "roles": ("admin",),
    },
    {
        "method": "POST",
        "path": r"/api/v1/leases/?",
        "operation": "provisioning_lease_create",
        "roles": ("admin",),
    },
    {
        "method": "GET",
        "path": r"/api/v1/leases/by-escrow/(?P<escrow_uid>[^/]+)",
        "operation": "provisioning_lease_by_escrow",
        "roles": ("admin",),
        "path_resource": "escrow_uid",
    },
    {
        "method": "GET",
        "path": r"/api/v1/leases/(?P<lease_id>[^/]+)",
        "operation": "provisioning_lease_admin_get",
        "roles": ("admin",),
        "path_resource": "lease_id",
    },
    {
        "method": "PATCH",
        "path": r"/api/v1/leases/(?P<lease_id>[^/]+)",
        "operation": "provisioning_lease_update",
        "roles": ("admin",),
        "path_resource": "lease_id",
    },
    {
        "method": "POST",
        "path": r"/api/v1/leases/(?P<lease_id>[^/]+)/terminate",
        "operation": "provisioning_lease_admin_terminate",
        "roles": ("admin",),
        "path_resource": "lease_id",
    },
    {
        "method": "POST",
        "path": r"/api/v1/leases/(?P<lease_id>[^/]+)/release-oversight",
        "operation": "provisioning_lease_release_oversight",
        "roles": ("admin",),
        "path_resource": "lease_id",
    },
    {
        "method": "POST",
        "path": r"/api/v1/admin/leases/(?P<lease_id>[^/]+)/retry-release",
        "operation": "provisioning_lease_admin_retry_release",
        "roles": ("admin",),
        "path_resource": "lease_id",
    },
    {
        "method": "POST",
        "path": r"/api/v1/admin/leases/(?P<lease_id>[^/]+)/force-release",
        "operation": "provisioning_lease_admin_force_release",
        "roles": ("admin",),
        "path_resource": "lease_id",
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

__all__ = ["VM_PROVISIONING_ROUTES"]
