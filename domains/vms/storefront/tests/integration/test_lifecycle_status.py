"""System status reports every lifecycle loop and its last cycle's outcome.

Driven through the typed client against ``tests.publication_app``; the
deal-servicing case runs on ``tests.recurring_world``, whose served storefront
settles a deal through the typed buyer client. The
publication cases make the cycle fail where it composes what it reads, through
the capacity runtime the cycle takes from the container, and read system
status: the publication loop's state and its last outcome, whether the
controller's timer or an operator's step ran the cycle. The capacity-event case
fails one site's feed and reads that site's poller's outcome. The chain-probe
case steps the ``alkahest-chain-probe`` loop over a probe whose JSON-RPC
boundary refuses, then answers, and reads Alkahest's readiness in status, which
the harness's settlement double evaluates through the real registry.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import pytest
from market_alkahest import AlkahestChainProbe, ProbedChain
from market_capacity_publication import CapacityConfigurationError
from storefront_client import StorefrontClientError

from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction

import market_storefront.container as container
from market_storefront import lifecycle, lifecycle_steps, startup
from tests._settings_overrides import settings_overrides
from tests.integration.test_rate_delivery import accepted_recurring_deal, approve
from tests.publication_app import SITE, publication_app
from tests.recurring_world import recurring_world, settlement

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
    lifecycle_steps.register_vm_loops(alkahest_probe_interval_seconds=30.0)
    lifecycle.start_loops()
    await world.client.admin_pause_lifecycle_loops()

    loops = (await world.client.get_system_status()).lifecycle

    for name in (
        lifecycle.NEGOTIATION_WATCHDOG,
        lifecycle.DEAL_SERVICING,
        lifecycle.DELIVERY_RECOVERY,
        lifecycle.PAYMENT_RECONCILIATION,
        lifecycle.SETTLEMENT_SERVICING,
        lifecycle.SITE_PROJECTION_POLLER,
        lifecycle.PUBLICATION,
        lifecycle.CAPACITY_EVENTS_POLLER,
        lifecycle.capacity_site_loop_name(SITE),
        lifecycle.ALKAHEST_CHAIN_PROBE,
    ):
        assert loops[name]["state"] == "paused", name
        assert loops[name]["last_outcome"] is None, name


async def test_unstated_servicing_intervals_are_those_their_jobs_ran_at(world):
    """``deal-servicing`` runs at the settlement servicing interval and
    ``delivery-recovery`` at ``fulfillment_resume_sweep_interval`` until each
    states its own key; the other two loops keep their keys."""
    with settings_overrides(settlement_servicing_interval_seconds=45, fulfillment_resume_sweep_interval=20):
        unstated = lifecycle_steps.register_vm_loops()
    await lifecycle.reset_for_tests()
    with settings_overrides(
        settlement_servicing_interval_seconds=45, fulfillment_resume_sweep_interval=20,
        deal_servicing_interval_seconds=7, delivery_recovery_interval_seconds=9,
    ):
        stated = lifecycle_steps.register_vm_loops()

    servicing = (
        lifecycle.DEAL_SERVICING, lifecycle.DELIVERY_RECOVERY,
        lifecycle.PAYMENT_RECONCILIATION, lifecycle.SETTLEMENT_SERVICING,
    )
    assert [unstated[name] for name in servicing] == [45, 20, 20, 45]
    assert [stated[name] for name in servicing] == [7, 9, 20, 45]


async def test_a_servicing_interval_that_is_not_positive_seconds_is_refused_by_key(world):
    with settings_overrides(deal_servicing_interval_seconds=0):
        with pytest.raises(ValueError, match="deal_servicing_interval_seconds"):
            lifecycle_steps.register_vm_loops()


async def test_stepping_deal_servicing_runs_one_cycle_and_re_drives_no_delivery(tmp_path, lifecycle_registry):
    """A deal left undelivered by an unreachable site is serviced by a step of
    ``deal-servicing`` — its payment authority read — and not re-driven, though
    the site answers again: re-driving is ``delivery-recovery``'s alone."""
    async with recurring_world(tmp_path) as world, settlement(world) as settled:
        negotiation_id, data = await accepted_recurring_deal(world)
        approve(settled, data)
        settled.site.unreachable = True
        await world.app.buyer.settle_agreement(negotiation_id)
        await settled.delivered(negotiation_id)
        assert settled.site.rows == {}
        settled.site.unreachable = False
        await world.app.client.admin_pause_lifecycle_loops()
        reads = settled.payments.count("get_transaction")

        stepped = await world.app.client.admin_run_lifecycle_cycle("deal-servicing")

        with transaction(world.app.db.db_path) as conn:
            record = EndSession(conn).read(negotiation_id)
    assert stepped["loop"] == lifecycle.DEAL_SERVICING and stepped["processed"] >= 1
    assert settled.payments.count("get_transaction") > reads
    assert settled.site.rows == {} and record.available_at is None


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


class _Rpc:
    """The chain's JSON-RPC endpoint, the boundary the probe calls: refusing
    connections until ``answering`` is set."""

    def __init__(self) -> None:
        self.answering = False

    def __call__(self, rpc_url, method, params, timeout):
        if not self.answering:
            raise ConnectionRefusedError("connection refused")
        return hex(31337) if method == "eth_chainId" else "0x6080"


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now


def _alkahest(status) -> dict:
    (alkahest,) = [item for item in status.settlement if item["mechanism"] == "alkahest.v1"]
    return alkahest


async def test_a_storefront_whose_chain_refuses_is_unready_until_a_stepped_probe_reaches_it(
    world, monkeypatch
):
    """Spec scenario "A storefront starts with its chain down": Alkahest is
    unready with the reachability blocker until a probe succeeds, then ready,
    with no restart; status reports the probe's result and when it was taken."""
    rpc, clock = _Rpc(), _Clock()
    probe = AlkahestChainProbe(
        [ProbedChain(name="anvil", rpc_url="http://anvil.test", chain_id=31337)],
        json_rpc=rpc,
        required_addresses=lambda _chain: {"escrow": "0x" + "11" * 20},
        clock=clock,
    )
    monkeypatch.setattr(container, "resolved_alkahest_chain_probe", probe)
    monkeypatch.setattr(container, "resolved_settlement_composition", world.composition)

    unprobed = _alkahest(await world.client.get_system_status())
    assert unprobed["ready"] is False
    assert [(b["code"], b["kind"]) for b in unprobed["blockers"]] == [
        ("alkahest.chain_unreachable", "reachability")
    ]
    assert unprobed["public_details"]["chain_probe"] == {"anvil": None}

    await world.client.admin_run_lifecycle_cycle("alkahest-chain-probe")
    refused = _alkahest(await world.client.get_system_status())
    assert [(b["code"], b["kind"]) for b in refused["blockers"]] == [
        ("alkahest.chain_unreachable", "reachability")
    ]
    assert refused["public_details"]["chain_probe"] == {
        "anvil": {"result": "alkahest.chain_unreachable", "probed_at": clock.now.isoformat()}
    }

    # A step probes at once, with no interval to wait out.
    rpc.answering = True
    stepped = await world.client.admin_run_lifecycle_cycle("alkahest-chain-probe")
    assert stepped["probed"] == ["anvil"]

    ready = _alkahest(await world.client.get_system_status())
    assert ready["ready"] is True
    assert ready["blockers"] == []
    assert ready["public_details"]["chain_probe"]["anvil"]["result"] == "reachable"
