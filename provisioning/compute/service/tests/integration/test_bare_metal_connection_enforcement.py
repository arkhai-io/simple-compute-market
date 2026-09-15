"""A pinned bare-metal spawn connects only through the pinned OpenSSH client.

Pinned host trust is expressed as OpenSSH options, so it constrains a
connection only when Ansible's OpenSSH plugin is the one selected, and only
when nothing an inventory or the inherited environment supplies can replace the
executable, reuse an unverified multiplexed connection or add a host-key
source. These tests run the real playbook through the production spawn against
a hostile inventory and environment, and inspect every SSH command line the
plugin built. No connection is made: the ``ssh`` on ``PATH`` records its
arguments and refuses.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from vm_provisioning_adapter.services.ansible_service import SshHostTrust

from .bare_metal_playbook import INVENTORY_ADDRESS, BareMetalPlaybook, first_option

PORT = 6001


def _pins(tmp_path: Path) -> Path:
    public = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    pins = tmp_path / "known_hosts"
    pins.write_text(f"[{INVENTORY_ADDRESS}]:{PORT} {public.decode()}\n", encoding="utf-8")
    return pins


def _trust(pins: Path) -> SshHostTrust:
    return SshHostTrust(known_hosts_path=pins, host=INVENTORY_ADDRESS, port=PORT)


@pytest.mark.parametrize(
    "connection",
    [
        "paramiko",
        "ansible.builtin.paramiko_ssh",
        "local",
        "ansible.builtin.local",
        "ssh",
        None,
    ],
)
async def test_pinned_spawn_uses_only_the_pinned_openssh_client(
    tmp_path, monkeypatch, connection
):
    playbook = BareMetalPlaybook(tmp_path, monkeypatch, hostile_environment=True)
    pins = _pins(tmp_path)
    inventory = playbook.write_inventory(
        port=PORT, host_vars=playbook.hostile_vars(connection=connection)
    )

    run = await playbook.run(inventory, _trust(pins))

    assert run.module_calls == [], "a module ran without going through the pinned client"
    assert run.calls("hostile") == [], "a hostile ssh/scp/sftp executable was run"
    assert run.unexplained_calls() == []
    connections = run.connections("ssh")
    assert connections, run.output[-3000:]
    for argv in connections:
        assert first_option(argv, "StrictHostKeyChecking") == "yes"
        assert first_option(argv, "UserKnownHostsFile") == str(pins)
        assert first_option(argv, "GlobalKnownHostsFile") == "/dev/null"
        # No host-key source besides the pinned file, and no multiplexed
        # connection that could have been opened without it.
        assert first_option(argv, "KnownHostsCommand") == "/bin/true"
        assert first_option(argv, "VerifyHostKeyDNS") == "no"
        assert first_option(argv, "ControlMaster") == "no"
        assert first_option(argv, "ControlPath") == "none"
        assert first_option(argv, "Port") == str(PORT)
    assert run.returncode != 0


async def test_a_provider_proxy_command_still_applies_to_a_pinned_spawn(tmp_path, monkeypatch):
    playbook = BareMetalPlaybook(tmp_path, monkeypatch)
    pins = _pins(tmp_path)
    inventory = playbook.write_inventory(
        port=PORT, host_vars='ansible_ssh_common_args="-o ProxyCommand=/bin/false"'
    )

    run = await playbook.run(inventory, _trust(pins))

    assert run.unexplained_calls() == []
    argv = run.connections("ssh")[0]
    assert first_option(argv, "ProxyCommand") == "/bin/false"
    assert first_option(argv, "StrictHostKeyChecking") == "yes"
    assert first_option(argv, "UserKnownHostsFile") == str(pins)


async def test_control_without_pinned_trust_the_hostile_inventory_selects_paramiko(
    tmp_path, monkeypatch
):
    """The hostile selection is real: it is the enforcement that overrides it.

    This is also the VM path — a spawn without host trust — which keeps whatever
    connection its inventory names. paramiko is not installed here, so the
    selection surfaces as that plugin's refusal rather than as a connection.
    """
    playbook = BareMetalPlaybook(tmp_path, monkeypatch, hostile_environment=True)
    inventory = playbook.write_inventory(
        port=PORT, host_vars=playbook.hostile_vars(connection="paramiko")
    )

    run = await playbook.run(inventory, None)

    assert run.connections("ssh") == []
    assert run.calls("hostile") == []
    assert "paramiko" in run.output.lower(), run.output[-3000:]
    assert run.returncode != 0


async def test_a_spawn_without_trust_keeps_ansible_defaults(tmp_path, monkeypatch):
    """VM playbooks are not the managed profile and keep multiplexing."""
    playbook = BareMetalPlaybook(tmp_path, monkeypatch)
    inventory = playbook.write_inventory(port=PORT)

    run = await playbook.run(inventory, None)

    assert run.unexplained_calls() == []
    argv = run.connections("ssh")[0]
    assert first_option(argv, "ControlMaster") == "auto"
    assert first_option(argv, "ControlPersist") == "60s"
    # The IaC ansible.cfg disables checking for the VM path.
    assert first_option(argv, "StrictHostKeyChecking") == "no"
    assert first_option(argv, "UserKnownHostsFile") is None
