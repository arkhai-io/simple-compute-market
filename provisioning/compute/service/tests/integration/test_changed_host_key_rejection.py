"""A changed host key at the same endpoint is refused on the production path.

What this qualifies
-------------------
The whole path a bare-metal access playbook takes to a host.
``AnsibleService.start_playbook`` spawns the real node-access playbook with the
enforced trust, exactly as the job service does; Ansible resolves the inventory,
the inherited environment and the enforced extra-vars, selects the connection
plugin and builds the command line; the real OpenSSH client then makes the
host-key decision against a loopback endpoint. Nothing here writes an SSH
option or selects a plugin.

Every pinned attempt also carries the inventory a compromised or careless
operator could supply: ``ansible_connection=paramiko`` with its own checking
alias disabled, substitute ssh/scp/sftp executables, a pre-set control socket,
and ``ssh_common_args``/``ssh_extra_args`` naming a ``UserKnownHostsFile``,
``GlobalKnownHostsFile`` and ``KnownHostsCommand`` that all vouch for the key
being served. Those hostile values are fixture-owned inputs; nothing is taken
from the invoking environment.

Isolation is the ``bare_metal_playbook`` fixture's: an explicit ``-F`` client
configuration, a destination allowlist validated before any connection starts,
a fixture-owned ``ansible.cfg``, an allowlisted child environment, and an owned
process group that is ended and verified empty after every run. The endpoint
itself is ``ssh_endpoint``: a disposable loopback peer that performs a real key
exchange, never authenticates anyone and never opens a session, under one
never-rebound listening socket so "the same endpoint, a different key" is exact.

Positive control
----------------
Acceptance is asserted affirmatively from both sides: Ansible reports the
client's authentication-stage denial ``Permission denied (publickey)``, and the
endpoint records that the client completed the key exchange and sent an
authentication request. A test that only checked for the absence of a host-key
error would pass if the connection had failed for an unrelated reason.

Running it
----------
Gated so routine suites never depend on a loopback SSH connection. From the
service package directory:

    ARKHAI_RUN_SSH_TRUST_HARNESS=1 uv run --frozen --find-links <worktree>/.dist \\
        --with pytest --with pytest-asyncio \\
        pytest -q tests/integration/test_changed_host_key_rejection.py
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from vm_provisioning_adapter.services.ansible_service import HostTrustError, SshHostTrust

from .bare_metal_playbook import BareMetalPlaybook, PlaybookRun, first_option
from .ssh_endpoint import LOOPBACK, Endpoint, known_hosts_line

RUN_FLAG = "ARKHAI_RUN_SSH_TRUST_HARNESS"

pytestmark = pytest.mark.skipif(
    os.environ.get(RUN_FLAG) != "1",
    reason=f"needs a loopback SSH connection; set {RUN_FLAG}=1 to run",
)

HOST = LOOPBACK


@pytest.fixture
def real_ssh() -> str:
    # Resolved before the playbook fixture replaces PATH with the recorder.
    client = shutil.which("ssh")
    if client is None:
        pytest.fail("the harness needs an OpenSSH client on PATH")
    return client


@pytest.fixture
def key_a() -> ed25519.Ed25519PrivateKey:
    return ed25519.Ed25519PrivateKey.generate()


@pytest.fixture
def key_b() -> ed25519.Ed25519PrivateKey:
    return ed25519.Ed25519PrivateKey.generate()


@pytest.fixture
def endpoint(key_a):
    served = Endpoint(key_a)
    try:
        yield served
    finally:
        served.close()


@pytest.fixture
def identity(tmp_path) -> Path:
    """A client key no endpoint will ever accept."""
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


@pytest.fixture
def playbook(tmp_path, monkeypatch, real_ssh) -> BareMetalPlaybook:
    return BareMetalPlaybook(tmp_path, monkeypatch, real_ssh=real_ssh)


def _pins(tmp_path: Path, port: int, key: ed25519.Ed25519PrivateKey) -> Path:
    pins = tmp_path / "known_hosts"
    pins.write_text(known_hosts_line(port, key), encoding="utf-8")
    return pins


def _trust(pins: Path, port: int) -> SshHostTrust:
    return SshHostTrust(known_hosts_path=pins, host=HOST, port=port)


def _vouch(playbook: BareMetalPlaybook, port: int, key: ed25519.Ed25519PrivateKey) -> None:
    """Make every hostile known-hosts source vouch for *key*."""
    playbook.hostile_known_hosts.write_text(known_hosts_line(port, key), encoding="utf-8")


async def _attempt(
    playbook: BareMetalPlaybook,
    endpoint: Endpoint,
    inventory: Path,
    trust: SshHostTrust | None,
) -> tuple[PlaybookRun, list[list[str]]]:
    """Run the playbook once; return it with the endpoint transcripts it caused."""
    before = len(endpoint.transcripts)
    run = await playbook.run(inventory, trust)
    endpoint.settle()
    assert run.survivors == [], f"processes outlived the run: {run.survivors}"
    return run, endpoint.transcripts[before:]


def _assert_enforced(
    run: PlaybookRun, pins: Path, transcripts: list[list[str]]
) -> None:
    """The run reached the endpoint only through the pinned OpenSSH client."""
    assert run.module_calls == [], "a module ran without going through the pinned client"
    assert run.calls("hostile") == [], "a hostile ssh/scp/sftp executable was run"
    assert run.unexplained_calls() == []
    connections = run.connections("ssh")
    assert connections, run.output[-3000:]
    # Every connection the endpoint saw came through a recorded pinned command.
    assert len(transcripts) == len(connections), (transcripts, connections)
    for argv in connections:
        assert first_option(argv, "StrictHostKeyChecking") == "yes"
        assert first_option(argv, "UserKnownHostsFile") == str(pins)
        assert first_option(argv, "GlobalKnownHostsFile") == "/dev/null"
        assert first_option(argv, "KnownHostsCommand") == "/bin/true"
        assert first_option(argv, "ControlMaster") == "no"
        assert first_option(argv, "ControlPath") == "none"


# --- the enforced path ----------------------------------------------------


async def test_pinned_host_key_is_accepted_and_only_authentication_refuses(
    tmp_path, playbook, endpoint, identity, key_a
):
    """Positive control: the pinned endpoint is reached, then denied by auth."""
    pins = _pins(tmp_path, endpoint.port, key_a)
    playbook.allow_endpoint(endpoint.port, pins)
    _vouch(playbook, endpoint.port, key_a)
    inventory = playbook.write_inventory(
        port=endpoint.port,
        identity=identity,
        host_vars=playbook.hostile_vars(connection="paramiko"),
    )

    run, transcripts = await _attempt(playbook, endpoint, inventory, _trust(pins, endpoint.port))

    _assert_enforced(run, pins, transcripts)
    assert "Permission denied (publickey)" in run.output, run.output[-3000:]
    assert "Host key verification failed" not in run.output
    assert "client_accepted_host_key" in transcripts[0]
    assert "userauth_request" in transcripts[0]
    assert run.returncode != 0
    assert endpoint.errors == []


async def test_changed_host_key_at_the_same_endpoint_is_rejected(
    tmp_path, playbook, endpoint, identity, key_a, key_b
):
    pins = _pins(tmp_path, endpoint.port, key_a)
    playbook.allow_endpoint(endpoint.port, pins)
    _vouch(playbook, endpoint.port, key_a)
    inventory = playbook.write_inventory(
        port=endpoint.port,
        identity=identity,
        host_vars=playbook.hostile_vars(connection="paramiko"),
    )
    trust = _trust(pins, endpoint.port)

    accepted_run, accepted = await _attempt(playbook, endpoint, inventory, trust)
    assert "Permission denied (publickey)" in accepted_run.output, accepted_run.output[-3000:]
    assert "client_accepted_host_key" in accepted[0]

    # Same listening socket, same address and port, different host key — and
    # every hostile known-hosts source now vouches for the new one.
    endpoint.use_host_key(key_b)
    _vouch(playbook, endpoint.port, key_b)
    refused_run, refused = await _attempt(playbook, endpoint, inventory, trust)

    _assert_enforced(refused_run, pins, refused)
    assert "REMOTE HOST IDENTIFICATION HAS CHANGED" in refused_run.output, refused_run.output[-3000:]
    assert "Host key verification failed" in refused_run.output
    assert "Permission denied" not in refused_run.output
    # The refusal is the host-key comparison, not an earlier protocol failure.
    assert "host_key_offered" in refused[0]
    assert "client_accepted_host_key" not in refused[0]
    assert refused_run.returncode != 0
    assert endpoint.errors == []


async def test_hostile_known_hosts_sources_cannot_rescue_a_changed_key(
    tmp_path, playbook, endpoint, identity, key_a, key_b
):
    """The inventory's known-hosts sources name the served key, and lose."""
    pins = _pins(tmp_path, endpoint.port, key_a)
    playbook.allow_endpoint(endpoint.port, pins)
    endpoint.use_host_key(key_b)
    _vouch(playbook, endpoint.port, key_b)
    inventory = playbook.write_inventory(
        port=endpoint.port,
        identity=identity,
        host_vars=playbook.hostile_vars(connection="paramiko"),
    )

    run, transcripts = await _attempt(playbook, endpoint, inventory, _trust(pins, endpoint.port))

    _assert_enforced(run, pins, transcripts)
    assert "Host key verification failed" in run.output, run.output[-3000:]
    assert "client_accepted_host_key" not in transcripts[0]
    assert endpoint.errors == []


