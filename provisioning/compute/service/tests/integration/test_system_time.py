"""The provisioning service's time: its setting, its time route, its status, and
the lease lifecycle following it.

The running service through the family client, signed as the administrator, as
every system test is; the storefront's view through the family client signed as
the seller. The client and the service read this process's one time source, so
a setting moves both. The service mounts its time route only when its source is
injected when it is imported, which this suite's process is not, so an injected
test mounts the route on the suite's app as the service would, as the suite
mounts the mock profile's routers. Once mounted, the route sets nothing under
wall time and answers 404, as the unmounted route's absence does.

Identities and origins are deterministic development fixtures, never used on a
public network.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone

import injected_time
import pytest
from compute_provisioning_client import ComputeProvisioningError
from compute_provisioning_contracts import LeaseTermination, verify_lease_end
from injected_time import InjectedTime, WallTime

from compute_provisioning_service import container
from compute_provisioning_service.controllers.system_controller import make_time_router
from compute_provisioning_service.main import app

from .conftest import SERVICE_AUTHORITIES, STOREFRONT_SIGNER, mount_unless_served
from .test_leases_api import _committed, seller  # noqa: F401 - a fixture these tests take

T = 1794822300


@pytest.fixture
def installed_source():
    """Restore the process source after a test installs its own."""
    before = injected_time.installed()
    yield
    injected_time.install(before)


@pytest.fixture
def injected_source(installed_source):
    """The process source, injected a minute before ``T``, with the time route
    mounted as an injected service mounts it."""
    source = InjectedTime(start=T - 60)
    injected_time.install(source)
    mount_unless_served(app, make_time_router())
    return source


async def test_an_injected_service_is_set_through_its_route_and_reports_it(
    injected_source, client_and_queue
):
    clients, _ = client_and_queue

    before = await clients.family.get_system_status()
    answer = await clients.family.set_time(T)
    after = await clients.family.get_system_status()
    with pytest.raises(ComputeProvisioningError) as backward:
        await clients.family.set_time(T - 60)
    with pytest.raises(ComputeProvisioningError) as invalid:
        await clients.family.set_time(True)  # type: ignore[arg-type]
    held = await clients.family.get_system_status()

    assert before.time == {"source": "injected", "now": T - 60}
    assert (answer.source, answer.now) == ("injected", T)
    assert after.time == {"source": "injected", "now": T}
    # The client raises with the refusal's detail; its code is the component's
    # refusal of that kind.
    assert backward.value.status_code == 409
    assert "only forward" in str(backward.value)
    assert invalid.value.status_code == 422
    assert held.time == {"source": "injected", "now": T}


async def test_a_wall_time_service_sets_no_time_and_reports_wall(
    installed_source, client_and_queue
):
    injected_time.install(WallTime())
    clients, _ = client_and_queue

    status = await clients.family.get_system_status()
    with pytest.raises(ComputeProvisioningError) as missing:
        await clients.family.set_time(T)

    assert status.time == {"source": "wall"}
    assert missing.value.status_code == 404


async def test_a_truncated_lease_ends_by_expiry_at_the_instant_set(
    injected_source, client_and_queue, seller
):
    """`physical-provisioning`'s "A truncated lease ends at the set instant":
    a lease ending at T, the watchdog held, is left by a cycle a minute before T
    and ended by expiry, effective and claimed at T, by the cycle after the
    service is set to T."""
    clients, _ = client_and_queue
    ledger = container.resolved_capacity_ledger_service
    reservation = _committed("fixture-expiry")
    await clients.site.truncate_lease(
        capacity_reservation_id=reservation,
        lease_end_utc=datetime.fromtimestamp(T, timezone.utc).isoformat(),
    )
    await clients.family.pause_lease_watchdog()

    early = await clients.family.check_leases()
    await clients.family.set_time(T)
    due = await clients.family.check_leases()

    assert early.released == 0
    assert due.released == 1
    (report,) = (await seller.get_lease(reservation)).end_reports
    event = verify_lease_end(
        report,
        capacity_reservation_id=reservation,
        site_id=ledger.lease_end_events(reservation)[0]["site_id"],
        expected_sites=SERVICE_AUTHORITIES,
    )
    assert (event.cause, event.effective_at, event.claimed_deadline) == ("expiry", T, T)


async def test_a_termination_states_the_injected_instant(
    injected_source, client_and_queue, seller
):
    """`physical-provisioning`'s "A termination is stamped in lane time"."""
    clients, _ = client_and_queue
    ledger = container.resolved_capacity_ledger_service
    reservation = _committed("fixture-termination")
    await clients.family.set_time(T)

    await seller.terminate_lease(reservation, LeaseTermination(reason="fixture maintenance"))

    (report,) = (await seller.get_lease(reservation)).end_reports
    event = verify_lease_end(
        report,
        capacity_reservation_id=reservation,
        site_id=ledger.lease_end_events(reservation)[0]["site_id"],
        expected_sites=SERVICE_AUTHORITIES,
    )
    assert (event.cause, event.effective_at) == ("termination", T)
    assert event.caller == STOREFRONT_SIGNER.identity


def test_a_service_started_with_a_misspelled_source_refuses_naming_it():
    """The composition root itself, started in a process of its own with
    ``time.source`` set through the loader's override layer."""
    started = subprocess.run(
        [sys.executable, "-c", "import compute_provisioning_service.main"],
        env={**os.environ, "PROVISIONING_TIME__SOURCE": "injectd"},
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert started.returncode != 0
    assert "InvalidTimeSource: time.source is \"wall\" or \"injected\", not 'injectd'" in (
        started.stderr
    )
