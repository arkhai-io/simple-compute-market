"""VM's part of the canonical compute deal against a real KVM host.

The real-provisioning lane deals on one host an environment owner describes in
the run's target (``e2e_harness.real_vm_target``): this driver registers that
host's supply, negotiates a key generated for the run, reads the access the
storefront delivered, and finds the real jobs the deal runs. It implements
``ComputeDealDriver`` alone. A real lane has no mock gate to hold a job at, so
where a mock lane releases a gate this lane waits for the job itself, found
through its fulfillment's capacity reservation and read to a terminal status
within a bound.

What the lane proves of the guest's absence is a VM list job on the host, not
the teardown job's own report: a succeeded teardown says what its playbook did,
and a refused connection is as consistent with a running guest whose forward or
key was removed.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from compute_provisioning_contracts import ConnectionSubmission

from e2e_harness.real_vm_target import RealVmTarget
from tests.e2e.roles.helpers.compute_deal import advance_fulfillment_to
from tests.e2e.roles.helpers.compute_deal_stages import (
    DURATION_HOURS,
    E2E_LEASE_EXPIRY_BACKDATE,
    ComputeDealState,
)
from tests.e2e.roles.helpers.ssh_access import SshEndpoint
from tests.e2e.roles.scenarios.vms.compute_deal_driver import VmDealDriverBase
from tests.e2e.roles.scenarios.vms.host_registry import (
    provision_e2e_executor,
    refresh_storefront_projections,
)

log = logging.getLogger(__name__)

#: The pool and the capacity declaration the lane registers for its host. Fixed,
#: so a rerun reconciles what an earlier run registered rather than adding
#: another; a declaration is updated in place when the target names another
#: host or capacity.
REAL_POOL_ID = "compute-e2e-real-pool"
REAL_RESOURCE_ID = "compute-e2e-real-001"
#: The region the listing and the declaration both state: the seller's inventory
#: guard compares it by equality, and it names no real place.
REAL_REGION = "e2e-real-host"
#: How long a job on the real host has to reach a terminal status. Sized for a
#: create — the cloud image's download, the guest's install, and its first
#: boot — on a host and network nobody here controls.
JOB_BOUND_SECONDS = 1800
#: The pause between reads of a job's status.
JOB_POLL_SECONDS = 10
#: How much of a failed or late job's logs a failure message carries.
_LOG_TAIL = 4000
#: The most listings one read of the storefront's listings asks for: the
#: largest page the storefront serves, which refuses a larger limit.
_LISTING_PAGE = 200


@dataclass
class RealVmDealState(ComputeDealState):
    """The real lane's observations layered over the canonical compute deal's."""

    domain_identity: str = "vms.compute"
    #: The host the provisioning service reaches is the one the target
    #: describes, read back after registration.
    _target_host_confirmed: bool = False
    #: The create job this deal's reservation ran, once it succeeded.
    create_job_id: Optional[str] = None
    #: The guest the create job reported creating.
    vm_name: Optional[str] = None
    #: Where the buyer connects, as the storefront delivered it.
    delivered_access: Optional[SshEndpoint] = None
    #: A VM list job on the host no longer names the guest.
    _guest_absent: bool = False


def vm_executor_is_real(execution: Any) -> Any:
    """The VM executor the provisioning service reports, required not mocked.

    Read per offering mode, because ``execution.mocked`` is true only when every
    composed executor is the mock: a service with a real bare-metal executor
    and a mocked VM one reports it false. One entry decides every VM action,
    since the VM bundle composes one executor for all of them.
    """
    entries = [entry for entry in execution.executors if entry.offering_mode == "vm"]
    assert entries and not any(entry.mocked for entry in entries), (
        "the provisioning service does not execute VM jobs for real, so this lane "
        f"would report mock delivery as real: executors={execution.executors!r}"
    )
    return entries[0]


def target_connection(target: RealVmTarget) -> ConnectionSubmission:
    """The connection the provisioning service reaches the target's host by.

    The key is named by where the service reads it; the target never carries
    key material.
    """
    host = target.host
    return ConnectionSubmission(
        kind="ssh",
        public={
            "ssh_host": host.ssh_host,
            "ssh_port": host.ssh_port,
            "ssh_user": host.ssh_user,
            "key_path": host.ssh_key_path,
            "public_host": host.public_host,
        },
    )


def assert_registered_as_target(registered: Any, target: RealVmTarget) -> None:
    """The registered host is the target's: its pool and its whole connection."""
    wanted = target_connection(target)
    connection = registered.connection
    stated = {name: connection.public.get(name) for name in wanted.public}
    assert registered.host_id == target.host.host_id, registered
    assert registered.enabled, f"host {registered.host_id!r} is disabled: {registered!r}"
    assert registered.pool_id == REAL_POOL_ID, (
        f"host {registered.host_id!r} is in pool {registered.pool_id!r}, not {REAL_POOL_ID!r}"
    )
    assert connection.kind == wanted.kind and stated == wanted.public, (
        f"host {registered.host_id!r} is registered with {connection.kind!r} "
        f"connection {stated!r}, not the target's {wanted.public!r}"
    )


