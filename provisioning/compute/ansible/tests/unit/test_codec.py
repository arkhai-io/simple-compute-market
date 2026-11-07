"""Rendering a plan's variables into the playbook's extra-vars file."""

from __future__ import annotations

import shutil
import stat
import subprocess

import pytest
import yaml

from compute_provisioning.relays.variables import RELAY_JOB_RESERVED_VARIABLES
from compute_provisioning_ansible import AnsibleJobPlan, render_extra_vars, write_extra_vars


def test_every_value_reads_back_as_the_value_it_was() -> None:
    variables = {
        "host_id": "007",
        "password": 'with: colon and "quotes"',
        "count": 4,
        "enabled": False,
        "devices": ["0000:03:00.0"],
        "ref": {"physical_host_id": "p-1"},
    }

    assert yaml.safe_load(render_extra_vars(variables)) == variables


def test_extra_variables_follow_the_jobs_own_in_name_order() -> None:
    rendered = render_extra_vars({"host_id": "h"}, {"zone": "b", "region": "eu"})

    assert rendered.splitlines() == ['host_id: "h"', 'region: "eu"', 'zone: "b"']


def test_an_extra_variable_may_not_replace_one_of_the_jobs_own() -> None:
    with pytest.raises(ValueError, match="host_id"):
        render_extra_vars({"host_id": "h"}, {"host_id": "elsewhere"})


def test_the_variables_file_is_created_owner_only() -> None:
    path = write_extra_vars(AnsibleJobPlan(variables={"secret": "s"}, limit="h"))
    try:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert yaml.safe_load(path.read_text()) == {"secret": "s"}
    finally:
        path.unlink()


@pytest.mark.parametrize("key", sorted(RELAY_JOB_RESERVED_VARIABLES))
def test_role_control_inputs_are_reserved_even_when_no_relay_variables_are_emitted(key):
    with pytest.raises(ValueError, match=key):
        render_extra_vars({"host_id": "fixture-host"}, {key: "synthetic-other"})


def test_unrelated_options_do_not_require_a_prefix_ban():
    assert yaml.safe_load(render_extra_vars({}, {"relay_operator_note": "fixture"})) == {
        "relay_operator_note": "fixture"
    }


@pytest.mark.skipif(shutil.which("ansible-playbook") is None, reason="requires real Ansible")
@pytest.mark.parametrize("domain,prefix,local_ip", [("vm", "vm", "192.0.2.10"), ("bare_metal", "bm", "127.0.0.1")])
@pytest.mark.parametrize("action", ["add", "remove"])
def test_accepted_extra_vars_preserve_include_role_authority(tmp_path, domain, prefix, local_ip, action):
    # Public deterministic fixtures only; never use them on a public network.
    role_vars = {
        "relay_proxy_action": action, "relay_proxy_name": f"{prefix}-guest-example",
        "relay_proxy_local_ip": local_ip, "relay_proxy_local_port": 22,
        "relay_proxy_remote_port": 22001,
    }
    for key in role_vars:
        with pytest.raises(ValueError, match=key):
            render_extra_vars({"offering_mode": domain}, {key: "synthetic-other"})
    # Execute a harmless role at the actual Ansible precedence boundary. The
    # assertion observes inputs only; no proxy, file or network is modified.
    role = tmp_path / "roles" / "authority-probe" / "tasks"
    role.mkdir(parents=True)
    (role / "main.yml").write_text(yaml.safe_dump([{
        "ansible.builtin.assert": {"that": [
            f"{key} == {value!r}" for key, value in role_vars.items()
        ] + ["region == 'fixture-region'"]}
    }]))
    play = tmp_path / "play.yml"
    play.write_text(yaml.safe_dump([{
        "hosts": "localhost", "gather_facts": False,
        "tasks": [{"ansible.builtin.include_role": {"name": "authority-probe"}, "vars": role_vars}],
    }]))
    extras = tmp_path / "extras.yml"
    extras.write_text(render_extra_vars({"offering_mode": domain}, {"region": "fixture-region"}))
    result = subprocess.run([
        "ansible-playbook", "-i", "localhost,", "-c", "local", str(play), "-e", f"@{extras}",
    ], cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
