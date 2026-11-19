"""Stages of the buyer watchdog's delivered-deal cases, on one rate deal per lane.

Each compute lane runs one module, on a deal of its own, bought through the
shipped buyer run in the harness's process (``in_process_buyer.py``) with a
default buyer under the on-demand preset, opting into the watchdog with a
one-second interval and a threshold of two. The module shares the recurring
purchase's stages through ``Recurring06`` (``recurring_purchase_stages.py``):
the listing, the purchase, delivery at the Agreement's start and the rate
part's start, while the buyer's ``buy`` waits for its deal at the harness's
gate. It then runs the four cases in the one order a deal allows, since once
the watchdog journals its stop the buyer's read shows ``stopped``:

- **monitored from available** — the wait released, the same ``buy`` reads its
  deal available and enters its watchdog, which probes the endpoint the deal
  disclosed; one interval released, the buyer's read shows ``monitored``
  (``Watchdog01``), and again once lane time is a minute into the first period,
  so the later stop charges the started period (``Watchdog02``);
- **killed, then stale** — an interrupt at the gate ends the command, its read
  still ``monitored``; lane time set past its last probe by one interval, the
  probe timeout and the grace a reader allows, the read shows ``unmonitored``,
  and nothing was sent (``Watchdog03``);
- **resumed** — ``buy --from`` re-enters the watchdog; one interval released,
  the read shows ``monitored`` (``Watchdog04``);
- **access lost while the storefront is paused** — the storefront's loops are
  held for the module, the paused storefront the case needs; the probe answers
  unreachable for the threshold of released intervals, and the watchdog sends
  one payer stop and hint, accepted at the payments double, whose events are
  then the storefront's ``start`` and the payer's ``stop``, nothing between; the
  command ends ``stopped``; on the hint the storefront recorded the payer's end
  with no filing, and a ``deal-servicing`` step begins the teardown
  (``Watchdog05``), which ``Stage11a2`` and ``Stage11b`` complete.

The probe answers as the stage programs it and the watchdog's waits move only
as the stage releases them, so no probe leaves the harness and no case waits
on real time; staleness is reached by setting lane time, which the buyer's
probes are stamped with and its read compares against. No instant passes the
part's first reservation, so the modules reserve nothing further. The cases
need injected lane time and the lane's own payments double, so anywhere else
the in-process buyer is a blocked skip, and every stage reading what it ran.
Each module is lane-double evidence.

What differs between domains reaches a stage through the ``deal_driver``
fixture, a ``RateWatchdogDriver``: how the domain's ``buy`` resumes, the
endpoint the storefront disclosed for the deal, and the endpoint the domain's
probe factory was given.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional, Protocol

import pytest
from market_deal_lifecycle_buyer.watchdog import GRACE_SECONDS

from tests.e2e.roles.helpers.compute_deal import (
    advance_storefront,
    assert_lease_watchdog_held,
    assert_storefront_loops_held,
)
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.lane_time import LaneTime
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    PERIOD_GROSS,
    STOP_INTO_PERIOD_SECONDS,
    RecurringPurchaseDriver,
    RecurringPurchaseState,
    begin_teardown,
    buyer_read,
    lane_double_run,
    transaction_snapshot,
)

log = logging.getLogger(__name__)

#: The watchdog's opt-in: a probe every second, a stop after two failures in a
#: row. Its probe timeout is the default, shortened to the interval.
WATCHDOG_INTERVAL_SECONDS = 1
WATCHDOG_THRESHOLD = 2
WATCHDOG_PROBE_TIMEOUT_SECONDS = 1
WATCHDOG_OPT_IN = (
    "--watchdog", "--watchdog-interval", str(WATCHDOG_INTERVAL_SECONDS),
    "--watchdog-threshold", str(WATCHDOG_THRESHOLD),
)
#: The settings the watchdog records it started with.
WATCHDOG_SETTINGS = {
    "interval_seconds": WATCHDOG_INTERVAL_SECONDS, "threshold": WATCHDOG_THRESHOLD,
    "probe_timeout_seconds": WATCHDOG_PROBE_TIMEOUT_SECONDS,
}
#: How long after its last probe a deal's read stays ``monitored``.
FRESH_SECONDS = WATCHDOG_INTERVAL_SECONDS + WATCHDOG_PROBE_TIMEOUT_SECONDS + GRACE_SECONDS


@dataclass
class RateWatchdogState(RecurringPurchaseState):
    """What the watchdog cases' stages hand each other, beside the recurring purchase's."""

    #: The endpoint the storefront disclosed for the deal, as (host, port).
    disclosed_endpoint: Optional[tuple[str, int]] = None
    #: The lane instant the buyer's read last showed the watchdog's last probe at.
    last_probe_at: Optional[int] = None
    #: The resumed ``buy --from`` run.
    resumed_run: Optional[Any] = None
    #: The fresh ``buy`` entered its watchdog from ``available`` and its read
    #: showed ``monitored``.
    _watchdog_monitored: bool = False
    #: Lane time is a minute into the first period, the read still ``monitored``.
    _into_first_period: bool = False
    #: The interrupted command's read went ``unmonitored`` once its last probe
    #: was stale.
    _watchdog_stale: bool = False
    #: The resumed run's read showed ``monitored``.
    _watchdog_resumed: bool = False


class RateWatchdogDriver(RecurringPurchaseDriver, Protocol):
    """What a domain supplies to the watchdog cases, beside a recurring purchase's part.

    Its ``buy_arguments`` opt into the watchdog (``WATCHDOG_OPT_IN``).
    """

    def resume_arguments(self, run_id: str) -> list[str]:
        """The domain's ``buy`` resuming the run, and its arguments."""

    def disclosed_endpoint(self, negotiation_id: str) -> tuple[str, int]:
        """The SSH endpoint the storefront disclosed for the deal, as its buyer reads it."""

    def probed_endpoint(self, built_for: Any) -> tuple[str, int]:
        """The endpoint the domain's probe factory was given, as (host, port)."""


