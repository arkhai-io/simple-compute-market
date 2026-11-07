"""The Ansible configuration the service exports for every playbook it runs.

The profile's ``ansible_cfg`` is passed through verbatim, so an operator's own
configuration, a log file included, is never overridden; without one the
packaged configuration applies. The service never sets a log path itself.
Settings and the environment are handed in, so no process state is touched.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from compute_provisioning_ansible import DEFAULT_ANSIBLE_CONFIG

from compute_provisioning_service.app_runtime import apply_ansible_config


def test_an_operators_configuration_is_exported_verbatim(tmp_path) -> None:
    operator_config = tmp_path / "operator.cfg"
    operator_config.write_text("[defaults]\nlog_path = /var/log/ansible.log\n", encoding="utf-8")
    environ: dict[str, str] = {}

    apply_ansible_config(SimpleNamespace(ansible_cfg=str(operator_config)), environ)

    assert environ == {"ANSIBLE_CONFIG": str(operator_config)}


@pytest.mark.parametrize(
    "config",
    [
        SimpleNamespace(ansible_cfg=""),
        SimpleNamespace(ansible_cfg="   "),
        SimpleNamespace(ansible_cfg=None),
        SimpleNamespace(),
    ],
    ids=["empty", "blank", "null", "absent"],
)
def test_without_one_the_packaged_configuration_is_exported(config) -> None:
    environ: dict[str, str] = {}

    apply_ansible_config(config, environ)

    assert environ == {"ANSIBLE_CONFIG": str(DEFAULT_ANSIBLE_CONFIG)}
