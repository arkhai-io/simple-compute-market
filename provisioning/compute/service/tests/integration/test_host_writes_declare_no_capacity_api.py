"""No host write declares capacity, through the canonical clients.

A host's GPU count and model describe it and sell nothing: neither an INI
import through ``POST /api/v1/hosts/import``, nor the startup inventory seed,
nor a create or update through the individual host API creates a capacity
declaration, whatever pool the host is placed in. Capacity reads go through
``SiteCapacityAdminClient`` and the resource-pool projection through
``SiteCapacityClient``.
"""

from __future__ import annotations

from types import SimpleNamespace

from compute_provisioning_ansible import ssh_connection
from compute_provisioning_contracts import HostCreate, HostUpdate

from compute_provisioning_service import app_runtime

from .test_capacity_api import CapacityApi, capacity  # noqa: F401

_INI = (
    "[kvm_hosts]\n"
    "kvm1  ansible_host=10.0.0.1  ansible_user=ubuntu  "
    "ansible_ssh_private_key_file=/keys/id  gpus=4  gpu_model=H200  pool_id=default\n"
    "kvm2  ansible_host=10.0.0.2  ansible_user=ubuntu  "
    "ansible_ssh_private_key_file=/keys/id  gpus=8\n"
)


async def _declared(capacity: CapacityApi) -> list[dict]:
    return await capacity.admin.list_resources()


async def _projected(capacity: CapacityApi) -> list[str]:
    projection = await capacity.site.resource_pool_projection()
    return [
        resource["physical_resource_id"]
        for pool in projection["resource_pools"]
        for resource in pool["resources"]
    ]


async def test_an_ini_import_carrying_gpus_declares_nothing(
    client_and_queue, capacity: CapacityApi
):
    client, _ = client_and_queue

    imported = await client.host_import.import_hosts_from_text(_INI, ssh_key_type="path")

    hosts = {host.host_id: host for host in imported.hosts}
    assert (hosts["kvm1"].gpu_count, hosts["kvm1"].gpu_model) == (4, "H200")
    assert (hosts["kvm2"].gpu_count, hosts["kvm2"].gpu_model) == (8, None)
    assert (hosts["kvm1"].pool_id, hosts["kvm2"].pool_id) == ("default", None)
    assert await _declared(capacity) == []
    assert await _projected(capacity) == []


async def test_the_startup_inventory_seed_declares_nothing(
    client_and_queue, capacity: CapacityApi, monkeypatch
):
    """The seed step the service runs at startup, over the harness's host
    authority. The step reads the module's settings object, so the test gives
    it one stating ``inventory_ini``, the setting the Helm chart fills."""
    client, _ = client_and_queue
    monkeypatch.setattr(
        app_runtime,
        "settings",
        SimpleNamespace(inventory_ini=_INI, resolved_inventory_path=None),
    )

    app_runtime.seed_inventory_if_empty()

    listed = await client.family.list_hosts(include_disabled=True)
    assert {host.host_id: host.gpu_count for host in listed.hosts} == {"kvm1": 4, "kvm2": 8}
    assert await _declared(capacity) == []
    assert await _projected(capacity) == []


async def test_creating_or_updating_a_host_through_the_api_declares_nothing(
    client_and_queue, capacity: CapacityApi
):
    client, _ = client_and_queue

    await client.family.register_host(HostCreate(
        host_id="kvm1",
        connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", key_path="/keys/id"),
        gpu_count=4,
        pool_id="default",
    ))
    assert await _declared(capacity) == []

    await client.family.update_host("kvm1", HostUpdate(gpu_count=8, gpu_model="H200"))

    assert await _declared(capacity) == []
    assert await _projected(capacity) == []


async def test_a_declared_host_keeps_its_declaration_whatever_its_inventory_says(
    client_and_queue, capacity: CapacityApi
):
    """The operator's declaration is the only statement of what sells: a
    re-import changing the host's GPUs leaves it unchanged."""
    client, _ = client_and_queue
    await client.host_import.import_hosts_from_text(_INI, ssh_key_type="path")
    await capacity.register("kvm1-gpus", pool_id="default", total_units=2, host_id="kvm1")

    await client.host_import.import_hosts_from_text(
        _INI.replace("gpus=4", "gpus=8"), ssh_key_type="path"
    )

    (declared,) = await _declared(capacity)
    assert (declared["resource_id"], declared["capacity"]) == ("kvm1-gpus", {"gpu_count": 2})
    assert (await client.family.get_host("kvm1")).gpu_count == 8
