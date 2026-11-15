"""The bare-metal ``buy`` watchdog's resume, its bound and the deal read's status.

Unit: the command module's own seams are replaced (``end_target``,
``watchdog_journal``, ``watchdog_probe`` and ``wait_clock``), with a buyer
lifecycle double whose storefront answers what each test scripts, an in-memory
watchdog journal and a fake clock that sleeping advances. The read composes its
status through the buyer half's real ``BuyerLifecycle`` over a storefront double,
on the same fake clock.
"""

from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from market_deal_lifecycle.adapters import (
    DisputeAdapterTable, PaymentAdapterTable, PaymentBinding, PaymentSelector,
)
from market_deal_lifecycle_buyer import (
    BuyerDeal, BuyerLifecycle, EndDeliveryProgress, EndTarget, WaitClock, WatchdogSettings,
    WatchdogState, WatchdogStop,
)
from market_deal_lifecycle_buyer.watchdog import GRACE_SECONDS, ProbeObservation
from market_deal_lifecycle_contracts.models import (
    Accepted, AuthorityView, DeliveryView, LifecycleRead, RecordedEnd, Rejected,
)
from market_identity import Ed25519Signer
from typer.testing import CliRunner

from arkhai_bare_metal_buyer import cli

#: A deterministic development identity, never used on a public network.
ACTOR = Ed25519Signer(bytes([3]) * 32).identity


class Journal:
    """The watchdog journal's interface, in memory."""

    def __init__(self):
        self.states = {}

    def opt_in(self, negotiation_id, settings):
        state = self.states.get(negotiation_id)
        self.states[negotiation_id] = WatchdogState(
            settings, state.last_probe_at if state else None, state.stop if state else None,
        )

    def state(self, negotiation_id):
        return self.states.get(negotiation_id)

    def record_probe(self, negotiation_id, at):
        state = self.states[negotiation_id]
        self.states[negotiation_id] = WatchdogState(state.settings, at, state.stop)

    def record_stop(self, negotiation_id, stop):
        state = self.states[negotiation_id]
        self.states[negotiation_id] = WatchdogState(state.settings, state.last_probe_at, state.stop or stop)
        return self.states[negotiation_id].stop


class Clock:
    """Fake time: sleeping advances it, and it stamps probes."""

    def __init__(self, now=1000):
        self.now = now

    async def sleep(self, seconds):
        self.now += seconds

    def wait_clock(self):
        return WaitClock(now=lambda: int(self.now), monotonic=lambda: self.now, sleep=self.sleep)


#: One failed probe reaches the threshold.
IMMEDIATE = WatchdogSettings(interval_seconds=1, threshold=1, probe_timeout_seconds=1)
ACTIVE = DeliveryView(progress="active")
ENDED = DeliveryView(progress="end_recorded", recorded_end=RecordedEnd(
    ended_at=1, actor=ACTOR, cause="payer", source="watch",
))


def install(monkeypatch, journal, clock, *, reads=(ACTIVE,), answers=(False,)):
    """Replace the seams. The storefront answers ``reads`` in turn, then the last
    one again; ``reads`` of ``None`` is an unreadable storefront. Each probe
    answers the next of ``answers``."""
    stopped = EndDeliveryProgress(negotiation_id="deal", observed_at=1, mode="normal_stop", payment=Accepted())
    remaining = list(reads)

    async def read(_negotiation_id):
        view = remaining.pop(0) if len(remaining) > 1 else remaining[0]
        if view is None:
            raise OSError("storefront unreachable")
        return SimpleNamespace(delivery=view)

    lifecycle = SimpleNamespace(
        _deal=lambda _: SimpleNamespace(rate=True, buyer=None, payment=None),
        end=AsyncMock(return_value=stopped),
        end_journal=SimpleNamespace(read=lambda _: None),
        evidence=None, watchdog=journal,
        payments=SimpleNamespace(resolve=lambda _: None),
        peer=SimpleNamespace(read=AsyncMock(side_effect=read)),
    )
    events = []

    def end_target(run_id, config):
        @asynccontextmanager
        async def context():
            yield lifecycle

        return EndTarget(negotiation_id="deal", lifecycle=context(),
                         record=lambda name, fields: events.append(name))

    probes, scripted = [], list(answers)

    def watchdog_probe(run_id, config):
        async def probe():
            probes.append(clock.now)
            return scripted.pop(0)

        return probe

    monkeypatch.setattr(cli, "end_target", end_target)
    monkeypatch.setattr(cli, "watchdog_journal", lambda: journal)
    monkeypatch.setattr(cli, "watchdog_probe", watchdog_probe)
    monkeypatch.setattr(cli, "wait_clock", clock.wait_clock)
    return lifecycle, events, probes


