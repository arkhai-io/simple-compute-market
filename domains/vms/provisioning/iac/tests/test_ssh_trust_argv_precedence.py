"""Enforced trust wins the effective Ansible-built SSH command line.

The provisioning service forces host trust as an ``ansible_ssh_args`` extra-var
(asserted in the service suite's ``test_ansible_host_trust``). Extra-vars are
Ansible's highest-precedence source, so the connection plugin resolves
``ssh_args`` to that value however an inventory or inherited environment tries
to set it. This test takes that resolved value and drives Ansible's real ssh
connection plugin — the code that assembles the ssh command — with hostile
``ssh_common_args`` and a disabled ``host_key_checking`` alongside it, then
resolves the produced options with ``ssh -G``. No connection is made.

The strict option block is written here as test data. That the service emits
exactly this block is proven separately; here it stands for "whatever the
extra-var resolved ssh_args to".
"""

from __future__ import annotations

import shlex
import subprocess

import pytest

pytest.importorskip("ansible")

from ansible.playbook.play_context import PlayContext  # noqa: E402
from ansible.plugins.loader import connection_loader  # noqa: E402

PINS = "/etc/arkhai/ssh/known_hosts"
STRICT_SSH_ARGS = (
    "-o StrictHostKeyChecking=yes "
    f"-o UserKnownHostsFile={PINS} "
    "-o GlobalKnownHostsFile=/dev/null "
    "-o KnownHostsCommand=/bin/true "
    "-o VerifyHostKeyDNS=no "
    "-o HostName=192.0.2.20 "
    "-o ControlMaster=no -o ControlPath=none -C"
)
HOSTILE_COMMON_ARGS = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"


def _built_ssh_options(**options) -> list[str]:
    """Return the ``-o`` option pairs Ansible's ssh plugin builds for a spawn."""
    connection = connection_loader.get("ssh", PlayContext(), "/dev/null")
    connection.set_options(direct={"host": "192.0.2.20", "remote_addr": "192.0.2.20", **options})
    command = [part.decode() for part in connection._build_command("ssh", "ssh", "true")]
    pairs: list[str] = []
    for index, token in enumerate(command):
        if token == "-o" and index + 1 < len(command):
            pairs += ["-o", command[index + 1]]
    return pairs


def _resolved(options: list[str]) -> list[str]:
    return subprocess.run(
        ["ssh", "-G", "-F", "/dev/null", *options, "-p", "6001", "192.0.2.20"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()


def test_strict_ssh_args_win_over_hostile_common_args_and_disabled_checking():
    resolved = _resolved(
        _built_ssh_options(
            ssh_args=STRICT_SSH_ARGS,
            ssh_common_args=HOSTILE_COMMON_ARGS,
            host_key_checking=False,
        )
    )

    assert "stricthostkeychecking true" in resolved
    assert f"userknownhostsfile {PINS}" in resolved
    assert "globalknownhostsfile /dev/null" in resolved


def test_a_legitimate_proxycommand_in_common_args_is_preserved():
    resolved = _resolved(
        _built_ssh_options(
            ssh_args=STRICT_SSH_ARGS,
            ssh_common_args="-o ProxyCommand=/usr/bin/true",
        )
    )

    assert "stricthostkeychecking true" in resolved
    assert any(line.startswith("proxycommand ") for line in resolved)


def test_control_shows_hostile_common_args_are_actually_hostile():
    """Without the strict ssh_args the same hostile options relax the check.

    This proves the enforcement above is doing the work, not that the hostile
    input was inert.
    """
    resolved = _resolved(
        _built_ssh_options(ssh_common_args=HOSTILE_COMMON_ARGS, host_key_checking=False)
    )

    assert "stricthostkeychecking false" in resolved
    assert "userknownhostsfile /dev/null" in resolved
