"""Every loop the storefront registers is held by a pause within its bound.

The kit controller's tests prove its timer against synthetic loops. They cannot
prove that the storefront's loops use it. Every loop but the capacity-event
pollers is registered with the controller over its step, so the controller's
timer gates, runs the step through the one cycle boundary an operator's step
takes, and waits through the controller; what is left to prove here is the
registration: startup registers every loop under the name its step reports,
with the interval it is configured with, and a pause requested between cycles
reaches each one at once however long that interval is.

So the timers run the storefront's real steps over collaborators injected
through the container, with every interval set far longer than any test waits,
and the pause must report each loop `paused` well inside the controller's own
bound. Work is synchronized with events the collaborators set; nothing here
waits on time.

Capacity polling's per-site fan-out lives in `kit/capacity-publication`, so the
storefront holds no task per site; the per-site cases assert against declared
gate names, and that each site acknowledges for itself.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from functools import partial
from types import SimpleNamespace

import pytest

from core_storefront.app_startup import StorefrontBackgroundTask
import market_storefront.container as container
from market_storefront import lifecycle
from market_storefront import startup
from market_storefront.services.publication_loop import wake_publication_loop
from tests._settings_overrides import settings_overrides
from tests.fake_site import FakeProjectionSite, site_projection_state

#: Far longer than any test waits. A loop that slept this instead of waiting
#: through the controller could not be reported paused within `_PROMPTLY`.
_LONG_INTERVAL = 3600

#: Well inside the controller's own quiescence bound, so a loop that is only
#: reported paused once that bound expires fails here rather than passing late.
_PROMPTLY = 1.0

#: The loops startup registers on the controller while contact exchange is not
#: composed: every loop but the capacity-event pollers.
_TIMED_LOOPS = {
    lifecycle.NEGOTIATION_WATCHDOG,
    lifecycle.SETTLEMENT_SERVICING,
    lifecycle.FULFILLMENT_RESUME,
    lifecycle.SITE_PROJECTION_POLLER,
    lifecycle.PUBLICATION,
}


@pytest.fixture(autouse=True)
async def _clean_registry():
    await lifecycle.reset_for_tests()
    yield
    await lifecycle.reset_for_tests()


@pytest.fixture
def long_intervals():
    """Every configured loop interval far longer than any test waits."""
    with settings_overrides(
        negotiation_watchdog_interval=_LONG_INTERVAL,
        settlement_servicing_interval_seconds=_LONG_INTERVAL,
        fulfillment_resume_sweep_interval=_LONG_INTERVAL,
        **{
            "capacity.poll_interval": _LONG_INTERVAL,
            "capacity.publication_interval_seconds": _LONG_INTERVAL,
        },
    ):
        yield


class _Cycles:
    """The capacity runtime a publication cycle reads first, marking each cycle.

    It names no site, so a cycle goes straight to converging registries, which
    fails over the absent database; a failed cycle is recorded and its timer
    carries on to its interval, which is all these cases need.
    """

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.count = 0

    @property
    def site_ids(self) -> tuple[str, ...]:
        self.count += 1
        self.started.set()
        return ()


@pytest.fixture
def collaborators(monkeypatch):
    """The container the steps read: a projection site marking its first poll,
    a capacity runtime marking each publication cycle, and nothing else, so
    the remaining steps fail fast and wait out their intervals."""
    first_poll = asyncio.Event()

    class _Site(FakeProjectionSite):
        async def _snapshot(self, family, key):
            first_poll.set()
            return await super()._snapshot(family, key)

    site = _Site(resource_pools=[], capacity_buckets=[])
    cycles = _Cycles()
    monkeypatch.setattr(
        container, "resolved_site_projections", site_projection_state({"default": site})
    )
    monkeypatch.setattr(container, "resolved_capacity_runtime", cycles)
    monkeypatch.setattr(container, "resolved_sqlite_client", None)
    monkeypatch.setattr(container, "resolved_contact_exchange", None)
    return SimpleNamespace(site=site, first_poll=first_poll, publication=cycles)


@asynccontextmanager
async def _registered(coro_factory, name: str):
    """Run a self-gating loop body under the name startup registers it as.

    Cancellation is how the loop ends in this test, never how a pause works:
    these loops are not cancelled in production. It is only the test's way of
    reclaiming a coroutine designed never to return.
    """
    task = lifecycle.start_registered_loop(
        StorefrontBackgroundTask(name=name, task_factory=coro_factory)
    )
    try:
        yield task
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _paused_promptly() -> dict[str, str]:
    return await asyncio.wait_for(lifecycle.controller().pause(), timeout=_PROMPTLY)


class TestStartupRegistersEveryLoopOnTheController:
    def test_the_capacity_pollers_are_the_one_self_gating_loop(self):
        """The constant is the contract between the registration and the gate
        the kit's per-site fan-out reads; every other loop has no body here."""
        source = open(startup.__file__).read()
        assert "name=CAPACITY_EVENTS_POLLER" in source
        assert "start_registered_loop(" in source
        assert source.count("StorefrontBackgroundTask(") == 1, (
            "startup starts a loop body of its own besides the capacity pollers"
        )

    async def test_startup_registers_and_starts_every_loop(
        self, long_intervals, collaborators
    ):
        """Held from the start, so no loop runs a cycle here."""
        lifecycle.controller().request_pause(True)
        startup._start_lifecycle_loops()
        await asyncio.wait_for(lifecycle.await_quiescence(), timeout=_PROMPTLY)

        assert set(lifecycle.registered_loop_names()) == _TIMED_LOOPS
        snapshot = lifecycle.snapshot()
        assert {name: snapshot[name].state for name in _TIMED_LOOPS} == dict.fromkeys(
            _TIMED_LOOPS, "paused"
        )
        assert all(snapshot[name].last_outcome is None for name in _TIMED_LOOPS)
        assert collaborators.site.snapshots == {"resource_pool": 0, "capacity_bucket": 0}


