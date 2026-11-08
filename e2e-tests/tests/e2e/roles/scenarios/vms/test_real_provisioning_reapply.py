"""Observation 6: both hosts' canonical registrations reapplied, then a publication cycle.

The runbook's observation 6
(``docs/development/VALIDATION_RUNBOOK.md#observations-the-qualification-owes``):
on the stack the other qualification modules ran on, once the storefronts
have stepped a publication cycle to catch up, the VM and bare-metal hosts the
real-provisioning target names are registered again exactly as their real
drivers register them (``seed_supply``), and the storefronts step another
publication cycle. Nothing changes: the listings a run left are adopted with
their identities, states and pauses intact; no host, pool, capacity
declaration or listing is duplicated; a relay port still quarantined keeps its
quarantine; and the bare-metal host's consumed-UID history, read through the
working-data operator route's ``policy`` operation before and after, is
unchanged. That route is independent of provisioning, whose reapplied
registration is under test.

It needs both hosts, the bare-metal lane's settings (``BARE_METAL_LANE``) and
the payments target, and is a blocked skip naming whichever is missing, before
any hold or write. It needs a listing on each host's resource, which the
qualification modules leave: without one, its first stage skips naming it.
Without the bare-metal target's ``cleanup_qualification`` the consumed-UID
stages skip, naming the field. Every stage requires observation 6, and the
module logs its outcome (``helpers/qualification.py``). It makes no deal, so it
has nothing to compensate. The module is in no lane.

It holds both storefronts' loops and the VM site's convergence and lease
watchdog. The bare-metal site's two timers are left running: that site may be
the same provisioning service as the VM site, and a second hold of one service
would resume it when the first ended. The module steps neither timer and
needs neither held: neither writes a host row, pool or capacity declaration;
a release writes a lease's release time only on a lease not yet released, and
its owner and grant expiry are written only when the port is leased, which
never takes a quarantined port. So neither can restore what a faulty reapply
removed. Relay-port reconciliation, which runs ungated on both sites, could
release again a lease the reapply un-released; the comparison catches that by
comparing each quarantined lease's whole record, its release time included
(``registration_faults``).

The observation is of an idle stack after the other modules' cleanup. A port
active before and released after is no fault, since an unheld watchdog may end
a live lease, so the module claims nothing about a live tenancy surviving; and
its quarantine and consumed-UID comparisons prove preservation only where the
state read before names some, which the logged snapshot shows.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import pytest
from compute_provisioning_client import SyncComputeProvisioningClient

from e2e_harness.real_provisioning_target import SECTION, BareMetalHost, VmHost
from e2e_harness.settings import settings
from tests.e2e.roles.helpers.compute_deal import (
    SiteCapacity,
    advance_storefront,
    dry_run_storefront,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.payments import configured_payments
from tests.e2e.roles.helpers.qualification import (
    RegistrationSnapshot,
    quarantined_ports,
    registration_faults,
    target_host,
)
from tests.e2e.roles.helpers.real_provisioning import JobWatch, configured_relay
from tests.e2e.roles.helpers.ssh_access import ssh_session
from tests.e2e.roles.scenarios.bare_metal.conftest import (  # noqa: F401 (fixtures)
    _pinned,
    _signer,
    bare_metal_site_capacity,
    bare_metal_site_operator,
    bare_metal_storefront_admin,
    bare_metal_storefront_loops_held,
    buyer_fulfillment,
    lane_setting,
)
from tests.e2e.roles.scenarios.bare_metal.real_compute_deal_driver import (
    REAL_RESOURCE_ID as BARE_METAL_RESOURCE_ID,
    RealBareMetalComputeDealDriver,
    bare_metal_executor_is_real,
)
from tests.e2e.roles.scenarios.bare_metal.working_data_qualification import (
    WorkingDataQualification,
)
from tests.e2e.roles.scenarios.vms.composed_listing import listings_on_resource, real_target_resource
from tests.e2e.roles.scenarios.vms.conftest import (
    capacity_site_id,
    capacity_source_for,
    one_site,
)
from tests.e2e.roles.scenarios.vms.real_compute_deal_driver import (
    REAL_RESOURCE_ID as VM_RESOURCE_ID,
    RealVmComputeDealDriver,
    vm_executor_is_real,
)

log = logging.getLogger(__name__)

#: The runbook observation every stage of this module requires.
OBSERVATIONS = ("6",)
#: Where the target names the working-data probe's inputs.
CLEANUP_FIELD = f"{SECTION}.hosts.bare_metal.cleanup_qualification"

pytestmark = [
    # Every target and both services' executions first, so a run missing any
    # holds and writes nothing. The holds follow, so they are released after
    # every other fixture; the VM lane's storefront cleanup follows them.
    pytest.mark.usefixtures(
        "payments_config", "real_vm_target", "real_bare_metal_target", "real_executions",
        "storefront_loops_held", "bare_metal_storefront_loops_held",
        "fulfillment_convergence_held", "lease_watchdog_held", "ensure_storefront_resumed",
    ),
    pytest.mark.e2e_real_provisioning_reapply,
]


@dataclass
class ReapplyState:
    """What the module's stages hand each other."""

    #: Each host's registration before and after, by domain.
    before: dict[str, RegistrationSnapshot] = field(default_factory=dict)
    after: dict[str, RegistrationSnapshot] = field(default_factory=dict)
    consumed_before: Optional[list[int]] = None
    _storefronts_settled: bool = False
    _registrations_reapplied: bool = False
    _publication_stepped: bool = False


