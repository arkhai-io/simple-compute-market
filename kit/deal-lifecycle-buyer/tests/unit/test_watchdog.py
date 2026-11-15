"""The buyer's watchdog loop and its status, over mocked collaborators and a fake clock."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_deal_lifecycle_buyer import (
    EndDeliveryProgress, EndTarget, WatchdogSettings, WatchdogState, WatchdogStop, bound_notice, run_monitor,
    tcp_reachable, watch_deal, watchdog_settings, watchdog_status,
)
from market_deal_lifecycle_buyer.ending import EndPlan
from market_deal_lifecycle_buyer.watchdog import GRACE_SECONDS, ProbeObservation, deal_ended
from market_deal_lifecycle_contracts.models import Accepted, LifecycleCommand, Rejected, Unknown


class Clock:
    """Fake time: sleeping advances the wall clock, which stamps every probe, and
    the monotonic clock the schedule runs on; only the wall clock can be stepped."""

    def __init__(self, now=1000):
        self.now = now
        self.elapsed = 0

    def __call__(self):
        return self.now

    def monotonic(self):
        return self.elapsed

    async def sleep(self, seconds):
        self.now += seconds
        self.elapsed += seconds


class Journal:
    """The watchdog journal's interface, in memory."""

    def __init__(self, settings=None, stop=None):
        self.states = {"deal": WatchdogState(settings or WatchdogSettings(), stop=stop)}
        self.probes = []

    def state(self, negotiation_id):
        return self.states.get(negotiation_id)

    def record_probe(self, negotiation_id, at):
        self.probes.append(at)
        state = self.states[negotiation_id]
        self.states[negotiation_id] = WatchdogState(state.settings, at, state.stop)

    def record_stop(self, negotiation_id, stop):
        state = self.states[negotiation_id]
        kept = state.stop or stop
        self.states[negotiation_id] = WatchdogState(state.settings, state.last_probe_at, kept)
        return kept


def progress(payment):
    return EndDeliveryProgress(negotiation_id="deal", observed_at=1, mode="normal_stop", payment=payment)


def lifecycle(*, rate=True, kept_end=None):
    """A buyer lifecycle whose payment authority has no adapter and whose storefront is down."""
    return SimpleNamespace(
        _deal=lambda _: SimpleNamespace(rate=rate, buyer=None, payment=None),
        end=AsyncMock(return_value=progress(Accepted())),
        end_journal=SimpleNamespace(read=lambda _: kept_end),
        evidence=None,
        payments=SimpleNamespace(resolve=lambda _: None),
        peer=SimpleNamespace(read=AsyncMock(side_effect=OSError("storefront down"))),
    )


def kept_end(payment):
    return EndPlan(commitment_ref="c", operation_key="k", progress=progress(payment),
                   stop=LifecycleCommand(negotiation_id="deal", kind="stop", operation_key="k:stop"))


def probes(*answers):
    remaining = list(answers)

    async def probe():
        answer = remaining.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    return probe


async def never_ended():
    return False


SETTINGS = WatchdogSettings(interval_seconds=30, threshold=3, probe_timeout_seconds=5)


@pytest.mark.asyncio
async def test_the_threshold_of_consecutive_failures_sends_one_stop_and_journals_its_evidence():
    clock, journal, deal = Clock(), Journal(SETTINGS), lifecycle()
    outcome = await watch_deal(deal, "deal", journal=journal, probe=probes(False, OSError(), False),
                               clock=clock, monotonic=clock.monotonic, sleep=clock.sleep, ended=never_ended)
    assert outcome.reason == "stopped" and outcome.progress.payment == Accepted()
    deal.end.assert_awaited_once_with("deal")
    assert journal.probes == [1000, 1030, 1060]
    stop = journal.state("deal").stop
    assert [probe.at for probe in stop.probes] == [1000, 1030, 1060]
    assert stop.probes[1].detail == "probe failed: OSError"


