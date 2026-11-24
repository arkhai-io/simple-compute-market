"""The provisioning inventory through Ansible's actual SSH command builder."""

import json
import subprocess
import sys
from base64 import b64encode
from types import SimpleNamespace

from compute_provisioning_ansible.runner import AnsibleRunner, InventoryTarget


def test_ansible_ssh_command_uses_inventory_pins_even_with_operator_overrides(
    tmp_path, monkeypatch
):
    config = tmp_path / "ansible.cfg"
    config.write_text(
        "[defaults]\nhost_key_checking = False\n"
        "[ssh_connection]\nssh_args = -o StrictHostKeyChecking=no -o ControlMaster=auto\n"
    )
    monkeypatch.setenv("ANSIBLE_CONFIG", str(config))
    command_builder = """
import json
import sys
from ansible.inventory.manager import InventoryManager
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.play_context import PlayContext
from ansible.plugins.loader import connection_loader
from ansible.vars.manager import VariableManager

loader = DataLoader()
inventory = InventoryManager(loader=loader, sources=[sys.argv[1]])
host = inventory.get_host("kvm1")
variables = VariableManager(loader=loader, inventory=inventory).get_vars(host=host)
connection = connection_loader.get("ssh", PlayContext(), None)
connection.set_options(var_options=variables)
argv = connection._build_command("ssh", "ssh", variables["ansible_host"])
print(json.dumps([item.decode() for item in argv]))
"""
    # Deterministic fixture with no corresponding private key.
    wire = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + b"t" * 32
    pin = "ssh-ed25519 " + b64encode(wire).decode("ascii")
    host = InventoryTarget("kvm1", "192.0.2.2", None, 2201, "fixture", "path", "/fixture/id",
                           host_keys=(pin,))
    runner = AnsibleRunner(SimpleNamespace())
    with runner.write_inventory([host], group="nodes") as inventory:
        assert inventory.known_hosts_paths[0].read_text() == f"[192.0.2.2]:2201 {pin}\n"
        run = subprocess.run(
            [sys.executable, "-c", command_builder, str(inventory.path)],
            check=True, capture_output=True, text=True, timeout=20,
        )
        argv = json.loads(run.stdout)
        assert "StrictHostKeyChecking=yes" in argv
        assert "StrictHostKeyChecking=no" not in argv
        assert "ControlMaster=no" in argv
        assert "ControlMaster=auto" not in argv
        assert "GlobalKnownHostsFile=/dev/null" in argv
        assert f"UserKnownHostsFile={inventory.known_hosts_paths[0]}" in argv
        assert "HostKeyAlias=[192.0.2.2]:2201" in argv
