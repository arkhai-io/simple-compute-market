"""The buyer's watchdog loop and its status, over mocked collaborators and a fake clock."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_deal_lifecycle_buyer import (
    EndDeliveryProgress, EndTarget, WatchdogSettings, WatchdogState, WatchdogStop, run_monitor, tcp_reachable,
    watch_deal, watchdog_status,
)
from market_deal_lifecycle_buyer.ending import EndPlan
from market_deal_lifecycle_buyer.watchdog import GRACE_SECONDS, ProbeObservation, deal_ended
from market_deal_lifecycle_contracts.models import Accepted, LifecycleCommand, Unknown


class Clock:
    """Fake time: sleeping advances it, and every probe reads it."""

    def __init__(self, now=1000):
        self.now = now

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


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
                               clock=clock, sleep=clock.sleep, ended=never_ended)
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

    outcome = await watch_deal(deal, "deal", journal=journal, probe=probes(*answers),
                               clock=clock, sleep=clock.sleep, ended=ends_after_the_probes)
    assert outcome.reason == "ended" and outcome.progress is None
    deal.end.assert_not_awaited()
    assert journal.state("deal").stop is None and len(journal.probes) == 5


@pytest.mark.asyncio
async def test_probes_start_on_a_fixed_schedule_however_long_each_takes():
    clock, journal, deal = Clock(), Journal(SETTINGS), lifecycle()

    async def slow_failure():
        clock.now += 4  # the probe takes four of its five seconds, then fails
        return False

    await watch_deal(deal, "deal", journal=journal, probe=slow_failure, clock=clock,
                     sleep=clock.sleep, ended=never_ended)
    assert journal.probes == [1000, 1030, 1060]


@pytest.mark.asyncio
async def test_a_stop_that_has_not_landed_is_resent_every_interval_until_it_does():
    clock, journal, deal = Clock(), Journal(WatchdogSettings(30, 1, 5)), lifecycle()
    deal.end.side_effect = [progress(Unknown(reason="down")), progress(Unknown(reason="down")),
                            progress(Accepted())]
    outcome = await watch_deal(deal, "deal", journal=journal, probe=probes(False), clock=clock,
                               sleep=clock.sleep, ended=never_ended)
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
                               sleep=clock.sleep, ended=never_ended)
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
    unopted = Journal(SETTINGS)
    unopted.states.clear()
    assert run_monitor(monitor_target(lifecycle(), unopted, []), probe=AsyncMock(), echo=lines.append) is None
    assert lines == []