async def test_control_without_enforcement_the_same_sources_accept_the_changed_key(
    tmp_path, playbook, endpoint, identity, key_a, key_b
):
    """Without pinned trust the same hostile sources do accept key B.

    Spawned as the service spawns a VM playbook — no host trust. This proves
    the refusals above are the enforcement doing the work, rather than the
    hostile options being inert at the client. The fixture still confines the
    connection to its own endpoint; only the trust assertions are relaxed.
    """
    playbook.allow_endpoint(endpoint.port, require_trust=False)
    endpoint.use_host_key(key_b)
    _vouch(playbook, endpoint.port, key_b)
    inventory = playbook.write_inventory(
        port=endpoint.port,
        identity=identity,
        host_vars=playbook.hostile_vars(connection=None, replace_executables=False),
    )

    run, transcripts = await _attempt(playbook, endpoint, inventory, None)

    connections = run.connections("ssh")
    assert connections, run.output[-3000:]
    assert first_option(connections[0], "StrictHostKeyChecking") == "no"
    assert "Permission denied (publickey)" in run.output, run.output[-3000:]
    assert "Host key verification failed" not in run.output
    assert "client_accepted_host_key" in transcripts[0]
    assert endpoint.errors == []


async def test_an_unpinned_endpoint_is_refused_before_any_connection(
    tmp_path, playbook, endpoint, identity, key_a
):
    """No pin for this endpoint means no spawn, so the endpoint sees nothing."""
    pins = _pins(tmp_path, endpoint.port + 1, key_a)
    playbook.allow_endpoint(endpoint.port, pins)
    inventory = playbook.write_inventory(
        port=endpoint.port,
        identity=identity,
        host_vars=playbook.hostile_vars(connection="paramiko"),
    )

    with pytest.raises(HostTrustError):
        await playbook.run(inventory, _trust(pins, endpoint.port))

    assert endpoint.transcripts == []
    assert endpoint.errors == []
