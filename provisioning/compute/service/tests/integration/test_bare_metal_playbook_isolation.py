"""The harness fixture is isolated from the machine it runs on.

The bare-metal harnesses drive real production code and, when the parent runs
them, a real OpenSSH client. That is only acceptable if the fixture — not the
invoking account — supplies the client configuration, the Ansible
configuration, the child environment and the process boundary. These tests
assert those properties directly, and none of them makes an SSH connection: the
"client" is ``/bin/true`` or a stand-in that records and refuses.

Contamination is tested with synthetic sentinels planted in the environment,
never by reading or moving the invoking account's real files.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from vm_provisioning_adapter.services.ansible_service import SshHostTrust

from . import bare_metal_playbook
from .bare_metal_playbook import (
    BareMetalPlaybook,
    pinned_toolchain,
    process_group_members,
)

PORT = 2222


def _pins(tmp_path: Path) -> Path:
    public = ed25519.Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    )
    pins = tmp_path / "known_hosts"
    pins.write_text(f"[127.0.0.1]:{PORT} {public.decode()}\n", encoding="utf-8")
    return pins


def _trust(pins: Path) -> SshHostTrust:
    return SshHostTrust(known_hosts_path=pins, host="127.0.0.1", port=PORT)


def _entries(playbook: BareMetalPlaybook) -> list[dict]:
    record = playbook.root / "executable-calls.jsonl"
    if not record.exists():
        return []
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]


# --- client configuration -------------------------------------------------


async def test_the_real_client_is_handed_a_fixture_owned_configuration(tmp_path, monkeypatch):
    """Whatever Ansible built, the client starts with the fixture's own -F file.

    ``/bin/true`` stands in for the client: the hand-over path runs in full and
    nothing connects.
    """
    playbook = BareMetalPlaybook(tmp_path, monkeypatch, real_ssh="/bin/true")
    pins = _pins(tmp_path)
    playbook.allow_endpoint(PORT, pins)
    inventory = playbook.write_inventory(port=PORT)

    run = await playbook.run(inventory, _trust(pins))

    handed_over = [entry for entry in run.entries("ssh") if entry.get("action") == "handed-over"]
    assert handed_over, run.entries("ssh")
    for entry in handed_over:
        assert entry["final_argv"][:2] == ["-F", str(playbook.ssh_config)]
        # The fixture's file is the only one: nothing else may supply -F.
        assert entry["final_argv"].count("-F") == 1
    assert run.survivors == []


def test_the_fixture_configuration_neutralises_agent_proxy_and_forwarding(tmp_path, monkeypatch):
    playbook = BareMetalPlaybook(tmp_path, monkeypatch)
    configuration = playbook.ssh_config.read_text(encoding="utf-8")

    for directive in (
        "IdentityAgent none",
        "IdentitiesOnly yes",
        "ForwardAgent no",
        "ForwardX11 no",
        "PermitLocalCommand no",
        "ProxyCommand none",
        "ProxyJump none",
        "GlobalKnownHostsFile /dev/null",
        "KnownHostsCommand /bin/true",
        "BatchMode yes",
    ):
        assert directive in configuration, directive
    # An Include would reintroduce whatever it names.
    assert "Include" not in configuration


# --- configuration contamination ------------------------------------------


async def test_planted_environment_sentinels_never_reach_the_run(tmp_path, monkeypatch):
    """Synthetic ANSIBLE_* settings are dropped, not inherited."""
    sentinel = "arkhai-sentinel-must-not-be-used"
    decoy_config = tmp_path / "decoy.cfg"
    decoy_config.write_text(f"[defaults]\nroles_path = /{sentinel}\n", encoding="utf-8")
    planted = {
        "ANSIBLE_CONFIG": str(decoy_config),
        "ANSIBLE_LIBRARY": f"/{sentinel}",
        "ANSIBLE_SSH_ARGS": f"-o SendEnv={sentinel}",
        "ANSIBLE_SSH_COMMON_ARGS": f"-o SendEnv={sentinel}",
        "ANSIBLE_ROLES_PATH": f"/{sentinel}",
    }
    for name, value in planted.items():
        monkeypatch.setenv(name, value)

    playbook = BareMetalPlaybook(tmp_path, monkeypatch)
    pins = _pins(tmp_path)
    playbook.allow_endpoint(PORT, pins)

    # The fixture owns the configuration the child will read.
    assert os.environ["ANSIBLE_CONFIG"] == str(playbook.ansible_cfg)
    for name in ("ANSIBLE_LIBRARY", "ANSIBLE_SSH_ARGS", "ANSIBLE_SSH_COMMON_ARGS",
                 "ANSIBLE_ROLES_PATH"):
        assert name not in os.environ, name

    run = await playbook.run(playbook.write_inventory(port=PORT), _trust(pins))

    assert sentinel not in run.output
    for argv in run.calls("ssh"):
        assert sentinel not in " ".join(argv)
    assert run.survivors == []


# --- process boundary -----------------------------------------------------


async def test_a_stalled_run_is_ended_and_leaves_no_descendants(tmp_path, monkeypatch):
    """The timeout path ends the whole run group, not just ansible-playbook."""
    playbook = BareMetalPlaybook(tmp_path, monkeypatch, stall=True)
    pins = _pins(tmp_path)
    playbook.allow_endpoint(PORT, pins)

    run = await playbook.run(playbook.write_inventory(port=PORT), _trust(pins), timeout=5)

    assert any(entry.get("action") == "stalled" for entry in run.entries("ssh")), run.entries("ssh")
    # Production's own timeout cleanup must have ended the run; the fixture's
    # unconditional cleanup runs afterwards and must not be what proves this.
    assert run.production_survivors == [], (
        f"production cleanup left processes running: {run.production_survivors}"
    )
    assert run.survivors == [], f"processes outlived the timeout: {run.survivors}"


async def test_a_cancelled_run_is_ended_and_leaves_no_descendants(tmp_path, monkeypatch):
    playbook = BareMetalPlaybook(tmp_path, monkeypatch, stall=True)
    pins = _pins(tmp_path)
    playbook.allow_endpoint(PORT, pins)
    inventory = playbook.write_inventory(port=PORT)

    task = asyncio.create_task(playbook.run(inventory, _trust(pins), timeout=120))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if any(entry.get("action") == "stalled" for entry in _entries(playbook)):
            break
        await asyncio.sleep(0.05)
    else:
        task.cancel()
        pytest.fail("the ssh stand-in never reached its stall")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    # Production's cancellation path must have ended the run before the
    # fixture's unconditional cleanup ran.
    assert playbook.production_survivors == [], (
        "production cleanup left processes running after cancellation: "
        f"{playbook.production_survivors}"
    )
    assert playbook.survivors == [], f"processes outlived cancellation: {playbook.survivors}"
    assert process_group_members(playbook.last_group) == []


# --- the recorder's own refusal -------------------------------------------


def test_the_recorder_refuses_a_destination_outside_the_fixture(tmp_path, monkeypatch):
    """Validated before connecting: a foreign destination never reaches a client."""
    playbook = BareMetalPlaybook(tmp_path, monkeypatch, real_ssh="/bin/true")
    playbook.allow_endpoint(PORT, _pins(tmp_path))

    completed = subprocess.run(
        [
            str(playbook.root / "bin" / "ssh"),
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"Port={PORT}",
            "192.0.2.10",
            "true",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    # 255 is what a client that could not connect exits with, so Ansible treats
    # a refusal as the connection failure it is; the recorded verdict is what
    # distinguishes a rejection from an ordinary refusal.
    assert completed.returncode == 255, completed.stderr
    entries = _entries(playbook)
    rejected = [entry for entry in entries if entry.get("action") == "rejected"]
    assert rejected, entries
    assert any("not a fixture endpoint" in problem for problem in rejected[-1]["problems"])
    assert not [entry for entry in entries if entry.get("action") == "handed-over"]


def test_the_recorder_refuses_an_identity_outside_the_fixture(tmp_path, monkeypatch):
    playbook = BareMetalPlaybook(tmp_path, monkeypatch, real_ssh="/bin/true")
    pins = _pins(tmp_path)
    playbook.allow_endpoint(PORT, pins)

    completed = subprocess.run(
        [
            str(playbook.root / "bin" / "ssh"),
            "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={pins}",
            "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", f"Port={PORT}",
            "-i", "/etc/ssh/ssh_host_ed25519_key",
            "127.0.0.1",
            "true",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 255, completed.stderr
    entries = _entries(playbook)
    rejected = [entry for entry in entries if entry.get("action") == "rejected"]
    assert any(
        "is outside the fixture" in problem for problem in rejected[-1]["problems"]
    ), rejected
    assert not [entry for entry in entries if entry.get("action") == "handed-over"]


# --- toolchain ------------------------------------------------------------


def test_the_toolchain_under_test_is_the_intended_one():
    toolchain = pinned_toolchain()

    assert toolchain["ansible"].startswith("2.1")
    assert "site-packages" in toolchain["adapter"]


def test_a_stale_installed_adapter_fails_the_run(tmp_path, monkeypatch):
    """A worktree fix that was never rebuilt must not look like a passing run."""
    stale = tmp_path / "stale_ansible_service.py"
    stale.write_text("# not the installed adapter\n", encoding="utf-8")
    monkeypatch.setattr(bare_metal_playbook, "ADAPTER_SOURCE", stale)

    with pytest.raises(AssertionError, match="not the corrected worktree source"):
        pinned_toolchain()
