"""Bare metal's provisioning route declarations.

Bare metal mounts only its mock-profile test routes on the provisioning
service; its leases are the compute family's, and access is granted only
through fulfillment.
"""

from __future__ import annotations

import re

from arkhai_bare_metal import BARE_METAL_PROVISIONING_ROUTES


def test_every_declared_route_names_its_roles_and_a_unique_operation() -> None:
    operations = [route["operation"] for route in BARE_METAL_PROVISIONING_ROUTES]

    assert len(set(operations)) == len(operations)
    for route in BARE_METAL_PROVISIONING_ROUTES:
        assert route["roles"] and set(route["roles"]) <= {"seller", "admin"}
        assert "admin" in route["roles"]
        re.compile(route["path"])


def test_bare_metal_declares_only_its_test_routes() -> None:
    assert all(route["path"].startswith("/test/") for route in BARE_METAL_PROVISIONING_ROUTES)