@pytest.mark.asyncio
async def test_a_passing_probe_resets_the_count_so_nothing_is_sent_below_the_threshold():
    clock, journal, deal = Clock(), Journal(SETTINGS), lifecycle()
    answers = [False, False, True, False, False]
    ended = iter([False] * len(answers) + [True])

    async def ends_after_the_probes():
        return next(ended)

    # The round that finds the deal ended runs a probe beside the check, discarded.
    outcome = await watch_deal(deal, "deal", journal=journal, probe=probes(*answers, True),
                               clock=clock, monotonic=clock.monotonic, sleep=clock.sleep, ended=ends_after_the_probes)
    assert outcome.reason == "ended" and outcome.progress is None
    deal.end.assert_not_awaited()
    assert journal.state("deal").stop is None and len(journal.probes) == 5


@pytest.mark.asyncio
async def test_probes_start_on_a_fixed_schedule_however_long_each_takes():
    clock, journal, deal = Clock(), Journal(SETTINGS), lifecycle()

    async def slow_failure():
        await clock.sleep(4)  # the probe takes four of its five seconds, then fails
        return False

    await watch_deal(deal, "deal", journal=journal, probe=slow_failure, clock=clock,
                     monotonic=clock.monotonic, sleep=clock.sleep, ended=never_ended)
    assert journal.probes == [1000, 1030, 1060]


@pytest.mark.asyncio
async def test_a_wall_clock_stepped_back_does_not_postpone_the_next_probe():
    clock, journal, deal = Clock(), Journal(SETTINGS), lifecycle()
    scheduled = []

    async def failing_probe():
        scheduled.append(clock.elapsed)
        if len(scheduled) == 1:
            clock.now -= 3600  # the system clock is set back an hour after the first probe
        return False

    await watch_deal(deal, "deal", journal=journal, probe=failing_probe, clock=clock,
                     monotonic=clock.monotonic, sleep=clock.sleep, ended=never_ended)
    assert scheduled == [0, 30, 60]
    # Probe instants are still stamped with the wall clock, as it then read.
    assert journal.probes == [1000, 1030 - 3600, 1060 - 3600]


@pytest.mark.asyncio
async def test_a_stop_the_authority_refuses_is_rejected_never_stopped_and_not_resent():
    clock, journal, deal = Clock(), Journal(WatchdogSettings(30, 1, 5)), lifecycle()
    refusal = Rejected(reason="hold_matured: repair required before another monetary operation")
    deal.end.return_value = progress(refusal)
    outcome = await watch_deal(deal, "deal", journal=journal, probe=probes(False), clock=clock,
                               monotonic=clock.monotonic, sleep=clock.sleep, ended=never_ended)
    assert outcome.reason == "rejected" and outcome.progress.payment == refusal
    assert not outcome.resumed
    deal.end.assert_awaited_once_with("deal")
    # The journaled decision stays for diagnosis.
    assert journal.state("deal").stop is not None


@pytest.mark.asyncio
async def test_a_restart_finding_a_refused_stop_reports_it_rejected_and_sends_nothing():
    journal = Journal(SETTINGS, stop=WatchdogStop(1060, (ProbeObservation(1000, "x"),)))
    kept = kept_end(Rejected(reason="account has no entitled stop authority"))
    deal = lifecycle(kept_end=kept)
    outcome = await watch_deal(deal, "deal", journal=journal, probe=None, ended=never_ended)
    assert (outcome.reason, outcome.resumed, outcome.progress) == ("rejected", True, kept.progress)
    deal.end.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_stop_that_has_not_landed_is_resent_every_interval_until_it_does():
    clock, journal, deal = Clock(), Journal(WatchdogSettings(30, 1, 5)), lifecycle()
    deal.end.side_effect = [progress(Unknown(reason="down")), progress(Unknown(reason="down")),
                            progress(Accepted())]
    outcome = await watch_deal(deal, "deal", journal=journal, probe=probes(False), clock=clock,
                               monotonic=clock.monotonic, sleep=clock.sleep, ended=never_ended)
    assert outcome.progress.payment == Accepted()
    assert deal.end.await_count == 3 and clock.now == 1060


@pytest.mark.asyncio
async def test_the_deal_has_ended_when_the_buyer_ended_it_or_the_authority_shows_a_final_stop():
    assert await deal_ended(lifecycle(kept_end=kept_end(Accepted())), "deal")
    stopped = lifecycle()
    stopped.payments = SimpleNamespace(resolve=lambda _: SimpleNamespace(
        read=AsyncMock(return_value=SimpleNamespace(state="ended", parts=[])),
    ))
    assert await deal_ended(stopped, "deal")
    running = lifecycle()
    running.payments = SimpleNamespace(resolve=lambda _: SimpleNamespace(
        read=AsyncMock(return_value=SimpleNamespace(state="running", parts=[])),
    ))
    # The storefront is down and the authority shows the deal running.
    assert not await deal_ended(running, "deal")


