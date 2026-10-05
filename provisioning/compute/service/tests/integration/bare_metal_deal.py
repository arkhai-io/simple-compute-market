"""A bare-metal deal's capacity and fulfillment, set up as production does.

Access is granted only through fulfillment: a pool whose provider is the
bare-metal one, a registered host, a declaration delivered through it, a
committed reservation, scheduling, and ``begin``, which dispatches the grant
job. Every step a route serves goes through the canonical clients; the
declaration and the reservation, which a site's operator and a storefront make
at the site, are made on the composed ledger.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from compute_provisioning_ansible import ssh_connection
from compute_provisioning_contracts import (
    FulfillmentRequestBody,
    FulfillmentScheduleRequest,
    HostCreate,
)
from market_core import VersionedEnvelope
from market_resource_pools_contracts import PoolCreate
from market_site.ledger import ALLOCATION_MODE_EXCLUSIVE

from compute_provisioning_service import container as _container_module

HOST_ID = "bm-node-1"
SSH_HOST = "192.0.2.10"
PHYSICAL_HOST_ID = "host-physical-1"
POOL_ID = "bare-metal-pool"


async def bare_metal_capacity(clients) -> None:
    """The pool, host, and declaration one bare-metal machine is sold from."""
    await clients.pools.create_pool(
        PoolCreate(
            id=POOL_ID,
            label=POOL_ID,
            provider="bare_metal.ansible",
            policy_tags={
                "deliverable_modes": ["bare_metal"],
                "advertisable_modes": [],
                "capacity_backing": "backed",
            },
        )
    )
    await clients.family.register_host(
        HostCreate(
            host_id=HOST_ID,
            connection=ssh_connection(
                ssh_host=SSH_HOST, ssh_user="root", ssh_port=2201, key_path="/fake/id_ed25519"
            ),
        )
    )
    _container_module.resolved_capacity_ledger_service.register_resource(
        resource_id="bare-metal-node-1",
        pool_id=POOL_ID,
        total_units=1,
        resource_type="compute.bare-metal",
        host_id=HOST_ID,
        attributes={
            "physical_host_id": PHYSICAL_HOST_ID,
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
            "bare_metal_publication": {"enabled": True},
        },
    )


def committed_reservation(escrow_uid: str, *, lease_end: datetime | None = None) -> str:
    """A storefront's committed reservation of the machine."""
    ledger = _container_module.resolved_capacity_ledger_service
    reserved = ledger.reserve(
        claim={
            "offering_mode": "bare_metal",
            "physical_host_id": PHYSICAL_HOST_ID,
            "allocation_mode": ALLOCATION_MODE_EXCLUSIVE,
        },
        deal_ref={"escrow_uid": escrow_uid},
    )
    assert reserved is not None, "the machine could not be reserved"
    end = lease_end or datetime.now(timezone.utc) + timedelta(hours=2)
    ledger.commit(
        capacity_reservation_id=reserved["capacity_reservation_id"],
        lease_start_utc=(end - timedelta(hours=2)).isoformat(),
        lease_end_utc=end.isoformat(),
    )
    return reserved["capacity_reservation_id"]


async def schedule(clients, capacity_reservation_id: str) -> None:
    await clients.family.schedule_resource(
        FulfillmentScheduleRequest(
            capacity_reservation_id=capacity_reservation_id,
            market="bare_metal",
            requirements={"resource_kind": "compute.bare-metal"},
        )
    )


async def begin(clients, capacity_reservation_id: str, escrow_uid: str) -> str:
    """Begin the deal's fulfillment, which dispatches the grant; its id."""
    accepted = await clients.family.begin_fulfillment(
        FulfillmentRequestBody(
            capacity_reservation_id=capacity_reservation_id,
            market="bare_metal",
            fulfillment_request=VersionedEnvelope(
                kind="bare_metal.v2",
                schema_version=1,
                payload={
                    "kind": "bare_metal.v2",
                    "escrow_uid": escrow_uid,
                    "host_id": HOST_ID,
                    "physical_host_id": PHYSICAL_HOST_ID,
                    "lease_start_utc": "2030-01-01T00:00:00Z",
                    "lease_end_utc": "2030-01-02T00:00:00Z",
                    "access_method": "ssh",
                    "ssh_public_key": "ssh-ed25519 AAAA tenant-a",
                },
            ),
        )
    )
    return accepted.fulfillment_id


async def begun_bare_metal_deal(clients, escrow_uid: str) -> tuple[str, str]:
    """Capacity, a committed reservation, and its begun fulfillment."""
    await bare_metal_capacity(clients)
    capacity_reservation_id = committed_reservation(escrow_uid)
    await schedule(clients, capacity_reservation_id)
    return capacity_reservation_id, await begin(clients, capacity_reservation_id, escrow_uid)


def create_job_id(capacity_reservation_id: str) -> str:
    """The grant job the dispatch recorded on the reservation."""
    reservation = _container_module.resolved_capacity_ledger_service.get_reservation(
        capacity_reservation_id
    )
    job_id = reservation.get("create_job_id")
    assert job_id, "the dispatch recorded no create handle on the reservation"
    return job_id
