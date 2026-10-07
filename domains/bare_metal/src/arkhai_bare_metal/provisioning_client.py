"""Bare metal's provisioning routes, declared as plain data.

Bare metal declares the signed contract of each route it mounts on the
provisioning service, so this package needs no dependency on the compute family
kit: the operation and resource a request signs, and the caller roles the route
admits. The provisioning service assembles these declarations into the table its
request authentication reads.

Bare metal mounts only its mock-profile test routes. Its leases are the compute
family's, served by the provisioning service's lease routes, and access is
granted and reclaimed only through fulfillment.
"""

from __future__ import annotations

BARE_METAL_TEST_ROUTES = (
    {
        "method": "POST",
        "path": r"/test/bare-metal/mock-rules",
        "operation": "provisioning_test_bare_metal_rule_add",
        "roles": ("admin",),
    },
    {
        "method": "GET",
        "path": r"/test/bare-metal/mock-rules",
        "operation": "provisioning_test_bare_metal_rules_list",
        "roles": ("admin",),
    },
    {
        "method": "DELETE",
        "path": r"/test/bare-metal/mock-rules/(?P<rule_id>[^/]+)",
        "operation": "provisioning_test_bare_metal_rule_delete",
        "roles": ("admin",),
        "path_resource": "rule_id",
    },
    {
        "method": "POST",
        "path": r"/test/bare-metal/mock-rules/(?P<rule_id>[^/]+)/resume",
        "operation": "provisioning_test_bare_metal_rule_resume",
        "roles": ("admin",),
        "path_resource": "rule_id",
    },
    {
        "method": "POST",
        "path": r"/test/bare-metal/evaluate-job",
        "operation": "provisioning_test_bare_metal_job_evaluate",
        "roles": ("admin",),
    },
)

#: Every route bare metal mounts on the provisioning service, all of them
#: mounted only under the mock profile.
BARE_METAL_PROVISIONING_ROUTES = BARE_METAL_TEST_ROUTES
