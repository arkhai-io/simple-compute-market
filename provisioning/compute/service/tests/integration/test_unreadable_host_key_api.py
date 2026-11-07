"""A host whose protected key cannot be decrypted, through the canonical client.

A protected key that does not decrypt under the service's configured key is
named wherever it is used: the job fails with the reason and is not retried,
the connectivity check answers the host unreachable with it, and system status
reports the ``ansible`` component not ready naming the host, while another
host's key is reported as it is. A connectivity check's own output is returned
redacted.

Each unreadable host is seeded directly, as setup, because the API protects
every key it is given under the configured key and so cannot store one
protected under another; the version-1 host is seeded directly because the
API registers only the version it serves. Every key here is generated for the
test or is the suite's development key, and the private key is a placeholder;
none is ever used on a network.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from compute_provisioning.hosts import ConnectionEnvelope, ProtectedValue
from compute_provisioning.hosts.db import Host
from compute_provisioning_ansible import SshConnectionCodec, ssh_connection
from compute_provisioning_ansible.readiness import ANSIBLE_COMPONENT, AnsibleReadinessDetail
from compute_provisioning_ansible.runner import AnsibleRunner
from compute_provisioning_client import ComputeProvisioningJobError
from compute_provisioning_contracts import HostCreate, SystemStatusResponse
from cryptography.fernet import Fernet
from market_config import encrypt_secret
from vm_provisioning_operator.models import CreateVmRequest

from .conftest import TEST_CONNECTION_KEY

_PEM = "-----BEGIN OPENSSH PRIVATE KEY-----\nunreadable-fixture\n-----END OPENSSH PRIVATE KEY-----\n"
_PUBLIC = {
    "ssh_host": "198.51.100.20",
    "public_host": None,
    "ssh_port": 22,
    "ssh_user": "ops",
    "key_path": None,
}


def _seed(session_factory, host_id: str, *, key: str, version: int = 2) -> str:
    """Store an enabled host whose private key is protected under ``key``;
    return its ciphertext."""
    ciphertext = encrypt_secret(_PEM, key)
    host = Host(host_id=host_id, enabled=True)
    host.set_connection(
        ConnectionEnvelope(
            kind="ssh",
            version=version,
            public=dict(_PUBLIC),
            protected={"private_key": ProtectedValue("fernet-v1", ciphertext)},
        )
    )
    with session_factory() as db:
        db.add(host)
        db.commit()
    return ciphertext


def _rendered_by_a_real_runner(fake_ansible) -> None:
    """Inventories are rendered by a real runner holding the suite's key, so a
    key that does not decrypt under it fails as it would in production."""
    renderer = AnsibleRunner(SimpleNamespace(), ssh_codec=SshConnectionCodec(TEST_CONNECTION_KEY))
    fake_ansible.write_inventory.side_effect = renderer.write_inventory


def _unreadable(host_id: str) -> str:
    """The message the service names a key protected under another key with."""
    return (
        f"host {host_id!r}: its protected private key cannot be decrypted under the "
        "configured ssh_decryption_key; restore the ssh_decryption_key it was "
        "protected under, or submit the host's private key again"
    )


async def _ansible(client) -> tuple[AnsibleReadinessDetail, SystemStatusResponse]:
    """The ``ansible`` component's detail, and the whole status it came in."""
    status = await client.family.get_system_status()
    component = status.component(ANSIBLE_COMPONENT)
    assert component is not None and component.ready is False
    return AnsibleReadinessDetail.model_validate(component.detail.payload), status


