"""Where bare metal mounts its routes on the provisioning service.

Bare metal mounts only the compute family's mock routes, under the mock
profile: its leases are the compute family's, served by the provisioning
service's lease routes, and access is granted and reclaimed only through
fulfillment. The routes' contracts are the family's template, so bare metal
states only the two values its mount is built from, and this package needs no
dependency on the compute family's contracts: the bare-metal provisioning
adapter and bare metal's callers build ``MockRouteMount`` from them.
"""

from __future__ import annotations

#: The path prefix bare metal's mock rule and evaluate-job routes sit under.
BARE_METAL_MOCK_ROUTE_PREFIX = "/test/bare-metal"

#: The prefix of each of those routes' signed operation names.
BARE_METAL_MOCK_OPERATION_PREFIX = "provisioning_test_bare_metal"