# ---------------------------------------------------------------------------
# The targets, and what the module writes nothing before
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def payments_config():
    """The run's payments target, or a blocked skip naming it."""
    return configured_payments()


@pytest.fixture(scope="module")
def real_vm_target() -> VmHost:
    return target_host(settings, "vm")


@pytest.fixture(scope="module")
def real_bare_metal_target() -> BareMetalHost:
    if not settings.get("BARE_METAL_LANE"):
        pytest.skip("blocked: settings hold no BARE_METAL_LANE section for the bare-metal "
                    "storefront and site")
    host = target_host(settings, "bare_metal")
    assert host.access.mode == "relay", "the bare-metal qualification requires access.mode=relay"
    return host


@pytest.fixture(scope="module")
def bare_metal_provisioning_client():
    """The bare-metal site's family client, signed as its administrator."""
    client = SyncComputeProvisioningClient(
        lane_setting("site_url"), _signer("site_admin"), "admin", _pinned("site_authority"),
    )
    yield client
    client.close()


@pytest.fixture(scope="module")
def bare_metal_site_reads() -> SiteCapacity:
    return SiteCapacity(lane_setting("site_url"), _signer("site_admin"), _pinned("site_authority"))


@pytest.fixture(scope="module")
def real_executions(real_vm_target, real_bare_metal_target, provisioning_client,
                    bare_metal_provisioning_client):
    """Both services' executors, required real, and both relays configured."""
    executors = (
        vm_executor_is_real(provisioning_client.get_system_status().execution),
        bare_metal_executor_is_real(bare_metal_provisioning_client.get_system_status().execution),
    )
    configured_relay(provisioning_client, real_vm_target)
    configured_relay(bare_metal_provisioning_client, real_bare_metal_target)
    return executors


@pytest.fixture(scope="module", autouse=True)
def _ensure_provisioning_host_registered():
    """Registers nothing: this module writes only the targets' registrations."""


@pytest.fixture(scope="module")
def reapply_state() -> ReapplyState:
    return ReapplyState()


@pytest.fixture(scope="module")
def vm_driver(
    real_vm_target, provisioning_client, vm_operator_client, storefront_client,
    storefront_admin_client, storefront_service_client, site_capacity_admin_client, site_capacity,
) -> RealVmComputeDealDriver:
    """The VM host's canonical registration, as the real lanes reconcile it."""
    return RealVmComputeDealDriver(
        provisioning_client=provisioning_client, storefront_client=storefront_client,
        storefront_admin_client=storefront_admin_client,
        storefront_service_client=storefront_service_client,
        site_capacity_admin_client=site_capacity_admin_client, site_capacity=site_capacity,
        site_id=capacity_site_id(), vm_operator_client=vm_operator_client, target=real_vm_target,
        # This module makes no deal, so it negotiates no key.
        buyer_public_key="",
        listing_shape=capacity_source_for(real_target_resource(real_vm_target))["listing_shape"],
        jobs=JobWatch(provisioning_client),
    )


