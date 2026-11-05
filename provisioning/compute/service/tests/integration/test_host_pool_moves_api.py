"""Moving a host between pools, over the real API, through the canonical clients.

A host's pool changes through an update or through an imported inventory, and
both go through the pool-change hooks the composition contributes, unplacing a
host included. The relays' hook refuses moving a host to a pool that dials
another relay, or to no pool, while a tunnel is bound through the host, because
the buyer holds that relay's address and port; a move between pools on one
relay is free, whichever provider each uses.
These tests prove the refusal survives each route as a 409 that leaves the host
where it was, and that the move goes through once the host is drained.

The bound tunnel is seeded as a port-lease row: fulfillment is the only route
that takes one, and driving a whole fulfillment here would test fulfillment, not
the move.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from compute_provisioning_ansible import ssh_connection
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import HostCreate, HostUpdate, RelayCreate, RelayUpdate
from market_resource_pools_contracts import PoolCreate, PoolUpdate

from compute_provisioning_service import container as _container_module
from compute_provisioning.relays import RelayPortLease

_RELAY_POOL = "relay-pool"
_PLAIN_POOL = "plain-pool"


def _inventory(pool_id: str, address: str = "10.0.0.1") -> str:
    return (
        "[kvm_hosts]\n"
        f"kvm1  ansible_host={address}  ansible_user=ubuntu  "
        f"ansible_ssh_private_key_file=/keys/id  pool_id={pool_id}\n"
    )


async def _relay_and_pools(clients) -> None:
    await clients.family.create_relay(
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
                provider="vm.ansible",
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


async def test_an_inventory_unplacing_a_tunnelled_host_is_refused_whole(client_and_queue):
    """Unplacing is a move: the host would stop dialling its relay, so the
    relays' hook refuses it, and the import's other entries are not applied
    either."""
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    await clients.host_import.import_hosts_from_text(_inventory(_RELAY_POOL))
    _bind_tunnel()

    # The new host comes first, so it is applied before the refusal and only
    # the rollback can take it away.
    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.host_import.import_hosts_from_text(
            "[kvm_hosts]\n"
            "kvm2  ansible_host=10.0.0.2  ansible_user=ubuntu  "
            "ansible_ssh_private_key_file=/keys/id\n"
            + _inventory("", address="10.0.0.99").removeprefix("[kvm_hosts]\n")
        )

    assert refused.value.status_code == 409
    assert "kvm1:6100" in str(refused.value)
    host = await clients.family.get_host("kvm1")
    assert (host.pool_id, host.connection.public["ssh_host"]) == (_RELAY_POOL, "10.0.0.1")
    with pytest.raises(ComputeProvisioningError) as missing:
        await clients.family.get_host("kvm2")
    assert missing.value.status_code == 404


async def test_an_update_unplacing_a_tunnelled_host_is_refused(client_and_queue):
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    await clients.host_import.import_hosts_from_text(_inventory(_RELAY_POOL))
    _bind_tunnel()

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.family.update_host("kvm1", HostUpdate(pool_id=None))

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


async def test_a_tunnelled_host_moves_to_a_bare_metal_pool_on_its_relay(client_and_queue):
    """The pools' providers differ and the relay is the same, so no delivered
    connection string moves and the move is accepted while the tunnel is bound."""
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    await clients.pools.create_pool(
        PoolCreate(
            id="bare-metal-relay-pool",
            label="bare-metal-relay-pool",
            provider="bare_metal.ansible",
            policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
            provider_config={"relay_id": "site-a"},
        )
    )
    await clients.host_import.import_hosts_from_text(_inventory(_RELAY_POOL))
    _bind_tunnel()

    moved = await clients.family.update_host("kvm1", HostUpdate(pool_id="bare-metal-relay-pool"))

    assert moved.pool_id == "bare-metal-relay-pool"


async def test_a_host_reached_at_its_pools_relay_address_is_not_placed(client_and_queue):
    """Management proxies carry no grant, so a host reached through its pool's
    buyer relay would be refused by that relay: each way of placing it is
    refused, naming the host and the relay, and leaves it where it was."""
    clients, _ = client_and_queue
    await _relay_and_pools(clients)

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.family.register_host(
            HostCreate(
                host_id="kvm-relayed",
                connection=ssh_connection(ssh_host="203.0.113.9", key_path="/keys/id"),
                pool_id=_RELAY_POOL,
            )
        )
    assert refused.value.status_code == 409
    assert "kvm-relayed" in str(refused.value) and "site-a" in str(refused.value)
    assert await _absent(clients, "kvm-relayed")

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.host_import.import_hosts_from_text(
            _inventory(_RELAY_POOL, address="203.0.113.9")
        )
    assert refused.value.status_code == 409
    assert "kvm1" in str(refused.value) and "site-a" in str(refused.value)
    assert await _absent(clients, "kvm1")

    await clients.host_import.import_hosts_from_text(
        _inventory(_PLAIN_POOL, address="203.0.113.9")
    )
    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.family.update_host("kvm1", HostUpdate(pool_id=_RELAY_POOL))
    assert refused.value.status_code == 409
    assert "kvm1" in str(refused.value) and "site-a" in str(refused.value)
    assert (await clients.family.get_host("kvm1")).pool_id == _PLAIN_POOL


async def test_a_relay_is_not_moved_onto_a_placed_hosts_address(client_and_queue):
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    await clients.host_import.import_hosts_from_text(_inventory(_RELAY_POOL, address="10.0.0.1"))

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.family.update_relay("site-a", RelayUpdate(relay_addr="10.0.0.1"))

    assert refused.value.status_code == 409
    assert "kvm1" in str(refused.value) and "site-a" in str(refused.value)
    assert (await clients.family.get_relay("site-a")).relay_addr == "203.0.113.9"


async def test_a_placed_hosts_connection_is_not_moved_onto_its_pools_relay(client_and_queue):
    """A host already in a relay-backed pool loses its management route as
    surely by a connection edit as by a move: an update and an inventory
    giving it the relay's address are each refused, naming the host and the
    relay, and it keeps its previous connection."""
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    await clients.host_import.import_hosts_from_text(_inventory(_RELAY_POOL, address="10.0.0.1"))

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.family.update_host(
            "kvm1",
            HostUpdate(connection=ssh_connection(ssh_host="203.0.113.9", key_path="/keys/id")),
        )
    assert refused.value.status_code == 409
    assert "kvm1" in str(refused.value) and "site-a" in str(refused.value)

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.host_import.import_hosts_from_text(
            _inventory(_RELAY_POOL, address="203.0.113.9")
        )
    assert refused.value.status_code == 409
    assert "kvm1" in str(refused.value) and "site-a" in str(refused.value)

    host = await clients.family.get_host("kvm1")
    assert (host.pool_id, host.connection.public["ssh_host"]) == (_RELAY_POOL, "10.0.0.1")


async def test_a_host_in_a_pool_without_a_relay_takes_the_relays_address(client_and_queue):
    """The rule constrains a host in the relay's pools only: a host in a pool
    with no relay may be managed through that relay's address."""
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    await clients.host_import.import_hosts_from_text(_inventory(_PLAIN_POOL, address="10.0.0.1"))

    updated = await clients.family.update_host(
        "kvm1",
        HostUpdate(connection=ssh_connection(ssh_host="203.0.113.9", key_path="/keys/id")),
    )

    assert (updated.pool_id, updated.connection.public["ssh_host"]) == (
        _PLAIN_POOL,
        "203.0.113.9",
    )


