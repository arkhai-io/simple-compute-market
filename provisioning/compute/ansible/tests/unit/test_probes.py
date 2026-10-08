"""The connectivity probe."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost, ProtectedValue
from cryptography.fernet import Fernet
from market_config import encrypt_secret

from compute_provisioning_ansible import SshConnectionCodec
from compute_provisioning_contracts import ConnectivityResult
from compute_provisioning_ansible.probes import PROBE_INVENTORY_GROUP, probe_connectivity
from compute_provisioning_ansible.runner import AnsibleRunner


class _ProbingRunner(AnsibleRunner):
    """The real runner, with the ping itself replaced."""

    def __init__(self, key: str) -> None:
        super().__init__(SimpleNamespace(), ssh_codec=SshConnectionCodec(key))
        self.seen: dict = {}

    async def check_connectivity_with_inventory(self, host, inventory_path):
        text = inventory_path.read_text()
        self.seen = {
            "host": host,
            "inventory": inventory_path,
            "group line": text.splitlines()[0],
            "key": Path(text.split("ansible_ssh_private_key_file=")[1].split()[0]),
        }
        self.seen["key existed"] = self.seen["key"].exists()
        return ConnectivityResult(host=host, reachable=True, detail="pong")


async def test_a_probe_pings_the_registered_host_and_leaves_nothing_behind():
    key = Fernet.generate_key().decode()
    host = ExecutionHost(
        host_id="node-1",
        pool_id="default",
        connection=ConnectionEnvelope(
            kind="ssh",
            version=1,
            public={"ssh_host": "10.0.0.1", "ssh_port": 22, "ssh_user": "ops", "key_path": None},
            protected={"private_key": ProtectedValue("fernet-v1", encrypt_secret("PEM", key))},
        ),
    )
    runner = _ProbingRunner(key)

    result = await probe_connectivity(runner, host)

    assert (result.host, result.reachable) == ("node-1", True)
    assert runner.seen["group line"] == f"[{PROBE_INVENTORY_GROUP}]"
    assert runner.seen["key existed"]
    assert not runner.seen["key"].exists()
    assert not runner.seen["inventory"].exists()
