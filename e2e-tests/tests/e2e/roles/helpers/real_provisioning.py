"""Real compute lanes' job observation and relay readiness, with no domain effects."""
from __future__ import annotations

import time
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from e2e_harness.real_provisioning_target import BareMetalHost, VmHost
from tests.e2e.roles.helpers.ssh_access import SshEndpoint

log = logging.getLogger(__name__)

JOB_BOUND_SECONDS = 1800
JOB_POLL_SECONDS = 10
_LOG_TAIL = 4000


def configured_relay(provisioning_client: Any, target: VmHost | BareMetalHost) -> Any | None:
    """Read an operator-owned relay before any scenario mutation; never create it."""
    if target.access.mode == "direct":
        return None
    relay = provisioning_client.get_relay(target.access.relay_id)
    assert relay.id == target.access.relay_id, "relay read returned another identity"
    assert relay.enabled, f"target relay {relay.id!r} is disabled"
    assert relay.token_configured, f"target relay {relay.id!r} has no configured token"
    assert relay.grant_keys.active is not None, f"target relay {relay.id!r} has no active grant key"
    return relay



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



class RealComputeObservations:
    """Read-only job, management and relay proofs common to real compute lanes."""

    provisioning_client: Any
    target: VmHost | BareMetalHost
    jobs: JobWatch

    def assert_management_connected(self) -> None:
        result = self.provisioning_client.check_connectivity(self.target.host_id)
        assert result.host == self.target.host_id and result.reachable, (
            f"target management connection failed: {result}"
        )

    def assert_relay_delivery(self, fulfillment_id: str, endpoint: SshEndpoint) -> None:
        if self.target.access.mode == "direct":
            return
        reservation, _state = self.reservation_of(fulfillment_id)
        holdings = self.provisioning_client.list_relay_leases(self.target.access.relay_id)
        owned = [lease for lease in holdings.leases
                 if lease.owner_kind == "fulfillment" and lease.owner_id == reservation]
        assert len(owned) == 1 and owned[0].released_at is None, (
            f"no unique active relay holding for reservation {reservation!r}"
        )
        assert owned[0].host_id == self.target.host_id and owned[0].remote_port == endpoint.port, (
            "delivered port/host differs from the reservation's relay holding"
        )

    def assert_relay_released(self, fulfillment_id: str, endpoint: SshEndpoint) -> None:
        if self.target.access.mode == "direct":
            return
        reservation, _state = self.reservation_of(fulfillment_id)
        holdings = self.provisioning_client.list_relay_leases(self.target.access.relay_id)
        owned = [lease for lease in holdings.leases
                 if lease.owner_kind == "fulfillment" and lease.owner_id == reservation]
        assert len(owned) == 1, f"no unique released relay holding for {reservation!r}"
        lease = owned[0]
        assert lease.remote_port == endpoint.port and lease.released_at is not None, (
            "relay holding did not record release of the delivered port"
        )
        assert lease.grant_expires_at is not None, "released holding lost its grant expiry"
        assert not any(other.remote_port == endpoint.port and other.released_at is None
                       for other in holdings.leases), "released port has another active owner"
        log.info("Relay port released; quarantine follows original grant expiry %s", lease.grant_expires_at)

    def reservation_of(self, fulfillment_id: str) -> tuple[str, str]:
        """The capacity reservation a fulfillment serves, and its state."""
        status = self.provisioning_client.get_fulfillment_status(fulfillment_id)
        return status.capacity_reservation_id, status.state

    def create_job(self, fulfillment_id: str) -> Any:
        """The deal's create job, once it succeeded."""
        reservation, state = self.reservation_of(fulfillment_id)
        job = self.jobs.only_job(
            reservation,
            host_id=self.target.host_id,
            context=f"fulfillment {fulfillment_id} is {state!r}",
        )
        result = self.jobs.until_succeeded(job.job_id, describe="create job")
        self.assert_management_connected()
        return result

    def teardown_job(self, fulfillment_id: str, *, create_job_id: str) -> Any:
        """The deal's teardown job, the one job besides its create, once it succeeded."""
        reservation, state = self.reservation_of(fulfillment_id)
        job = self.jobs.only_job(
            reservation,
            host_id=self.target.host_id,
            besides=(create_job_id,),
            context=f"fulfillment {fulfillment_id} is {state!r}",
        )
        result = self.jobs.until_succeeded(job.job_id, describe="teardown job")
        self.assert_management_connected()
        return result
