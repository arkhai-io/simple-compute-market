"""A fresh site seeded from the packaged seed document, through the typed clients.

The harness here stores no pool, as migration leaves a fresh database, and the
service's own seed step runs over the harness's pool service with the packaged
`pool_seed_path`. The seeded pools are ordinary and usable at once. Registering
a host, placed in one or unplaced, declares none of its capacity: only capacity
an operator declares is admitted.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from compute_provisioning_ansible import ssh_connection
from compute_provisioning_contracts import HostCreate

from compute_provisioning_service import app_runtime
from compute_provisioning_service.config import settings as service_settings
from compute_provisioning_service.db.database import create_db_engine

from .conftest import _initialize_test_database
from .test_capacity_api import CapacityApi, capacity  # noqa: F401


@pytest.fixture
def db_engine(tmp_path):
    """A fresh site's database: every table, and no pool."""
    engine = create_db_engine(f"sqlite:///{tmp_path / 'provisioning.db'}", is_sqlite=True)
    try:
        _initialize_test_database(engine, default_pool=False)
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def seeded(client_and_queue, monkeypatch):
    """Run the service's seed step as a fresh start with no pool document does."""
    client, _ = client_and_queue
    monkeypatch.setattr(app_runtime, "settings", SimpleNamespace(
        resolved_pool_definitions_path=None,
        resolved_pool_seed_path=service_settings.resolved_pool_seed_path,
    ))
    app_runtime.seed_initial_pools_if_fresh()
    return client


def _host(host_id: str, pool_id: str | None) -> HostCreate:
    return HostCreate(
        host_id=host_id,
        connection=ssh_connection(ssh_host="10.0.0.1", ssh_user="ubuntu", key_path="/keys/id"),
        gpu_count=4,
        gpu_model="H200",
        pool_id=pool_id,
    )


async def _projected(capacity: CapacityApi) -> dict[str, list[str]]:
    projection = await capacity.site.resource_pool_projection()
    return {
        pool["pool_id"]: sorted(resource["physical_resource_id"] for resource in pool["resources"])
        for pool in projection["resource_pools"]
    }


async def test_the_seeded_pools_list_through_the_pool_client(seeded):
    pools = {pool.id: pool for pool in (await seeded.pools.list_pools()).pools}

    assert sorted(pools) == ["bare-metal-default", "vm-default"]
    assert pools["vm-default"].provider == "vm.ansible"
    assert pools["bare-metal-default"].provider == "bare_metal.ansible"
    assert all(pool.enabled for pool in pools.values())


async def test_a_host_and_capacity_declared_into_the_vm_pool_are_admitted(
    seeded, capacity: CapacityApi,
):
    host = await seeded.family.register_host(_host("kvm1", "vm-default"))
    assert host.pool_id == "vm-default"
    # Placed, and selling nothing until capacity is declared.
    assert await capacity.admin.list_resources() == []

    await capacity.register(
        "kvm1-gpus", pool_id="vm-default", total_units=4, host_id="kvm1",
        attributes={"gpu_model": "H200"},
    )
    reservation = await capacity.reserve(
        {"offering_mode": "vm", "gpu_count": 1}, {"escrow_uid": "escrow-seeded-1"},
    )

    assert reservation is not None
    assert (await _projected(capacity))["vm-default"] == ["kvm1-gpus"]


async def test_a_host_registered_without_a_pool_declares_no_capacity(
    seeded, capacity: CapacityApi,
):
    host = await seeded.family.register_host(_host("kvm2", None))

    assert host.pool_id is None
    assert await capacity.admin.list_resources() == []
    assert await capacity.reserve(
        {"offering_mode": "vm", "gpu_count": 1}, {"escrow_uid": "escrow-unplaced-1"},
    ) is None
