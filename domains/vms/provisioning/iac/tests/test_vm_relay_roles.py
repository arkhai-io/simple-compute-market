"""Run the VM relay call boundary and create facts through native Ansible.

Family roles are controlled stand-ins for these domain dispatch tests. The family
suite exercises the real roles. The fact tests render the shipped tasks without
creating a guest. All keys, grants and addresses below are synthetic development
fixtures and must never be used on a public network.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "ansible/roles/vm-management/tasks"


def _ansible() -> tuple[str | None, str]:
    binary = shutil.which("ansible-playbook")
    if binary is None:
        return None, "native tests require ansible-core 2.17 to 2.19"
    version = subprocess.run([binary, "--version"], capture_output=True, text=True, check=False)
    if not re.search(r"core 2\.(1[7-9])\.", version.stdout):
        return None, "native tests require ansible-core 2.17 to 2.19"
    return binary, ""


ANSIBLE_PLAYBOOK, UNAVAILABLE = _ansible()


def _tasks(name: str) -> list[dict]:
    return yaml.safe_load((TASKS / name).read_text(encoding="utf-8"))


@unittest.skipIf(ANSIBLE_PLAYBOOK is None, UNAVAILABLE)
class TestVmRelayBoundary(unittest.TestCase):
    def _run(self, tasks: list[dict], variables: dict, *, proxy_role: list[dict] | None = None) -> dict:
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            if proxy_role is not None:
                role = work / "roles/relay-proxy/tasks"
                role.mkdir(parents=True)
                (role / "main.yml").write_text(yaml.safe_dump(proxy_role), encoding="utf-8")
            output = work / "fact.json"
            play = [{"hosts": "localhost", "connection": "local", "gather_facts": False,
                     "vars": variables,
                     "tasks": tasks + [{"name": "Export the rendered fact", "copy": {
                         "content": "{{ vm_creation_data | default({}) | to_json }}", "dest": str(output),
                         "mode": "0600"}}]}]
            path = work / "play.yml"
            path.write_text(yaml.safe_dump(play, sort_keys=False), encoding="utf-8")
            environment = {key: value for key, value in os.environ.items() if not key.startswith("ANSIBLE_")}
            environment.update(ANSIBLE_ROLES_PATH=str(work / "roles"), ANSIBLE_NOCOLOR="true")
            run = subprocess.run([ANSIBLE_PLAYBOOK, "-i", "localhost,", str(path)], cwd=work,
                                 env=environment, capture_output=True, text=True, timeout=90, check=False)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            return json.loads(output.read_text(encoding="utf-8"))

    def test_both_shipped_fact_variants_render_the_same_relay_endpoint(self) -> None:
        facts = [task for task in _tasks("vm-create.yml") if "vm_creation_data" in task.get("set_fact", {})]
        for key in ("", "ssh-ed25519 AAAAfixture buyer@example.invalid"):
            with self.subTest(key_type="provided" if key else "generated"):
                fact = self._run(facts, {
                    "vm_action": "create", "vm_name": "guest-example", "vm_tenant_pubkey": key,
                    "vm_create_result": {}, "vm_ip": "192.0.2.10", "tenant_ssh_host": "198.51.100.10",
                    "creation_timestamp": {"stdout": "2026-11-01T12:00:00Z"},
                    "root_password": "synthetic-root", "tenant_password": "synthetic-tenant",
                    "vm_root_ssh_filename": "example-root", "random_string": "example",
                    "frp_server_addr": "203.0.113.10", "vm_remote_port": 6101,
                })
                self.assertNotIn("frp", fact)
                self.assertEqual(fact["relay"], {
                    "enabled": True, "relay_addr": "203.0.113.10", "remote_port": 6101,
                    "ssh_access": "ssh -p 6101 guestexample@203.0.113.10",
                })

    def test_create_supplies_the_exact_proxy_endpoint_and_grant(self) -> None:
        (call,) = [task for task in _tasks("vm-create.yml") if task.get("vars", {}).get("relay_proxy_action") == "add"]
        self._run([call], {
            "vm_action": "create", "vm_name": "guest-example", "vm_ip": "192.0.2.10",
            "vm_remote_port": 6101, "frp_server_addr": "203.0.113.10", "target_host": "localhost",
            "relay_grant": "synthetic-grant", "frp_auth_token": "synthetic-token",
        }, proxy_role=[{"name": "Assert domain inputs", "assert": {"that": [
            "relay_proxy_action == 'add'", "relay_proxy_name == 'vm-guest-example'",
            "relay_proxy_local_ip == '192.0.2.10'", "relay_proxy_remote_port | int == 6101",
            "relay_grant == 'synthetic-grant'", "frp_auth_token == 'synthetic-token'",
            "inventory_hostname == 'localhost'",
        ]}}])

    def test_a_direct_create_does_not_invoke_a_proxy_role(self) -> None:
        (call,) = [task for task in _tasks("vm-create.yml") if task.get("vars", {}).get("relay_proxy_action") == "add"]
        self._run([call], {"vm_action": "create", "vm_name": "guest-example", "vm_ip": "192.0.2.10"},
                  proxy_role=[{"name": "Refuse unexpected proxy", "fail": {"msg": "direct host invoked relay"}}])