def delivered_endpoint(settle_status: Any) -> SshEndpoint:
    """Where the buyer connects, from the connection details settle status delivers."""
    details = settle_status.extra.get("connection_details")
    if isinstance(details, str):
        details = json.loads(details)
    assert isinstance(details, Mapping) and all(
        details.get(name) for name in ("host", "port", "user")
    ), f"the settlement delivered no complete SSH endpoint: {details!r}"
    return SshEndpoint(host=str(details["host"]), port=int(details["port"]), user=str(details["user"]))


def created_guest_name(job: Any) -> str:
    """The guest a succeeded create job reported creating, from its operator detail."""
    detail = (job.result.value if job.result is not None else {}).get("detail") or {}
    name = detail.get("vm_name")
    assert isinstance(name, str) and name, (
        f"create job {job.job_id} reported no guest name: {job.result!r}"
    )
    return name


def listed_guests(job: Any) -> list[str]:
    """The guests a succeeded VM list job names, refusing a malformed list.

    The list is the playbook's own result fact, which the service keeps whole:
    the result's convenience copy of it is omitted when no guest is listed.
    """
    result = job.result
    assert result is not None and result.result_kind == "vm_list", (
        f"VM list job {job.job_id} reported no list: {result!r}"
    )
    listing = result.value.get("ansible_result")
    assert isinstance(listing, Mapping) and listing.get("action") == "list" and (
        listing.get("status") == "success"
    ), f"VM list job {job.job_id} reported no successful list: {result.value!r}"
    guests = listing.get("vms")
    assert isinstance(guests, list) and all(
        isinstance(guest, Mapping) and guest.get("name") for guest in guests
    ), f"VM list job {job.job_id} reported a malformed list: {guests!r}"
    return [str(guest["name"]) for guest in guests]


@dataclass
class JobWatch:
    """Reads the jobs a deal's reservation runs, and waits for one to finish."""

    provisioning_client: Any
    bound: float = JOB_BOUND_SECONDS
    poll_interval: float = JOB_POLL_SECONDS
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    def reservation_jobs(self, capacity_reservation_id: str) -> list[Any]:
        return list(
            self.provisioning_client.list_jobs(
                capacity_reservation_id=capacity_reservation_id,
                limit=100,
                sort="created_at_asc",
            ).jobs
        )

    def only_job(
        self,
        capacity_reservation_id: str,
        *,
        host_id: str,
        besides: tuple[str, ...] = (),
        context: str,
    ) -> Any:
        """The one job the reservation ran besides ``besides``, on ``host_id``.

        ``context`` says what the deal's fulfillment is doing, for a failure to
        name.
        """
        jobs = [
            job
            for job in self.reservation_jobs(capacity_reservation_id)
            if job.job_id not in besides
        ]
        assert jobs, (
            f"reservation {capacity_reservation_id} ran no job besides "
            f"{list(besides)}; {context}"
        )
        assert len(jobs) == 1, (
            f"reservation {capacity_reservation_id} ran {len(jobs)} jobs besides "
            f"{list(besides)}, where one was expected: "
            f"{[(job.job_id, job.status, job.host_id) for job in jobs]}; {context}"
        )
        (job,) = jobs
        assert job.host_id == host_id, (
            f"job {job.job_id} of reservation {capacity_reservation_id} ran on "
            f"{job.host_id!r}, not the target host {host_id!r}"
        )
        return job

    def until_succeeded(self, job_id: str, *, describe: str) -> Any:
        """The job once it succeeds; fails once it fails, or at the bound."""
        deadline = self.clock() + self.bound
        while True:
            job = self.provisioning_client.get_job(job_id)
            if job.status == "succeeded":
                return job
            if job.status in ("failed", "cancelled"):
                raise AssertionError(
                    f"{describe} {job_id} {job.status}: "
                    f"{job.error or 'no error recorded'}\n{self._logs(job_id)}"
                )
            if self.clock() >= deadline:
                raise AssertionError(
                    f"{describe} {job_id} did not finish within {self.bound}s; its "
                    f"last status was {job.status!r}\n{self._logs(job_id)}"
                )
            self.sleep(max(0.0, min(self.poll_interval, deadline - self.clock())))

    def _logs(self, job_id: str) -> str:
        try:
            logs = self.provisioning_client.get_job_logs(job_id).logs or ""
        except Exception as error:
            return f"Its logs could not be read: {error}"
        return f"Its logs, last {_LOG_TAIL} characters:\n{logs[-_LOG_TAIL:]}"


