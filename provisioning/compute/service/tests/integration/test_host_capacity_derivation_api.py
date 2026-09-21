"""Capacity derived where INI inventory enters, through the canonical clients.

``POST /api/v1/hosts/import`` applies INI hosts and derives declarations for
their legacy capacity in the same transaction. ``POST /api/v1/hosts`` is
administration of connection identity and derives nothing. Every call goes
through ``ProvisioningClient``, and every read of capacity through
``SiteCapacityAdminClient``.
"""

from __future__ import annotations

import pytest
from vm_provisioning_operator.models import HostCreate

from compute_provisioning_service import container as _container_module

from .test_capacity_api import CapacityApi, capacity  # noqa: F401

_INI = (
    "[kvm_hosts]\n"
    "kvm1  ansible_host=10.0.0.1  ansible_user=ubuntu  "
    "ansible_ssh_private_key_file=/keys/id  gpus=4  gpu_model=H200\n"
    "kvm2  ansible_host=10.0.0.2  ansible_user=ubuntu  "
    "ansible_ssh_private_key_file=/keys/id\n"
)


async def _resources(capacity: CapacityApi) -> dict[str, dict]:
    return {row["resource_id"]: row for row in await capacity.admin.list_resources()}


async def test_an_ini_import_declares_capacity_for_hosts_with_gpus(
    client_and_queue, capacity: CapacityApi
):
    client, _ = client_and_queue

    await client.import_hosts_from_text(_INI, ssh_key_type="path")

    resources = await _resources(capacity)
    assert set(resources) == {"kvm1"}
    assert resources["kvm1"]["host_id"] == "kvm1"
    assert resources["kvm1"]["capacity"] == {"gpu_count": 4}
    assert resources["kvm1"]["attributes"] == {"gpu_model": "H200"}


async def test_a_reimport_with_changed_gpus_leaves_the_declaration(
    client_and_queue, capacity: CapacityApi
):
    """Once a declaration names the host, INI values stop affecting capacity."""
    client, _ = client_and_queue
    await client.import_hosts_from_text(_INI, ssh_key_type="path")

    await client.import_hosts_from_text(
        _INI.replace("gpus=4", "gpus=8"), ssh_key_type="path"
    )

    assert (await _resources(capacity))["kvm1"]["capacity"] == {"gpu_count": 4}


async def test_registering_a_host_through_the_api_derives_nothing(
    client_and_queue, capacity: CapacityApi
):
    client, _ = client_and_queue

    await client.register_host(HostCreate(
        host_id="kvm1", ssh_host="10.0.0.1", ssh_user="ubuntu",
        ssh_key_value="/keys/id", gpu_count=4,
    ))

    assert await _resources(capacity) == {}


async def test_a_failure_before_the_derivation_commits_leaves_neither(
    client_and_queue, capacity: CapacityApi, monkeypatch
):
    """The upsert and the derivation are one transaction."""
    client, _ = client_and_queue
    derivation = _container_module.resolved_host_service._capacity_derivation
    derive = derivation.derive_in_session

    def derive_then_fail(db, host_ids=None):
        derive(db, host_ids)
        raise RuntimeError("injected after derivation, before commit")

    monkeypatch.setattr(derivation, "derive_in_session", derive_then_fail)

    # The in-process transport re-raises the server's exception rather than
    # answering 500; what matters is the state it leaves.
    with pytest.raises(RuntimeError, match="injected"):
        await client.import_hosts_from_text(_INI, ssh_key_type="path")

    assert (await client.list_hosts(include_disabled=True)).hosts == []
    assert await _resources(capacity) == {}