@pytest.fixture(scope="module")
def bare_metal_driver(
    real_bare_metal_target, bare_metal_provisioning_client, bare_metal_site_reads,
    bare_metal_site_operator, bare_metal_site_capacity, bare_metal_storefront_admin,
    buyer_fulfillment,
) -> RealBareMetalComputeDealDriver:
    """The bare-metal host's canonical registration, as the real lanes reconcile it."""
    return RealBareMetalComputeDealDriver(
        site_operator=bare_metal_site_operator, site_capacity_admin=bare_metal_site_capacity,
        provisioning_client=bare_metal_provisioning_client,
        storefront_admin_client=bare_metal_storefront_admin, fulfillment=buyer_fulfillment,
        site_capacity=bare_metal_site_reads, buyer_config={},
        site_id=lane_setting("site_id"), target=real_bare_metal_target,
        jobs=JobWatch(bare_metal_provisioning_client),
    )


@pytest.fixture(scope="module")
def uid_observer(real_bare_metal_target):
    """The working-data operator route, or ``None`` without its inputs."""
    if real_bare_metal_target.cleanup_qualification is None:
        yield None
        return
    with ssh_session(host_key=real_bare_metal_target.ssh_host_public_key) as session:
        yield WorkingDataQualification(real_bare_metal_target, session, [], "normal")


def _registration(provisioning_client: Any, site_capacity: Any, target: VmHost | BareMetalHost,
                  listings: list[Any], *, now: datetime) -> RegistrationSnapshot:
    hosts = provisioning_client.list_hosts(include_disabled=True).hosts
    declarations = [row for row in site_capacity.snapshot() if row.get("host_id") == target.host_id]
    quarantined, active = (), ()
    if target.access.mode == "relay":
        leases = provisioning_client.list_relay_leases(target.access.relay_id).leases
        quarantined = quarantined_ports(leases, now)
        active = tuple(sorted(lease.remote_port for lease in leases if lease.released_at is None))
    return RegistrationSnapshot(
        hosts=tuple(sorted((host.host_id, host.pool_id, host.enabled)
                           for host in hosts if host.host_id == target.host_id)),
        declarations=tuple(sorted((str(row.get("resource_id")), row.get("pool_id"))
                                  for row in declarations)),
        listings=tuple(sorted((str(listing.listing_id), listing.status, bool(listing.paused))
                              for listing in listings)),
        quarantined=quarantined,
        active_ports=active,
    )


def _bare_metal_listings(storefront_admin_client: Any, target: BareMetalHost) -> list[Any]:
    """Every bare-metal listing on the target's machine, whatever its status."""
    found, offset = [], 0
    while True:
        page = storefront_admin_client.list_listings(limit=200, offset=offset).listings
        found += [listing for listing in page
                  if listing.listing_resource.get("host_id") == target.host_id
                  and listing.listing_resource.get("physical_host_id") == target.physical_host_id]
        if len(page) < 200:
            return found
        offset += len(page)


def _registrations(
    provisioning_client, site_capacity, storefront_admin_client, real_vm_target,
    bare_metal_provisioning_client, bare_metal_site_reads, bare_metal_storefront_admin,
    real_bare_metal_target,
) -> dict[str, RegistrationSnapshot]:
    now = datetime.now(timezone.utc)
    return {
        "vm": _registration(
            provisioning_client, site_capacity, real_vm_target,
            listings_on_resource(storefront_admin_client, real_vm_target.resource_id or VM_RESOURCE_ID), now=now,
        ),
        "bare_metal": _registration(
            bare_metal_provisioning_client, bare_metal_site_reads, real_bare_metal_target,
            _bare_metal_listings(bare_metal_storefront_admin, real_bare_metal_target), now=now,
        ),
    }


