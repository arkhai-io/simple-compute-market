"""A bare-metal access job reaches the spawner with its host's pinned endpoint.

The job runs through the real operations service, job queue and job service;
only the Ansible subprocess boundary is the controlled ``fake_ansible``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from arkhai_bare_metal import BareMetalLeaseCreate, canonical_lease_account
from compute_provisioning_service import container as _container_module
from vm_provisioning_adapter.services.ansible_service import HostTrustError
from vm_provisioning_operator import ProvisioningJobError
from vm_provisioning_operator.models import HostCreate


async def _grant(name: str, escrow: str) -> str:
    _container_module.resolved_host_service.register_host(HostCreate(
        name=name,
        kvm_host="192.0.2.20",
        ssh_port=6001,
        public_host="198.51.100.20",
        public_port=22,
        ssh_user="root",
        ssh_key_type="path",
        ssh_key_value="/fake/id_ed25519",
    ))
    submitted = await _container_module.resolved_bare_metal_operations_service.grant_access(
        BareMetalLeaseCreate(
            escrow_uid=escrow,
            machine_id=name,
            physical_host_id=f"host-{name}",
            lease_end_utc=datetime.now(timezone.utc) + timedelta(hours=2),
            access_ref={
                "ssh_user": canonical_lease_account(escrow),
                "ssh_public_key": "ssh-ed25519 AAAA test",
            },
        ),
    )
    return submitted.job_id


async def test_bare_metal_grant_is_spawned_with_the_management_endpoint(
    client_and_queue, fake_ansible,
):
    client, _ = client_and_queue
    job_id = await _grant("bm-trust-1", "escrow-trust-1")
    try:
        await client.poll_until_complete(job_id, timeout=5.0, poll_interval=0.05)
    except ProvisioningJobError:
        pass  # the job outcome is not under test; how it was spawned is

    host_trust = fake_ansible.start_playbook.call_args.kwargs["host_trust"]
    # Trust pins the endpoint the provisioner connects to, never the buyer's.
    assert (host_trust.host, host_trust.port) == ("192.0.2.20", 6001)


async def test_refused_host_trust_fails_the_job_without_running_a_playbook(
    client_and_queue, fake_ansible,
):
    client, _ = client_and_queue
    fake_ansible.start_playbook.side_effect = HostTrustError(
        "no pinned host key for the bare-metal management endpoint"
    )
    job_id = await _grant("bm-trust-2", "escrow-trust-2")

    with pytest.raises(ProvisioningJobError):
        await client.poll_until_complete(job_id, timeout=5.0, poll_interval=0.05)

    job = await client.get_job(job_id)
    assert job.status == "failed"
    assert "host trust" in (job.error or "")
    fake_ansible.wait_for_playbook.assert_not_called()
