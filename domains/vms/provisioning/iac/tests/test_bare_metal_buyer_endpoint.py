"""The buyer endpoint the role returns must be the tenant-facing one.

When the provisioner reaches a host through a management tunnel, handing the
buyer `ansible_host`/`ansible_port` would point it at that tunnel. The role
returns `public_host`/`public_port` when the inventory carries them, and falls
back to the provisioner's values when a host serves both from one endpoint.

This reads the role's own task definitions rather than a copy of them, so a
change to the emitted expression fails here.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROLE = (
    Path(__file__).resolve().parents[1]
    / "ansible"
    / "roles"
    / "bare-metal-access"
    / "tasks"
    / "main.yml"
)


def _grant_result_fields() -> dict:
    tasks = yaml.safe_load(ROLE.read_text())
    for task in tasks:
        fact = task.get("set_fact") or {}
        if "node_grant_access_data" in fact:
            return fact["node_grant_access_data"]
    raise AssertionError("the role no longer builds node_grant_access_data")


def test_buyer_host_prefers_the_tenant_facing_address() -> None:
    host = _grant_result_fields()["host"]

    assert "public_host" in host
    assert host.index("public_host") < host.index("ansible_host"), (
        "the provisioner's own address must only be a fallback"
    )


def test_buyer_port_prefers_the_tenant_facing_port() -> None:
    port = _grant_result_fields()["port"]

    assert "public_port" in port
    assert port.index("public_port") < port.index("ansible_port")


def test_the_fallbacks_are_retained_for_single_endpoint_hosts() -> None:
    fields = _grant_result_fields()

    assert "ansible_host" in fields["host"]
    assert "ansible_port" in fields["port"]
    assert "22" in fields["port"]