#: How many capacity-event cycles draining the VM storefront's feed may take,
#: the bound a deal's reconciliation also allows.
CAPACITY_EVENT_CYCLES = 5


def drain_capacity_events(storefront_admin_client) -> tuple[int, int]:
    """Refresh the VM storefront's site projections and apply every capacity
    event pending, returning how many were pending and how many were applied.

    A deal's reconciliation (``step_listing_reconciliation``) requires events
    pending, since its deal reserved capacity. This module makes no deal, and a
    reapplied registration that changes nothing adds no event, so an empty feed
    is the expected case here. A cycle's error fails, and a feed still
    truncated after the bounded cycles fails rather than reading as drained.
    """
    pending = one_site(dry_run_storefront(storefront_admin_client, "capacity-events"))
    assert pending["error"] is None, (
        f"capacity-event dry run failed for site {pending['site']!r}: {pending['error']}"
    )
    assert not pending["would_position"], (
        "the dry run would position at the feed head rather than apply the pending "
        "events, so the poller's cursor was lost"
    )
    projections = advance_storefront(storefront_admin_client, "site-projections")
    assert projections.get("sites"), (
        "the site-projections advance reported no site state, so the projection "
        "the capacity cycle decides from was not refreshed"
    )
    applied = 0
    for step in range(CAPACITY_EVENT_CYCLES):
        cycle = one_site(advance_storefront(storefront_admin_client, "capacity-events"))
        assert cycle["error"] is None, (
            f"capacity-event cycle {step} failed for site {cycle['site']!r}: {cycle['error']}"
        )
        applied += int(cycle["applied_count"])
        if not cycle["truncated"]:
            break
    else:
        raise AssertionError(
            f"the capacity-event feed still reports a truncated page after "
            f"{CAPACITY_EVENT_CYCLES} cycles (applied {applied} events)"
        )
    assert applied >= pending["pending_count"], (
        f"the cycles applied {applied} event(s) where the dry run named "
        f"{pending['pending_count']} pending"
    )
    return pending["pending_count"], applied


def _publication_cycle(storefront_admin_client, bare_metal_storefront_admin) -> str:
    """One publication cycle on each storefront: VM's capacity events, bare
    metal's site projections and publication."""
    pending, applied = drain_capacity_events(storefront_admin_client)
    advance_storefront(bare_metal_storefront_admin, "site-projections")
    report = advance_storefront(bare_metal_storefront_admin, "publication")
    return (f"VM capacity events: {pending} pending, {applied} applied; bare-metal "
            f"publication: {[item.get('action') for item in report.get('actions') or []]}")


# ===========================================================================
# Before
# ===========================================================================

class TestStage00_StorefrontsSettled:
    def test_00_each_storefront_has_caught_up_before_the_read(
        self, storefront_admin_client, bare_metal_storefront_admin, reapply_state: ReapplyState,
    ):
        """A publication cycle before the read, so the state read before is
        what the earlier runs settled into, not what the storefronts' held
        loops had yet to apply: the observation is that one more cycle, after
        the registrations are reapplied, changes nothing."""
        log.info("[00] Settled: %s", _publication_cycle(storefront_admin_client,
                                                         bare_metal_storefront_admin))
        reapply_state._storefronts_settled = True


class TestStage01_RegistrationsBefore:
    def test_01_each_hosts_registration_and_listing_before_reapplying(
        self, provisioning_client, site_capacity, storefront_admin_client, real_vm_target,
        bare_metal_provisioning_client, bare_metal_site_reads, bare_metal_storefront_admin,
        real_bare_metal_target, reapply_state: ReapplyState,
    ):
        """Each host's registration, read before anything is reapplied. A
        resource no run has listed has nothing to adopt."""
        require_state(reapply_state, "_storefronts_settled")
        before = _registrations(
            provisioning_client, site_capacity, storefront_admin_client, real_vm_target,
            bare_metal_provisioning_client, bare_metal_site_reads, bare_metal_storefront_admin,
            real_bare_metal_target,
        )
        bare_metal_resource = real_bare_metal_target.resource_id or BARE_METAL_RESOURCE_ID
        for domain, resource in (("vm", real_vm_target.resource_id or VM_RESOURCE_ID), ("bare_metal", bare_metal_resource)):
            if not before[domain].listings:
                pytest.skip(f"no listing on the {domain} target's resource {resource} yet; run "
                            "e2e_vm_qualification and e2e_bare_metal_qualification first")
        reapply_state.before = before
        log.info("[01] Before: %s", before)