def test_a_resume_re_enters_the_watchdog_and_states_its_bound_while_it_runs(monkeypatch):
    journal = Journal()
    journal.opt_in("deal", IMMEDIATE)
    lifecycle, events, probes = install(monkeypatch, journal, Clock())

    result = CliRunner().invoke(cli.bare_metal_app, ["buy", "--from", "run"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout.strip().splitlines()[-1]) == {
        "run_id": "run", "negotiation_id": "deal", "available": True, "watchdog": "stopped",
    }
    assert "at most 2 seconds" in result.stderr and "only while this command runs" in result.stderr
    assert len(probes) == 1
    lifecycle.end.assert_awaited_once_with("deal")
    assert journal.state("deal").stop is not None
    assert events == ["watchdog_started", "watchdog_exited"]


def test_a_deal_never_available_is_left_unmonitored_and_the_bound_is_never_stated(monkeypatch):
    journal = Journal()
    journal.opt_in("deal", IMMEDIATE)
    clock = Clock()
    lifecycle, events, probes = install(monkeypatch, journal, clock,
                                        reads=(DeliveryView(progress="repair_required"),))

    result = CliRunner().invoke(cli.bare_metal_app, [
        "buy", "--run-id", "run", "--delivery-timeout-seconds", "30", "--poll-interval", "5",
    ])

    assert result.exit_code == cli.UNAVAILABLE_EXIT_CODE, result.output
    assert json.loads(result.stdout.strip().splitlines()[-1])["available"] is False
    # The wait ran its thirty seconds in fake time, reading every five.
    assert clock.now == 1030 and lifecycle.peer.read.await_count == 7
    assert "Watchdog running" not in result.stderr
    assert probes == [] and events == []
    lifecycle.end.assert_not_awaited()
    assert journal.state("deal").last_probe_at is None


def test_a_journaled_stop_is_carried_on_resume_while_the_storefront_is_down(monkeypatch):
    journal = Journal()
    journal.opt_in("deal", IMMEDIATE)
    journal.record_stop("deal", WatchdogStop(990, (ProbeObservation(980, "probe timed out"),)))
    lifecycle, _, probes = install(monkeypatch, journal, Clock(), reads=(None,))

    result = CliRunner().invoke(cli.bare_metal_app, ["buy", "--from", "run"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout.strip().splitlines()[-1])["watchdog"] == "stopped"
    # No wait for availability and no probe: only the stop, carried to the authority.
    assert lifecycle.peer.read.await_count == 0 and probes == []
    lifecycle.end.assert_awaited_once_with("deal")
    assert "carried to the payment authority" in result.stderr


def test_a_resume_of_a_deal_that_has_ended_reports_the_end_and_watches_nothing(monkeypatch):
    journal = Journal()
    journal.opt_in("deal", IMMEDIATE)
    lifecycle, events, probes = install(monkeypatch, journal, Clock(), reads=(ENDED,))

    result = CliRunner().invoke(cli.bare_metal_app, ["buy", "--from", "run"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout.strip().splitlines()[-1])["watchdog"] == "ended"
    assert probes == [] and events == []
    lifecycle.end.assert_not_awaited()


def test_a_resume_of_a_deal_never_opted_in_runs_no_watchdog(monkeypatch):
    lifecycle, _, probes = install(monkeypatch, Journal(), Clock())

    result = CliRunner().invoke(cli.bare_metal_app, ["buy", "-r", "run"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout.strip().splitlines()[-1])["watchdog"] is None
    assert probes == [] and lifecycle.peer.read.await_count == 0


def test_a_resume_names_only_its_run(monkeypatch):
    install(monkeypatch, Journal(), Clock())
    result = CliRunner().invoke(cli.bare_metal_app, ["buy", "listing", "--from", "run", "--watchdog"])
    assert result.exit_code == 2


class Peer:
    async def read(self, negotiation_id):
        return LifecycleRead(negotiation_id=negotiation_id, authority=AuthorityView(outcome=Rejected(reason="x")),
                             delivery=DeliveryView(progress="active"))


def test_the_read_shows_monitored_while_a_resumed_loop_probes_unmonitored_after_a_kill_and_stopped(
    monkeypatch,
):
    journal = Journal()
    clock = Clock()

    def read_target(run_id, config):
        deal = BuyerDeal("deal", "commitment", PaymentBinding("deal", PaymentSelector("fixture.payment")), rate=True)

        @asynccontextmanager
        async def context():
            yield BuyerLifecycle(deal=lambda _: deal, payments=PaymentAdapterTable([]),
                                 disputes=DisputeAdapterTable([]), operations=None, peer=Peer(),
                                 watchdog=journal, clock=lambda: int(clock.now))

        return EndTarget(negotiation_id="deal", lifecycle=context())

    def read():
        monkeypatch.setattr(cli, "end_target", read_target)
        result = CliRunner().invoke(cli.bare_metal_app, ["delivery", "--run-id", "run", "--config", "buyer.toml"])
        assert result.exit_code == 0, result.output
        view = json.loads(result.stdout)
        assert view["delivery"]["progress"] == "active"
        return view["watchdog"]["status"]

    def resume():
        result = CliRunner().invoke(cli.bare_metal_app, ["buy", "--from", "run"])
        assert result.exit_code == 0, result.output

    assert read() == "unmonitored"
    settings = WatchdogSettings(interval_seconds=60, threshold=3, probe_timeout_seconds=10)
    journal.opt_in("deal", settings)
    # The opt-in alone is no protection.
    assert read() == "unmonitored"

    # A resumed loop probes once, the access answering, and exits when the deal
    # then ends by another path: its probe is the freshest instant.
    install(monkeypatch, journal, clock, reads=(ACTIVE, ACTIVE, ENDED), answers=(True,))
    resume()
    assert journal.state("deal").last_probe_at == 1000
    clock.now = 1000 + 60 + 10 + GRACE_SECONDS
    assert read() == "monitored"
    # The command is gone: no probe follows, so the last one goes stale.
    clock.now += 1
    assert read() == "unmonitored"

    # Resumed again, the loop finds the access lost and stops the deal.
    journal.opt_in("deal", IMMEDIATE)
    lifecycle, _, _ = install(monkeypatch, journal, clock)
    resume()
    lifecycle.end.assert_awaited_once_with("deal")
    assert read() == "stopped"
