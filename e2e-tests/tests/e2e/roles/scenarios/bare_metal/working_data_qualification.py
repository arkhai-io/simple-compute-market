"""Bounded working-data checks around an ordinary real bare-metal lifecycle."""
from __future__ import annotations

import json
import logging
import os
import shlex
import stat
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from _pytest.mark.expression import Expression

from e2e_harness.real_provisioning_target import BareMetalHost
from tests.e2e.roles.helpers.ssh_access import SshEndpoint, SshKey, SshSession

log = logging.getLogger(__name__)

PROBE = Path(__file__).with_name("working_data_probe.py")
QUALIFICATION_MARKER = "e2e_bare_metal_bounded_cleanup"


def qualification_requested(expression: str) -> bool:
    """Require cleanup inputs when that marker is necessary to select this module."""
    if not expression:
        return False
    compiled = Expression.compile(expression)
    markers = {QUALIFICATION_MARKER, "e2e_bare_metal_real_provisioning"}
    with_cleanup = compiled.evaluate(markers.__contains__)
    markers.remove(QUALIFICATION_MARKER)
    return with_cleanup and not compiled.evaluate(markers.__contains__)


def qualification_cycles(target: BareMetalHost | None, *, required: bool) -> tuple[str, ...]:
    """A dedicated qualification request cannot silently run baseline proof."""
    configured = target is not None and target.cleanup_qualification is not None
    if required and not configured:
        raise ValueError("bounded cleanup qualification requires an explicit bare-metal cleanup_qualification target")
    return ("normal", "refusal") if configured else ("baseline",)


def checked_key_reference(path: str) -> SshKey:
    """Validate a protected local key reference without reading or copying it."""
    key = Path(path)
    info = key.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
        raise ValueError("operator key reference must be an owner-only regular file")
    if not 0 < info.st_size <= 16384:
        raise ValueError("operator key reference has an invalid size")
    return SshKey(private_key=key, public_line="")


def probe_command(request: dict[str, Any], *, operator: bool) -> str:
    """Carry only fixed observer code and JSON arguments through the shared SSH seam."""
    argv = ["python3", "-c", PROBE.read_text(), json.dumps(request)]
    if operator:
        argv = ["sudo", "-n", "--", *argv]
    return shlex.join(argv)


def retryable_refusal(job: Any) -> bool:
    """Only an actual failed attempt with a scheduled remaining retry is repairable."""
    if job.status in ("failed", "cancelled", "succeeded"):
        raise AssertionError("refusal qualification needs a queued retry, not a terminal job")
    return (job.status == "queued" and job.retry_count >= 1
            and job.retry_count <= job.max_retries and job.next_retry_at is not None
            and bool(job.error))


