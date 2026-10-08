"""Rendering a plan's variables into the playbook's extra-vars file."""

from __future__ import annotations

import stat

import pytest
import yaml

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
