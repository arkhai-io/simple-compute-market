"""A bare-metal pool's relay reference, over the real API, through the canonical clients.

Both providers accept ``provider_config.relay_id`` and write it through the
compute family's one reference, so a bare-metal pool's relay reads back as a VM
pool's does and the same rebinding rule refuses changing it while its hosts
hold leases. The bound tunnel is seeded as a port-lease row: fulfillment is the
only route that takes one, and driving a whole fulfillment here would test
fulfillment, not the pool write.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from compute_provisioning.relays import RelayPortLease
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import RelayCreate
from market_resource_pools_contracts import PoolCreate, PoolReplace, PoolUpdate

from compute_provisioning_service import container as _container_module

_POOL = "bare-metal-relay-pool"
_TAGS = {"advertisable_modes": [], "capacity_backing": "backed"}


async def _relays(clients) -> None:
    for relay_id, addr in (("site-a", "203.0.113.9"), ("site-b", "203.0.113.10")):
        await clients.family.create_relay(
            RelayCreate(
                id=relay_id,
                relay_addr=addr,
                relay_port=7000,
                vm_port_range_start=6100,
                vm_port_range_count=100,
            )
        )


async def _bare_metal_pool(clients, provider_config) -> None:
    await clients.pools.create_pool(
        PoolCreate(
            id=_POOL,
            label=_POOL,
            provider="bare_metal.ansible",
            policy_tags=_TAGS,
            provider_config=provider_config,
        )
    )


def _bind_tunnel() -> None:
    with _container_module.resolved_session_factory() as db, db.begin():
        db.add(
            RelayPortLease(
                id="lease-bm-1",
                relay_id="site-a",
                remote_port=6100,
                host_id="bm-1",
                pool_id=_POOL,
                owner_kind="fulfillment",
                owner_id="cr-bm-1",
            )
        )


async def test_a_bare_metal_pool_is_written_with_a_relay(client_and_queue):
    clients, _ = client_and_queue
    await _relays(clients)

    await _bare_metal_pool(clients, {"relay_id": "site-a"})

    assert (await clients.pools.get_pool(_POOL)).provider_config == {"relay_id": "site-a"}


async def test_the_reference_survives_a_write_that_does_not_state_it(client_and_queue):
    clients, _ = client_and_queue
    await _relays(clients)
    await _bare_metal_pool(clients, {"relay_id": "site-a"})

    await clients.pools.patch_pool(_POOL, PoolUpdate(label="renamed"))

    pool = await clients.pools.get_pool(_POOL)
    assert (pool.label, pool.provider_config) == ("renamed", {"relay_id": "site-a"})


async def test_a_bare_metal_pool_accepts_no_other_field(client_and_queue):
    clients, _ = client_and_queue
    await _relays(clients)

    with pytest.raises(ComputeProvisioningError) as refused:
        await _bare_metal_pool(clients, {"relay_id": "site-a", "playbook_path": "x.yaml"})

    assert refused.value.status_code == 400
    assert "playbook_path" in str(refused.value)


async def test_a_pool_naming_no_existing_relay_is_refused(client_and_queue):
    clients, _ = client_and_queue
    await _relays(clients)

    with pytest.raises(ComputeProvisioningError) as refused:
        await _bare_metal_pool(clients, {"relay_id": "never-created"})

    assert refused.value.status_code == 400
    assert "never-created" in str(refused.value)
    with pytest.raises(ComputeProvisioningError):
        await clients.pools.get_pool(_POOL)


async def test_the_execution_read_resolves_the_relay_and_its_token(client_and_queue):
    """What the dispatch path reads: the relay's endpoint and decrypted token,
    which the pool reads above never carry."""
    clients, _ = client_and_queue
    await clients.family.create_relay(
        RelayCreate(
            id="site-a",
            relay_addr="203.0.113.9",
            relay_port=7000,
            vm_port_range_start=6100,
            vm_port_range_count=100,
            token="admission-token",
        )
    )
    await _bare_metal_pool(clients, {"relay_id": "site-a"})

    pools = _container_module.resolved_resource_pool_service
    with _container_module.resolved_session_factory() as db:
        config = pools.get_pool_for_execution(db, _POOL).provider_config

    assert (config["relay_addr"], config["relay_port"]) == ("203.0.113.9", 7000)
    assert config["relay_token"] == "admission-token"
    assert "relay_token" not in (await clients.pools.get_pool(_POOL)).provider_config


async def test_a_relay_change_is_refused_during_a_lease(client_and_queue):
    clients, _ = client_and_queue
    await _relays(clients)
    await _bare_metal_pool(clients, {"relay_id": "site-a"})
    _bind_tunnel()

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.pools.patch_pool(_POOL, PoolUpdate(provider_config={"relay_id": "site-b"}))

    assert refused.value.status_code == 409
    assert "bm-1:6100" in str(refused.value)
    assert (await clients.pools.get_pool(_POOL)).provider_config == {"relay_id": "site-a"}


async def test_a_replacement_dropping_the_relay_is_refused_during_a_lease(client_and_queue):
    """A full replacement that states no relay clears it, which is a change."""
    clients, _ = client_and_queue
    await _relays(clients)
    await _bare_metal_pool(clients, {"relay_id": "site-a"})
    _bind_tunnel()

    with pytest.raises(ComputeProvisioningError) as refused:
        await clients.pools.replace_pool(
            _POOL,
            PoolReplace(
                label=_POOL,
                provider="bare_metal.ansible",
                enabled=True,
                policy_tags=_TAGS,
                provider_config={},
            ),
        )

    assert refused.value.status_code == 409
    assert (await clients.pools.get_pool(_POOL)).provider_config == {"relay_id": "site-a"}


async def test_the_change_is_accepted_once_drained(client_and_queue):
    clients, _ = client_and_queue
    await _relays(clients)
    await _bare_metal_pool(clients, {"relay_id": "site-a"})
    _bind_tunnel()
    with _container_module.resolved_session_factory() as db, db.begin():
        db.query(RelayPortLease).one().released_at = datetime.now(timezone.utc)

    await clients.pools.patch_pool(_POOL, PoolUpdate(provider_config={"relay_id": "site-b"}))

    assert (await clients.pools.get_pool(_POOL)).provider_config == {"relay_id": "site-b"}
