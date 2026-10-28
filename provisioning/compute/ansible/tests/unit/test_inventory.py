"""Ansible INI inventories parsed into hosts with ssh connections."""

from __future__ import annotations

from types import SimpleNamespace

from compute_provisioning.hosts import ExecutionHost
from compute_provisioning.hosts.service import POOL_UNSTATED
from compute_provisioning_ansible import DEFAULT_KEY_PATH, SshConnectionCodec, parse_inventory_ini
from compute_provisioning_ansible.runner import AnsibleRunner, inventory_target

_INI = """
ungrouped1 ansible_host=10.0.2.1 ansible_user=root

[hypervisors]
kvm1 ansible_host=10.0.0.1 ansible_user=root ansible_port=2201 gpus=2 gpu_model=H100 public_host=203.0.113.1 pool_id=gpu
kvm2 ansible_host=10.0.0.2 ansible_user=ops ansible_ssh_private_key_file=/keys/kvm2

[whole_machines]
bm1 ansible_host=10.0.1.1 ansible_user=root

[hypervisors:vars]
ansible_python_interpreter=/usr/bin/python3

[sellable:children]
hypervisors
whole_machines

[hypervisors]
broken ansible_user=root
badport ansible_host=10.0.0.3 ansible_user=root ansible_port=99999
"""


def test_every_host_entry_becomes_a_host_whatever_its_section() -> None:
    """Section names are the file's own; none is known to the importer."""
    hosts = {host.host_id: host for host in parse_inventory_ini(_INI)}

    assert sorted(hosts) == ["bm1", "kvm1", "kvm2", "ungrouped1"]
    kvm1 = hosts["kvm1"]
    assert (kvm1.gpu_count, kvm1.gpu_model, kvm1.pool_id) == (2, "H100", "gpu")
    assert kvm1.connection.kind == "ssh"
    assert kvm1.connection.public["ssh_port"] == 2201
    assert kvm1.connection.public["public_host"] == "203.0.113.1"
    assert kvm1.connection.public["key_path"] == DEFAULT_KEY_PATH
    assert hosts["kvm2"].connection.public["key_path"] == "/keys/kvm2"


def test_a_pool_is_named_cleared_or_left_unstated() -> None:
    """A non-empty ``pool_id=`` names a pool, an empty one unplaces the host,
    and no ``pool_id`` at all leaves its pool unstated, never a default."""
    hosts = {
        host.host_id: host
        for host in parse_inventory_ini(
            "[hosts]\n"
            "placed ansible_host=10.0.0.1 ansible_user=root pool_id=gpu\n"
            "cleared ansible_host=10.0.0.2 ansible_user=root pool_id=\n"
            "unstated ansible_host=10.0.0.3 ansible_user=root\n"
        )
    }

    assert hosts["placed"].pool_id == "gpu"
    assert hosts["cleared"].pool_id is None
    assert hosts["unstated"].pool_id is POOL_UNSTATED


def test_variables_and_children_sections_list_no_hosts() -> None:
    hosts = parse_inventory_ini(
        "[nodes:vars]\nansible_user=ubuntu\n[all:children]\nnodes\n"
    )

    assert hosts == []


def test_embedded_key_material_is_read_and_submitted_as_a_secret() -> None:
    read: list[str] = []

    def read_key(path: str) -> str:
        read.append(path)
        return f"material for {path}"

    hosts = parse_inventory_ini(
        "[kvm_hosts]\nkvm2 ansible_host=10.0.0.2 ansible_user=ops "
        "ansible_ssh_private_key_file=/keys/kvm2\n",
        key_material="embedded",
        read_key=read_key,
    )

    assert read == ["/keys/kvm2"]
    assert hosts[0].connection.public["key_path"] is None
    assert hosts[0].connection.secrets == {"private_key": "material for /keys/kvm2"}


# Tenant-facing routes on RFC 5737 documentation addresses: development fixture
# values that must never be used on a public network.
_ROUTED_INI = """
[nodes]
routed ansible_host=198.51.100.1 ansible_user=root ansible_port=6000 public_host=192.0.2.10 public_port=22
portonly ansible_host=198.51.100.2 ansible_user=root public_port=2222
plain ansible_host=198.51.100.3 ansible_user=root
notaport ansible_host=198.51.100.4 ansible_user=root public_port=ssh
zeroport ansible_host=198.51.100.5 ansible_user=root public_port=0
hugeport ansible_host=198.51.100.6 ansible_user=root public_port=70000
"""


def test_a_tenant_facing_port_is_read_and_a_malformed_one_rejects_only_its_entry() -> None:
    hosts = {host.host_id: host for host in parse_inventory_ini(_ROUTED_INI)}

    assert sorted(hosts) == ["plain", "portonly", "routed"]
    routed = hosts["routed"].connection.public
    assert (routed["ssh_port"], routed["public_host"], routed["public_port"]) == (6000, "192.0.2.10", 22)
    assert (hosts["portonly"].connection.public["public_host"], hosts["portonly"].connection.public["public_port"]) == (None, 2222)
    assert "public_port" not in hosts["plain"].connection.public


def test_an_inventory_round_trips_through_the_rendered_execution_inventory() -> None:
    """What an entry states survives registration and rendering, so the
    inventory a job runs against reads back as the entry it came from."""
    codec = SshConnectionCodec()
    parsed = parse_inventory_ini(_ROUTED_INI)
    targets = [
        inventory_target(
            ExecutionHost(
                host.host_id,
                None,
                codec.build(host.connection.public, host.connection.secrets),
            )
        )
        for host in parsed
    ]

    with AnsibleRunner(SimpleNamespace()).write_inventory(targets, group="nodes") as inventory:
        reparsed = parse_inventory_ini(inventory.path.read_text())

    assert [(host.host_id, dict(host.connection.public)) for host in reparsed] == [
        (host.host_id, dict(host.connection.public)) for host in parsed
    ]