def require_watchdog_lane(lane_time: LaneTime | None) -> None:
    """A blocked skip unless the run is a Compose lane's: injected lane time, which
    staleness is reached by, and the lane's own payments double, which the
    watchdog's stop lands at."""
    if not lane_double_run(lane_time):
        pytest.skip("blocked: the watchdog cases set lane time and stop the deal at the lane's "
                    "own payments double, which only a Compose lane's injected run with its own "
                    "payments target reaches (PAYMENTS.LANE_OWNED)")


def watchdog_view(purchase_cli: Any, deal_driver: RateWatchdogDriver,
                  deal_state: RateWatchdogState) -> tuple[str, Optional[int]]:
    """The watchdog status the buyer's read shows, and the probe instant it rests on."""
    view = buyer_read(purchase_cli, deal_driver, deal_state)["watchdog"]
    return view["status"], view["last_probe_at"]


def _events(run: Any, name: str) -> list[dict[str, Any]]:
    """The run log's events named ``name``: what a background command records,
    which a stage reads rather than its streams (``in_process_buyer.py``)."""
    return [event for event in run.read_events() if event.get("event") == name]


def _monitored_at(purchase_cli: Any, deal_driver: RateWatchdogDriver,
                  deal_state: RateWatchdogState, lane_time: LaneTime) -> int:
    """The read shows ``monitored``, resting on a probe stamped at the lane's instant."""
    status, last_probe_at = watchdog_view(purchase_cli, deal_driver, deal_state)
    assert (status, last_probe_at) == ("monitored", lane_time.now()), (
        f"the buyer's read shows the watchdog {status} with its last probe at "
        f"{last_probe_at}; the lane is at {lane_time.now()}"
    )
    return last_probe_at


# ===========================================================================
# Monitored from available
# ===========================================================================

class Watchdog01_MonitoredFromAvailable:
    def test_w01_the_waiting_buy_enters_its_watchdog_from_available(
        self, purchase_cli, lane_time, deal_driver: RateWatchdogDriver,
        deal_state: RateWatchdogState,
    ):
        """The fresh ``buy``, parked at the gate while it waited for its deal,
        is released: it reads the deal available and enters its watchdog.

        Delivery has been stepped while the command waited (``Recurring05`` to
        ``Recurring06``), and nothing was probed while it did. Released, the
        same command reads the deal available, probes once at once and parks
        at its watchdog's first interval; that probe was built for the
        endpoint the storefront disclosed for the deal. One interval released
        with the probe reachable, the buyer's read shows ``monitored``, resting
        on a probe stamped at the lane's instant.
        """
        require_state(deal_state, "purchase_run", "negotiation_id", "_rate_started")
        probe = purchase_cli.probe
        purchase_cli.wait_parked()
        assert probe.built_for == [], (
            f"a probe was built before the deal was available: {probe.built_for}"
        )
        purchase_cli.release()
        run = deal_state.purchase_run
        assert not run.exited, (
            f"the buy ended (exit {run.returncode}) instead of watching its deal: "
            f"{run.stderr()[-1500:]}"
        )
        assert len(probe.built_for) == 1 and probe.answered == [True], probe
        disclosed = deal_driver.disclosed_endpoint(deal_state.negotiation_id)
        probed = deal_driver.probed_endpoint(probe.built_for[0])
        assert probed == disclosed, (
            f"the watchdog's probe was built for {probed}; the deal disclosed {disclosed}"
        )
        (started,) = _events(run, "watchdog_started")
        settings = {key: started.get(key) for key in WATCHDOG_SETTINGS}
        assert settings == WATCHDOG_SETTINGS, started

        purchase_cli.release()
        assert probe.answered == [True, True], probe
        deal_state.last_probe_at = _monitored_at(purchase_cli, deal_driver, deal_state, lane_time)
        deal_state.disclosed_endpoint = disclosed
        deal_state._watchdog_monitored = True
        log.info("[w01] Run %s watched Agreement %s from available, probing %s:%s; read "
                 "monitored at %s", run.run_id, deal_state.negotiation_id, *disclosed,
                 deal_state.last_probe_at)


