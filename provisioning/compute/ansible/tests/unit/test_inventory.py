"""Ansible INI inventories parsed into hosts with ssh connections."""

from __future__ import annotations

from compute_provisioning_ansible import DEFAULT_KEY_PATH, parse_inventory_ini

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
    assert hosts["bm1"].pool_id == "default"


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