@dataclass
class WorkingDataQualification:
    target: BareMetalHost
    operator_ssh: SshSession
    history: list[int]
    cycle: str
    nonce: str = field(default_factory=lambda: "scm-qualification-" + uuid.uuid4().hex)
    state: dict[str, Any] = field(default_factory=dict)
    heartbeat: Any | None = field(default=None, repr=False)

    def _operator(self, operation: str, **extra: Any) -> dict[str, Any]:
        config = self.target.cleanup_qualification
        assert config is not None
        endpoint = SshEndpoint(config.operator.host, config.operator.port, config.operator.user)
        key = checked_key_reference(config.operator.key_path)
        request = {**self.state, "operation": operation, "nonce": self.nonce,
                   "policy_id": config.policy_id, **extra}
        result = self.operator_ssh.run(endpoint, key, probe_command(request, operator=True))
        return json.loads(result)

    def preflight(self) -> None:
        """Authenticate the pinned route and read established policy before any writes."""
        self.state.update(self._operator("policy", needed_uids=2 if self.cycle == "normal" else 1))

    def repair_planted_fixture(self) -> bool:
        """Remove the planted foreign descendant if it is still there, so an
        ordinary reclaim can complete; whether there was one to remove."""
        if "foreign_child" not in self.state or self.state.get("fixture_repaired"):
            return False
        assert self._operator("repair")["fixture_only_repaired"]
        self.state["fixture_repaired"] = True
        return True

    def consumed_uids(self) -> list[int]:
        """The host ledger's consumed-UID history, read through the pinned
        operator route's ``policy`` operation, which changes nothing and, asked
        for no unused UID, requires none."""
        return list(self._operator("policy", needed_uids=0)["consumed"])

    def seed(self, *, ssh: SshSession, endpoint: SshEndpoint, key: SshKey,
             reservation_id: str) -> None:
        uid = int(ssh.run(endpoint, key, "id -u").strip())
        assert uid not in self.history, "successor tenant reused a predecessor UID"
        if self.cycle == "refusal":
            assert len(self.history) == 1, "successor proof requires the normal cleanup to complete first"
        home = self.state["home_parent"] + "/" + endpoint.user
        self.state.update(uid=uid, account=endpoint.user, home=home, reservation_id=reservation_id)
        assert self._operator("identity")["receipt_bound"]
        request = {**self.state, "operation": "seed", "nonce": self.nonce}
        seeded = json.loads(ssh.run(endpoint, key, probe_command(request, operator=False)))
        assert seeded["uid"] == uid and seeded["cron_seeded"]
        assert len(seeded["ipc"]) == 3 and len(seeded["paths"]) == 3 and seeded["process"] > 0
        self.state.update(self._operator("sentinels"))
        if self.cycle == "refusal":
            self.state.update(self._operator("arm"))
        self.heartbeat = ssh.heartbeat(endpoint, key)
        self.heartbeat.assert_alive()

    def observe_refusal_and_repair(self, *, driver: Any, deal_state: Any,
                                   storefront_admin_client: Any) -> None:
        if self.cycle != "refusal":
            return
        reservation, state = driver.reservation_of(deal_state.teardown_fulfillment_id)
        assert reservation == self.state["reservation_id"]
        job = driver.jobs.only_job(reservation, host_id=self.target.host_id,
                                   besides=(deal_state.create_job_id,), context=f"cleanup refusal {state}")
        deadline = driver.jobs.clock() + driver.jobs.bound
        while True:
            observation = driver.provisioning_client.get_job(job.job_id)
            if retryable_refusal(observation):
                break
            assert driver.jobs.clock() < deadline, "no retryable cleanup refusal observed within bound"
            driver.jobs.sleep(min(1.0, max(0.0, deadline - driver.jobs.clock())))
        logs = driver.provisioning_client.get_job_logs(job.job_id).logs or ""
        assert "foreign descendant" in logs, "failed attempt did not prove the intended unsafe-tree refusal"
        # The operator's notification of the refusal is this record, read
        # through the typed job API: log where it was observed.
        log.info("Reclaim job %s of reservation %s refused: %s, retry %s of %s, next at %s; "
                 "observed through the provisioning job API", job.job_id, reservation,
                 observation.error, observation.retry_count, observation.max_retries,
                 observation.next_retry_at)
        assert deal_state.deal_lease.refresh()["status"] == "releasing"
        assert deal_state.deal_lease.resource_consumed(storefront_admin_client, deal_state.reserved_resource_id), "unsafe cleanup advertised available capacity"
        # The foreign child is inside a selected UID-owned directory. The
        # helper must refuse that tree; foreign top-level entries are preserved.
        assert self._operator("repair")["fixture_only_repaired"]
        self.state["fixture_repaired"] = True
        driver.assert_management_connected()
        self.state["refusal_observed"] = True

    def verify(self) -> None:
        if self.cycle == "refusal":
            assert self.state.get("refusal_observed"), "refusal/retry proof is missing"
        assert self.heartbeat is not None, "open-session termination proof was not armed"
        self.heartbeat.process.wait(timeout=10)
        result = self._operator("observe")
        assert all(result[name] for name in ("account_absent", "group_absent", "home_absent",
                                             "scratch_absent", "ipc_absent", "activity_absent", "sentinels_unchanged"))
        self.history.append(self.state["uid"])
