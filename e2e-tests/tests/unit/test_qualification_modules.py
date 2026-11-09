"""The real-provisioning qualification modules' wiring and their pure checks.

Read from source, or called on constructed inputs: the modules themselves need a
real-provisioning target and a payments target, which no lane has. That each
deal module, observation 2's and observations 4 and 5's, extends the purchase
stages without replacing a body is ``test_buyer_purchase_stages.py``'s check,
where each is a row; observation 6's module makes no deal and extends none,
following them on the stack their purchases populated. That every module checks
its targets before any hold is ``test_scenario_cleanup_order.py``'s.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import tomllib
import yaml

from e2e_harness.real_provisioning_target import SECTION
from tests.e2e.roles.helpers.qualification import (
    QuarantinedPort,
    RegistrationSnapshot,
    quarantined_ports,
    registration_faults,
    target_host,
)
from tests.e2e.roles.scenarios.vms.host_generations import (
    DiagnosticsRead,
    libvirtd_faults,
    management_unit_faults,
)
from tests.e2e.roles.scenarios.bare_metal.real_purchase_driver import RealBareMetalPurchaseDriver
from tests.e2e.roles.scenarios.vms.real_purchase_driver import (
    RealVmPurchaseDriver,
    listing_status_after,
)
from tests.e2e.roles.scenarios.vms.test_real_provisioning_reapply import (
    CAPACITY_EVENT_CYCLES,
    drain_capacity_events,
)
from tests.unit.test_real_provisioning_target import EXAMPLE

PROJECT = Path(__file__).resolve().parents[2]
SCENARIOS = PROJECT / "tests" / "e2e" / "roles" / "scenarios"
#: Each qualification module, its marker, and the observations it makes.
MODULES = {
    "e2e_vm_qualification": (SCENARIOS / "vms" / "test_vm_qualification.py", ("2",)),
    "e2e_bare_metal_qualification": (
        SCENARIOS / "bare_metal" / "test_bare_metal_qualification.py", ("4", "5"),
    ),
    "e2e_real_provisioning_reapply": (
        SCENARIOS / "vms" / "test_real_provisioning_reapply.py", ("6",),
    ),
}


def _registered_markers() -> set[str]:
    config = tomllib.loads((PROJECT / "pyproject.toml").read_text())
    return {line.split(":", 1)[0] for line in config["tool"]["pytest"]["ini_options"]["markers"]}


def _lane_modules() -> str:
    """Every ``E2E_*_MODULE`` expression the e2e Makefile runs a lane with."""
    makefile = (PROJECT / "Makefile").read_text().replace("\\\n", " ")
    return " ".join(re.findall(r"^E2E_\w*MODULE\s*\?=\s*(.*)$", makefile, flags=re.MULTILINE))


def _assigned(path: Path, name: str):
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    return None


@pytest.mark.parametrize("marker", sorted(MODULES))
def test_each_module_is_registered_under_its_marker_and_in_no_lane(marker):
    path, observations = MODULES[marker]
    assert marker in _registered_markers()
    assert f"pytest.mark.{marker}" in path.read_text()
    assert marker not in _lane_modules()
    assert _assigned(path, "OBSERVATIONS") == observations


def test_the_bare_metal_module_makes_one_observation_per_cycle():
    path, _ = MODULES["e2e_bare_metal_qualification"]
    assert _assigned(path, "CYCLE_PARAM") == "cleanup_cycle"
    assert _assigned(path, "CYCLE_OBSERVATIONS") == {"normal": ("4",), "refusal": ("5",)}


@pytest.mark.parametrize("marker", sorted(MODULES))
def test_the_readme_says_how_an_operator_runs_each(marker):
    readme = (PROJECT / "README.md").read_text()
    assert f"make test-module MODULE={marker} ACTIVE_PROFILES=local,real-provisioning-target" in readme


# ---------------------------------------------------------------------------
# A blocked skip without a target
# ---------------------------------------------------------------------------

def test_no_real_provisioning_target_is_a_blocked_skip():
    with pytest.raises(pytest.skip.Exception, match=f"blocked: no real-provisioning target.*{SECTION}"):
        target_host({}, "vm")


def test_a_target_without_the_domains_host_is_a_blocked_skip_naming_it():
    section = yaml.safe_load(EXAMPLE.read_text())[SECTION]
    section["hosts"] = [host for host in section["hosts"] if host["domain"] == "vm"]
    with pytest.raises(pytest.skip.Exception, match="blocked: .*holds no bare_metal host"):
        target_host({SECTION: section}, "bare_metal")
    assert target_host({SECTION: section}, "vm").host_id == "example-kvm-1"


# ---------------------------------------------------------------------------
# Observation 2: the host's services across the reads
# ---------------------------------------------------------------------------

def _unit(invocation="inv-1", restarts=0, state="active", result="success"):
    return SimpleNamespace(active_state=state, invocation_id=invocation, restart_count=restarts,
                           result=result)


def _read(label, *, libvirtd=None, management=None, running=True):
    return DiagnosticsRead(
        label, SimpleNamespace(libvirtd=libvirtd or _unit(), management=management), running,
    )


def test_unchanged_generations_have_no_fault():
    reads = [_read(label, management=_unit("agent-1")) for label in ("before", "during", "after")]
    assert management_unit_faults(reads, "agent.service") == []
    assert libvirtd_faults(reads) == []


@pytest.mark.parametrize(("changed", "named"), [
    (_unit("agent-2"), "invocation changed from 'agent-1' to 'agent-2'"),
    (_unit("agent-1", restarts=1), "restarted 1 time(s)"),
    (_unit("agent-1", state="inactive"), "is 'inactive', not active"),
    (None, "was not reported"),
])
def test_a_management_unit_that_did_not_keep_its_generation_is_named(changed, named):
    reads = [_read("before", management=_unit("agent-1")), _read("during", management=changed)]
    (fault,) = management_unit_faults(reads, "agent.service")
    assert fault.startswith("during: ") and named in fault


def test_libvirtd_may_start_anew_while_no_guest_runs():
    reads = [
        _read("before", libvirtd=_unit("lv-1"), running=False),
        _read("during", libvirtd=_unit("lv-2")),
        _read("still during", libvirtd=_unit("lv-2")),
        _read("after", libvirtd=_unit("lv-3"), running=False),
    ]
    assert libvirtd_faults(reads) == []


@pytest.mark.parametrize(("changed", "named"), [
    (_unit("lv-3"), "invocation changed from 'lv-2' to 'lv-3' while the first guest ran"),
    (_unit("lv-2", restarts=2), "restarted 2 time(s)"),
    (_unit("lv-2", result="exit-code"), "result is 'exit-code'"),
])
def test_a_libvirtd_restart_or_failure_is_named(changed, named):
    reads = [_read("during", libvirtd=_unit("lv-2")), _read("still during", libvirtd=changed)]
    (fault,) = libvirtd_faults(reads)
    assert fault.startswith("still during: libvirtd.service") and named in fault


@pytest.mark.parametrize(("guests", "status"), [(1, "open"), (2, "closed")])
def test_the_listing_stays_open_while_another_guest_fits(guests, status):
    capacity, shape = {"vcpu_count": 4, "ram_gb": 8, "disk_gb": 60}, {"vcpu_count": 2, "ram_gb": 3, "disk_gb": 25}
    assert listing_status_after(capacity, shape, guests) == status


# ---------------------------------------------------------------------------
# Compensation: a failed purchase's delivery ended through its lease
# ---------------------------------------------------------------------------

class _RecordingVmDriver(RealVmPurchaseDriver):
    """The real VM purchase driver with its lease recovery recorded, not run."""

    dispatched = "f-1"

    def dispatched_fulfillment(self, deal_state):
        self.asked = deal_state
        return self.dispatched

    def tear_down_after_failure(self, deal_state):
        self.ended = deal_state


class _RecordingBareMetalDriver(RealBareMetalPurchaseDriver):
    def tear_down_after_failure(self, state):
        self.ended = state


def test_a_vm_purchases_guest_is_ended_by_its_negotiation_with_its_known_jobs():
    """The recovery is given the create job and guest the stages recorded, so
    it tells the create job from a teardown job the reservation also ran."""
    driver = object.__new__(_RecordingVmDriver)
    assert driver.purchase_status("negotiation-1") == {"fulfillment_id": "f-1"}
    assert driver.asked.negotiation_id == "negotiation-1"
    known = SimpleNamespace(create_job_id="create-1", vm_name="guest-1")
    driver.end_purchase("negotiation-1", {"fulfillment_id": "f-1"}, known)
    ended = driver.ended
    assert (ended.negotiation_id, ended.settlement_ref, ended.fulfillment_id,
            ended.create_job_id, ended.vm_name) == (
        "negotiation-1", "negotiation-1", "f-1", "create-1", "guest-1")


def test_a_vm_purchase_the_storefront_dispatched_nothing_for_has_no_guest():
    driver = object.__new__(_RecordingVmDriver)
    driver.dispatched = None
    assert driver.purchase_status("negotiation-1") is None


@pytest.mark.parametrize("status", ["refunding", "refunded"])
def test_a_vm_purchase_refunded_before_any_delivery_has_no_guest(status):
    driver = object.__new__(RealVmPurchaseDriver)
    driver.storefront_client = SimpleNamespace(
        get_settle_status=lambda negotiation_id: SimpleNamespace(status=status, fulfillment_id=None))
    assert driver.purchase_status("negotiation-1") is None


def test_a_bare_metal_purchases_tenancy_is_ended_by_its_negotiation_with_its_known_job():
    driver = object.__new__(_RecordingBareMetalDriver)
    driver.fulfillment = SimpleNamespace(
        status=lambda negotiation_id: {"fulfillment_id": "f-2", "state": "active"})
    status = driver.purchase_status("negotiation-2")
    assert status == {"fulfillment_id": "f-2", "state": "active"}
    known = SimpleNamespace(create_job_id="grant-2", delivered_access=None)
    driver.end_purchase("negotiation-2", status, known)
    ended = driver.ended
    assert (ended.negotiation_id, ended.fulfillment_id, ended.create_job_id) == (
        "negotiation-2", "f-2", "grant-2")


# ---------------------------------------------------------------------------
# Observation 6: registration reapplied
# ---------------------------------------------------------------------------

NOW = datetime(2027, 1, 1, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=1)
#: When the quarantined lease was released, before the module's first read.
RELEASED = NOW - timedelta(hours=2)
QUARANTINED = QuarantinedPort("lease-1", 6101, "reservation-1", LATER, RELEASED)


def _snapshot(**changes) -> RegistrationSnapshot:
    fields = dict(
        hosts=(("example-bm-1", "pool-1", True),),
        declarations=(("resource-1", "pool-1"),),
        listings=(("listing-1", "open", False),),
        quarantined=(QUARANTINED,),
        active_ports=(6102,),
    )
    fields.update(changes)
    return RegistrationSnapshot(**fields)


def test_an_unchanged_registration_has_no_fault():
    assert registration_faults("bare_metal", _snapshot(), _snapshot(), now=NOW) == []


@pytest.mark.parametrize("name", ["vm", "bare_metal"])
@pytest.mark.parametrize("listings", [
    (("current", "open", True), ("historical", "closed", True)),
    (("current", "open", False), ("old-1", "closed", False), ("old-2", "closed", True)),
    (("old-1", "closed", False), ("old-2", "closed", True)),
])
def test_reapply_preserves_unchanged_listing_history(name, listings):
    before = _snapshot(listings=listings)
    assert registration_faults(name, before, _snapshot(listings=listings), now=NOW) == []


@pytest.mark.parametrize("listings", [
    (("current", "open", True),),
    (("current", "open", True), ("historical", "closed", True), ("extra", "closed", True)),
    (("current", "open", True), ("replacement", "closed", True)),
    (("current", "open", True), ("historical", "open", True)),
    (("current", "open", True), ("historical", "closed", False)),
], ids=["dropped", "added", "replaced", "reopened", "pause changed"])
def test_reapply_rejects_a_changed_historical_listing(listings):
    before = _snapshot(listings=(("current", "open", True), ("historical", "closed", True)))
    faults = registration_faults("vm", before, _snapshot(listings=listings), now=NOW)
    assert any("listings changed" in fault for fault in faults), faults


@pytest.mark.parametrize(("after", "named"), [
    (_snapshot(listings=(("listing-1", "open", False), ("listing-2", "open", True))), "2 listings"),
    (_snapshot(listings=(("listing-1", "open", True),)), "listings changed"),
    (_snapshot(hosts=(("example-bm-1", "pool-1", True), ("example-bm-1", "pool-2", True))), "2 hosts"),
    (_snapshot(declarations=(("resource-1", "pool-1"), ("resource-2", "pool-1"))),
     "2 capacity declarations"),
    (_snapshot(quarantined=()), "left quarantine"),
    (_snapshot(active_ports=(6101, 6102)), "quarantined relay port 6101 has a new owner"),
])
def test_a_duplicate_a_change_or_a_lost_quarantine_is_named(after, named):
    faults = registration_faults("bare_metal", _snapshot(), after, now=NOW)
    assert any(named in fault for fault in faults), faults


def test_a_quarantine_whose_grants_expired_meanwhile_may_end():
    expired = _snapshot(quarantined=(dataclasses.replace(QUARANTINED, grant_expires_at=NOW),))
    assert registration_faults("bare_metal", expired, _snapshot(quarantined=()), now=NOW) == []


def test_a_quarantined_lease_released_again_is_named_though_its_identity_is_kept():
    """Un-released by the reapply and released again by relay-port
    reconciliation's ungated sweep: the same lease, quarantined, owned and
    expiring as before, with only its release time new."""
    released_again = _snapshot(
        quarantined=(dataclasses.replace(QUARANTINED, released_at=NOW),),
    )
    faults = registration_faults("bare_metal", _snapshot(), released_again, now=NOW)
    assert len(faults) == 1 and "lease record changed" in faults[0], faults


@pytest.mark.parametrize("change", [
    {"owner_id": "reservation-2"}, {"grant_expires_at": LATER + timedelta(hours=1)},
], ids=["owner", "grant-expiry"])
def test_a_quarantined_leases_changed_owner_or_grant_expiry_is_named(change):
    changed = _snapshot(quarantined=(dataclasses.replace(QUARANTINED, **change),))
    faults = registration_faults("bare_metal", _snapshot(), changed, now=NOW)
    assert any("lease record changed" in fault for fault in faults), faults


def test_a_port_active_before_and_released_after_is_no_fault():
    """The stated limit: an unheld watchdog may end a live lease, so the
    comparison claims nothing about a live tenancy surviving."""
    ended = dataclasses.replace(QUARANTINED, lease_id="lease-2", remote_port=6102,
                                owner_id="reservation-2", released_at=NOW)
    after = _snapshot(quarantined=(QUARANTINED, ended), active_ports=())
    assert registration_faults("bare_metal", _snapshot(), after, now=NOW) == []


def test_only_released_unexpired_leases_are_quarantined():
    def lease(lease_id, released, expires):
        return SimpleNamespace(lease_id=lease_id, remote_port=6100 + int(lease_id[-1]),
                               owner_id="r-" + lease_id, released_at=released,
                               grant_expires_at=expires)

    leases = [lease("lease-1", NOW, LATER), lease("lease-2", None, LATER),
              lease("lease-3", NOW, NOW - timedelta(seconds=1)), lease("lease-4", NOW, None)]
    assert [port.lease_id for port in quarantined_ports(leases, NOW)] == ["lease-1"]
    (port,) = quarantined_ports(leases, NOW)
    assert port.released_at == NOW


def test_the_services_zoneless_lease_times_are_read_as_utc():
    """The provisioning service returns a relay lease's times without a zone,
    in UTC, and the module's ``now`` is aware: they compare rather than raise."""
    def naive(moment: datetime) -> datetime:
        return moment.replace(tzinfo=None)

    leases = [
        SimpleNamespace(lease_id="lease-1", remote_port=6101, owner_id="reservation-1",
                        released_at=naive(RELEASED), grant_expires_at=naive(LATER)),
        SimpleNamespace(lease_id="lease-2", remote_port=6102, owner_id="reservation-2",
                        released_at=naive(RELEASED), grant_expires_at=naive(NOW)),
    ]
    assert quarantined_ports(leases, NOW) == (QUARANTINED,)
    assert registration_faults(
        "bare_metal", _snapshot(), _snapshot(quarantined=quarantined_ports(leases, NOW)), now=NOW,
    ) == []