class Watchdog02_IntoTheFirstPeriod:
    def test_w02_lane_time_moves_into_the_first_period_and_the_watchdog_keeps_probing(
        self, purchase_cli, lane_time, deal_driver: RateWatchdogDriver,
        deal_state: RateWatchdogState,
    ):
        """Lane time is set a minute into the first period, as the recurring
        purchase's buyer end is (``STOP_INTO_PERIOD_SECONDS``), so the
        watchdog's later stop charges the started period, which a stop at the
        start itself would leave uncharged. One interval released with the
        probe reachable, the read shows ``monitored`` at that instant."""
        require_state(deal_state, "_watchdog_monitored", "agreement_start")
        instant = int(deal_state.agreement_start.timestamp()) + STOP_INTO_PERIOD_SECONDS
        lane_time.reach(instant, fixed_by_agreement=False)
        purchase_cli.release()
        deal_state.last_probe_at = _monitored_at(purchase_cli, deal_driver, deal_state, lane_time)
        deal_state._into_first_period = True
        log.info("[w02] Lane at %s, a minute into the first period; read monitored", instant)


# ===========================================================================
# Killed, then stale
# ===========================================================================

class Watchdog03_KilledCommandGoesStale:
    def test_w03_a_killed_command_reads_unmonitored_once_its_last_probe_is_stale(
        self, purchase_cli, payments_config, lane_time, deal_driver: RateWatchdogDriver,
        deal_state: RateWatchdogState,
    ):
        """An interrupt at the gate ends the command as a buyer's interrupt does.

        The command ends successfully, its watchdog having recorded no exit:
        the buyer stopped it before it decided to stop, and it journaled no
        stop. Its last probe is still fresh, so the read still shows
        ``monitored``: the status rests on the probes, not on the command. Lane
        time set past that probe by one interval, the probe timeout and the
        grace a reader allows, the read shows ``unmonitored``, and the payments
        double records no stop.
        """
        require_state(deal_state, "_into_first_period", "last_probe_at", "payer_account",
                      "settlement_id")
        run = purchase_cli.interrupt()
        assert run.returncode == 0, f"the interrupted buy exited {run.returncode}: {run.stderr()}"
        assert _events(run, "watchdog_exited") == [], _events(run, "watchdog_exited")
        status, _ = watchdog_view(purchase_cli, deal_driver, deal_state)
        assert status == "monitored", status

        stale = deal_state.last_probe_at + FRESH_SECONDS + 1
        lane_time.reach(stale, fixed_by_agreement=False)
        status, last_probe_at = watchdog_view(purchase_cli, deal_driver, deal_state)
        assert (status, last_probe_at) == ("unmonitored", deal_state.last_probe_at), (
            status, last_probe_at,
        )
        (part,) = transaction_snapshot(payments_config, deal_state.payer_account,
                                       deal_state.settlement_id)["parts"]
        assert part.get("stop") is None, f"the killed watchdog sent a stop: {part}"
        deal_state._watchdog_stale = True
        log.info("[w03] Run %s interrupted; read unmonitored at lane %s, its last probe at %s",
                 run.run_id, stale, last_probe_at)


# ===========================================================================
# Resumed
# ===========================================================================

