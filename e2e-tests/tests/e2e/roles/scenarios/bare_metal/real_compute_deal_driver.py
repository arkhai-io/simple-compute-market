"""Bare-metal's canonical compute deal against a real, relay-backed host.

Supply is reconciled through typed authority APIs. No mock execution or gate is
available; cleanup follows only the run's own reservation and lease lifecycle.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import ConnectionSubmission, HostCreate, HostUpdate
from market_resource_pools_contracts import PoolCreate, PoolUpdate

from e2e_harness.real_provisioning_target import BareMetalHost
from tests.e2e.roles.helpers.compute_deal import advance_fulfillment_to, advance_storefront
from tests.e2e.roles.helpers.compute_deal_stages import ComputeDealState, E2E_LEASE_EXPIRY_BACKDATE
from tests.e2e.roles.helpers.real_provisioning import JobWatch, RealComputeObservations, configured_relay
from tests.e2e.roles.helpers.ssh_access import SshEndpoint
from tests.e2e.roles.scenarios.bare_metal.compute_deal_driver import (
    BARE_METAL_RESOURCE_KIND, BareMetalDealDriverBase,
)

REAL_POOL_ID = "bare-metal-e2e-real-pool"
REAL_RESOURCE_ID = "bare-metal-e2e-real-001"
REAL_REGION = "e2e-real-host"


@dataclass
class RealBareMetalDealState(ComputeDealState):
    """Run-owned observations beyond the compute-family shared stage state."""

    domain_identity: str = "bare_metal.v1"
    _target_host_confirmed: bool = False
    _publication_previewed: bool = False
    create_job_id: str | None = None
    delivered_access: SshEndpoint | None = None
    _access_ended: bool = False
    _working_data_seeded: bool = False


def bare_metal_executor_is_real(execution: Any) -> Any:
    entries = [entry for entry in execution.executors if entry.offering_mode == "bare_metal"]
    assert entries and not any(entry.mocked for entry in entries), (
        "the provisioning service does not execute bare-metal jobs for real: "
        f"executors={execution.executors!r}"
    )
    return entries[0]


def target_connection(target: BareMetalHost) -> ConnectionSubmission:
    """The operator's management connection, separate from the buyer relay."""
    return ConnectionSubmission(kind="ssh", version=2, public={
        "ssh_host": target.connection.ssh_host,
        "ssh_port": target.connection.ssh_port,
        "ssh_user": target.connection.ssh_user,
        "key_path": target.connection.ssh_key_path,
    })


def _missing(error: ComputeProvisioningError) -> bool:
    return error.status_code == 404


