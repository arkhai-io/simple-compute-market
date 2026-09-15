"""Bare-metal playbooks are spawned with pinned, strict SSH host trust.

The real ``AnsibleService`` spawns a stand-in ``ansible-playbook`` placed first
on ``PATH`` that records the argv and environment it was started with; nothing
connects anywhere. Pins are generated with the real ``ssh-keygen``, and the SSH
options the spawn carries are evaluated by the real ``ssh -G``, which resolves
configuration without connecting.

Whether those options and the enforced connection survive a hostile inherited
or inventory configuration is covered by
``tests/integration/test_bare_metal_connection_enforcement.py``, which runs the
real playbook through this spawn and Ansible's own plugin selection.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from vm_provisioning_adapter.services.ansible_service import (
    AnsibleService,
    HostTrustError,
    SshHostTrust,
)

HOST = "192.0.2.20"
PORT = 6001


@pytest.fixture
def recorder(tmp_path, monkeypatch) -> Path:
    """A stand-in ``ansible-playbook`` that records how it was started."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "spawn.json"
    shim = bin_dir / "ansible-playbook"
    shim.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "with open(os.environ['HOST_TRUST_TEST_RECORD'], 'w') as handle:\n"
        "    json.dump({'argv': sys.argv[1:], 'env': {\n"
        "        key: os.environ.get(key)\n"
        "        for key in ('ANSIBLE_HOST_KEY_CHECKING', 'ANSIBLE_SSH_ARGS')\n"
        "    }}, handle)\n",
        encoding="utf-8",
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{Path(sys.executable).parent}:/usr/bin:/bin")
    monkeypatch.setenv("HOST_TRUST_TEST_RECORD", str(record))
    monkeypatch.delenv("ANSIBLE_HOST_KEY_CHECKING", raising=False)
    monkeypatch.delenv("ANSIBLE_SSH_ARGS", raising=False)
    return record


def _pin_line(tmp_path: Path, endpoint: str) -> str:
    key_file = tmp_path / f"hostkey-{abs(hash(endpoint))}"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key_file)],
        check=True,
    )
    key_type, key_data = key_file.with_suffix(".pub").read_text().split()[:2]
    return f"{endpoint} {key_type} {key_data}\n"


def _spawn(tmp_path: Path, host_trust: SshHostTrust | None):
    run = AnsibleService(MagicMock()).start_playbook(
        playbook_path=tmp_path / "playbook.yaml",
        inventory_path=tmp_path / "inventory.ini",
        extra_vars_path=tmp_path / "vars.yml",
        limit="bm1",
        host_trust=host_trust,
    )
    assert run.process.wait(timeout=30) == 0
    return run


def _recorded(record: Path) -> dict:
    return json.loads(record.read_text(encoding="utf-8"))


def _trust_extra_vars(argv: list[str]) -> dict:
    """The last ``-e`` JSON object on the command line: the enforced trust."""
    for index in range(len(argv) - 1, 0, -1):
        if argv[index - 1] == "-e" and argv[index].startswith("{"):
            return json.loads(argv[index])
    raise AssertionError(f"no trust extra-vars in argv: {argv}")


def test_bare_metal_spawn_forces_trust_through_highest_precedence_extra_vars(tmp_path, recorder):
    pins = tmp_path / "known_hosts"
    pins.write_text(_pin_line(tmp_path, f"[{HOST}]:{PORT}"), encoding="utf-8")

    _spawn(tmp_path, SshHostTrust(known_hosts_path=pins, host=HOST, port=PORT))

    spawned = _recorded(recorder)
    extra = _trust_extra_vars(spawned["argv"])
    # The connection plugin, both aliases of its checking option and the client
    # executables are fixed, not only the OpenSSH options.
    assert {key: value for key, value in extra.items() if key != "ansible_ssh_args"} == {
        "ansible_connection": "ansible.builtin.ssh",
        "ansible_ssh_executable": "ssh",
        "ansible_scp_executable": "scp",
        "ansible_sftp_executable": "sftp",
        # The connection is bound to the selected endpoint through every host and
        # port alias the ssh plugin resolves, so no inventory address redirects
        # the action to another host that happens to be pinned in the same file.
        "ansible_host": HOST,
        "ansible_ssh_host": HOST,
        "ansible_port": PORT,
        "ansible_ssh_port": PORT,
        "ansible_host_key_checking": True,
        "ansible_ssh_host_key_checking": True,
    }
    # The strict options lead so they win OpenSSH's first-value race over any
    # later inventory or inherited argument, and nothing re-enables sharing or
    # redirects the TCP destination away from the selected endpoint.
    assert shlex.split(extra["ansible_ssh_args"]) == [
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={pins}",
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "KnownHostsCommand=/bin/true",
        "-o", "VerifyHostKeyDNS=no",
        "-o", f"HostName={HOST}",
        "-o", "ControlMaster=no",
        "-o", "ControlPath=none",
        "-C",
    ]
    # The trust extra-vars are last on the command line, so no earlier -e or
    # @file can shadow them.
    assert spawned["argv"][-2] == "-e"
    assert spawned["env"]["ANSIBLE_HOST_KEY_CHECKING"] == "True"