class TestStage02_ConsumedUidsBefore:
    def test_02_the_consumed_uid_history_before(
        self, uid_observer, reapply_state: ReapplyState,
    ):
        if uid_observer is None:
            pytest.skip(f"{CLEANUP_FIELD} is not set, so the consumed-UID history is unread")
        reapply_state.consumed_before = uid_observer.consumed_uids()
        log.info("[02] %d consumed UIDs before", len(reapply_state.consumed_before))


# ===========================================================================
# Reapplied
# ===========================================================================

class TestStage03_RegistrationsReapplied:
    def test_03_both_hosts_canonical_registrations_are_reapplied(
        self, vm_driver: RealVmComputeDealDriver, bare_metal_driver: RealBareMetalComputeDealDriver,
        reapply_state: ReapplyState,
    ):
        require_state(reapply_state, "before")
        vm_driver.seed_supply()
        bare_metal_driver.seed_supply()
        reapply_state._registrations_reapplied = True
        log.info("[03] Registrations reapplied: VM host %s (resource %s), bare-metal host %s "
                 "(resource %s)", vm_driver.target.host_id, vm_driver.reserved_resource_id,
                 bare_metal_driver.target.host_id, bare_metal_driver.reserved_resource_id)


class TestStage04_PublicationCycleStepped:
    def test_04_each_storefront_steps_a_publication_cycle(
        self, storefront_admin_client, bare_metal_storefront_admin, reapply_state: ReapplyState,
    ):
        require_state(reapply_state, "_registrations_reapplied")
        stepped = _publication_cycle(storefront_admin_client, bare_metal_storefront_admin)
        reapply_state._publication_stepped = True
        log.info("[04] %s", stepped)


# ===========================================================================
# After
# ===========================================================================

class TestStage05_RegistrationsUnchanged:
    def test_05_nothing_duplicated_dropped_or_changed(
        self, provisioning_client, site_capacity, storefront_admin_client, real_vm_target,
        bare_metal_provisioning_client, bare_metal_site_reads, bare_metal_storefront_admin,
        real_bare_metal_target, reapply_state: ReapplyState,
    ):
        require_state(reapply_state, "_publication_stepped")
        after = _registrations(
            provisioning_client, site_capacity, storefront_admin_client, real_vm_target,
            bare_metal_provisioning_client, bare_metal_site_reads, bare_metal_storefront_admin,
            real_bare_metal_target,
        )
        reapply_state.after = after
        now = datetime.now(timezone.utc)
        faults = [fault for domain in ("vm", "bare_metal")
                  for fault in registration_faults(domain, reapply_state.before[domain],
                                                   after[domain], now=now)]
        log.info("[05] After: %s", after)
        assert not faults, "; ".join(faults)


class TestStage06_ConsumedUidsUnchanged:
    def test_06_the_consumed_uid_history_is_unchanged(
        self, uid_observer, reapply_state: ReapplyState,
    ):
        if uid_observer is None:
            pytest.skip(f"{CLEANUP_FIELD} is not set, so the consumed-UID history is unread")
        require_state(reapply_state, "_publication_stepped")
        if reapply_state.consumed_before is None:
            pytest.skip("the consumed-UID history before reapplying was not read")
        after = uid_observer.consumed_uids()
        assert after == reapply_state.consumed_before, (
            f"the consumed-UID history changed from {reapply_state.consumed_before} to {after}"
        )
        log.info("[06] The consumed-UID history is unchanged: %d UIDs", len(after))
