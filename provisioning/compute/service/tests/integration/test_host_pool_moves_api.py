"""Moving a host between pools, over the real API, through the canonical clients.

A host's pool changes through an update or through an imported inventory, and
both go through the pool-change hooks the composition contributes. VM's hook
refuses moving a host to a pool that dials another relay while a VM tunnel is
bound through the host, because the buyer holds that relay's address and port.
These tests prove the refusal survives each route as a 409 that leaves the host
where it was, and that the move goes through once the host is drained.

The bound tunnel is seeded as a port-lease row: fulfillment is the only route
that takes one, and driving a whole fulfillment here would test fulfillment, not
the move.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import HostUpdate
from market_resource_pools_contracts import PoolCreate
from vm_provisioning_operator.relays import RelayCreate

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.db.models import RelayPortLease

_RELAY_POOL = "relay-pool"
_PLAIN_POOL = "plain-pool"


def _inventory(pool_id: str, address: str = "10.0.0.1") -> str:
    return (
        "[kvm_hosts]\n"
        f"kvm1  ansible_host={address}  ansible_user=ubuntu  "
        f"ansible_ssh_private_key_file=/keys/id  pool_id={pool_id}\n"
    )


async def _relay_and_pools(clients) -> None:
    await clients.vm.create_relay(
        RelayCreate(
            id="site-a",
            relay_addr="203.0.113.9",
            relay_port=7000,
            vm_port_range_start=6100,
            vm_port_range_count=100,
        )
    )
    for pool_id, provider_config in (
        (_RELAY_POOL, {"playbook_path": "playbooks/vm-operations.yaml", "relay_id": "site-a"}),
        (_PLAIN_POOL, {"playbook_path": "playbooks/vm-operations.yaml"}),
    ):
        await clients.pools.create_pool(
            PoolCreate(
                id=pool_id,
                label=pool_id,
                provider="ansible",
                policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
                provider_config=provider_config,
            )
        )


def _bind_tunnel(host_id: str = "kvm1") -> None:
    with _container_module.resolved_session_factory() as db, db.begin():
        db.add(
            RelayPortLease(
                id=f"lease-{host_id}",
                relay_id="site-a",
                remote_port=6100,
                host_id=host_id,
                pool_id=_RELAY_POOL,
                owner_kind="fulfillment",
                owner_id=f"cr-{host_id}",
            )
        )


def _release_tunnels() -> None:
    with _container_module.resolved_session_factory() as db, db.begin():
        for lease in db.query(RelayPortLease).all():
            lease.released_at = datetime.now(timezone.utc)


async def test_an_inventory_moving_a_tunnelled_host_to_another_relay_is_refused(
    client_and_queue,
):
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    await clients.host_import.import_hosts_from_text(_inventory(_RELAY_POOL))
    _bind_tunnel()

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.host_import.import_hosts_from_text(
            _inventory(_PLAIN_POOL, address="10.0.0.99")
        )

    assert refused.value.status_code == 409
    assert "kvm1:6100" in str(refused.value)
    host = await clients.family.get_host("kvm1")
    assert host.pool_id == _RELAY_POOL
    assert host.connection.public["ssh_host"] == "10.0.0.1"


async def test_an_update_moving_a_tunnelled_host_to_another_relay_is_refused(
    client_and_queue,
):
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    await clients.host_import.import_hosts_from_text(_inventory(_RELAY_POOL))
    _bind_tunnel()

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.family.update_host("kvm1", HostUpdate(pool_id=_PLAIN_POOL))

    assert refused.value.status_code == 409
    assert (await clients.family.get_host("kvm1")).pool_id == _RELAY_POOL


async def test_a_drained_host_moves_by_inventory(client_and_queue):
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    await clients.host_import.import_hosts_from_text(_inventory(_RELAY_POOL))
    _bind_tunnel()
    _release_tunnels()

    imported = await clients.host_import.import_hosts_from_text(_inventory(_PLAIN_POOL))

    assert [host.pool_id for host in imported.hosts] == [_PLAIN_POOL]