class Watchdog04_ResumedRunMonitored:
    def test_w04_the_resumed_run_re_enters_its_watchdog(
        self, purchase_cli, lane_time, deal_driver: RateWatchdogDriver,
        deal_state: RateWatchdogState,
    ):
        """``buy --from`` resumes the run: it finds its deal available, re-enters
        the watchdog the deal opted into, probes the same endpoint at once and
        parks at the watchdog's first interval. One interval released with the
        probe reachable, the read shows ``monitored`` again."""
        require_state(deal_state, "_watchdog_stale", "purchase_run", "negotiation_id",
                      "disclosed_endpoint")
        probe = purchase_cli.probe
        resumed = purchase_cli.run(
            deal_driver.resume_arguments(deal_state.purchase_run.run_id), background=True,
        )
        deal_state.resumed_run = resumed
        purchase_cli.wait_parked()
        assert len(probe.built_for) == 2, probe
        assert deal_driver.probed_endpoint(probe.built_for[-1]) == deal_state.disclosed_endpoint
        purchase_cli.release()
        deal_state.last_probe_at = _monitored_at(purchase_cli, deal_driver, deal_state, lane_time)
        deal_state._watchdog_resumed = True
        log.info("[w04] Run %s resumed; read monitored at %s", deal_state.purchase_run.run_id,
                 deal_state.last_probe_at)


# ===========================================================================
# Access lost while the storefront is paused
# ===========================================================================

class Watchdog05_AccessLostStopsOnce:
    def test_w05_lost_access_yields_one_buyer_stop_with_the_storefront_paused(
        self, purchase_cli, payments_config, provisioning_client, storefront_admin_client,
        deal_driver: RateWatchdogDriver, deal_state: RateWatchdogState,
    ):
        """The probe answers unreachable for the threshold of intervals, and the
        watchdog sends one payer stop and hint.

        The storefront's loops are held for the module, so no time-based signal
        of its own — a term end, a teardown, a filing — can come between: the
        payments double's events for the transaction are the storefront's
        ``start`` and then the payer's ``stop``, the part stopped by the payer
        and its started period charged. The command ends ``stopped``. On the
        hint, before any loop is stepped, the storefront recorded the payer's
        end with no filing; one ``deal-servicing`` step then carries out that
        end at the site (bare metal's hint already has) and the teardown begins
        (``begin_teardown``).
        """
        require_state(deal_state, "_watchdog_resumed", "_teardown_gate_armed", "payer_account",
                      "settlement_id", "negotiation_id", "deal_lease", "lease_id",
                      "reserved_resource_id")
        assert_storefront_loops_held(storefront_admin_client)
        # The release is Stage11b's own lease cycle, not the timer's.
        assert_lease_watchdog_held(provisioning_client)
        probe = purchase_cli.probe
        probe.reachable = False
        # From here the deal is being ended by the watchdog's stop, so cleanup
        # sends no stop of the buyer's own.
        deal_state._deal_ending = True
        answered = len(probe.answered)
        purchase_cli.release(WATCHDOG_THRESHOLD)
        run = purchase_cli.wait_ended()
        assert probe.answered[answered:] == [False] * WATCHDOG_THRESHOLD, probe
        assert run.returncode == 0, f"the resumed buy exited {run.returncode}: {run.stderr()}"
        (exited,) = _events(run, "watchdog_exited")
        assert (exited.get("reason"), exited.get("resumed")) == ("stopped", False), exited
        assert (exited.get("progress") or {}).get("payment", {}).get("status") == "accepted", exited

        snapshot = transaction_snapshot(payments_config, deal_state.payer_account,
                                        deal_state.settlement_id)
        (part,) = snapshot["parts"]
        assert part.get("started") is not None, part
        stop = part.get("stop") or {}
        assert (stop.get("cause"), stop.get("partialPeriod")) == ("payer", "charged"), part
        assert int(part["held"]) + int(part["released"]) == PERIOD_GROSS, part
        kinds = [event.get("event", {}).get("kind") for event in snapshot["events"]]
        assert kinds == ["start", "stop"], snapshot["events"]

        read = deal_driver.lifecycle_read(deal_state.negotiation_id)
        assert read.delivery.recorded_end is not None, read.delivery
        assert read.delivery.recorded_end.cause == "payer", read.delivery
        assert read.filings == [], read.filings

        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
        filings = deal_driver.lifecycle_read(deal_state.negotiation_id).filings
        assert filings == [], filings
        deal_state.teardown_fulfillment_id = begin_teardown(
            provisioning_client, storefront_admin_client, deal_driver, deal_state,
        )
        log.info("[w05] The watchdog's stop of Agreement %s accepted at %s, charging the "
                 "started period; end recorded at %s with no filing; fulfillment %s "
                 "tearing down", deal_state.negotiation_id, stop.get("effectiveAt"),
                 read.delivery.recorded_end.ended_at, deal_state.teardown_fulfillment_id)