class TestEachLoopIsHeldWithinItsInterval:
    async def test_a_pause_during_the_idle_wait_reaches_every_gate(
        self, long_intervals, collaborators
    ):
        """The poller and publication run their first cycle on starting, the
        others are in their first interval; a pause then holds every one within
        the bound, and none runs again."""
        startup._start_lifecycle_loops()
        await asyncio.wait_for(collaborators.first_poll.wait(), timeout=_PROMPTLY)
        await asyncio.wait_for(collaborators.publication.started.wait(), timeout=_PROMPTLY)

        states = await _paused_promptly()

        assert {name: states[name] for name in _TIMED_LOOPS} == dict.fromkeys(
            _TIMED_LOOPS, "paused"
        )
        assert collaborators.site.snapshots == {"resource_pool": 1, "capacity_bucket": 1}, (
            "a held poller polled again"
        )
        assert collaborators.publication.count == 1, "a held publication loop ran again"

    async def test_a_failing_cycle_is_recorded_and_the_loop_keeps_running(
        self, long_intervals, collaborators
    ):
        """Publication's first cycle fails over the absent database; the
        controller records it in the stage it failed in and the loop runs on."""
        startup._start_lifecycle_loops()
        await asyncio.wait_for(collaborators.publication.started.wait(), timeout=_PROMPTLY)
        await _paused_promptly()

        loop = lifecycle.snapshot()[lifecycle.PUBLICATION]
        assert loop.state == "paused"
        assert loop.last_outcome is not None
        assert loop.last_outcome.trigger == "timer"
        assert not loop.last_outcome.completed
        assert loop.last_outcome.stage == "converge"

    async def test_a_projection_change_wakes_the_publication_timer(
        self, long_intervals, collaborators
    ):
        """A site's declaration change starts the next cycle without its interval."""
        startup._start_lifecycle_loops()
        await asyncio.wait_for(collaborators.publication.started.wait(), timeout=_PROMPTLY)
        collaborators.publication.started.clear()

        wake_publication_loop()
        await asyncio.wait_for(collaborators.publication.started.wait(), timeout=_PROMPTLY)

        assert collaborators.publication.count == 2


