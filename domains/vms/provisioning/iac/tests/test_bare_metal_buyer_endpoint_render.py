"""Ansible evaluates the grant result's buyer endpoint from real inventory.

The role's own ``node_grant_access_data`` host and port expressions are rendered
with Ansible's templar against host variables Ansible's inventory manager loads
from an INI inventory in the form the provisioning service writes. No play runs
and no connection is made.

ansible-core is a locked test dependency of this project, pinned to the range
the provisioning image installs. It is imported unconditionally: an environment
without it fails collection here rather than skipping the only check that
evaluates the role's buyer endpoint.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from ansible.inventory.manager import InventoryManager
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar
from ansible.vars.hostvars import HostVars
from ansible.vars.manager import VariableManager

try:
    # ansible-core 2.19 renders only templates marked trusted; the role's own
    # task file is trusted input, exactly as it is when Ansible loads it.
    from ansible.template import trust_as_template
except ImportError:  # ansible-core < 2.19 has no trust model
    def trust_as_template(value):
        return value


ROLE = (
    Path(__file__).resolve().parents[1]
    / "ansible"
    / "roles"
    / "bare-metal-access"
    / "tasks"
    / "main.yml"
)


def _grant_result_fields() -> dict:
    tasks = yaml.safe_load(ROLE.read_text(encoding="utf-8"))
    for task in tasks:
        fact = task.get("set_fact") or {}
        if "node_grant_access_data" in fact:
            return fact["node_grant_access_data"]
    raise AssertionError("the role no longer builds node_grant_access_data")


def _rendered_endpoint(tmp_path: Path, inventory_line: str) -> tuple[str, str]:
    inventory_file = tmp_path / "inventory.ini"
    inventory_file.write_text(f"[kvm_hosts]\n{inventory_line}\n", encoding="utf-8")
    loader = DataLoader()
    inventory = InventoryManager(loader=loader, sources=[str(inventory_file)])
    variables = VariableManager(loader=loader, inventory=inventory)
    play_vars = variables.get_vars(host=inventory.get_host("bm1"))
    # Outside a play Ansible does not add ``hostvars``; the role reads the
    # target through it, so it is built the way a play builds it.
    hostvars = HostVars(inventory=inventory, variable_manager=variables, loader=loader)
    templar = Templar(
        loader=loader,
        variables={**play_vars, "hostvars": hostvars, "target_host": "bm1"},
    )
    fields = _grant_result_fields()
    host = templar.template(trust_as_template(fields["host"]))
    port = templar.template(trust_as_template(fields["port"]))
    return str(host), str(port)


def test_configured_tenant_endpoint_is_what_the_buyer_receives(tmp_path):
    host, port = _rendered_endpoint(
        tmp_path,
        "bm1  ansible_host=10.0.0.5  public_host=192.0.2.50  public_port=22"
        "  ansible_port=6001  ansible_user=svc  ansible_ssh_private_key_file=/k",
    )

    assert (host, port) == ("192.0.2.50", "22")


def test_host_without_a_tenant_endpoint_falls_back_to_the_management_endpoint(tmp_path):
    host, port = _rendered_endpoint(
        tmp_path,
        "bm1  ansible_host=10.0.0.5  ansible_port=6001  ansible_user=svc"
        "  ansible_ssh_private_key_file=/k",
    )

    assert (host, port) == ("10.0.0.5", "6001")


def test_tenant_address_without_a_tenant_port_keeps_the_management_port(tmp_path):
    host, port = _rendered_endpoint(
        tmp_path,
        "bm1  ansible_host=10.0.0.5  public_host=192.0.2.50  ansible_port=6001"
        "  ansible_user=svc  ansible_ssh_private_key_file=/k",
    )

    assert (host, port) == ("192.0.2.50", "6001")