async def test_a_pool_is_not_pointed_at_the_relay_its_host_is_managed_through(
    client_and_queue,
):
    """Pointing a pool at a relay checks the hosts it already holds, for both
    providers: each write is refused, naming the host and the relay, and the
    pool keeps its previous relay reference."""
    clients, _ = client_and_queue
    await _relay_and_pools(clients)
    await clients.pools.create_pool(
        PoolCreate(
            id="bare-metal-pool",
            label="bare-metal-pool",
            provider="bare_metal.ansible",
            policy_tags={"advertisable_modes": [], "capacity_backing": "backed"},
            provider_config={},
        )
    )
    await clients.host_import.import_hosts_from_text(
        "[kvm_hosts]\n"
        "kvm1  ansible_host=203.0.113.9  ansible_user=ubuntu  "
        f"ansible_ssh_private_key_file=/keys/id  pool_id={_PLAIN_POOL}\n"
        "bm1  ansible_host=203.0.113.9  ansible_user=ubuntu  "
        "ansible_ssh_private_key_file=/keys/id  pool_id=bare-metal-pool\n"
    )

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.pools.patch_pool(
            _PLAIN_POOL,
            PoolUpdate(
                provider_config={
                    "playbook_path": "playbooks/vm-operations.yaml",
                    "relay_id": "site-a",
                }
            ),
        )
    assert refused.value.status_code == 409
    assert "kvm1" in str(refused.value) and "site-a" in str(refused.value)
    assert (await clients.pools.get_pool(_PLAIN_POOL)).provider_config.get("relay_id") is None

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.pools.patch_pool(
            "bare-metal-pool", PoolUpdate(provider_config={"relay_id": "site-a"})
        )
    assert refused.value.status_code == 409
    assert "bm1" in str(refused.value) and "site-a" in str(refused.value)
    assert (await clients.pools.get_pool("bare-metal-pool")).provider_config == {}


async def _absent(clients, host_id: str) -> bool:
    try:
        await clients.family.get_host(host_id)
    except ComputeProvisioningError as missing:
        return missing.status_code == 404
    return False