class TestAKeyProtectedUnderAnotherKey:
    async def test_a_job_against_it_fails_unretried_naming_the_host(
        self, client_and_queue, fake_ansible, session_factory
    ):
        client, _ = client_and_queue
        ciphertext = _seed(session_factory, "rotated", key=Fernet.generate_key().decode())
        _rendered_by_a_real_runner(fake_ansible)
        started = fake_ansible.start_playbook.call_count

        submit = await client.vm.create_vm("rotated", CreateVmRequest(vm_target="rotated-vm"))
        with pytest.raises(ComputeProvisioningJobError):
            await client.family.poll_until_complete(submit.job_id, timeout=5.0, poll_interval=0.05)

        job = await client.family.get_job(submit.job_id)
        assert job.status == "failed"
        assert _unreadable("rotated") in job.error
        assert ciphertext not in job.error and "unreadable-fixture" not in job.error
        assert (job.retry_count, job.next_retry_at) == (0, None)
        assert fake_ansible.start_playbook.call_count == started

    async def test_its_connectivity_check_answers_unreachable_with_the_reason(
        self, client_and_queue, fake_ansible, session_factory
    ):
        client, _ = client_and_queue
        ciphertext = _seed(session_factory, "rotated", key=Fernet.generate_key().decode())
        _rendered_by_a_real_runner(fake_ansible)

        result = await client.family.check_connectivity("rotated")

        assert (result.host, result.reachable) == ("rotated", False)
        assert result.detail == _unreadable("rotated")
        assert ciphertext not in result.detail
        fake_ansible.check_connectivity_with_inventory.assert_not_called()

    async def test_status_names_the_host_and_reports_the_other_key_as_it_is(
        self, client_and_queue, session_factory
    ):
        client, _ = client_and_queue
        rotated = _seed(session_factory, "rotated", key=Fernet.generate_key().decode())
        await client.family.register_host(
            HostCreate(host_id="current", connection=ssh_connection(
                ssh_host="198.51.100.21", ssh_user="ops", private_key=_PEM,
            ))
        )
        with session_factory() as db:
            current = db.get(Host, "current").connection_protected["private_key"]["ciphertext"]

        detail, status = await _ansible(client)

        assert _unreadable("rotated") in detail.not_ready_reasons
        assert not any("'current'" in reason for reason in detail.not_ready_reasons)
        keys = {tuple(key.referenced_by): key for key in detail.ssh_keys}
        assert (keys[("rotated",)].key_type, keys[("rotated",)].exists) == ("embedded", False)
        assert (keys[("current",)].key_type, keys[("current",)].exists) == ("embedded", True)
        rendered = status.model_dump_json()
        assert rotated not in rendered and current not in rendered
        assert "unreadable-fixture" not in rendered


async def test_status_names_a_host_stored_at_version_1_and_the_version_served(
    client_and_queue, session_factory
):
    client, _ = client_and_queue
    _seed(session_factory, "legacy", key=TEST_CONNECTION_KEY, version=1)

    detail, _ = await _ansible(client)

    (reason,) = [reason for reason in detail.not_ready_reasons if "'legacy'" in reason]
    assert reason.startswith("host 'legacy' cannot be executed against: ")
    assert "at version 2" in reason and "'ssh' at 1" in reason
    assert not any(key.referenced_by == ["legacy"] for key in detail.ssh_keys)


async def test_a_connectivity_checks_output_is_returned_redacted(
    client_and_queue, fake_ansible, tmp_path, monkeypatch
):
    """A real runner checks the host, through a stand-in ``ansible`` placed first
    on ``PATH`` that prints a credential-shaped value, a fixture never used
    anywhere."""
    client, _ = client_and_queue
    await client.family.register_host(
        HostCreate(host_id="probed", connection=ssh_connection(
            ssh_host="198.51.100.22", ssh_user="ops", key_path="/home/appuser/.ssh/id_ed25519",
        ))
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stand_in = bin_dir / "ansible"
    stand_in.write_text(
        '#!/bin/sh\necho "probed | SUCCESS"\necho "password: hunter2"\nexit 0\n', encoding="utf-8"
    )
    stand_in.chmod(0o700)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    runner = AnsibleRunner(
        SimpleNamespace(ansible_timeout_seconds=10),
        ssh_codec=SshConnectionCodec(TEST_CONNECTION_KEY),
    )
    fake_ansible.write_inventory.side_effect = runner.write_inventory
    fake_ansible.check_connectivity_with_inventory.side_effect = (
        runner.check_connectivity_with_inventory
    )

    result = await client.family.check_connectivity("probed")

    assert (result.host, result.reachable) == ("probed", True)
    assert "probed | SUCCESS" in result.detail
    assert "hunter2" not in result.detail
    assert "password: [REDACTED]" in result.detail