def test_ssh_evaluates_the_forced_options_as_strict_and_pinned(tmp_path, recorder):
    pins = tmp_path / "known_hosts"
    pins.write_text(_pin_line(tmp_path, f"[{HOST}]:{PORT}"), encoding="utf-8")
    _spawn(tmp_path, SshHostTrust(known_hosts_path=pins, host=HOST, port=PORT))
    options = shlex.split(_trust_extra_vars(_recorded(recorder)["argv"])["ansible_ssh_args"])

    resolved = subprocess.run(
        ["ssh", "-G", "-F", "/dev/null", *options, "-p", str(PORT), HOST],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert "stricthostkeychecking true" in resolved
    assert f"userknownhostsfile {pins}" in resolved
    assert "globalknownhostsfile /dev/null" in resolved


def test_hashed_pins_are_recognised(tmp_path, recorder):
    pins = tmp_path / "known_hosts"
    pins.write_text(_pin_line(tmp_path, f"[{HOST}]:{PORT}"), encoding="utf-8")
    subprocess.run(["ssh-keygen", "-q", "-H", "-f", str(pins)], check=True)

    _spawn(tmp_path, SshHostTrust(known_hosts_path=pins, host=HOST, port=PORT))

    assert _recorded(recorder)["env"]["ANSIBLE_HOST_KEY_CHECKING"] == "True"


def test_default_port_pins_use_the_bare_host_form(tmp_path, recorder):
    pins = tmp_path / "known_hosts"
    pins.write_text(_pin_line(tmp_path, HOST), encoding="utf-8")

    _spawn(tmp_path, SshHostTrust(known_hosts_path=pins, host=HOST, port=22))

    assert _recorded(recorder)["env"]["ANSIBLE_HOST_KEY_CHECKING"] == "True"


def test_spawn_without_trust_adds_no_trust_arguments(tmp_path, recorder):
    """VM playbooks are not the managed bare-metal profile and are unchanged."""
    _spawn(tmp_path, None)

    spawned = _recorded(recorder)
    assert spawned["env"] == {"ANSIBLE_HOST_KEY_CHECKING": None, "ANSIBLE_SSH_ARGS": None}
    assert "ansible_ssh_args" not in " ".join(spawned["argv"])


@pytest.mark.parametrize(
    "case",
    ["unset", "missing-file", "empty-file", "other-port", "other-host"],
)
def test_absent_or_mismatched_trust_refuses_before_spawning(tmp_path, recorder, case):
    pins = tmp_path / "known_hosts"
    if case == "unset":
        pins = None
    elif case == "empty-file":
        pins.write_text("", encoding="utf-8")
    elif case == "other-port":
        pins.write_text(_pin_line(tmp_path, HOST), encoding="utf-8")
    elif case == "other-host":
        pins.write_text(_pin_line(tmp_path, f"[192.0.2.99]:{PORT}"), encoding="utf-8")

    with pytest.raises(HostTrustError):
        AnsibleService(MagicMock()).start_playbook(
            playbook_path=tmp_path / "playbook.yaml",
            inventory_path=tmp_path / "inventory.ini",
            extra_vars_path=tmp_path / "vars.yml",
            limit="bm1",
            host_trust=SshHostTrust(known_hosts_path=pins, host=HOST, port=PORT),
        )

    assert not recorder.exists(), "ansible-playbook must not start without trust"
