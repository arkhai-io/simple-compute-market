"""Which SSH host trust the job service asks the spawner to enforce."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from vm_provisioning_adapter.services.ansible_service import (
    AnsibleService,
    HostTrustError,
    SshHostTrust,
)
from vm_provisioning_adapter.services.job_service import AnsibleJobService

PINS = Path("/pins/known_hosts")
HOST = SimpleNamespace(kvm_host="192.0.2.20", ssh_port=6001, public_host="198.51.100.20", public_port=22)


def _service() -> AnsibleJobService:
    settings = MagicMock()
    settings.bare_metal_ssh_known_hosts_path = PINS
    return AnsibleJobService(
        settings=settings,
        session_factory=MagicMock(),
        ansible_service=MagicMock(),
    )


def _params(service: AnsibleJobService, **overrides):
    return service._build_params({"vm_host": "bm1", **overrides})


def test_bare_metal_jobs_pin_the_management_endpoint():
    service = _service()
    params = _params(service, vm_action="node_grant_access", offering_mode="bare_metal")

    assert service._ssh_host_trust(params, HOST) == SshHostTrust(
        known_hosts_path=PINS, host="192.0.2.20", port=6001,
    )


def test_vm_jobs_carry_no_host_trust():
    service = _service()
    params = _params(service, vm_action="create", offering_mode="vm")

    assert service._ssh_host_trust(params, HOST) is None


def test_bare_metal_job_without_a_registered_host_fails_closed(tmp_path):
    service = _service()
    params = _params(service, vm_action="node_reclaim_access", offering_mode="bare_metal")
    trust = service._ssh_host_trust(params, None)

    assert trust is not None and trust.host is None
    with pytest.raises(HostTrustError):
        AnsibleService(MagicMock()).start_playbook(
            playbook_path=tmp_path / "playbook.yaml",
            inventory_path=tmp_path / "inventory.ini",
            extra_vars_path=tmp_path / "vars.yml",
            limit="bm1",
            host_trust=trust,
        )