@pytest.mark.asyncio
async def test_the_tcp_probe_answers_for_a_listener_and_fails_for_a_closed_port():
    server = await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        assert await tcp_reachable("127.0.0.1", port)
    with pytest.raises(OSError):
        await tcp_reachable("127.0.0.1", port)


@pytest.mark.asyncio
async def test_a_timed_out_probe_is_a_failure():
    clock, journal, deal = Clock(), Journal(WatchdogSettings(1, 1, 1)), lifecycle()

    async def timed_out():
        # What the loop's bounded wait raises once the probe outlasts its timeout.
        raise asyncio.TimeoutError

    outcome = await watch_deal(deal, "deal", journal=journal, probe=timed_out, clock=clock,
                               monotonic=clock.monotonic, sleep=clock.sleep, ended=never_ended)
    assert outcome.reason == "stopped"
    assert journal.state("deal").stop.probes[0].detail == "probe timed out"


@pytest.mark.asyncio
async def test_a_restart_after_the_stop_landed_sends_nothing_more():
    journal = Journal(SETTINGS, stop=WatchdogStop(1060, (ProbeObservation(1000, "x"),)))
    kept = kept_end(Accepted())
    deal = lifecycle(kept_end=kept)
    probe = AsyncMock()
    outcome = await watch_deal(deal, "deal", journal=journal, probe=probe, ended=never_ended)
    assert outcome.reason == "stopped" and outcome.progress == kept.progress
    deal.end.assert_not_awaited()
    probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_restart_before_the_stop_landed_resumes_that_one_stop():
    journal = Journal(SETTINGS, stop=WatchdogStop(1060, (ProbeObservation(1000, "x"),)))
    deal = lifecycle(kept_end=kept_end(Unknown(reason="down")))
    outcome = await watch_deal(deal, "deal", journal=journal, probe=AsyncMock(), ended=never_ended)
    assert outcome.reason == "stopped"
    deal.end.assert_awaited_once_with("deal")


@pytest.mark.asyncio
async def test_a_once_only_deal_is_never_watched():
    with pytest.raises(ValueError, match="rate deals"):
        await watch_deal(lifecycle(rate=False), "deal", journal=Journal(), probe=AsyncMock(), ended=never_ended)


def test_the_status_rests_on_the_last_probe_not_the_opt_in():
    settings = WatchdogSettings(interval_seconds=60, threshold=5, probe_timeout_seconds=10)
    fresh = 60 + 10 + GRACE_SECONDS
    assert watchdog_status(None, 5000) == "unmonitored"
    assert watchdog_status(WatchdogState(settings), 5000) == "unmonitored"
    assert watchdog_status(WatchdogState(settings, 5000 - fresh), 5000) == "monitored"
    assert watchdog_status(WatchdogState(settings, 5000 - fresh - 1), 5000) == "unmonitored"
    stopped = WatchdogState(settings, 0, WatchdogStop(1, ()))
    assert watchdog_status(stopped, 5000) == "stopped"


def test_the_bound_is_interval_times_threshold_plus_the_probe_timeout():
    assert WatchdogSettings(60, 5, 10).bound_seconds == 310
    with pytest.raises(ValueError):
        WatchdogSettings(0, 5, 10)
    # A probe that could outlast the interval would push the next one off schedule.
    with pytest.raises(ValueError, match="must not exceed its interval"):
        WatchdogSettings(7, 2, 10)


def test_the_opt_in_shortens_the_probe_timeout_to_an_interval_below_it():
    assert watchdog_settings(True, 60, 5) == WatchdogSettings(60, 5, 10)
    assert watchdog_settings(True, 7, 2) == WatchdogSettings(7, 2, 7)
    assert watchdog_settings(False, 60, 5) is None


