"""The connectivity probe and the readiness report."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

from compute_provisioning.hosts import ConnectionEnvelope, ExecutionHost, ProtectedValue
from cryptography.fernet import Fernet
from market_config import encrypt_secret

from compute_provisioning_ansible import (
    ConnectivityResult,
    SshConnectionCodec,
    ansible_readiness,
)
from compute_provisioning_ansible.probes import (
    PROBE_INVENTORY_GROUP,
    collect_ssh_keys_from_hosts,
    probe_connectivity,
)
from compute_provisioning_ansible.runner import AnsibleRunner


def _host(host_id: str, *, key_path: str | None = None, embedded: bool = False):
    return SimpleNamespace(
        host_id=host_id,
        connection=SimpleNamespace(
            public={"key_path": key_path},
            protected={"private_key": object()} if embedded else {},
        ),
    )


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


def test_key_references_are_grouped_by_path_and_embedded_keys_listed_alone(tmp_path):
    key_file = tmp_path / "id_ed25519"
    key_file.write_bytes(b"key")
    hosts = [
        _host("b", key_path=str(key_file)),
        _host("a", key_path=str(key_file)),
        _host("c", key_path=str(tmp_path / "missing")),
        _host("d", embedded=True),
    ]

    keys = {info.raw_path: info for info in collect_ssh_keys_from_hosts(hosts)}

    assert keys[str(key_file)].referenced_by == ["a", "b"]
    assert keys[str(key_file)].sha256 == hashlib.sha256(b"key").hexdigest()
    assert keys[str(tmp_path / "missing")].exists is False
    assert keys["<encrypted>"].key_type == "embedded"
    assert keys["<encrypted>"].referenced_by == ["d"]


def test_readiness_reports_the_registry_the_playbook_and_the_modes(tmp_path):
    playbook = tmp_path / "playbook.yaml"
    playbook.write_text("- hosts: all\n")

    report = ansible_readiness(
        list_hosts=lambda: [_host("a", embedded=True)],
        inventory_path="sqlite:///hosts.db",
        playbook_path=playbook,
        ansible_mode="mock",
        executor_modes={"vm": "mock"},
    )

    assert report.ansible_mode == "mock"
    assert report.executor_modes == {"vm": "mock"}
    assert (report.inventory.exists, report.inventory.host_count) == (True, 1)
    assert report.inventory.path == "sqlite:///hosts.db"
    assert report.playbook.exists is True
    assert report.playbook.sha256 == hashlib.sha256(playbook.read_bytes()).hexdigest()
    assert [key.key_type for key in report.ssh_keys] == ["embedded"]


def test_an_unreadable_or_absent_registry_is_reported_not_raised(tmp_path):
    def failing():
        raise RuntimeError("database unavailable")

    for list_hosts in (failing, None):
        report = ansible_readiness(
            list_hosts=list_hosts,
            inventory_path="sqlite:///hosts.db",
            playbook_path=tmp_path / "absent.yaml",
            ansible_mode="real",
            executor_modes={},
        )

        assert (report.inventory.exists, report.inventory.host_count) == (False, None)
        assert report.ssh_keys == []
        assert (report.playbook.exists, report.playbook.sha256) == (False, None)