def assert_guest_absent(
    watch: JobWatch, vm_operator_client: Any, *, host_id: str, vm_name: str
) -> list[str]:
    """Run a VM list job on the host and require it not to name ``vm_name``.

    Returns the guests it names.
    """
    submitted = vm_operator_client.list_vms(host_id)
    job = watch.until_succeeded(submitted.job_id, describe="VM list job")
    guests = listed_guests(job)
    assert vm_name not in guests, (
        f"host {host_id!r} still lists guest {vm_name!r} after teardown: {guests}"
    )
    return guests


@dataclass
class RealVmComputeDealDriver(VmDealDriverBase):
    """VM's ``ComputeDealDriver`` for a real host: no mock gate, by construction."""

    vm_operator_client: Any
    target: RealVmTarget
    #: The OpenSSH public line of the key generated for this run.
    buyer_public_key: str
    #: The listing's shape, as the scenario's listing states it; the pool states
    #: the same shape.
    listing_shape: dict[str, Any]
    jobs: JobWatch
    reserved_resource_id: str = REAL_RESOURCE_ID

    @property
    def capacity(self) -> dict[str, int]:
        """What the host sells, in the VM capacity dimensions."""
        return self.target.host.capacity.model_dump()

    def seed_supply(self) -> None:
        """Register the target's pool, host, and capacity, and load the projection.

        The host is registered with the target's connection, replacing the one
        an earlier run left; the declaration states everything the host sells
        and no GPU, so the one deal takes all of it.
        """
        host = provision_e2e_executor(
            self.provisioning_client,
            self.site_capacity_admin_client,
            host=self.target.host.host_id,
            pool_id=REAL_POOL_ID,
            resource_id=REAL_RESOURCE_ID,
            sellable_units=None,
            capacity=self.capacity,
            attributes={"region": REAL_REGION, "sla": "90.0"},
            listing_shapes={"vm": [self.listing_shape]},
            connection=target_connection(self.target),
        )
        assert host.host_id == self.target.host.host_id
        refresh_storefront_projections(self.storefront_admin_client)

    def registered_host(self) -> Any:
        return self.provisioning_client.get_host(self.target.host.host_id)

    def listing_for_run(self) -> Optional[Any]:
        """The listing an earlier run left on the lane's resource, adopted paused.

        A publication source backs one listing for good, open or closed, and a
        rerun derives the same source from the same target, so a second listing
        on it is refused: a rerun takes over the listing already there. None on
        the resource returns nothing, for the run to create its own. Exactly
        one, open, stating everything the host sells is paused unless it is
        already, read back paused and open, and returned. Any other finding
        fails naming the listings and the capacity, for an operator to recover,
        and changes nothing.
        """
        listings = self._listings_on_resource()
        if not listings:
            return None
        capacity = self.capacity
        stated = [
            (listing, {name: listing.listing_resource.get(name) for name in capacity})
            for listing in listings
        ]
        (listing, shape), *others = stated
        assert not others and listing.status == "open" and shape == capacity, (
            f"the storefront holds listings on resource {REAL_RESOURCE_ID!r} this "
            f"run cannot adopt, where one open listing of the target's capacity "
            f"{capacity} can be: "
            + "; ".join(
                f"{each.listing_id} {each.status!r} paused={each.paused} {each_shape}"
                for each, each_shape in stated
            )
            + ". Closing a listing does not free its source: rerun with the target "
            "the listing was made for, or against a fresh stack"
        )
        if not listing.paused:
            self.storefront_admin_client.pause_listing(listing.listing_id)
        adopted = self.storefront_admin_client.get_listing(listing.listing_id)
        assert (adopted.status, adopted.paused) == ("open", True), adopted
        return adopted

    def _listings_on_resource(self) -> list[Any]:
        """Every storefront listing on the lane's resource, read page by page."""
        found: list[Any] = []
        offset = 0
        while True:
            page = self.storefront_admin_client.list_listings(
                limit=_LISTING_PAGE, offset=offset
            ).listings
            found += [
                listing for listing in page
                if listing.listing_resource.get("resource_id") == REAL_RESOURCE_ID
            ]
            if len(page) < _LISTING_PAGE:
                return found
            offset += len(page)

    def provision_terms(self) -> dict[str, Any]:
        return {
            "kind": "compute.v1",
            "version": 1,
            "payload": {
                "duration_seconds": DURATION_HOURS * 3600,
                # The run's own key: the access checks connect with its private
                # half, so a key negotiated here is the only one that can pass.
                "ssh_public_key": self.buyer_public_key,
            },
        }

    def evaluate_settle_arguments(self) -> dict[str, Any]:
        return {
            "ssh_public_key": self.buyer_public_key,
            "duration_seconds": DURATION_HOURS * 3600,
        }

    def assert_delivery(self, deal_state: Any) -> None:
        """VM's delivery, and an SSH endpoint on the host the target names."""
        super().assert_delivery(deal_state)
        endpoint = self.delivered_access(deal_state)
        log.info("Delivered access: %s@%s:%s", endpoint.user, endpoint.host, endpoint.port)

    def delivered_access(self, deal_state: Any) -> SshEndpoint:
        """Where the buyer connects, required to be the target's address for its
        access mode."""
        endpoint = delivered_endpoint(
            self.storefront_client.get_settle_status(deal_state.real_escrow_uid)
        )
        expected = self._buyer_address()
        assert endpoint.host == expected, (
            f"the delivered access names {endpoint.host!r}, not {expected!r}, the "
            f"address the target's {self.target.access.mode!r} access reaches"
        )
        return endpoint

    def _buyer_address(self) -> str:
        """The address a buyer reaches the guest at under the target's access mode."""
        if self.target.access.mode == "direct":
            return self.target.host.public_host
        raise AssertionError(f"access mode {self.target.access.mode!r} is not one this driver proves")

    def reserve_released_capacity(
        self, storefront_admin_client: Any, *, listing_id: str, escrow_uid: str
    ) -> Any:
        # Everything the host sells, so a reservation coming back shows all of
        # it was released, not only some dimension. The quantities go under
        # `dimensions`: the site matches every other key exactly against the
        # resource's attributes, which state none of them, and reads
        # quantities only from `dimensions`.
        return storefront_admin_client.admin_reserve_capacity(
            required_attributes={
                "resource_id": REAL_RESOURCE_ID,
                "dimensions": dict(self.capacity),
            },
            listing_id=listing_id,
            escrow_uid=escrow_uid,
        )

    # -- the deal's real jobs ---------------------------------------------

    def reservation_of(self, fulfillment_id: str) -> tuple[str, str]:
        """The capacity reservation a fulfillment serves, and its state."""
        status = self.provisioning_client.get_fulfillment_status(fulfillment_id)
        return status.capacity_reservation_id, status.state

    def create_job(self, fulfillment_id: str) -> Any:
        """The deal's create job, once it succeeded."""
        reservation, state = self.reservation_of(fulfillment_id)
        job = self.jobs.only_job(
            reservation,
            host_id=self.target.host.host_id,
            context=f"fulfillment {fulfillment_id} is {state!r}",
        )
        return self.jobs.until_succeeded(job.job_id, describe="create job")

    def teardown_job(self, fulfillment_id: str, *, create_job_id: str) -> Any:
        """The deal's teardown job, the one job besides its create, once it succeeded."""
        reservation, state = self.reservation_of(fulfillment_id)
        job = self.jobs.only_job(
            reservation,
            host_id=self.target.host.host_id,
            besides=(create_job_id,),
            context=f"fulfillment {fulfillment_id} is {state!r}",
        )
        return self.jobs.until_succeeded(job.job_id, describe="teardown job")

    def assert_guest_absent(self, vm_name: str) -> list[str]:
        return assert_guest_absent(
            self.jobs, self.vm_operator_client, host_id=self.target.host.host_id, vm_name=vm_name
        )

    # -- a failed run ---------------------------------------------------

    def tear_down_after_failure(self, deal_state: RealVmDealState) -> None:
        """Have the provisioning service tear down the guest a failed run left.

        For a run that submitted settlement and did not confirm its guest gone.
        The fulfillment is read from the deal's state, or from the settle status
        where the stage that records it failed after settle dispatched it; a
        settlement that dispatched none leaves nothing to tear down.

        A create still in flight is waited for and converged first: release
        waits for it, and convergence is held. The lease is then expired at the
        site unless it already is, and the held watchdog and convergence are
        stepped through teardown and release, so the provisioning service tears
        the guest down through its own lease lifecycle; the test layer
        reimplements no teardown. The guest is then confirmed gone as the lane
        confirms it. Raises naming everything an operator needs to recover the
        guest by hand where its removal is not confirmed.
        """
        known: dict[str, Any] = {
            "fulfillment": deal_state.fulfillment_id,
            "reservation": None,
            "create job": deal_state.create_job_id,
            "teardown job": None,
            "guest": deal_state.vm_name,
            "host": self.target.host.host_id,
        }
        try:
            fulfillment_id = deal_state.fulfillment_id or self.storefront_client.get_settle_status(
                deal_state.real_escrow_uid
            ).fulfillment_id
            if not fulfillment_id:
                log.info("[recovery] Settlement dispatched no fulfillment; nothing to tear down")
                return
            known["fulfillment"] = fulfillment_id
            reservation, state = self.reservation_of(fulfillment_id)
            known["reservation"] = reservation
            host_id = self.target.host.host_id
            if not known["create job"]:
                known["create job"] = self.jobs.only_job(
                    reservation, host_id=host_id, context=f"fulfillment {fulfillment_id} is {state!r}"
                ).job_id
            if state in ("dispatch_pending", "dispatching"):
                create = self.jobs.until_succeeded(known["create job"], describe="create job")
                known["guest"] = known["guest"] or created_guest_name(create)
                advance_fulfillment_to(self.provisioning_client, fulfillment_id, "active")
            elif not known["guest"]:
                known["guest"] = created_guest_name(
                    self.provisioning_client.get_job(known["create job"])
                )
            # The lease is recorded once the fulfillment is active; the read
            # fails for one that never was, which is reported below.
            lease = self.provisioning_client.get_lease(reservation)
            if lease.status == "active" and lease.lease_end_utc > datetime.now(timezone.utc):
                end = datetime.now(timezone.utc) - E2E_LEASE_EXPIRY_BACKDATE
                assert self.site_capacity.truncate_lease(
                    reservation, end.isoformat().replace("+00:00", "Z")
                ) is not None, f"the site refused to truncate lease {reservation}"
            if lease.status != "released" and not lease.release_job_id:
                self.provisioning_client.check_leases()
                lease = self.provisioning_client.get_lease(reservation)
            assert lease.release_job_id, (
                f"lease {reservation} is {lease.status!r} with no release begun"
            )
            teardown_state = self.provisioning_client.get_fulfillment_status(
                lease.release_job_id
            ).state
            if teardown_state == "teardown_dispatch_pending":
                advance_fulfillment_to(self.provisioning_client, lease.release_job_id, "tearing_down")
            teardown = self.jobs.only_job(
                reservation,
                host_id=host_id,
                besides=(known["create job"],),
                context=f"its teardown was {teardown_state!r} when recovery began",
            )
            known["teardown job"] = teardown.job_id
            self.jobs.until_succeeded(teardown.job_id, describe="teardown job")
            if lease.status != "released":
                advance_fulfillment_to(self.provisioning_client, lease.release_job_id, "torn_down")
                self.provisioning_client.check_leases()
            self.assert_guest_absent(known["guest"])
        except (Exception, pytest.fail.Exception) as error:
            named = ", ".join(f"{name} {value!r}" for name, value in known.items())
            raise AssertionError(
                f"the run failed with a guest possibly left on the host, and its "
                f"removal could not be confirmed ({error}); recover it by hand: {named}"
            ) from error
        log.info("[recovery] The failed run's guest was torn down: %s", known)