@pytest.mark.asyncio
async def test_the_ended_check_runs_beside_the_probe_never_ahead_of_it():
    clock, journal, deal = Clock(), Journal(SETTINGS), lifecycle()
    started, overlapped = [], []

    async def probe():
        started.append(True)
        return False

    async def ended():
        await asyncio.sleep(0)  # a read in flight: the probe has started meanwhile
        overlapped.append(bool(started))
        started.clear()
        return False

    await watch_deal(deal, "deal", journal=journal, probe=probe, clock=clock, monotonic=clock.monotonic, sleep=clock.sleep, ended=ended)
    assert overlapped == [True, True, True]
    assert journal.probes == [1000, 1030, 1060]


def test_the_stated_bound_covers_the_ssh_endpoint_accepting_connections_only_while_the_command_runs():
    notice = bound_notice(WatchdogSettings(60, 5, 10))
    assert "if the deal's disclosed SSH endpoint stops accepting connections" in notice
    assert "the loss is detected within at most 310 seconds" in notice
    assert "only while this command runs" in notice
    assert "lost" not in notice


def monitor_target(deal, journal, events):
    deal.watchdog = journal

    @asynccontextmanager
    async def context():
        yield deal

    return EndTarget(negotiation_id="deal", lifecycle=context(),
                     record=lambda name, fields: events.append(name))


def test_the_monitor_states_the_bound_only_when_it_runs():
    lines, events = [], []
    deal = lifecycle()
    # One failed probe reaches a threshold of one, so the loop stops without sleeping.
    outcome = run_monitor(monitor_target(deal, Journal(WatchdogSettings(1, 1, 1)), events),
                          probe=AsyncMock(return_value=False), echo=lines.append)
    assert outcome.reason == "stopped"
    deal.end.assert_awaited_once_with("deal")
    assert "at most 2 seconds" in lines[0] and "only while this command runs" in lines[0]
    assert "acknowledgement" in lines[0] and "priced notice" in lines[0]
    assert lines[-1] == "Watchdog sent the buyer's stop: accepted."
    assert events == ["watchdog_started", "watchdog_exited"]


def test_an_interrupt_says_whether_the_stop_was_journaled():
    lines = []
    interrupted = AsyncMock(side_effect=KeyboardInterrupt)
    assert run_monitor(monitor_target(lifecycle(), Journal(SETTINGS), []), probe=interrupted,
                       echo=lines.append) is None
    assert lines[-1].startswith("Watchdog stopped by the buyer before deciding to stop")

    lines.clear()
    deal = lifecycle()
    deal.end.side_effect = KeyboardInterrupt
    journal = Journal(WatchdogSettings(1, 1, 1))
    assert run_monitor(monitor_target(deal, journal, []), probe=AsyncMock(return_value=False),
                       echo=lines.append) is None
    assert journal.state("deal").stop is not None
    assert lines[-1].startswith("Watchdog interrupted after it journaled the buyer's stop")


def test_a_journaled_stop_is_resumed_with_no_probe_and_no_bound():
    lines = []
    deal = lifecycle(kept_end=kept_end(Unknown(reason="payment authority down")))
    journal = Journal(SETTINGS, stop=WatchdogStop(1060, (ProbeObservation(1000, "x"),)))
    outcome = run_monitor(monitor_target(deal, journal, []), probe=None, echo=lines.append)
    assert outcome.reason == "stopped" and outcome.resumed
    deal.end.assert_awaited_once_with("deal")
    assert lines == ["Watchdog's journaled stop carried to the payment authority: accepted."]

    lines.clear()
    refused = lifecycle(kept_end=kept_end(Rejected(reason="account has no entitled stop authority")))
    outcome = run_monitor(monitor_target(refused, journal, []), probe=None, echo=lines.append)
    assert outcome.reason == "rejected" and outcome.resumed
    (line,) = lines
    assert line.startswith("Watchdog's stop was refused by the payment authority: "
                           "account has no entitled stop authority.")
    assert "billing continues" in line and "'end --end-now-regardless'" in line
    assert "carried" not in line and "sent the buyer's stop" not in line

    lines.clear()
    unopted = Journal(SETTINGS)
    unopted.states.clear()
    assert run_monitor(monitor_target(lifecycle(), unopted, []), probe=AsyncMock(), echo=lines.append) is None
    assert lines == []
