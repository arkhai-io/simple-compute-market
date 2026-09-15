"""A pinned bare-metal spawn reaches the selected endpoint, never another pin.

The trust preflight verifies the pin for the selected ``SshHostTrust`` endpoint,
but the physical action must reach *that* host. A known_hosts file legitimately
holds a pin for every managed host, so "the connection is to a pinned host" is
not enough: it must be the selected one. A hostile or careless inventory that
names another pinned host's address or port — or injects an OpenSSH
``HostName``/``Port``/``HostKeyAlias`` — must not redirect the action there.

These offline tests run the real node-access playbook through the production
spawn (``bare_metal_playbook``) with a recording ``ssh`` that connects nowhere,
and inspect the command line Ansible's own ssh plugin built. Both the selected
and a decoy endpoint are pinned in the same file; the built connection must
still target the selected endpoint. The connection-level counterparts that
prove a wrong-host attempt reaches the selected live endpoint or fails closed
are gated behind ``ARKHAI_RUN_SSH_TRUST_HARNESS=1`` and are the parent's to run;
they use the same isolated fixture and endpoint as the changed-host-key harness.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from vm_provisioning_adapter.services.ansible_service import SshHostTrust

from .bare_metal_playbook import CONTROLPERSIST_PROBE, BareMetalPlaybook, first_option
from .ssh_endpoint import LOOPBACK, Endpoint, known_hosts_line

# Selected management endpoint, and a decoy that is pinned in the same file but
# must never receive the action. Both are loopback so the gated connection tests
# can bind them; they differ by port, which is what the pin key records.
SELECTED_HOST = LOOPBACK
SELECTED_PORT = 2222
DECOY_HOST = "127.0.0.9"
DECOY_PORT = 9999


def _known_hosts_name(host: str, port: int) -> str:
    return host if port == 22 else f"[{host}]:{port}"


def _pin_line(host: str, port: int) -> str:
    public = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    return f"{_known_hosts_name(host, port)} {public.decode()}\n"


def _pins_with_both(tmp_path: Path) -> Path:
    """A known_hosts file pinning both the selected endpoint and the decoy."""
    pins = tmp_path / "known_hosts"
    pins.write_text(
        _pin_line(SELECTED_HOST, SELECTED_PORT) + _pin_line(DECOY_HOST, DECOY_PORT),
        encoding="utf-8",
    )
    return pins


def _trust(pins: Path) -> SshHostTrust:
    return SshHostTrust(known_hosts_path=pins, host=SELECTED_HOST, port=SELECTED_PORT)


def _redirect_to_decoy() -> str:
    """Inventory host vars that try to aim the spawn at the decoy endpoint."""
    alias = _known_hosts_name(DECOY_HOST, DECOY_PORT)
    return (
        f"ansible_host={DECOY_HOST} ansible_ssh_host={DECOY_HOST}"
        f" ansible_port={DECOY_PORT} ansible_ssh_port={DECOY_PORT}"
        f' ansible_ssh_common_args="-o HostName={DECOY_HOST} -o Port={DECOY_PORT}'
        f' -o HostKeyAlias={alias}"'
    )


def _connection_argv(run) -> list[str]:
    """The single ssh command line built to reach the host (not the probe)."""
    connections = [argv for argv in run.calls("ssh") if argv != CONTROLPERSIST_PROBE]
    assert connections, run.output[-3000:]
    assert len(connections) == 1, connections
    return connections[0]


def _target(argv: list[str]) -> str:
    # Ansible builds ``ssh <options...> <host> <remote-command>``.
    return argv[-2]


def _assert_targets_selected(argv: list[str], pins: Path) -> None:
    assert _target(argv) == SELECTED_HOST, argv
    assert first_option(argv, "HostName") == SELECTED_HOST
    assert first_option(argv, "Port") == str(SELECTED_PORT)
    assert first_option(argv, "UserKnownHostsFile") == str(pins)
    assert first_option(argv, "StrictHostKeyChecking") == "yes"
    assert first_option(argv, "GlobalKnownHostsFile") == "/dev/null"


async def test_a_pinned_spawn_targets_the_selected_endpoint(tmp_path, monkeypatch):
    """Positive control: with a matching inventory the spawn targets selected."""
    playbook = BareMetalPlaybook(tmp_path, monkeypatch)
    pins = _pins_with_both(tmp_path)
    # The selected endpoint is the only one the fixture would let a client
    # reach, so a clean verdict is part of what these assertions mean.
    playbook.allow_endpoint(SELECTED_PORT, pins)
    inventory = playbook.write_inventory(port=SELECTED_PORT)

    run = await playbook.run(inventory, _trust(pins))

    _assert_targets_selected(_connection_argv(run), pins)
    assert run.calls("hostile") == []
    assert run.survivors == []


async def test_inventory_address_and_port_cannot_redirect_to_another_pinned_host(
    tmp_path, monkeypatch
):
    playbook = BareMetalPlaybook(tmp_path, monkeypatch)
    pins = _pins_with_both(tmp_path)
    playbook.allow_endpoint(SELECTED_PORT, pins)
    inventory = playbook.write_inventory(port=DECOY_PORT, host_vars=_redirect_to_decoy())

    run = await playbook.run(inventory, _trust(pins))

    # Built to reach the selected endpoint despite every decoy alias, and the
    # known_hosts lookup key (host + port) is the selected endpoint's pin.
    _assert_targets_selected(_connection_argv(run), pins)
    assert run.calls("hostile") == []
    assert run.survivors == []


async def test_a_provider_proxy_command_survives_while_the_host_stays_selected(
    tmp_path, monkeypatch
):
    playbook = BareMetalPlaybook(tmp_path, monkeypatch)
    pins = _pins_with_both(tmp_path)
    playbook.allow_endpoint(SELECTED_PORT, pins)
    inventory = playbook.write_inventory(
        port=SELECTED_PORT,
        host_vars='ansible_ssh_common_args="-o ProxyCommand=/bin/false"',
    )

    run = await playbook.run(inventory, _trust(pins))

    argv = _connection_argv(run)
    assert first_option(argv, "ProxyCommand") == "/bin/false"
    _assert_targets_selected(argv, pins)


# --- connection-level, parent-run -----------------------------------------
#
# These bind two live endpoints and prove a wrong-host attempt reaches the
# selected one or fails closed, never accepting the decoy merely because it is
# pinned. They open loopback SSH connections, so they are gated; the writer
# runs collection only.

_RUN = os.environ.get("ARKHAI_RUN_SSH_TRUST_HARNESS") == "1"
connection_test = pytest.mark.skipif(
    not _RUN, reason="needs a loopback SSH connection; set ARKHAI_RUN_SSH_TRUST_HARNESS=1"
)


def _identity(tmp_path: Path) -> Path:
    path = tmp_path / "id_ed25519"
    path.write_bytes(
        ed25519.Ed25519PrivateKey.generate().private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.OpenSSH,
            serialization.NoEncryption(),
        )
    )
    path.chmod(0o600)
    return path


def _two_endpoints(tmp_path: Path):
    """A selected endpoint and a decoy, both pinned in one known_hosts file."""
    key_selected = ed25519.Ed25519PrivateKey.generate()
    key_decoy = ed25519.Ed25519PrivateKey.generate()
    selected = Endpoint(key_selected)
    decoy = Endpoint(key_decoy)
    pins = tmp_path / "known_hosts"
    pins.write_text(
        known_hosts_line(selected.port, key_selected)
        + known_hosts_line(decoy.port, key_decoy),
        encoding="utf-8",
    )
    return selected, decoy, pins


@connection_test
async def test_connection_reaches_selected_endpoint_positive_control(tmp_path, monkeypatch):
    selected, decoy, pins = _two_endpoints(tmp_path)
    try:
        playbook = BareMetalPlaybook(tmp_path, monkeypatch, real_ssh=shutil.which("ssh"))
        playbook.allow_endpoint(selected.port, pins)
        inventory = playbook.write_inventory(port=selected.port, identity=_identity(tmp_path))
        trust = SshHostTrust(known_hosts_path=pins, host=LOOPBACK, port=selected.port)

        run = await playbook.run(inventory, trust)
        selected.settle()
        decoy.settle()

        assert selected.transcripts and "client_accepted_host_key" in selected.transcripts[0]
        assert decoy.transcripts == []
        assert "Permission denied (publickey)" in run.output, run.output[-3000:]
        assert selected.errors == [] and decoy.errors == []
        assert run.survivors == []
    finally:
        selected.close()
        decoy.close()


@connection_test
async def test_inventory_pointing_at_another_pinned_endpoint_still_reaches_selected(
    tmp_path, monkeypatch
):
    selected, decoy, pins = _two_endpoints(tmp_path)
    try:
        playbook = BareMetalPlaybook(tmp_path, monkeypatch, real_ssh=shutil.which("ssh"))
        # Only the selected endpoint is reachable: if the binding failed, the
        # fixture refuses the connection instead of contacting the decoy.
        playbook.allow_endpoint(selected.port, pins)
        inventory = playbook.write_inventory(
            port=decoy.port,
            identity=_identity(tmp_path),
            host_vars=(
                f"ansible_ssh_host={LOOPBACK} ansible_ssh_port={decoy.port}"
                f' ansible_ssh_common_args="-o Port={decoy.port}"'
            ),
        )
        trust = SshHostTrust(known_hosts_path=pins, host=LOOPBACK, port=selected.port)

        run = await playbook.run(inventory, trust)
        selected.settle()
        decoy.settle()

        assert selected.transcripts and "client_accepted_host_key" in selected.transcripts[0]
        assert decoy.transcripts == []
        assert "Permission denied (publickey)" in run.output, run.output[-3000:]
        assert selected.errors == [] and decoy.errors == []
        assert run.survivors == []
    finally:
        selected.close()
        decoy.close()


@connection_test
async def test_hostile_hostkeyalias_to_another_pinned_endpoint_fails_closed(
    tmp_path, monkeypatch
):
    selected, decoy, pins = _two_endpoints(tmp_path)
    try:
        playbook = BareMetalPlaybook(tmp_path, monkeypatch, real_ssh=shutil.which("ssh"))
        playbook.allow_endpoint(selected.port, pins)
        # The connection reaches the selected endpoint, but the lookup is aimed
        # at the decoy's pin: the selected host cannot present the decoy's key.
        inventory = playbook.write_inventory(
            port=selected.port,
            identity=_identity(tmp_path),
            host_vars=(
                'ansible_ssh_common_args='
                f'"-o HostKeyAlias=[{LOOPBACK}]:{decoy.port}"'
            ),
        )
        trust = SshHostTrust(known_hosts_path=pins, host=LOOPBACK, port=selected.port)

        run = await playbook.run(inventory, trust)
        selected.settle()
        decoy.settle()

        assert "Host key verification failed" in run.output, run.output[-3000:]
        assert selected.transcripts and "host_key_offered" in selected.transcripts[0]
        assert "client_accepted_host_key" not in selected.transcripts[0]
        assert decoy.transcripts == []
        assert selected.errors == [] and decoy.errors == []
        assert run.survivors == []
    finally:
        selected.close()
        decoy.close()
