"""System status reports every lifecycle loop and its last cycle's outcome.

Driven through the typed client against ``tests.publication_app``. The
publication cases make the cycle fail where it composes what it reads, through
the capacity runtime the cycle takes from the container, and read system
status: the publication loop's state and its last outcome, whether the
controller's timer or an operator's step ran the cycle. The capacity-event case
fails one site's feed and reads that site's poller's outcome.
"""

from __future__ import annotations

import asyncio
import logging

import pytest
from market_capacity_publication import CapacityConfigurationError
from storefront_client import StorefrontClientError

import market_storefront.container as container
from market_storefront import lifecycle, lifecycle_steps, startup
from tests.publication_app import SITE, publication_app

pytestmark = pytest.mark.asyncio

#: A configured site's authority URL, as an unexpected error's text may carry
#: one. A development value on a reserved domain.
_SITE_URL = "http://site-a.invalid:8081"


class _FailingCapacity:
    """The capacity runtime a publication cycle reads first, failing there.

    ``started`` is set as each cycle reaches it, so a test knows a timer's
    cycle has run without waiting on time.
    """

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.started = asyncio.Event()

    @property
    def site_ids(self) -> tuple[str, ...]:
        self.started.set()
        raise self.error


@pytest.fixture
async def lifecycle_registry():
    """A clean loop registry and pause flag, as a fresh process has; any timer
    a test started is cancelled and awaited before its event loop closes."""
    await lifecycle.reset_for_tests()
    yield
    await lifecycle.reset_for_tests()


@pytest.fixture
async def world(tmp_path, lifecycle_registry):
    async with publication_app(tmp_path) as app:
        yield app


def _failing(monkeypatch, error: Exception) -> _FailingCapacity:
    capacity = _FailingCapacity(error)
    monkeypatch.setattr(container, "resolved_capacity_runtime", capacity)
    return capacity


async def _publication_status(world) -> dict:
    status = await world.client.get_system_status()
    return status.lifecycle[lifecycle.PUBLICATION]


async def test_publication_failing_every_timer_cycle_is_reported_running_and_failed(
    world, monkeypatch
):
    """Spec scenario "Publication fails every cycle": the loop is reported
    running and its last cycle failed, with the storefront's own
    configuration error named in full."""
    capacity = _failing(
        monkeypatch,
        CapacityConfigurationError("capacity site 'site-a' requires an authority URL"),
    )
    lifecycle_steps.register_vm_loops()
    lifecycle.start_loops()
    await asyncio.wait_for(capacity.started.wait(), timeout=1)

    publication = await _publication_status(world)

    assert publication["state"] == "running"
    outcome = publication["last_outcome"]
    assert outcome["trigger"] == "timer"
    assert outcome["completed"] is False
    assert outcome["stage"] == "compose"
    assert outcome["error"] == {
        "type": "CapacityConfigurationError",
        "message": "capacity site 'site-a' requires an authority URL",
    }


async def test_a_stepped_cycle_failing_on_an_unexpected_error_is_reported_by_type(
    world, monkeypatch
):
    """Spec scenarios "A stepped cycle fails" and "A cycle fails on an
    unexpected exception": the step's failure is recorded as the timer's would
    be, naming its stage and the error's type and not its text, which names a
    site URL."""
    _failing(monkeypatch, ConnectionError(f"{_SITE_URL} refused the connection"))
    before = await _publication_status(world)
    assert before["state"] is None and before["last_outcome"] is None

    with pytest.raises(StorefrontClientError) as failed:
        await world.client.admin_run_lifecycle_cycle("publication")
    assert failed.value.status_code == 500
    assert _SITE_URL not in str(failed.value)

    publication = await _publication_status(world)
    outcome = publication["last_outcome"]
    assert outcome["trigger"] == "step"
    assert outcome["completed"] is False
    assert outcome["stage"] == "compose"
    assert outcome["error"] == {"type": "ConnectionError", "message": None}
    assert _SITE_URL not in str(await world.client.get_system_status())


async def test_every_loop_is_reported_with_its_state(world):
    """Held from the start: each loop startup registers is reported paused,
    with no cycle recorded yet."""
    await world.client.admin_pause_lifecycle_loops()
    lifecycle_steps.register_vm_loops()
    lifecycle.start_loops()
    await world.client.admin_pause_lifecycle_loops()

    loops = (await world.client.get_system_status()).lifecycle

    for name in (
        lifecycle.NEGOTIATION_WATCHDOG,
        lifecycle.SETTLEMENT_SERVICING,
        lifecycle.FULFILLMENT_RESUME,
        lifecycle.SITE_PROJECTION_POLLER,
        lifecycle.PUBLICATION,
        lifecycle.CAPACITY_EVENTS_POLLER,
        lifecycle.capacity_site_loop_name(SITE),
    ):
        assert loops[name]["state"] == "paused", name
        assert loops[name]["last_outcome"] is None, name


class _FailedCycleSeen(logging.Handler):
    """Set once the loop controller logs a failed cycle of loop ``name``.

    The controller logs each failure as it records it, so this is the point a
    test can read status at, with no wait on time.
    """

    def __init__(self, name: str) -> None:
        super().__init__(level=logging.ERROR)
        self.name_ = name
        self.seen = asyncio.Event()

    def emit(self, record: logging.LogRecord) -> None:
        if record.args and record.args[0] == self.name_:
            self.seen.set()


async def test_a_sites_failing_capacity_event_feed_is_reported_under_its_loop(world):
    """Each site's capacity-event poller records its timer cycles' outcomes
    under the site's own loop name, the failure by type alone: its text names
    the site's address."""
    world.site.reachable = False
    name = lifecycle.capacity_site_loop_name(SITE)
    seen = _FailedCycleSeen(name)
    lifecycle_logger = logging.getLogger(lifecycle.__name__)
    lifecycle_logger.addHandler(seen)
    try:
        # The fan-out alone, as startup registers it; no timer runs beside it.
        lifecycle_steps.register_capacity_events_fan_out()
        lifecycle.start_loops()
        await asyncio.wait_for(seen.seen.wait(), timeout=1)
    finally:
        lifecycle_logger.removeHandler(seen)

    loops = (await world.client.get_system_status()).lifecycle

    assert loops[name]["state"] == "running"
    outcome = loops[name]["last_outcome"]
    assert outcome["trigger"] == "timer"
    assert outcome["completed"] is False
    assert outcome["error"] == {"type": "SiteCapacityClientError", "message": None}
    # The aggregate loop runs no cycle of its own to record.
    assert loops[lifecycle.CAPACITY_EVENTS_POLLER]["last_outcome"] is None