@dataclass
class RealBareMetalComputeDealDriver(BareMetalDealDriverBase, RealComputeObservations):
    """Bare-metal domain behavior without the provisioning mock profile's gates."""

    target: BareMetalHost
    jobs: JobWatch
    pool_id: str = REAL_POOL_ID
    reserved_resource_id: str = REAL_RESOURCE_ID
    dispatch_bound: float = 60

    @property
    def physical_host_id(self) -> str:
        return self.target.physical_host_id

    def seed_supply(self) -> None:
        """Reconcile a backed pool, its one executor and one whole-machine declaration."""
        assert self.target.access.mode == "relay", "real bare-metal lane requires access.mode=relay"
        configured_relay(self.provisioning_client, self.target)
        conflicts = [row for row in self.site_capacity.snapshot()
                     if row.get("resource_id") != self.reserved_resource_id
                     and (row.get("host_id") == self.target.host_id
                          or (row.get("attributes") or {}).get("physical_host_id") == self.physical_host_id)]
        assert not conflicts, (
            "target already has another capacity declaration; pause admission and reconcile it "
            f"before this lane registers supply: {[row.get('resource_id') for row in conflicts]}"
        )
        tags = {"deliverable_modes": ["bare_metal"], "advertisable_modes": ["bare_metal"],
                "capacity_backing": "backed", "region": REAL_REGION}
        config = {"relay_id": self.target.access.relay_id}
        try:
            pool = self.site_operator.get_pool(self.pool_id)
        except ComputeProvisioningError as error:
            if not _missing(error):
                raise
            self.site_operator.create_pool(PoolCreate(
                id=self.pool_id, label=self.pool_id, provider="bare_metal.ansible",
                policy_tags=tags, provider_config=config,
            ))
        else:
            assert pool.provider == "bare_metal.ansible" and pool.enabled, (
                f"real lane's existing pool has another provider or is disabled: {pool}"
            )
            if pool.provider_config != config or any(pool.policy_tags.get(k) != v for k, v in tags.items()):
                self.site_operator.patch_pool(self.pool_id, PoolUpdate(
                    policy_tags={**pool.policy_tags, **tags}, provider_config=config,
                ))
        wanted = target_connection(self.target)
        try:
            host = self.provisioning_client.get_host(self.target.host_id)
        except ComputeProvisioningError as error:
            if not _missing(error):
                raise
            self.provisioning_client.register_host(HostCreate(
                host_id=self.target.host_id, connection=wanted, enabled=True, pool_id=self.pool_id,
            ))
        else:
            assert host.enabled, f"target host is disabled: {host.host_id}"
            if host.pool_id != self.pool_id or host.connection.kind != wanted.kind or host.connection.version != wanted.version or any(host.connection.public.get(k) != v for k, v in wanted.public.items()):
                self.provisioning_client.update_host(self.target.host_id, HostUpdate(
                    connection=wanted, pool_id=self.pool_id,
                ))
        self.assert_registered_as_target()
        asyncio.run(self.site_capacity_admin.register_resource(
            self.reserved_resource_id, pool_id=self.pool_id, host_id=self.target.host_id,
            resource_type=BARE_METAL_RESOURCE_KIND,
            capacity={"units": 1, **self.target.capacity.model_dump()},
            attributes={"physical_host_id": self.physical_host_id, "allocation_mode": "exclusive",
                        "bare_metal_publication": {"enabled": True, "access_methods": ["ssh"]}},
        ))
        stepped = advance_storefront(self.storefront_admin_client, "site-projections")
        assert stepped["sites"][self.site_id]["resource_pool"]["state"] == "loaded", stepped
        self.assert_management_connected()

    def assert_registered_as_target(self) -> None:
        host = self.provisioning_client.get_host(self.target.host_id)
        wanted = target_connection(self.target)
        assert host.host_id == self.target.host_id and host.enabled and host.pool_id == self.pool_id, host
        assert (host.connection.kind, host.connection.version) == (wanted.kind, wanted.version), host
        assert all(host.connection.public.get(k) == v for k, v in wanted.public.items()), host

    def open_listing_for_run(self) -> Any:
        """Adopt exactly one open listing on this declaration, never create or pause one."""
        found = []
        offset = 0
        while True:
            page = self.storefront_admin_client.list_listings(limit=200, offset=offset).listings
            found += [listing for listing in page
                      if listing.listing_resource.get("host_id") == self.target.host_id
                      and listing.listing_resource.get("physical_host_id") == self.physical_host_id
                      and listing.status == "open"]
            if len(page) < 200:
                break
            offset += len(page)
        assert len(found) == 1, (
            f"expected one open published listing for resource {self.reserved_resource_id!r}; "
            f"found {[listing.listing_id for listing in found]}"
        )
        listing = found[0]
        resource = listing.listing_resource
        assert all(resource.get(k) == v for k, v in self.target.capacity.model_dump().items()), (
            "published machine shape differs from the target", resource
        )
        assert resource.get("region") == REAL_REGION and resource.get("capacity_backing") == "backed", resource
        assert not any(resource.get(k) is not None for k in ("gpu_model", "gpu_count")), (
            "target declares no GPUs, but listing advertises them", resource
        )
        return listing

    def assert_delivery(self, deal_state: Any) -> None:
        status = self.fulfillment.status(deal_state.negotiation_id)
        assert status.get("state") == "active", status
        delivered = self.fulfillment.result(deal_state.negotiation_id)
        assert delivered["receipt"]["status"] == "ready", delivered
        result = delivered["result"]
        assert "host" not in result and "port" not in result, result
        endpoint = self.delivered_access(deal_state)
        assert endpoint.user == result.get("ssh_user"), (endpoint, result)

    def delivered_access(self, deal_state: Any) -> SshEndpoint:
        access = self.fulfillment.access(deal_state.negotiation_id)
        assert all(access.get(field) for field in ("host", "port", "username")), access
        endpoint = SshEndpoint(str(access["host"]), int(access["port"]), str(access["username"]))
        relay = configured_relay(self.provisioning_client, self.target)
        assert endpoint.host == relay.relay_addr, "delivered endpoint is not the selected relay"
        self.assert_relay_delivery(deal_state.fulfillment_id, endpoint)
        return endpoint

    def reserve_released_capacity(self, storefront_admin_client: Any, *, listing_id: str, escrow_uid: str) -> Any:
        return storefront_admin_client.admin_reserve_capacity(
            required_attributes={"resource_id": self.reserved_resource_id, "dimensions": {"units": 1}},
            listing_id=listing_id, escrow_uid=escrow_uid,
        )

    def dispatched_fulfillment(self, state: RealBareMetalDealState) -> str:
        """Bound an uncertain settlement response, never assume no host effect from silence."""
        deadline = self.jobs.clock() + self.dispatch_bound
        while True:
            status = self.fulfillment.status(state.negotiation_id)
            if status.get("fulfillment_id"):
                return str(status["fulfillment_id"])
            if self.jobs.clock() >= deadline:
                raise AssertionError(f"settlement dispatch not confirmed: {status}")
            self.jobs.sleep(min(self.jobs.poll_interval, max(0, deadline - self.jobs.clock())))

    def tear_down_after_failure(self, state: RealBareMetalDealState) -> None:
        """Expire only this deal's lease and verify successful reclaim and release."""
        known = {"negotiation": state.negotiation_id, "escrow": state.real_escrow_uid,
                 "fulfillment": state.fulfillment_id, "reservation": None,
                 "grant_job": state.create_job_id, "reclaim_job": None,
                 "host": self.target.host_id}
        try:
            fulfillment_id = state.fulfillment_id or self.dispatched_fulfillment(state)
            known["fulfillment"] = fulfillment_id
            reservation, current = self.reservation_of(fulfillment_id)
            known["reservation"] = reservation
            if not known["grant_job"]:
                known["grant_job"] = self.jobs.only_job(
                    reservation, host_id=self.target.host_id, context=f"fulfillment state {current}",
                ).job_id
            if current in ("dispatch_pending", "dispatching"):
                self.jobs.until_succeeded(known["grant_job"], describe="grant job")
                advance_fulfillment_to(self.provisioning_client, fulfillment_id, "active")
            lease = self.provisioning_client.get_lease(reservation)
            if lease.status == "released":
                self.assert_relay_released(fulfillment_id, state.delivered_access) if state.delivered_access else None
                return
            if lease.status == "active" and lease.lease_end_utc > datetime.now(timezone.utc):
                end = datetime.now(timezone.utc) - E2E_LEASE_EXPIRY_BACKDATE
                assert self.site_capacity.truncate_lease(reservation, end.isoformat().replace("+00:00", "Z")) is not None
            self.provisioning_client.check_leases()
            lease = self.provisioning_client.get_lease(reservation)
            assert lease.release_job_id, f"lease {reservation} has no reclaim fulfillment"
            current = self.provisioning_client.get_fulfillment_status(lease.release_job_id).state
            if current == "teardown_dispatch_pending":
                advance_fulfillment_to(self.provisioning_client, lease.release_job_id, "tearing_down")
            reclaim = self.jobs.only_job(
                reservation, host_id=self.target.host_id, besides=(known["grant_job"],), context=f"reclaim state {current}",
            )
            known["reclaim_job"] = reclaim.job_id
            self.jobs.until_succeeded(reclaim.job_id, describe="reclaim job")
            advance_fulfillment_to(self.provisioning_client, lease.release_job_id, "torn_down")
            self.provisioning_client.check_leases()
            assert self.provisioning_client.get_lease(reservation).status == "released"
            self.assert_management_connected()
        except (Exception, pytest.fail.Exception) as error:
            raise AssertionError(f"bare-metal reclaim could not be confirmed ({error}); operator recovery required: {known}") from error