class TestCapacityEventPollers:
    async def test_capacity_events_poller(self, monkeypatch):
        """The aggregate keeps gating under its own name after starting its fan-out.

        It performs no polling itself -- the per-site pollers do that inside the
        kit -- but it stays registered so a storefront with no site configured
        still has a capacity loop to report, and so the admin advance route has
        a name to address. Its fan-out never returns, so an aggregate that
        awaited it would gate exactly once and never observe a pause.
        """
        from market_storefront.services import capacity_client as cc

        started = asyncio.Event()

        class _Runtime:
            async def poll_events(self, *, interval_seconds, paused=None, wait=None):
                started.set()
                await asyncio.Event().wait()

        monkeypatch.setattr(cc, "build_capacity_runtime", lambda _f: _Runtime())
        name = lifecycle.CAPACITY_EVENTS_POLLER
        async with _registered(partial(cc.capacity_events_poller_loop, object()), name):
            # The fan-out starts only once the aggregate has passed its first
            # gate, so being paused now requires a further gate read.
            await asyncio.wait_for(started.wait(), timeout=_PROMPTLY)
            states = await _paused_promptly()

        assert states == {name: "paused"}

    async def test_capacity_events_poller_declares_a_gate_per_site(self, monkeypatch):
        """Each site acknowledges for itself, through the wait it is given.

        The pollers fan out across configured sites. Sharing one gate between
        them means whichever site reaches its gate first satisfies the
        acknowledgement for every other, so a pause can return `paused` while a
        second site's cycle is still writing -- optimistic in the single
        direction the pause exists to rule out. Each site is a declared gate,
        which is what makes the pause wait for it.
        """
        from market_storefront.services import capacity_client as cc

        started = asyncio.Event()

        class _Runtime:
            async def poll_events(self, *, interval_seconds, paused=None, wait=None):
                gates = [paused(site) for site in ("site-a", "site-b")]
                started.set()
                while True:
                    for gate in gates:
                        gate()
                    await wait(_LONG_INTERVAL)

        monkeypatch.setattr(cc, "build_capacity_runtime", lambda _f: _Runtime())
        async with _registered(
            partial(cc.capacity_events_poller_loop, object()),
            lifecycle.CAPACITY_EVENTS_POLLER,
        ):
            await asyncio.wait_for(started.wait(), timeout=_PROMPTLY)
            states = await _paused_promptly()

        for site in ("site-a", "site-b"):
            name = lifecycle.capacity_site_loop_name(site)
            assert name in lifecycle.controller()._declared, (
                f"{site} has no declared gate, so it cannot be waited on"
            )
            assert states[name] == "paused", f"{site} did not acknowledge its own gate"

    async def test_a_second_site_still_working_is_not_reported_paused(self, monkeypatch):
        """The reason per-site gates exist.

        One site parks at its gate; the other never reaches one. A pause must
        report the capacity pollers as still stopping, because one of them is.
        """
        from market_storefront.services import capacity_client as cc

        site_a = lifecycle.capacity_site_loop_name("site-a")
        site_b = lifecycle.capacity_site_loop_name("site-b")
        declared = asyncio.Event()

        class _Runtime:
            async def poll_events(self, *, interval_seconds, paused=None, wait=None):
                gate_a = paused("site-a")
                # site-b's gate is bound -- so it is declared and waited on --
                # but never consulted, standing in for a cycle still in flight.
                paused("site-b")
                declared.set()
                while True:
                    gate_a()
                    await wait(_LONG_INTERVAL)

        monkeypatch.setattr(cc, "build_capacity_runtime", lambda _f: _Runtime())
        async with _registered(
            partial(cc.capacity_events_poller_loop, object()),
            lifecycle.CAPACITY_EVENTS_POLLER,
        ):
            await asyncio.wait_for(declared.wait(), timeout=_PROMPTLY)
            controller = lifecycle.controller()
            controller.request_pause(True)
            await asyncio.wait_for(controller._acked[site_a].wait(), timeout=_PROMPTLY)
            states = lifecycle.loop_states()

        assert states[site_a] == "paused"
        assert states[site_b] == "starting", (
            "a site that never reached its gate must not be reported as stopped "
            "on the strength of another site's acknowledgement"
        )


class TestIntroductionRetention:

    async def test_the_sweep_is_registered_while_contact_exchange_is_composed(
        self, long_intervals, collaborators, monkeypatch
    ):
        retention = SimpleNamespace(
            policy=SimpleNamespace(sweep_interval_seconds=_LONG_INTERVAL)
        )
        monkeypatch.setattr(
            container,
            "resolved_contact_exchange",
            SimpleNamespace(retention=lambda: retention),
        )
        lifecycle.controller().request_pause(True)
        startup._start_lifecycle_loops()
        await asyncio.wait_for(lifecycle.await_quiescence(), timeout=_PROMPTLY)

        assert set(lifecycle.registered_loop_names()) == {
            *_TIMED_LOOPS,
            lifecycle.INTRODUCTION_RETENTION,
        }
        assert lifecycle.loop_states()[lifecycle.INTRODUCTION_RETENTION] == "paused"