# ---------------------------------------------------------------------------
# Observation 6's VM capacity-event drain
# ---------------------------------------------------------------------------

class _FakeStorefrontAdmin:
    """A held storefront's lifecycle routes, answering from a plan: one dry run
    of the capacity-event loop, then each capacity-event cycle in turn."""

    def __init__(self, pending: int, cycles: list[dict]) -> None:
        self._pending = pending
        self._cycles = list(cycles)
        self.ran: list[str] = []

    def admin_dry_run_lifecycle_cycle(self, loop: str) -> dict:
        assert loop == "capacity-events", loop
        return {"sites": [{"site": "site-1", "error": None, "would_position": False,
                           "pending_count": self._pending, "cursor": "c", "feed_head": "h"}]}

    def admin_run_lifecycle_cycle(self, loop: str) -> dict:
        self.ran.append(loop)
        if loop == "site-projections":
            return {"sites": [{"site": "site-1"}]}
        assert loop == "capacity-events", loop
        return {"sites": [self._cycles.pop(0)]}


def _cycle(applied: int, *, truncated: bool = False, error: str | None = None) -> dict:
    return {"site": "site-1", "error": error, "applied_count": applied, "truncated": truncated}


def test_an_empty_capacity_feed_drains_as_nothing_pending():
    admin = _FakeStorefrontAdmin(0, [_cycle(0)])
    assert drain_capacity_events(admin) == (0, 0)
    assert admin.ran == ["site-projections", "capacity-events"]


def test_a_truncated_capacity_feed_is_drained_across_cycles():
    admin = _FakeStorefrontAdmin(3, [_cycle(2, truncated=True), _cycle(1)])
    assert drain_capacity_events(admin) == (3, 3)
    assert admin.ran.count("capacity-events") == 2


def test_a_capacity_cycle_error_fails_the_drain():
    admin = _FakeStorefrontAdmin(1, [_cycle(0, error="feed unavailable")])
    with pytest.raises(AssertionError, match="feed unavailable"):
        drain_capacity_events(admin)


def test_fewer_events_applied_than_were_pending_fails_the_drain():
    admin = _FakeStorefrontAdmin(2, [_cycle(1)])
    with pytest.raises(AssertionError, match="applied 1 event"):
        drain_capacity_events(admin)


def test_a_feed_still_truncated_after_the_bound_fails_rather_than_reading_drained():
    admin = _FakeStorefrontAdmin(
        CAPACITY_EVENT_CYCLES, [_cycle(1, truncated=True)] * CAPACITY_EVENT_CYCLES,
    )
    with pytest.raises(AssertionError, match="still reports a truncated page"):
        drain_capacity_events(admin)
